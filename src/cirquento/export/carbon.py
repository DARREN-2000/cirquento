"""Export material facts to carbon platforms (carbmee, Sphera, Cozero).

This module is where the "complementary, not competitive" claim stops being a
positioning slide and becomes a file format.

The contract is deliberately narrow. Cirquento exports **what a product is made
of and how well that is evidenced**, and refuses to emit anything resembling an
emissions figure. Two reasons, both practical:

1. A carbon platform already owns emission factors, allocation rules and an
   audited methodology. A second system quietly publishing its own kg CO₂e is
   how an organisation ends up with two numbers and no answer.
2. Every field here is traceable to a source row. An emissions estimate derived
   from an industry-average factor is not, and mixing the two would destroy the
   provenance guarantee that makes the rest of the export useful.

So the payload carries material mass, recycled fractions, **explicit data-quality
tiers**, and the gaps — the inputs a carbon model needs — and stops there.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

CONTRACT_VERSION = "cirquento.material-facts.v1"

# Data-quality tiers, exported so the receiving system can weight or reject.
# "primary" means a supplier evidenced it; "unclassified" means we could not
# identify the material and are saying so rather than guessing a proxy.
TIERS = ("primary", "secondary", "proxy", "unclassified")


class ExportError(ValueError):
    """Raised when a payload would violate the export contract."""


def _tier(code: str, has_evidence: bool) -> str:
    if not code or code == "UNCLASSIFIED":
        return "unclassified"
    return "primary" if has_evidence else "secondary"


def build_payload(
    passport: Mapping[str, Any], *, source_system: str = "cirquento"
) -> dict[str, Any]:
    """Turn one passport into a carbon-platform material-facts payload."""
    composition = passport.get("materialComposition", {})
    total_mass = float(passport.get("totalMassKg", 0.0))
    gaps = passport.get("dataGaps", {})
    component_count = int(passport.get("componentCount", 0)) or 1
    evidenced = component_count - int(gaps.get("missingRecycledContent", 0))

    materials = []
    for code, pct in sorted(composition.items()):
        materials.append(
            {
                "materialCode": code,
                "massFractionPct": round(float(pct), 4),
                "massKg": round(total_mass * float(pct) / 100.0, 6),
                "dataQuality": _tier(code, evidenced > 0),
            }
        )

    dims = passport.get("dimensions", {})
    payload = {
        "contract": CONTRACT_VERSION,
        "sourceSystem": source_system,
        "productId": passport.get("productId"),
        "productName": passport.get("productName"),
        "rulesetVersion": passport.get("rulesetVersion"),
        # The receiving system can re-request the exact passport this came from.
        "passportContentHash": passport.get("contentHash"),
        "totalMassKg": round(total_mass, 6),
        "materials": materials,
        "recycledContentPct": round(
            float(dims.get("recycled_content", {}).get("value", 0.0)), 4
        ),
        "evidenceCoverage": {
            "componentsTotal": int(passport.get("componentCount", 0)),
            "componentsWithRecycledEvidence": max(evidenced, 0),
            "unclassifiedLines": int(gaps.get("unclassifiedLines", 0)),
        },
        # Stated in the payload, not just the docs, so a downstream integrator
        # cannot accidentally treat this as a carbon feed.
        "excludes": [
            "No emission factors, kg CO2e, GWP or allocation are provided.",
            "Carbon accounting remains the responsibility of the receiving platform.",
        ],
    }
    validate(payload)
    return payload


def build_batch(
    passports: Iterable[Mapping[str, Any]], *, run_content_hash: str | None = None
) -> dict[str, Any]:
    items = [build_payload(p) for p in passports]
    return {
        "contract": CONTRACT_VERSION,
        "runContentHash": run_content_hash,
        "productCount": len(items),
        "products": items,
    }


def validate(payload: Mapping[str, Any]) -> None:
    """Enforce the contract at the boundary.

    Written as explicit checks rather than a schema library so the export path
    keeps working in an environment with no third-party packages installed —
    the same constraint the rest of the offline path honours.
    """
    if payload.get("contract") != CONTRACT_VERSION:
        raise ExportError(f"Unknown contract {payload.get('contract')!r}.")
    if not payload.get("productId"):
        raise ExportError("productId is required; an unattributed payload is unusable.")

    forbidden = {"co2e", "kgco2e", "gwp", "emissions", "carbonFootprint", "pcf"}
    for key in payload:
        if key.lower().replace("_", "") in forbidden:
            raise ExportError(
                f"Field {key!r} looks like a carbon figure. This contract exports material "
                "facts only — emitting a second, unaudited emissions number is the failure "
                "mode it exists to prevent."
            )

    materials = payload.get("materials", [])
    if not isinstance(materials, list):
        raise ExportError("materials must be a list.")
    for m in materials:
        if m.get("dataQuality") not in TIERS:
            raise ExportError(
                f"Material {m.get('materialCode')!r} has data quality "
                f"{m.get('dataQuality')!r}, which is not one of {TIERS}."
            )
        if float(m.get("massFractionPct", 0)) < 0:
            raise ExportError("Negative mass fraction.")

    total_pct = sum(float(m.get("massFractionPct", 0)) for m in materials)
    # Rounding across many lines legitimately drifts; a large gap means the
    # composition is wrong and should not be shipped to another system.
    if materials and abs(total_pct - 100.0) > 1.0:
        raise ExportError(
            f"Material fractions sum to {total_pct:.2f}%, not ~100%. "
            "Refusing to export a composition that does not add up."
        )
