"""Offline classification backend.

The public demo, the tests and CI must run with no API key and no network.
Rather than mocking inside the test suite only, offline mode is a real backend
with the same contract as the live one — so the code path exercised in CI is
the code path that runs in production, minus the provider call.

It replays recorded provider responses when a fixture exists, and otherwise
falls back to a conservative keyword mapper that **abstains whenever it is not
sure**. That keeps the demo honest: the offline run produces genuine review
items and genuine data gaps rather than a suspiciously perfect dataset.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel

from cirquento.classify.taxonomy import Taxonomy, TaxonomyCode

# Weak signals: enough to guess, not enough to be certain. Deliberately not the
# same table as the deterministic aliases in taxonomy.py, which are exact.
_HINTS: Mapping[str, tuple[TaxonomyCode, float]] = {
    "alu": (TaxonomyCode.ALU_WROUGHT, 0.81),
    "aluminium": (TaxonomyCode.ALU_WROUGHT, 0.86),
    "steel": (TaxonomyCode.STEEL_CARBON, 0.79),
    "stainless": (TaxonomyCode.STEEL_STAINLESS, 0.88),
    "copper": (TaxonomyCode.CU_WIRE, 0.84),
    "harness": (TaxonomyCode.CU_WIRE, 0.74),
    "polyamide": (TaxonomyCode.PA66_GF30, 0.83),
    "nylon": (TaxonomyCode.PA66_GF30, 0.76),
    "polypropylene": (TaxonomyCode.PP_TALC, 0.8),
    "abs": (TaxonomyCode.ABS, 0.75),
    "epoxy": (TaxonomyCode.EPOXY, 0.9),
    "potting": (TaxonomyCode.EPOXY, 0.87),
    "pcb": (TaxonomyCode.PCBA, 0.85),
    "board": (TaxonomyCode.PCBA, 0.71),
    "mosfet": (TaxonomyCode.SEMI, 0.86),
    "semiconductor": (TaxonomyCode.SEMI, 0.88),
    "carbon fibre": (TaxonomyCode.CFRP, 0.89),
}


class OfflineLLM:
    """Implements the LLMClient protocol without a network call."""

    def __init__(self, fixture: str | Path | None = None) -> None:
        self._fixtures: dict[str, dict[str, object]] = {}
        self._taxonomy = Taxonomy()
        if fixture and Path(fixture).exists():
            for line in Path(fixture).read_text(encoding="utf-8").splitlines():
                if line.strip():
                    row = json.loads(line)
                    self._fixtures[Taxonomy.normalize(row["description"])] = row["response"]

    async def structured(
        self, *, system: str, user: str, schema: type[BaseModel]
    ) -> BaseModel:
        description = self._extract_description(user)
        key = Taxonomy.normalize(description)

        if key in self._fixtures:
            # Recorded provider output, replayed verbatim — including any
            # recorded failures, which is the point of keeping them.
            return schema.model_validate(self._fixtures[key])

        for hint, (code, confidence) in sorted(_HINTS.items(), key=lambda kv: -len(kv[0])):
            if hint in key:
                span = self._span_for(description, hint)
                return schema.model_validate(
                    {
                        "code": code.value,
                        "confidence": confidence,
                        "evidence_span": span,
                        "reasoning": f"Offline backend matched the term '{hint}'.",
                    }
                )

        # Nothing recognised: abstain. This is the correct answer, not a failure.
        return schema.model_validate(
            {
                "code": None,
                "confidence": 0.0,
                "evidence_span": "",
                "reasoning": "Offline backend recognised no term in the closed taxonomy.",
            }
        )

    @staticmethod
    def _extract_description(user_prompt: str) -> str:
        for line in user_prompt.splitlines():
            if line.startswith("Description: "):
                return line.removeprefix("Description: ")
        return user_prompt.strip()

    @staticmethod
    def _span_for(description: str, hint: str) -> str:
        """Return a span copied verbatim from the input.

        The classifier rejects evidence it cannot find in the source, so the
        offline backend must respect the same rule the live model is held to.
        """
        lowered = description.lower()
        idx = lowered.find(hint)
        if idx < 0:
            return ""
        start = max(0, idx - 12)
        end = min(len(description), idx + len(hint) + 12)
        return description[start:end]
