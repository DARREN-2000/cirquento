"""Produce the classification eval report that `evals/gate.py` judges.

Runs the real classifier over a labelled golden set. Two measurements matter
more than accuracy:

* **abstention rate** — rows the classifier refused to answer. The golden set
  deliberately contains untranslatable shop-floor descriptions where abstaining
  is the *correct* answer, so this number should never fall to zero.
* **evidence fabrication rate** — answers whose quoted span is not present
  verbatim in the input. The gate treats any value above zero as a hard fail.

Abstentions are excluded from precision/recall rather than counted as errors:
refusing to guess is a correct behaviour, not a miss. They are governed by
their own threshold instead.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from cirquento.classify.cache import ClassificationCache
from cirquento.classify.classifier import MaterialClassifier
from cirquento.classify.offline import OfflineLLM
from cirquento.classify.taxonomy import Taxonomy, TaxonomyCode

VALID_CODES = {c.value for c in TaxonomyCode}


async def run(golden_path: Path, out_path: Path) -> dict[str, Any]:
    rows = [
        json.loads(line)
        for line in golden_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    classifier = MaterialClassifier(
        llm=OfflineLLM(fixture="evals/fixtures/responses.jsonl"),
        taxonomy=Taxonomy(),
        cache=ClassificationCache(None),  # never cache an eval run
    )

    answered = 0
    correct = 0
    abstained = 0
    offtaxonomy = 0
    fabricated = 0
    answerable = sum(1 for r in rows if r["label"] is not None)
    mistakes: list[dict[str, Any]] = []

    for row in rows:
        outcome = await classifier.classify(row["description"])
        predicted = outcome.code.value if outcome.code else None

        if predicted is not None and predicted not in VALID_CODES:
            offtaxonomy += 1
        if outcome.evidence_span and outcome.evidence_span not in row["description"]:
            fabricated += 1

        if outcome.abstained or predicted is None:
            abstained += 1
            continue

        answered += 1
        if predicted == row["label"]:
            correct += 1
        else:
            mistakes.append(
                {
                    "description": row["description"],
                    "expected": row["label"],
                    "predicted": predicted,
                    "confidence": outcome.confidence,
                }
            )

    n = len(rows)
    precision = correct / answered if answered else 0.0
    recall = correct / answerable if answerable else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    report = {
        "n": n,
        "f1": round(f1, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "abstention_rate": round(abstained / n, 4),
        "offtaxonomy_rate": round(offtaxonomy / n, 4),
        "evidence_fabrication_rate": round(fabricated / n, 4),
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps({**report, "mistakes": mistakes}, indent=2, sort_keys=True), encoding="utf-8"
    )

    print(f"Evaluated {n} golden lines → {out_path}")
    print(f"  answered {answered} | correct {correct} | abstained {abstained}")
    for m in mistakes:
        print(f"  × {m['description'][:52]:<52} expected {m['expected']} got {m['predicted']}")
    return report


def main() -> int:
    p = argparse.ArgumentParser(description="Run the classification eval.")
    p.add_argument("--golden", type=Path, default=Path("evals/golden.jsonl"))
    p.add_argument("--out", type=Path, default=Path(".data/eval_report.json"))
    args = p.parse_args()
    asyncio.run(run(args.golden, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
