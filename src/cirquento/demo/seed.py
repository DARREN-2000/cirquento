"""Deterministic synthetic dataset.

Seeded with a fixed value so the demo, the screenshots and the GitHub Pages
build all show the *same* numbers. A demo whose figures drift on every run
cannot be used to prove replay determinism, which is the property this project
is actually selling.

Each product has a **designed** bill of materials rather than a random draw,
because the demo has to carry an engineering argument:

  CM-4470-B  epoxy-potted power stage  -> disassembly collapses to the potting
             joint, and no amount of recycled aluminium can compensate.
  CM-4470-C  the same module, clip-retained  -> the single design change the
             counterfactual recommends, so the two can be compared directly.
  BR-2210-A  all-metal, all-screwed bracket  -> what a good score looks like.
  HS-9001-D  cast aluminium + thermally bonded semiconductors -> the mixed case.

The data stays deliberately messy: missing recycled-content values, duplicate
suppliers under different legal forms, and untranslatable German shop-floor
descriptions that the classifier must abstain on.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Any, Sequence

SEED = 4470

# (description, joining_method, mass_range, recycled_choices, substances)
# recycled_choices containing None models "supplier never sent the evidence".
PartSpec = tuple[str, str, tuple[float, float], Sequence[float | None], Sequence[str]]

_ALU_HOUSING: PartSpec = (
    "ALU EXTR 6060-T6 ANOD housing profile", "screw", (0.6, 1.9), (0.62, 0.45, 0.75), ()
)
_ALU_RAIL: PartSpec = (
    "Aluminium extrusion EN AW-6082 rail", "screw", (0.3, 0.9), (0.45, 0.62, None), ()
)
_ALU_CAST: PartSpec = (
    "ALDC12 die cast aluminium end cap", "clip", (0.25, 0.8), (0.31, None), ()
)
_STEEL_PLATE: PartSpec = (
    "S235JR steel mounting plate", "screw", (0.4, 1.4), (0.75, 0.62), ()
)
_FASTENER: PartSpec = (
    "Stainless 1.4301 fastener M6", "screw", (0.004, 0.03), (0.45, None), ()
)
_HARNESS: PartSpec = (
    "Cu-ETP copper wire harness 2.5mm2", "clip", (0.05, 0.4), (0.31, None), ()
)
_CONNECTOR: PartSpec = (
    "PA66-GF30 connector body", "clip", (0.02, 0.18), (0.0, 0.12, None), ()
)
_COVER: PartSpec = (
    "PP-T20 cover, talc filled", "clip", (0.1, 0.5), (0.12, 0.31, None), ()
)
_BEZEL: PartSpec = (
    "PC/ABS bezel, flame retardant", "clip", (0.03, 0.2), (0.0, None), ("SVHC.BPA",)
)
_POTTING: PartSpec = (
    "Epoxy potting compound, power stage", "potting", (0.08, 0.35), (0.0,), ()
)
_PCBA_BONDED: PartSpec = (
    "PCB assembly, 6-layer control board", "adhesive", (0.04, 0.22), (0.0, None), ()
)
_PCBA_CLIPPED: PartSpec = (
    "PCB assembly, 6-layer control board, clip-retained", "clip", (0.04, 0.22), (0.0, None), ()
)
_GASKET_CLIP: PartSpec = (
    "PA66-GF30 clip-retained potting replacement gasket", "clip", (0.06, 0.3), (0.12, None), ()
)
_MOSFET: PartSpec = (
    "MOSFET power module TO-247", "weld", (0.01, 0.06), (0.0, None), ()
)
_TIM: PartSpec = (
    "Thermal interface pad, silicone", "adhesive", (0.002, 0.02), (0.0, None), ("RoHS.CR6",)
)
# Real ERP extracts are full of these. The classifier must abstain, not guess.
_OPAQUE_1: PartSpec = (
    "SPEZTL-KOMP 44/B ers. 21.09", "screw", (0.01, 0.4), (None,), ()
)
_OPAQUE_2: PartSpec = (
    "Baugruppe kpl. n. Zeichnung 4470-2", "rivet", (0.05, 0.6), (None,), ()
)

PRODUCTS: list[dict[str, Any]] = [
    {
        "product_id": "CM-4470-B",
        "product_name": "EV charge module",
        "lines": 280,
        "bom": [
            _ALU_HOUSING, _ALU_HOUSING, _ALU_RAIL, _STEEL_PLATE, _FASTENER, _FASTENER,
            _HARNESS, _CONNECTOR, _COVER, _BEZEL,
            _POTTING,        # the defect the whole demo is built around
            _PCBA_BONDED, _MOSFET, _TIM, _OPAQUE_1, _OPAQUE_2,
        ],
    },
    {
        "product_id": "CM-4470-C",
        "product_name": "EV charge module, clip-retained housing",
        "lines": 280,
        "bom": [
            _ALU_HOUSING, _ALU_HOUSING, _ALU_RAIL, _STEEL_PLATE, _FASTENER, _FASTENER,
            _HARNESS, _CONNECTOR, _COVER, _BEZEL,
            _GASKET_CLIP,    # potting removed
            _PCBA_CLIPPED,   # adhesive removed
            _MOSFET, _OPAQUE_1, _OPAQUE_2,
        ],
    },
    {
        "product_id": "BR-2210-A",
        "product_name": "Battery retention bracket",
        "lines": 120,
        "bom": [_STEEL_PLATE, _STEEL_PLATE, _ALU_RAIL, _FASTENER, _FASTENER, _OPAQUE_1],
    },
    {
        "product_id": "HS-9001-D",
        "product_name": "Inverter heatsink assembly",
        "lines": 132,
        "bom": [
            _ALU_CAST, _ALU_CAST, _ALU_RAIL, _FASTENER, _HARNESS,
            _MOSFET, _TIM, _PCBA_BONDED, _OPAQUE_2,
        ],
    },
]

# Same companies, different spellings. This is what entity resolution must fix:
# two share a VAT id (identifier-first merge), two differ only by transliterated
# umlaut (fuzzy merge), one has no identifier at all (human review).
SUPPLIERS = [
    ("S-001", "Nordmetall GmbH", "DE", "DE811234567"),
    ("S-002", "NORDMETALL Gmbh & Co KG", "DE", "DE811234567"),
    ("S-003", "Nord Metall", "DE", None),
    ("S-010", "Hexion Speciality Chemicals", "NL", "NL004567890"),
    ("S-011", "Hexion Specialty Chemicals B.V.", "NL", "NL004567890"),
    ("S-020", "Kunststofftechnik S\u00fcd AG", "DE", "DE812345678"),
    ("S-021", "Kunststofftechnik Sued AG", "DE", None),
    ("S-030", "Shenzhen Powerlink Electronics", "CN", None),
    ("S-040", "Alu Profile Werke", "AT", "ATU12345678"),
]


# Suppliers specialise by material family, the way real ones do. Without this
# every supplier ends up with the same profile and the "supplier signals" view
# has nothing to say — the resin supplier must be the one visibly blocking
# recyclability, because that is the decision the buyer has to make.
SUPPLIER_FOR: dict[str, tuple[str, ...]] = {
    "ALU EXTR 6060-T6 ANOD housing profile": ("S-001", "S-002", "S-040"),
    "Aluminium extrusion EN AW-6082 rail": ("S-001", "S-040"),
    "ALDC12 die cast aluminium end cap": ("S-003", "S-001"),
    "S235JR steel mounting plate": ("S-001", "S-002"),
    "Stainless 1.4301 fastener M6": ("S-003",),
    "Cu-ETP copper wire harness 2.5mm2": ("S-030",),
    "PA66-GF30 connector body": ("S-020", "S-021"),
    "PP-T20 cover, talc filled": ("S-020",),
    "PC/ABS bezel, flame retardant": ("S-021",),
    "Epoxy potting compound, power stage": ("S-010", "S-011"),
    "PCB assembly, 6-layer control board": ("S-030",),
    "PCB assembly, 6-layer control board, clip-retained": ("S-030",),
    "PA66-GF30 clip-retained potting replacement gasket": ("S-020",),
    "MOSFET power module TO-247": ("S-030",),
    "Thermal interface pad, silicone": ("S-010",),
    "SPEZTL-KOMP 44/B ers. 21.09": ("S-003", "S-020"),
    "Baugruppe kpl. n. Zeichnung 4470-2": ("S-003",),
}


def build(lines: int | None = None) -> dict[str, Any]:
    rng = random.Random(SEED)
    rows: list[dict[str, Any]] = []
    counter = 0

    for product in PRODUCTS:
        bom: list[PartSpec] = product["bom"]
        target = product["lines"]
        for i in range(target):
            description, joint, (lo, hi), recycled_pool, substances = bom[i % len(bom)]
            counter += 1
            recycled = recycled_pool[rng.randrange(len(recycled_pool))]
            rows.append(
                {
                    "line_id": f"L{counter:04d}",
                    "product_id": product["product_id"],
                    "product_name": product["product_name"],
                    "description": description,
                    "joining_method": joint,
                    "mass_kg": round(rng.uniform(lo, hi), 4),
                    "recycled_fraction": recycled,
                    "substances": list(substances),
                    "supplier_id": (
                        lambda pool: pool[rng.randrange(len(pool))]
                    )(SUPPLIER_FOR.get(description, ("S-003",))),
                    "supplier_name": "",
                    "spend_eur": round(rng.uniform(120, 41000), 2),
                }
            )

    for row in rows:
        match = next(s for s in SUPPLIERS if s[0] == row["supplier_id"])
        row["supplier_name"] = match[1]
        row["supplier_country"] = match[2]
        row["supplier_vat"] = match[3]

    if lines is not None and lines < len(rows):
        rows = rows[:lines]

    return {
        "source_uri": "demo://erp-export/bom_2026_q2.csv",
        "dataset": "demo",
        "rows": rows,
        "suppliers": [
            {"record_id": s[0], "name": s[1], "country": s[2], "vat_id": s[3]} for s in SUPPLIERS
        ],
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Generate the deterministic demo dataset.")
    p.add_argument("--lines", type=int, default=None)
    p.add_argument("--out", type=Path, default=Path(".data/demo_bom.json"))
    args = p.parse_args()

    payload = build(args.lines)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Seeded {len(payload['rows'])} BOM lines → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
