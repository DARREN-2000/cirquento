"""Ingest real files: CSV/TSV BOM extracts with a schema contract.

This is the layer that meets actual enterprise data, so it is built around one
assumption: **the file will be wrong**. Column names differ per ERP, numbers
arrive with German decimal commas, percentages arrive as both `0.35` and `35`,
mass arrives in grams, and a fifth of the rows have a blank where the schema
says there is a number.

The contract therefore does two things that a naive `pandas.read_csv` does not:

* **Never silently coerce.** A cell that cannot be parsed produces a rejection
  with the row number and the offending value, not a `NaN` that becomes a 0 and
  then becomes a published score.
* **Never guess an ambiguous unit.** `recycled_fraction: 35` could be 35% or a
  corrupt 3500%. The rule is explicit and documented below, and anything
  outside the accepted range is rejected rather than clamped.

Rejections are returned alongside accepted rows so the caller can report
"loaded 780 of 812 lines, here is exactly what failed" — the difference between
a tool an enterprise data team trusts and one they work around.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

# Column aliases seen across SAP / Oracle / Excel exports. Lowercased and
# stripped of separators before matching.
ALIASES: dict[str, tuple[str, ...]] = {
    "line_id": ("lineid", "line", "itemno", "item", "position", "pos", "bomline"),
    "product_id": ("productid", "product", "assembly", "parentmaterial", "topmaterial", "fg"),
    "product_name": ("productname", "assemblyname", "description_parent", "parentdescription"),
    "description": (
        "description",
        "materialdescription",
        "text",
        "componentdescription",
        "bezeichnung",
        "materialbeschreibung",
        "beschreibung",
        "komponente",
        "materialtext",
        "partdescription",
    ),
    "mass_kg": ("masskg", "mass", "weight", "weightkg", "netweight", "gewicht"),
    "mass_g": ("massg", "weightg", "grams"),
    "recycled_fraction": ("recycledfraction", "recycledcontent", "recycled", "rezyklatanteil"),
    "joining_method": ("joiningmethod", "joint", "jointtype", "fastening", "verbindung"),
    "supplier_id": ("supplierid", "supplier", "vendor", "vendorno", "lieferant"),
    "substances": ("substances", "svhc", "substanceofconcern", "hazardous"),
}

REQUIRED = ("line_id", "product_id", "description", "mass_kg", "joining_method")


class SchemaError(ValueError):
    """Raised when a file cannot be mapped to the BOM contract at all."""


@dataclass(slots=True)
class Rejection:
    row_number: int
    field: str
    value: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "rowNumber": self.row_number,
            "field": self.field,
            "value": self.value,
            "reason": self.reason,
        }


@dataclass(slots=True)
class IngestResult:
    rows: list[dict[str, Any]] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    column_mapping: dict[str, str] = field(default_factory=dict)

    @property
    def accepted(self) -> int:
        return len(self.rows)

    @property
    def rejected(self) -> int:
        return len(self.rejections)

    def summary(self) -> str:
        total = self.accepted + self.rejected
        return f"accepted {self.accepted}/{total} rows, rejected {self.rejected}"


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def map_columns(headers: Sequence[str]) -> dict[str, str]:
    """Map source headers onto canonical field names.

    Exact alias matches only. Fuzzy header matching sounds helpful and produces
    silent catastrophes: a column called `net_weight_gross` matching `mass_kg`
    is not an error anyone catches downstream.
    """
    normalised = {_norm(h): h for h in headers}
    mapping: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        for alias in (_norm(canonical), *aliases):
            if alias in normalised:
                mapping[canonical] = normalised[alias]
                break
    missing = [f for f in REQUIRED if f not in mapping and not (f == "mass_kg" and "mass_g" in mapping)]
    if missing:
        raise SchemaError(
            f"Cannot map required column(s) {missing} from headers {list(headers)}. "
            "Add an alias in cirquento.ingest.readers.ALIASES or rename the column; "
            "guessing which column holds mass is not an acceptable default."
        )
    return mapping


def detect_comma_decimal(values: Iterable[str]) -> bool:
    """Decide, for a whole column, whether ',' is the decimal separator.

    This exists because `1.240` is genuinely ambiguous: 1240 in a German export,
    1.24 in an English one. Guessing per cell means a mass can be wrong by a
    factor of 1000 while looking completely plausible, which is the worst class
    of data bug — it never raises, it just produces a confident wrong number.

    So the decision is made once per column, from the whole file: if ANY value
    in the column uses a comma as a decimal separator (`0,048`), the column is
    German-formatted and `.` is therefore a thousands separator throughout.
    One unambiguous cell disambiguates every ambiguous one.
    """
    for value in values:
        text = (value or "").strip().replace("\u00a0", "").replace(" ", "").rstrip("%")
        if not text:
            continue
        if "," in text and "." in text:
            # Whichever separator comes last is the decimal one.
            return text.rfind(",") > text.rfind(".")
        if "," in text:
            # "1,234" could be English thousands, but a 1-2 digit tail ("0,5")
            # can only be a decimal comma.
            tail = text.rsplit(",", 1)[1]
            if len(tail) != 3:
                return True
    return False


def _decimal(raw: str, comma_decimal: bool = False) -> Decimal:
    """Parse a number tolerant of European formatting, strict about garbage."""
    text = raw.strip().replace("\u00a0", "").replace(" ", "")
    if not text:
        raise InvalidOperation("empty")
    if comma_decimal:
        # Column-level decision already made: '.' groups thousands, ',' decimals.
        text = text.replace(".", "").replace(",", ".")
    elif "," in text and "." in text:
        # "1.234,56" -> German thousands; "1,234.56" -> English thousands.
        text = text.replace(".", "").replace(",", ".") if text.rfind(",") > text.rfind(".") else text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    return Decimal(text)


def _parse_fraction(raw: str, comma_decimal: bool = False) -> Decimal | None:
    """Normalise recycled content to a 0..1 fraction.

    Rule: values in [0, 1] are fractions; values in (1, 100] are percentages;
    anything above 100 or below 0 is rejected. The ambiguity at exactly 1 is
    resolved as 100%, matching how every ERP export encountered writes
    "fully recycled", and it is documented rather than hidden.
    """
    text = raw.strip().rstrip("%").strip()
    if not text or text.lower() in {"n/a", "na", "none", "unknown", "-", "?"}:
        return None  # a gap, which the engine scores as 0 and reports as a gap
    value = _decimal(text, comma_decimal)
    if value < 0 or value > 100:
        raise ValueError(f"{value} is outside the plausible range 0..100")
    if value > 1:
        value = value / Decimal(100)
    return value


def read_rows(
    source: str | Path | io.TextIOBase,
    *,
    delimiter: str | None = None,
    source_uri: str | None = None,
) -> IngestResult:
    if isinstance(source, (str, Path)):
        path = Path(source)
        text = path.read_text(encoding="utf-8-sig")
        source_uri = source_uri or f"file://{path.resolve()}"
    else:
        text = source.read()
        source_uri = source_uri or "stream://input"

    if delimiter is None:
        try:
            delimiter = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|").delimiter
        except csv.Error:
            delimiter = ","

    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        raise SchemaError("File has no header row.")
    mapping = map_columns(reader.fieldnames)
    result = IngestResult(column_mapping=mapping)

    # Materialise so numeric formatting can be decided per column across the
    # whole file before any single cell is parsed. Streaming would force a
    # per-cell guess on exactly the values that must not be guessed.
    raw_rows = list(reader)
    styles: dict[str, bool] = {}
    for field_name in ("mass_kg", "mass_g", "recycled_fraction"):
        column = mapping.get(field_name)
        if column:
            styles[field_name] = detect_comma_decimal(r.get(column) or "" for r in raw_rows)

    for number, raw in enumerate(raw_rows, start=2):  # row 1 is the header
        def cell(field_name: str) -> str:
            column = mapping.get(field_name)
            return (raw.get(column) or "").strip() if column else ""

        try:
            if "mass_kg" in mapping and cell("mass_kg"):
                mass = _decimal(cell("mass_kg"), styles.get("mass_kg", False))
            elif "mass_g" in mapping and cell("mass_g"):
                mass = _decimal(cell("mass_g"), styles.get("mass_g", False)) / Decimal(1000)
            else:
                raise InvalidOperation("no mass value")
            if mass < 0:
                raise ValueError("negative mass")
        except (InvalidOperation, ValueError) as exc:
            # A rejection is read by a data engineer triaging a failed load, so
            # it must say what is wrong with the value — not leak a Decimal
            # exception repr like "[<class 'decimal.ConversionSyntax'>]".
            reason = (
                "not a parseable number"
                if isinstance(exc, InvalidOperation)
                else str(exc) or "invalid mass"
            )
            result.rejections.append(
                Rejection(number, "mass_kg", cell("mass_kg") or cell("mass_g"), reason)
            )
            continue

        try:
            recycled = _parse_fraction(
                cell("recycled_fraction"), styles.get("recycled_fraction", False)
            )
        except (InvalidOperation, ValueError) as exc:
            reason = (
                "not a parseable number"
                if isinstance(exc, InvalidOperation)
                else str(exc) or "invalid recycled fraction"
            )
            result.rejections.append(
                Rejection(number, "recycled_fraction", cell("recycled_fraction"), reason)
            )
            continue

        description = cell("description")
        if not description:
            result.rejections.append(
                Rejection(number, "description", "", "empty description cannot be classified")
            )
            continue

        substances = tuple(
            s.strip() for s in cell("substances").replace(";", ",").split(",") if s.strip()
        )
        result.rows.append(
            {
                "line_id": cell("line_id") or f"L-{number:05d}",
                "product_id": cell("product_id"),
                "product_name": cell("product_name") or cell("product_id"),
                "description": description,
                "mass_kg": str(mass),
                "recycled_fraction": None if recycled is None else str(recycled),
                "joining_method": (cell("joining_method") or "unknown").lower(),
                "supplier_id": cell("supplier_id") or None,
                "substances": list(substances),
            }
        )

    return result


def to_dataset(
    result: IngestResult, *, source_uri: str, suppliers: Iterable[Mapping[str, Any]] = ()
) -> dict[str, Any]:
    """Shape an ingest result into the dataset the pipeline consumes."""
    return {
        "source_uri": source_uri,
        "rows": result.rows,
        "suppliers": [dict(s) for s in suppliers],
        "ingestReport": {
            "accepted": result.accepted,
            "rejected": result.rejected,
            "columnMapping": result.column_mapping,
            "rejections": [r.as_dict() for r in result.rejections[:50]],
        },
    }
