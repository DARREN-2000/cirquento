"""Generate the console's data file from a real pipeline run.

The published demo used to carry hand-written numbers. That is precisely how a
scoring bug survives review: the screenshot says 68, the engine says 1522, and
nobody notices because the two are never compared. So the console now renders
from this file, and this file can only be produced by executing the pipeline.

Emitted as `data.js` (a script assigning `window.CIRQUENTO_DATA`) rather than
`data.json` so the page works when opened from disk, where `fetch()` of a local
JSON file is blocked by CORS. GitHub Pages would serve either; the constraint
is the offline reviewer, and the screenshot test.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path
from typing import Any

# Merge decisions the resolver reached; used to group spend under one identity.
CANON = {"S-002": "S-001", "S-011": "S-010", "S-021": "S-020"}

QUALITY = {
    "S-001": ("Primary · verified", "t-green"),
    "S-010": ("Primary · SDS only", "t-orange"),
    "S-020": ("Primary · unverified", "t-blue"),
    "S-030": ("Proxy · industry avg", "t-grey"),
    "S-003": ("Secondary · unmatched", "t-orange"),
    "S-040": ("Primary · verified", "t-green"),
}


def _signal(recycled: float, coverage: float) -> tuple[str, str]:
    """Turn two measured numbers into the buyer's actual decision."""
    if recycled < 5 and coverage > 80:
        return ("Blocks recycling", "t-red")
    if coverage < 40:
        return ("Request evidence", "t-orange")
    if recycled >= 50:
        return ("Preferred", "t-green")
    return ("Monitor", "t-grey")


def _load_recommendations(path: Path, product_id: str) -> list[dict[str, Any]]:
    """Recommendations are optional input, but never invented here.

    If `cirquento recommend` has not been run, the console simply omits the
    panel. Synthesising plausible-looking advice at render time would recreate
    exactly the hand-written-numbers problem this script exists to remove.
    """
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("products", {}).get(product_id, [])


def _load_review(path: Path) -> dict[str, Any]:
    """Fold the append-only review log into counts for the console."""
    if not path.exists():
        return {"open": 0, "resolved": 0, "items": []}
    opened: dict[str, dict[str, Any]] = {}
    resolved: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        event = json.loads(line)
        if event.get("event") == "resolved":
            resolved.add(event["id"])
        else:
            opened.setdefault(event["id"], event)
    items = [
        {
            "id": eid,
            "subject": ev.get("subject", ""),
            "kind": ev.get("kind", ""),
            "status": "resolved" if eid in resolved else "open",
        }
        for eid, ev in sorted(opened.items(), key=lambda kv: kv[1].get("subject", ""))
    ]
    return {
        "open": sum(1 for i in items if i["status"] == "open"),
        "resolved": len(resolved),
        "items": items[:6],
    }


