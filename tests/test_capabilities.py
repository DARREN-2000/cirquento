"""Tests for the capabilities added beyond the core scoring engine.

Each test here pins a behaviour that is easy to regress into something that
looks like it works: a seal that accepts a tampered document, an exporter that
quietly emits a carbon number, a recommender that promises an improvement it
cannot deliver, an ingest that turns a bad cell into a silent zero.
"""

from __future__ import annotations

import io
import json
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from cirquento.export import carbon
from cirquento.ingest.readers import SchemaError, map_columns, read_rows
from cirquento.passport import pdf as passport_pdf
from cirquento.passport import seal as passport_seal
from cirquento.review.queue import KIND_CLASSIFICATION, ReviewQueue
from cirquento.rules.engine import Component, RuleEngine
from cirquento.rules.recommend import Recommender
from cirquento.rules.spec import RuleSet

KEY = "unit-test-key"
RULESET = RuleSet.load("rules/circularity.v3.yaml")


def _component(line_id: str, code: str, joint: str, mass: str = "1", recycled: str | None = None,
               substances: tuple[str, ...] = (), supplier: str = "S-1") -> Component:
    return Component(
        line_id=line_id,
        material_code=code,
        mass_kg=Decimal(mass),
        recycled_fraction=None if recycled is None else Decimal(recycled),
        joining_method=joint,
        substances=substances,
        supplier_id=supplier,
    )


# -- sealing -------------------------------------------------------------------


def test_seal_roundtrip_verifies() -> None:
    sealed = passport_seal.seal_hash("a" * 64, key=KEY)
    assert passport_seal.verify(sealed.as_dict(), "a" * 64, key=KEY) is True


def test_seal_rejects_tampered_content() -> None:
    sealed = passport_seal.seal_hash("a" * 64, key=KEY)
    assert passport_seal.verify(sealed.as_dict(), "b" * 64, key=KEY) is False


def test_seal_rejects_wrong_key() -> None:
    sealed = passport_seal.seal_hash("a" * 64, key=KEY)
    assert passport_seal.verify(sealed.as_dict(), "a" * 64, key="other-key") is False


def test_seal_fails_closed_on_unknown_algorithm() -> None:
    """An unrecognised algorithm must raise, never quietly return False.

    Returning False would be indistinguishable from a tampered document and
    would hide a downgrade attack behind a normal-looking failure.
    """
    bad = {"algorithm": "NONE", "contentHash": "a" * 64, "signature": ""}
    with pytest.raises(passport_seal.SealError):
        passport_seal.verify(bad, "a" * 64, key=KEY)


def test_seal_refuses_document_whose_hash_does_not_match_body() -> None:
    doc = {"productId": "P1", "circularityScore": 40.0, "contentHash": "deadbeef"}
    with pytest.raises(passport_seal.SealError):
        passport_seal.seal_document(doc, key=KEY)


def test_seal_requires_a_key() -> None:
    with pytest.raises(passport_seal.SealError):
        passport_seal.seal_hash("a" * 64, key="")


# -- carbon export -------------------------------------------------------------


def _passport_doc() -> dict:
    return {
        "productId": "P-1",
        "productName": "Widget",
        "rulesetVersion": "circularity.v3",
        "componentCount": 4,
        "totalMassKg": 10.0,
        "contentHash": "c" * 64,
        "materialComposition": {"MET.ALU.WROUGHT": 60.0, "POL.ABS": 40.0},
        "dimensions": {"recycled_content": {"value": 25.0, "weight": 0.3}},
        "dataGaps": {"unclassifiedLines": 1, "missingRecycledContent": 2},
    }


def test_export_payload_carries_mass_and_provenance() -> None:
    payload = carbon.build_payload(_passport_doc())
    assert payload["passportContentHash"] == "c" * 64
    assert payload["totalMassKg"] == 10.0
    assert {m["materialCode"] for m in payload["materials"]} == {"MET.ALU.WROUGHT", "POL.ABS"}


