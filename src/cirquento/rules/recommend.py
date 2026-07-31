"""Ranked recommendations, produced by re-running the engine.

The product's whole claim is that it explains itself, so a recommendation may
never be a model's opinion about what would probably help. Every item here is a
**counterfactual**: modify the input, re-score with the same deterministic
engine, report the delta that would actually appear in the passport if the
change shipped.

Two classes of recommendation, deliberately kept apart:

* **Design changes** (`kind="design"`) — a real score delta. Swap a joint, drop
  a substance. If you do this, the number moves.
* **Evidence requests** (`kind="evidence"`) — a *conditional* upside, never a
  score change. "If this supplier confirms recycled content at the rate their
  other lines already evidence, the score could reach X." Presenting this as an
  achieved improvement would be exactly the optimistic imputation the engine
  refuses everywhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Sequence

from cirquento.rules.engine import Component, RuleEngine
from cirquento.rules.spec import RuleSet


@dataclass(frozen=True, slots=True)
class Recommendation:
    kind: str  # "design" | "evidence"
    action: str
    target: str
    score_before: Decimal
    score_after: Decimal
    delta: Decimal
    lines_affected: int
    conditional: bool
    rationale: str

    def as_dict(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "action": self.action,
            "target": self.target,
            "scoreBefore": float(round(self.score_before, 0)),
            "scoreAfter": float(round(self.score_after, 0)),
            "delta": float(round(self.delta, 0)),
            "linesAffected": self.lines_affected,
            "conditional": self.conditional,
            "rationale": self.rationale,
        }


class Recommender:
    def __init__(self, engine: RuleEngine, ruleset: RuleSet) -> None:
        self._engine = engine
        self._rs = ruleset

    # -- helpers ---------------------------------------------------------------

    def _best_reversible_joint(self) -> str:
        """The highest-scoring joint the ruleset knows about.

        Read from the ruleset rather than hardcoded, so that changing the
        regulatory logic changes the advice, which is the entire reason the
        rules live in versioned YAML.
        """
        joints = self._rs.joints
        return max(joints, key=lambda j: joints[j])

    # -- recommendation families -----------------------------------------------

    def _joint_swaps(
        self, components: Sequence[Component], base: Decimal
    ) -> list[Recommendation]:
        """Disassembly is a min(), so the unit of action is a joint *type*.

        Fixing a single potted line while nine others remain potted moves the
        score by exactly zero. Recommending it would be technically true and
        practically useless, so joints are grouped by method.
        """
        target = self._best_reversible_joint()
        offenders: dict[str, list[str]] = {}
        for c in components:
            if self._rs.joint_score(c.joining_method) < self._rs.separability_floor:
                offenders.setdefault(c.joining_method, []).append(c.line_id)

        out: list[Recommendation] = []
        for method, line_ids in sorted(offenders.items()):
            swaps = {lid: target for lid in line_ids}
            after = self._engine.counterfactual(components, swaps).score
            out.append(
                Recommendation(
                    kind="design",
                    action=f"Replace every '{method}' joint with '{target}'",
                    target=method,
                    score_before=base,
                    score_after=after,
                    delta=after - base,
                    lines_affected=len(line_ids),
                    conditional=False,
                    rationale=(
                        f"{len(line_ids)} line(s) use '{method}', which scores "
                        f"{self._rs.joint_score(method)}/100 against a separability floor of "
                        f"{self._rs.separability_floor}. Disassembly is scored as a minimum, so "
                        f"these lines cap the whole assembly."
                    ),
                )
            )

        # The bundle: fix every non-separable joint at once. Often the only
        # option that actually moves a min(), which individual swaps hide.
        if len(offenders) > 1:
            all_lines = [lid for ids in offenders.values() for lid in ids]
            swaps = {lid: target for lid in all_lines}
            after = self._engine.counterfactual(components, swaps).score
            out.append(
                Recommendation(
                    kind="design",
                    action=f"Replace all non-separable joints with '{target}'",
                    target="all joints below the separability floor",
                    score_before=base,
                    score_after=after,
                    delta=after - base,
                    lines_affected=len(all_lines),
                    conditional=False,
                    rationale=(
                        "Disassembly is a minimum over joints, so partial fixes can score "
                        "identically to no fix. This is the bundle that actually lifts the floor."
                    ),
                )
            )
        return out

    def _substance_removal(
        self, components: Sequence[Component], base: Decimal
    ) -> list[Recommendation]:
        flagged: dict[str, list[str]] = {}
        for c in components:
            for s in c.substances:
                if s in self._rs.substances_of_concern:
                    flagged.setdefault(s, []).append(c.line_id)

        out: list[Recommendation] = []
        for substance, line_ids in sorted(flagged.items()):
            ids = set(line_ids)
            modified = [
                replace(c, substances=tuple(s for s in c.substances if s != substance))
                if c.line_id in ids
                else c
                for c in components
            ]
            after = self._engine.score(modified).score
            out.append(
                Recommendation(
                    kind="design",
                    action=f"Substitute the material carrying '{substance}'",
                    target=substance,
                    score_before=base,
                    score_after=after,
                    delta=after - base,
                    lines_affected=len(line_ids),
                    conditional=False,
                    rationale=(
                        f"'{substance}' is on the substances-of-concern list and appears on "
                        f"{len(line_ids)} line(s), each costing "
                        f"{self._rs.substance_penalty} points of the substances dimension."
                    ),
                )
            )
        return out

    def _evidence_requests(
        self, components: Sequence[Component], base: Decimal
    ) -> list[Recommendation]:
        """Quantify what closing a data gap is worth — as a conditional.

        The upside is modelled at the rate the supplier's *own evidenced* lines
        already demonstrate. If a supplier has evidenced nothing, no upside is
        claimed at all: there is no defensible basis for a number.
        """
        by_supplier: dict[str, list[Component]] = {}
        for c in components:
            by_supplier.setdefault(c.supplier_id or "UNKNOWN", []).append(c)

        out: list[Recommendation] = []
        for supplier, comps in sorted(by_supplier.items()):
            missing = [c for c in comps if c.recycled_fraction is None]
            known = [c for c in comps if c.recycled_fraction is not None]
            if not missing or not known:
                continue

            known_mass = sum((c.mass_kg for c in known), Decimal(0))
            if known_mass == 0:
                continue
            evidenced_rate = (
                sum((c.mass_kg * (c.recycled_fraction or Decimal(0)) for c in known), Decimal(0))
                / known_mass
            )

            gap_ids = {c.line_id for c in missing}
            modified = [
                replace(c, recycled_fraction=evidenced_rate) if c.line_id in gap_ids else c
                for c in components
            ]
            after = self._engine.score(modified).score
            if after <= base:
                continue
            out.append(
                Recommendation(
                    kind="evidence",
                    action=f"Request recycled-content evidence from supplier {supplier}",
                    target=supplier,
                    score_before=base,
                    score_after=after,
                    delta=after - base,
                    lines_affected=len(missing),
                    conditional=True,
                    rationale=(
                        f"{len(missing)} line(s) from {supplier} have no recycled-content "
                        f"evidence and are scored at 0%. Their evidenced lines average "
                        f"{evidenced_rate * 100:.0f}%. This is an upside IF the evidence "
                        f"arrives and confirms that rate — the score does not move until it does."
                    ),
                )
            )
        return out

    # -- entry point -----------------------------------------------------------

    def recommend(
        self, components: Sequence[Component], *, top_n: int = 6
    ) -> list[Recommendation]:
        base = self._engine.score(components).score
        items = [
            *self._joint_swaps(components, base),
            *self._substance_removal(components, base),
            *self._evidence_requests(components, base),
        ]
        # Real deltas outrank conditional ones at equal value: a change you can
        # make beats a change you have to ask someone else to justify.
        items.sort(key=lambda r: (-r.delta, r.conditional, r.action))
        return [r for r in items if r.delta > 0][:top_n]
