"""Deterministic rule engine.

Every regulated number in a passport is produced here, never by a model.
Rules live in versioned YAML (`rules/*.yaml`) so that a passport can record
*which* version of the logic produced it — an auditor in 2029 must be able to
replay a 2027 passport and get the identical result.

The engine is intentionally boring: pure functions, no I/O, no network.  That
is what makes `make eval` and byte-identical replays possible.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Mapping, Sequence

from cirquento.evidence import Evidence, EvidenceRef
from cirquento.rules.spec import RuleSet, ScoreDimension


@dataclass(frozen=True, slots=True)
class Component:
    """One resolved BOM line, after classification."""

    line_id: str
    material_code: str
    mass_kg: Decimal
    recycled_fraction: Decimal | None
    joining_method: str  # "screw" | "clip" | "weld" | "adhesive" | "potting"
    substances: Sequence[str] = ()
    supplier_id: str | None = None
    evidence: Sequence[EvidenceRef] = ()


@dataclass(slots=True)
class DimensionResult:
    dimension: str
    value: Decimal  # 0..100
    weight: Decimal
    findings: list[str] = field(default_factory=list)
    evidence: list[EvidenceRef] = field(default_factory=list)


@dataclass(slots=True)
class CircularityResult:
    score: Decimal
    ruleset_version: str
    dimensions: list[DimensionResult]
    evidence: Evidence

    def explain(self) -> str:
        worst = min(self.dimensions, key=lambda d: d.value)
        lead = f"Score {self.score:.0f}/100 under ruleset {self.ruleset_version}."
        if not worst.findings:
            return lead
        return f"{lead} Held back by {worst.dimension}: {worst.findings[0]}"


class RuleEngine:
    def __init__(self, ruleset: RuleSet) -> None:
        self._rs = ruleset

    # -- individual dimensions -------------------------------------------------

    def _recycled_content(self, components: Sequence[Component]) -> DimensionResult:
        """Mass-weighted recycled fraction.

        Unknown fractions count as ZERO, never as the average. Optimistic
        imputation is how a platform ends up defending a number it cannot
        evidence; a gap must look like a gap.
        """
        total = sum((c.mass_kg for c in components), Decimal(0))
        if total == 0:
            return DimensionResult("recycled_content", Decimal(0), self._rs.weight("recycled_content"),
                                   ["No mass data on any component."])
        recycled = sum(
            (c.mass_kg * (c.recycled_fraction or Decimal(0)) for c in components), Decimal(0)
        )
        unknown = [c.line_id for c in components if c.recycled_fraction is None]
        findings = []
        if unknown:
            findings.append(
                f"{len(unknown)} component(s) have no recycled-content evidence and are counted as 0%."
            )
        return DimensionResult(
            "recycled_content",
            (recycled / total) * 100,
            self._rs.weight("recycled_content"),
            findings,
            [e for c in components for e in c.evidence],
        )

    def _disassembly(self, components: Sequence[Component]) -> DimensionResult:
        """Separability of the assembly.

        A single non-reversible joint between two different material families
        can make an otherwise recyclable product unrecyclable, so this is a
        *minimum*, not an average. Averaging here would hide exactly the defect
        the regulation is trying to surface.
        """
        scores: list[Decimal] = []
        findings: list[str] = []
        for c in components:
            joint_score = self._rs.joint_score(c.joining_method)
            scores.append(joint_score)
            if joint_score < self._rs.separability_floor:
                findings.append(
                    f"Line {c.line_id}: '{c.joining_method}' joint is not reversibly separable."
                )
        value = min(scores) if scores else Decimal(0)
        return DimensionResult("disassembly", value, self._rs.weight("disassembly"), findings)

    def _substances(self, components: Sequence[Component]) -> DimensionResult:
        if not components:
            # Nothing to inspect is not the same as nothing to declare. Scoring
            # a full 100 here let an empty BOM earn 15/100 overall.
            return DimensionResult(
                "substances",
                Decimal(0),
                self._rs.weight("substances"),
                ["No components supplied; substance screening could not be performed."],
            )
        flagged = {
            (c.line_id, s)
            for c in components
            for s in c.substances
            if s in self._rs.substances_of_concern
        }
        value = Decimal(100) if not flagged else max(
            Decimal(0), Decimal(100) - Decimal(len(flagged)) * self._rs.substance_penalty
        )
        findings = [f"Line {lid}: substance of concern '{s}'." for lid, s in sorted(flagged)]
        return DimensionResult("substances", value, self._rs.weight("substances"), findings)

    def _recyclability(self, components: Sequence[Component]) -> DimensionResult:
        total = sum((c.mass_kg for c in components), Decimal(0))
        if total == 0:
            return DimensionResult("recyclability", Decimal(0), self._rs.weight("recyclability"))
        # Recyclability rates in the YAML are already on a 0-100 scale, so the
        # mass-weighted mean IS the dimension value. Multiplying by 100 here
        # (the original bug) produced scores of ~1500/100.
        recyclable = sum(
            (c.mass_kg * self._rs.recyclability(c.material_code) for c in components), Decimal(0)
        )
        unclassified = [c.line_id for c in components if not c.material_code]
        findings: list[str] = []
        if unclassified:
            findings.append(
                f"{len(unclassified)} line(s) could not be classified and score 0% recyclable."
            )
        return DimensionResult(
            "recyclability", recyclable / total, self._rs.weight("recyclability"), findings
        )

    # -- entry point -----------------------------------------------------------

    def score(self, components: Sequence[Component]) -> CircularityResult:
        if not components:
            # An unscoreable product scores zero, never a default. Anything else
            # rewards submitting an empty extract.
            return CircularityResult(
                score=Decimal(0),
                ruleset_version=self._rs.version,
                dimensions=[
                    DimensionResult(d, Decimal(0), self._rs.weight(d), ["No components supplied."])
                    for d in (
                        "recycled_content", "recyclability", "disassembly", "substances",
                    )
                ],
                evidence=Evidence(),
            )
        dims = [
            self._recycled_content(components),
            self._recyclability(components),
            self._disassembly(components),
            self._substances(components),
        ]
        weight_total = sum((d.weight for d in dims), Decimal(0))
        weighted = sum((d.value * d.weight for d in dims), Decimal(0))
        score = (weighted / weight_total) if weight_total else Decimal(0)
        # Invariant, not a clamp-and-hope: every dimension is defined on 0-100
        # and the score is a convex combination of them, so a value outside the
        # range means a rule file and the engine disagree about units. Fail
        # loudly rather than publish a nonsense number into a passport.
        if not (Decimal(0) <= score <= Decimal(100)):
            raise ValueError(
                f"Ruleset {self._rs.version} produced an out-of-range score ({score}); "
                "check that every dimension is expressed on a 0-100 scale."
            )
        return CircularityResult(
            score=score.quantize(Decimal("1")),
            ruleset_version=self._rs.version,
            dimensions=dims,
            evidence=Evidence.merge(d.evidence for d in dims),
        )

    def counterfactual(
        self, components: Sequence[Component], swaps: Mapping[str, str]
    ) -> CircularityResult:
        """'What if we changed these joints?' — the recommendation engine.

        Recommendations are produced by re-running the same deterministic
        engine on a modified input, not by asking a model what it thinks would
        help. That way the promised improvement is the number we would actually
        report if the change shipped.
        """
        modified = [
            replace(c, joining_method=swaps[c.line_id]) if c.line_id in swaps else c
            for c in components
        ]
        return self.score(modified)