def test_export_refuses_to_emit_a_carbon_figure() -> None:
    """The contract's whole point is that it does not publish a second number."""
    payload = carbon.build_payload(_passport_doc())
    payload["kgCO2e"] = 123.0
    with pytest.raises(carbon.ExportError):
        carbon.validate(payload)


def test_export_rejects_composition_that_does_not_sum_to_100() -> None:
    doc = _passport_doc()
    doc["materialComposition"] = {"MET.ALU.WROUGHT": 60.0, "POL.ABS": 10.0}
    with pytest.raises(carbon.ExportError):
        carbon.build_payload(doc)


def test_export_marks_unclassified_material_as_such() -> None:
    doc = _passport_doc()
    doc["materialComposition"] = {"UNCLASSIFIED": 100.0}
    payload = carbon.build_payload(doc)
    assert payload["materials"][0]["dataQuality"] == "unclassified"


# -- recommendations -----------------------------------------------------------


def test_bundled_joint_fix_beats_partial_fix() -> None:
    """Disassembly is a min(), so fixing one of two bad joints must gain less.

    This is the property that makes the recommender useful rather than
    plausible-sounding: a partial fix to a minimum can be worth nothing.
    """
    engine = RuleEngine(RULESET)
    comps = [
        _component("L1", "MET.ALU.WROUGHT", "potting", recycled="0.5"),
        _component("L2", "MET.ALU.WROUGHT", "adhesive", recycled="0.5"),
        _component("L3", "MET.ALU.WROUGHT", "screw", recycled="0.5"),
    ]
    items = Recommender(engine, RULESET).recommend(comps)
    bundle = [r for r in items if "all non-separable" in r.action]
    single = [r for r in items if "'potting'" in r.action]
    assert bundle, "expected a bundled recommendation"
    assert single, "expected a per-joint recommendation"
    assert bundle[0].delta > single[0].delta


def test_recommendations_never_promise_a_negative_or_zero_gain() -> None:
    engine = RuleEngine(RULESET)
    comps = [_component("L1", "MET.ALU.WROUGHT", "screw", recycled="1")]
    assert all(r.delta > 0 for r in Recommender(engine, RULESET).recommend(comps))


def test_evidence_request_is_flagged_conditional() -> None:
    """Evidence upside must never be presented as an achieved improvement."""
    engine = RuleEngine(RULESET)
    comps = [
        _component("L1", "MET.ALU.WROUGHT", "screw", recycled="0.8", supplier="S-9"),
        _component("L2", "MET.ALU.WROUGHT", "screw", recycled=None, supplier="S-9"),
    ]
    evidence = [r for r in Recommender(engine, RULESET).recommend(comps) if r.kind == "evidence"]
    assert evidence and all(r.conditional for r in evidence)


def test_no_evidence_upside_claimed_when_supplier_has_evidenced_nothing() -> None:
    """With no evidenced line there is no defensible rate to project."""
    engine = RuleEngine(RULESET)
    comps = [
        _component("L1", "MET.ALU.WROUGHT", "screw", recycled=None, supplier="S-9"),
        _component("L2", "MET.ALU.WROUGHT", "screw", recycled=None, supplier="S-9"),
    ]
    items = Recommender(engine, RULESET).recommend(comps)
    assert not [r for r in items if r.kind == "evidence"]


# -- review queue --------------------------------------------------------------


def test_review_queue_enqueue_is_idempotent() -> None:
    with TemporaryDirectory() as tmp:
        q = ReviewQueue(Path(tmp) / "q.jsonl")
        q.enqueue(KIND_CLASSIFICATION, "mystery part", "below floor")
        q.enqueue(KIND_CLASSIFICATION, "mystery part", "below floor")
        assert q.stats()["total"] == 1


