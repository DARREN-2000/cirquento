"""Classification cache.

Why this is load-bearing rather than an optimisation: 1M BOM lines contain only
~11k distinct normalised descriptions. Without the cache the platform is
unaffordable; with it, a re-run costs nothing, which is also what makes
replay-determinism practical (a replay never re-queries the model).

Backed by an append-only JSONL file so a cache is diffable, inspectable and
cheap to ship into CI as a replay fixture.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid an import cycle with classifier.py
    from cirquento.classify.classifier import Classification


class ClassificationCache:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = Path(path) if path else None
        self._mem: dict[str, dict[str, object]] = {}
        if self._path and self._path.exists():
            self._load()

    def _load(self) -> None:
        assert self._path is not None
        for line in self._path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            # Later entries win: the file is a log, not a snapshot.
            self._mem[row["key"]] = row["value"]

    async def get(self, key: str) -> "Classification | None":
        from cirquento.classify.classifier import Classification
        from cirquento.classify.taxonomy import TaxonomyCode

        row = self._mem.get(key)
        if row is None:
            return None
        code = row["code"]
        return Classification(
            code=TaxonomyCode(code) if code else None,
            confidence=float(row["confidence"]),
            evidence_span=str(row["evidence_span"]),
            reasoning=str(row["reasoning"]),
            abstained=bool(row["abstained"]),
            needs_review=bool(row["needs_review"]),
            source="cache",
        )

    async def put(self, key: str, value: "Classification") -> None:
        row = {
            "code": value.code.value if value.code else None,
            "confidence": value.confidence,
            "evidence_span": value.evidence_span,
            "reasoning": value.reasoning,
            "abstained": value.abstained,
            "needs_review": value.needs_review,
        }
        self._mem[key] = row
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({"key": key, "value": row}, sort_keys=True) + "\n")

    def __len__(self) -> int:
        return len(self._mem)
