"""Digital Product Passport builder.

The passport is the regulated artefact, so this module has two hard rules:

1. **Nothing here computes a score.** It only serialises what the rule engine
   already decided, together with the evidence that supports it.
2. **The output is canonical.** Keys sorted, no wall-clock values inside the
   hashed body, so two replays of the same run hash identically. The hash is
   what a signature is taken over, and what `make replay` asserts on.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Sequence

from cirquento.rules.engine import CircularityResult, Component

CONTEXT = {
    "@vocab": "https://cirquento.dev/dpp#",
    "espr": "https://ec.europa.eu/espr#",
    "schema": "https://schema.org/",
}


@dataclass(frozen=True, slots=True)
class Passport:
    product_id: str
    product_name: str
    body: dict[str, Any]

    @property
    def content_hash(self) -> str:
        canonical = json.dumps(self.body, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def to_jsonld(self, *, issued_at: str | None = None) -> dict[str, Any]:
        """Wrap the hashed body with non-hashed envelope metadata.

        `issued_at` sits OUTSIDE the hashed body on purpose: the passport's
        identity is its content, not the moment it was printed.
        """
        doc: dict[str, Any] = {"@context": CONTEXT, **self.body}
        doc["contentHash"] = self.content_hash
        if issued_at:
            doc["issuedAt"] = issued_at
        return doc


def _f(value: Decimal, places: int = 2) -> float:
    return float(round(value, places))


class PassportBuilder:
    def build(
        self,
        *,
        product_id: str,
        product_name: str,
        components: Sequence[Component],
        result: CircularityResult,
        unresolved_lines: Sequence[str] = (),
    ) -> Passport:
        total_mass = sum((c.mass_kg for c in components), Decimal(0))

        composition: dict[str, Decimal] = {}
        for c in components:
            key = c.material_code or "UNCLASSIFIED"
            composition[key] = composition.get(key, Decimal(0)) + c.mass_kg

        dimensions = {
            d.dimension: {
                "value": _f(d.value),
                "weight": _f(d.weight, 4),
                "findings": list(d.findings),
            }
            for d in result.dimensions
        }

        body = {
            "@type": "DigitalProductPassport",
            "productId": product_id,
            "productName": product_name,
            "rulesetVersion": result.ruleset_version,
            "componentCount": len(components),
            "totalMassKg": _f(total_mass, 4),
            "circularityScore": _f(result.score, 0),
            "dimensions": dimensions,
            "materialComposition": {
                code: _f((mass / total_mass) * 100) if total_mass else 0.0
                for code, mass in sorted(composition.items())
            },
            # Gaps are published, not hidden. An auditor comparing two suppliers
            # needs to see which one actually has evidence.
            "dataGaps": {
                "unclassifiedLines": len(unresolved_lines),
                "missingRecycledContent": sum(
                    1 for c in components if c.recycled_fraction is None
                ),
            },
            "evidence": result.evidence.as_list(),
            "explanation": result.explain(),
        }
        return Passport(product_id=product_id, product_name=product_name, body=body)