def test_review_resolution_is_append_only_and_not_repeatable() -> None:
    with TemporaryDirectory() as tmp:
        q = ReviewQueue(Path(tmp) / "q.jsonl")
        item = q.enqueue(KIND_CLASSIFICATION, "mystery part", "below floor")
        q.resolve(item.id, "POL.ABS", "darren")
        assert q.stats() == {"total": 1, "open": 0, "resolved": 1}
        with pytest.raises(ValueError):
            q.resolve(item.id, "MET.ALU.WROUGHT", "someone-else")


def test_resolved_reviews_become_golden_labels_including_nulls() -> None:
    with TemporaryDirectory() as tmp:
        q = ReviewQueue(Path(tmp) / "q.jsonl")
        a = q.enqueue(KIND_CLASSIFICATION, "ABS panel", "below floor")
        b = q.enqueue(KIND_CLASSIFICATION, "unlabelled goo", "below floor")
        q.resolve(a.id, "POL.ABS", "darren")
        q.resolve(b.id, "unclassifiable", "darren")
        labels = {row["description"]: row["label"] for row in q.export_labels()}
        assert labels == {"ABS panel": "POL.ABS", "unlabelled goo": None}


# -- ingest --------------------------------------------------------------------


CSV = (
    "Item No;Top Material;Materialbeschreibung;Gewicht;Rezyklatanteil;Verbindung\n"
    "L1;P1;Aluminium profile;1.240;35%;screw\n"        # dot thousands + percent
    "L2;P1;Steel washer;0,048;0,12;screw\n"           # german decimal comma
    "L3;P1;Unknown goo;0,100;;clip\n"                 # blank = gap, not zero
    "L4;P1;Bad mass;n/a;0,3;screw\n"                  # rejected
    "L5;P1;Impossible fraction;0,2;350;screw\n"       # rejected
)


def test_ingest_parses_european_numbers_and_percentages() -> None:
    result = read_rows(io.StringIO(CSV), delimiter=";")
    rows = {r["line_id"]: r for r in result.rows}
    assert Decimal(rows["L1"]["mass_kg"]) == Decimal("1240")
    assert Decimal(rows["L1"]["recycled_fraction"]) == Decimal("0.35")
    assert Decimal(rows["L2"]["mass_kg"]) == Decimal("0.048")


def test_ingest_treats_blank_recycled_content_as_a_gap_not_a_zero() -> None:
    result = read_rows(io.StringIO(CSV), delimiter=";")
    rows = {r["line_id"]: r for r in result.rows}
    assert rows["L3"]["recycled_fraction"] is None


def test_ingest_rejects_bad_cells_with_row_numbers_instead_of_coercing() -> None:
    result = read_rows(io.StringIO(CSV), delimiter=";")
    assert result.accepted == 3
    assert result.rejected == 2
    fields = {r.field for r in result.rejections}
    assert fields == {"mass_kg", "recycled_fraction"}
    assert all(r.row_number > 1 for r in result.rejections)
    assert all("ConversionSyntax" not in r.reason for r in result.rejections)


def test_ingest_refuses_to_guess_a_missing_required_column() -> None:
    with pytest.raises(SchemaError):
        map_columns(["foo", "bar", "baz"])


# -- pdf -----------------------------------------------------------------------


def test_pdf_is_structurally_valid() -> None:
    blob = passport_pdf.render_passport(_passport_doc())
    assert blob.startswith(b"%PDF")
    assert blob.rstrip().endswith(b"%%EOF")
    assert b"/Type /Catalog" in blob and b"xref" in blob


def test_pdf_handles_non_latin1_characters_without_crashing() -> None:
    doc = _passport_doc()
    doc["productName"] = "Gr\u00fcnes Geh\u00e4use \u2014 f\u00fcr Pr\u00fcfung → 100%"
    doc["explanation"] = "Score 40/100 — held back by substances…"
    blob = passport_pdf.render_passport(doc)
    assert blob.startswith(b"%PDF")