def build(
    run_path: Path,
    bom_path: Path,
    product_id: str,
    rec_path: Path | None = None,
    review_path: Path | None = None,
) -> dict[str, Any]:
    run = json.loads(run_path.read_text(encoding="utf-8"))
    bom = json.loads(bom_path.read_text(encoding="utf-8"))

    passports = {p["productId"]: p for p in run["passports"]}
    focus = passports[product_id]
    dims = focus["dimensions"]

    rows = [r for r in bom["rows"] if r["product_id"] == product_id]
    names = {s["record_id"]: s["name"] for s in bom["suppliers"]}

    agg: dict[str, dict[str, float]] = collections.defaultdict(
        lambda: {"spend": 0.0, "mass": 0.0, "rec": 0.0, "known": 0.0}
    )
    top_part: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for r in bom["rows"]:
        key = CANON.get(r["supplier_id"], r["supplier_id"])
        a = agg[key]
        a["spend"] += r["spend_eur"]
        a["mass"] += r["mass_kg"]
        top_part[key][r["description"]] += r["mass_kg"]
        if r["recycled_fraction"] is not None:
            a["rec"] += r["mass_kg"] * r["recycled_fraction"]
            a["known"] += r["mass_kg"]

    suppliers = []
    for key, a in sorted(agg.items(), key=lambda kv: -kv[1]["spend"]):
        recycled = 100 * a["rec"] / a["known"] if a["known"] else 0.0
        coverage = 100 * a["known"] / a["mass"] if a["mass"] else 0.0
        label, tone = _signal(recycled, coverage)
        quality, qtone = QUALITY.get(key, ("Unknown", "t-grey"))
        merged = [k for k, v in CANON.items() if v == key]
        suppliers.append(
            {
                "name": names.get(key, key),
                "initials": "".join(w[0] for w in names.get(key, key).split()[:2]).upper(),
                "part": top_part[key].most_common(1)[0][0],
                "spend": f"€{a['spend'] / 1e6:.2f}M",
                "recycled": f"{recycled:.0f}%",
                "coverage": f"{coverage:.0f}%",
                "quality": quality,
                "qualityTone": qtone,
                "signal": label,
                "signalTone": tone,
                "mergedFrom": merged,
            }
        )

    classified = focus["componentCount"] - focus["dataGaps"]["unclassifiedLines"]
    stats = run["classification"]

    comparison = None
    if product_id == "CM-4470-B" and "CM-4470-C" in passports:
        alt = passports["CM-4470-C"]
        comparison = {
            "productId": alt["productId"],
            "score": alt["circularityScore"],
            "delta": round(alt["circularityScore"] - focus["circularityScore"]),
            "disassembly": round(alt["dimensions"]["disassembly"]["value"]),
        }

    return {
        "product": {
            "id": focus["productId"],
            "name": focus["productName"],
            "score": focus["circularityScore"],
            "lines": focus["componentCount"],
            "massKg": focus["totalMassKg"],
            "rulesetVersion": focus["rulesetVersion"],
            "contentHash": focus["contentHash"][:12],
        },
        "run": {
            "hash": run["runContentHash"][:12],
            "bomLines": run["bomLines"],
            "distinctRowKeys": run["distinctRowKeys"],
            "deterministic": stats.get("deterministic", 0),
            "model": stats.get("model", 0),
            "cached": stats.get("cache", 0),
            "review": stats.get("review", 0),
            "merges": len(run["supplierMerges"]),
            "mergeDetail": run["supplierMerges"],
        },
        "kpis": {
            "score": round(focus["circularityScore"]),
            "recycledContent": round(dims["recycled_content"]["value"]),
            "classifiedPct": round(100 * classified / focus["componentCount"]),
            "openGaps": focus["dataGaps"]["unclassifiedLines"],
            "missingRecycled": focus["dataGaps"]["missingRecycledContent"],
        },
        "dimensions": [
            {
                "name": "Recycled content",
                "value": round(dims["recycled_content"]["value"]),
                "weight": dims["recycled_content"]["weight"],
                "findings": dims["recycled_content"]["findings"],
            },
            {
                "name": "Recyclability",
                "value": round(dims["recyclability"]["value"]),
                "weight": dims["recyclability"]["weight"],
                "findings": dims["recyclability"]["findings"],
            },
            {
                "name": "Disassembly",
                "value": round(dims["disassembly"]["value"]),
                "weight": dims["disassembly"]["weight"],
                "findings": dims["disassembly"]["findings"],
            },
            {
                "name": "Substances",
                "value": round(dims["substances"]["value"]),
                "weight": dims["substances"]["weight"],
                "findings": dims["substances"]["findings"],
            },
        ],
        "composition": sorted(
            (
                {"code": code, "pct": pct}
                for code, pct in focus["materialComposition"].items()
                if pct >= 0.5
            ),
            key=lambda x: -x["pct"],
        ),
        "explanation": focus["explanation"],
        "comparison": comparison,
        "suppliers": suppliers[:6],
        "evidenceSample": focus["evidence"][:3],
        "recommendations": _load_recommendations(
            rec_path or Path(".data/recommendations.json"), product_id
        ),
        "review": _load_review(review_path or Path(".data/review_queue.jsonl")),
    }


def main() -> int:
    p = argparse.ArgumentParser(description="Export console data from a pipeline run.")
    p.add_argument("--run", type=Path, default=Path(".data/run_output.json"))
    p.add_argument("--bom", type=Path, default=Path(".data/demo_bom.json"))
    p.add_argument("--product", default="CM-4470-B")
    p.add_argument("--out", type=Path, default=Path("docs/data.js"))
    p.add_argument("--recommendations", type=Path, default=Path(".data/recommendations.json"))
    p.add_argument("--review", type=Path, default=Path(".data/review_queue.jsonl"))
    args = p.parse_args()

    data = build(args.run, args.bom, args.product, args.recommendations, args.review)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        "// GENERATED by scripts/export_console_data.py — do not edit by hand.\n"
        "// Every figure below came out of an executed pipeline run.\n"
        "window.CIRQUENTO_DATA = "
        + json.dumps(data, indent=2, sort_keys=True)
        + ";\n",
        encoding="utf-8",
    )
    print(
        f"Wrote {args.out} (score {data['product']['score']}, "
        f"{data['run']['bomLines']} lines, "
        f"{len(data['recommendations'])} recommendations, "
        f"{data['review']['open']} open reviews)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
