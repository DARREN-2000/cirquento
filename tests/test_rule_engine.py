"""Rule-engine tests.

These are the tests that matter: the rule engine produces the numbers that end
up in a regulated document, so its edge cases are specified here rather than
discovered in an audit.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from cirquento.rules.engine import Component, RuleEngine
from cirquento.rules.spec import RuleSet


@pytest.fixture
def engine() -> RuleEngine:
    return RuleEngine(RuleSet.load("rules/circularity.v3.yaml"))


def comp(line_id: str, **kw) -> Component:
    base = dict(
        material_code="MET.ALU.WROUGHT",
        mass_kg=Decimal("1"),
        recycled_fraction=Decimal("0.5"),
        joining_method="screw",
    )
    return Component(line_id=line_id, **{**base, **kw})


def test_unknown_recycled_content_counts_as_zero_not_average(engine: RuleEngine) -> None:
    """A missing value must never be imputed upward.

    Imputing the average would let a supplier improve a product's score by
    refusing to send data, which inverts the incentive the regulation creates.
    """
    known = comp("a", recycled_fraction=Decimal("1.0"))
    unknown = comp("b", recycled_fraction=None)
    result = engine.score([known, unknown])
    dim = next(d for d in result.dimensions if d.dimension == "recycled_content")
    assert dim.value == Decimal(50)  # not 100
    assert "counted as 0%" in dim.findings[0]


def test_one_potted_joint_caps_the_whole_assembly(engine: RuleEngine) -> None:
    """Disassembly is a minimum, not an average — the weakest joint decides."""
    result = engine.score([comp("a"), comp("b"), comp("c", joining_method="potting")])
    dim = next(d for d in result.dimensions if d.dimension == "disassembly")
    assert dim.value == Decimal(5)
    assert any("not reversibly separable" in f for f in dim.findings)


def test_empty_bom_scores_zero_and_does_not_divide_by_zero(engine: RuleEngine) -> None:
    result = engine.score([])
    assert result.score == Decimal(0)


def test_scoring_is_deterministic_across_input_order(engine: RuleEngine) -> None:
    """Replay guarantee: row order in an ERP export must not move the score."""
    comps = [comp("a"), comp("b", joining_method="weld"), comp("c", mass_kg=Decimal("3"))]
    assert engine.score(comps).score == engine.score(list(reversed(comps))).score


def test_substances_of_concern_penalise_and_are_reported(engine: RuleEngine) -> None:
    result = engine.score([comp("a", substances=["SVHC.DEHP"])])
    dim = next(d for d in result.dimensions if d.dimension == "substances")
    assert dim.value == Decimal(80)
    assert "SVHC.DEHP" in dim.findings[0]


def test_counterfactual_uses_the_same_engine_as_the_real_score(engine: RuleEngine) -> None:
    """A recommendation must promise exactly what we would actually report."""
    comps = [comp("a"), comp("b", joining_method="potting")]
    before = engine.score(comps)
    after = engine.counterfactual(comps, {"b": "clip"})
    assert after.score > before.score
    assert after.score == engine.score([comp("a"), comp("b", joining_method="clip")]).score


def test_ruleset_version_is_recorded_on_every_result(engine: RuleEngine) -> None:
    assert engine.score([comp("a")]).ruleset_version == "circularity.v3"
