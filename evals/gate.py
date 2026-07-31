"""Eval gate: CI fails if classification quality regresses.

Why a gate and not a dashboard: prompts and models change far more often than
schemas, and a silent regression here ships wrong material codes into signed
regulatory documents. So model/prompt changes are treated exactly like schema
migrations — they must prove they did not break the golden set.

The non-obvious threshold is `--min-abstention`. A model whose abstention rate
collapses looks better on accuracy while being strictly more dangerous: it has
stopped admitting uncertainty on the ambiguous rows a human should see.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Thresholds:
    min_f1: float
    min_abstention: float
    max_abstention: float
    max_offtaxonomy: float


@dataclass(frozen=True, slots=True)
class Report:
    f1: float
    precision: float
    recall: float
    abstention_rate: float
    offtaxonomy_rate: float
    evidence_fabrication_rate: float
    n: int

    @classmethod
    def load(cls, path: Path) -> "Report":
        data = json.loads(path.read_text())
        return cls(**{k: data[k] for k in cls.__annotations__})


def evaluate(report: Report, t: Thresholds) -> list[str]:
    failures: list[str] = []

    if report.f1 < t.min_f1:
        failures.append(f"F1 {report.f1:.3f} < required {t.min_f1:.3f}")

    if report.abstention_rate < t.min_abstention:
        failures.append(
            f"Abstention rate {report.abstention_rate:.3f} < {t.min_abstention:.3f}: "
            "the model stopped admitting uncertainty, which pushes ambiguous rows "
            "past human review and into signed passports."
        )
    if report.abstention_rate > t.max_abstention:
        failures.append(
            f"Abstention rate {report.abstention_rate:.3f} > {t.max_abstention:.3f}: "
            "the review queue would grow faster than humans can clear it."
        )

    if report.offtaxonomy_rate > t.max_offtaxonomy:
        failures.append(
            f"Off-taxonomy outputs {report.offtaxonomy_rate:.3f} > {t.max_offtaxonomy:.3f}: "
            "schema constraint is leaking."
        )

    # Not configurable on purpose: a fabricated evidence span means the passport
    # cannot quote its own source, which defeats the point of the product.
    if report.evidence_fabrication_rate > 0:
        failures.append(
            f"Fabricated evidence spans in {report.evidence_fabrication_rate:.3f} of answers. "
            "This is never acceptable."
        )

    return failures


def main() -> int:
    p = argparse.ArgumentParser(description="Enforce classification eval thresholds.")
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--min-f1", type=float, default=0.91)
    p.add_argument("--min-abstention", type=float, default=0.03)
    p.add_argument("--max-abstention", type=float, default=0.18)
    p.add_argument("--max-offtaxonomy", type=float, default=0.0)
    args = p.parse_args()

    report = Report.load(args.report)
    failures = evaluate(
        report,
        Thresholds(args.min_f1, args.min_abstention, args.max_abstention, args.max_offtaxonomy),
    )

    print(f"Golden set: {report.n} labelled BOM lines")
    print(f"  F1 {report.f1:.3f} | P {report.precision:.3f} | R {report.recall:.3f}")
    print(f"  abstention {report.abstention_rate:.3f} | off-taxonomy {report.offtaxonomy_rate:.3f}")

    if failures:
        print("\nEVAL GATE FAILED")
        for f in failures:
            print(f"  × {f}")
        return 1

    print("\nEVAL GATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
