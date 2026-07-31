"""Constrained material classification.

Design rule for the whole platform: **the model may propose, only rules may
decide.**  This module is the single place where an LLM touches regulated data,
so it is deliberately paranoid:

1. The output schema is generated from the *closed* material taxonomy, so an
   off-taxonomy answer cannot be parsed and therefore cannot be persisted.
2. Abstention is a first-class, rewarded outcome.  A model that never says
   "I don't know" is more dangerous than one that does.
3. Every accepted classification carries the evidence span it was derived from,
   so the passport can point an auditor at the exact source text.
4. Calls are cached by normalized description hash: 1M BOM lines collapse to
   roughly 11k distinct descriptions, which is what makes this affordable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Protocol


from cirquento.classify.cache import ClassificationCache
from cirquento.classify.taxonomy import Taxonomy, TaxonomyCode
from cirquento.observability import tracer

# Below this the answer is not trusted; it is routed to a human instead of
# silently entering a regulated document.  Calibrated on evals/golden_set.jsonl.
CONFIDENCE_FLOOR = 0.72


try:
    from pydantic import BaseModel, Field, ValidationError

    class MaterialProposal(BaseModel):
        """What the model is allowed to return. Anything else is a hard failure."""

        code: TaxonomyCode | None = Field(
            default=None, description="Closed-vocabulary material code, or null to abstain."
        )
        confidence: float = Field(ge=0.0, le=1.0)
        evidence_span: str = Field(
            default="",
            max_length=240,
            description="Verbatim substring of the input that justifies the code.",
        )
        reasoning: str = Field(default="", max_length=400)
except ImportError:
    # Zero-dependency offline fallback. The LLM is never called in this mode;
    # all classifications are satisfied from the cache or deterministic rules.
    BaseModel = object  # type: ignore
    ValidationError = Exception  # type: ignore
    class MaterialProposal: pass  # type: ignore


@dataclass(frozen=True, slots=True)
class Classification:
    code: TaxonomyCode | None
    confidence: float
    evidence_span: str
    reasoning: str
    abstained: bool
    needs_review: bool
    source: str  # "cache" | "model" | "deterministic"


class LLMClient(Protocol):
    async def structured(
        self, *, system: str, user: str, schema: type[BaseModel]
    ) -> BaseModel: ...


SYSTEM_PROMPT = """You map free-text manufacturing material descriptions onto a closed taxonomy.

Rules:
- Return a code ONLY if the description explicitly supports it.
- If the description is ambiguous, truncated, a trade name you do not recognise,
  or could map to more than one code, return code=null. Abstaining is correct
  behaviour and is never penalised.
- evidence_span must be copied verbatim from the input. Never paraphrase it.
- Never infer recycled content, recyclability or any regulatory conclusion.
  You classify material identity only."""


class MaterialClassifier:
    def __init__(
        self,
        llm: LLMClient,
        taxonomy: Taxonomy,
        cache: ClassificationCache,
        confidence_floor: float = CONFIDENCE_FLOOR,
    ) -> None:
        self._llm = llm
        self._taxonomy = taxonomy
        self._cache = cache
        self._floor = confidence_floor

    @staticmethod
    def _key(description: str) -> str:
        normalized = " ".join(description.lower().split())
        return hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    async def classify(self, description: str, *, uom: str | None = None) -> Classification:
        with tracer.start_as_current_span("classify.material") as span:
            key = self._key(description)
            span.set_attribute("cirquento.cache_key", key)

            # 1. Exact deterministic hits never reach the model. Cheaper, and
            #    a known code should not be re-litigated by a probabilistic system.
            if direct := self._taxonomy.exact_match(description):
                return Classification(
                    code=direct,
                    confidence=1.0,
                    evidence_span=description[:240],
                    reasoning="Exact taxonomy match.",
                    abstained=False,
                    needs_review=False,
                    source="deterministic",
                )

            if cached := await self._cache.get(key):
                span.set_attribute("cirquento.cache_hit", True)
                return cached

            user = f"Description: {description}"
            if uom:
                user += f"\nUnit of measure: {uom}"
            user += f"\n\nAllowed codes:\n{self._taxonomy.render_for_prompt()}"

            try:
                proposal = await self._llm.structured(
                    system=SYSTEM_PROMPT, user=user, schema=MaterialProposal
                )
            except ValidationError:
                # Off-taxonomy or malformed output. This is not a retry case:
                # a model that cannot answer inside the schema must not be
                # coaxed into one. Send it to a human.
                return self._review("Model returned an off-taxonomy answer.")

            assert isinstance(proposal, MaterialProposal)

            if proposal.code is None:
                result = self._review("Model abstained.", abstained=True)
            elif proposal.confidence < self._floor:
                result = self._review(
                    f"Confidence {proposal.confidence:.2f} below floor {self._floor:.2f}."
                )
            elif proposal.evidence_span and proposal.evidence_span not in description:
                # Fabricated evidence invalidates the answer even if the code
                # happens to be right: the passport must be able to quote it.
                result = self._review("Evidence span not found verbatim in input.")
            else:
                result = Classification(
                    code=proposal.code,
                    confidence=proposal.confidence,
                    evidence_span=proposal.evidence_span,
                    reasoning=proposal.reasoning,
                    abstained=False,
                    needs_review=False,
                    source="model",
                )

            await self._cache.put(key, result)
            span.set_attribute("cirquento.needs_review", result.needs_review)
            return result

    @staticmethod
    def _review(reason: str, *, abstained: bool = False) -> Classification:
        return Classification(
            code=None,
            confidence=0.0,
            evidence_span="",
            reasoning=reason,
            abstained=abstained,
            needs_review=True,
            source="model",
        )
