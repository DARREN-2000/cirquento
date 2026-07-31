"""Provenance graph.

The product's core promise is "every number traces to a source row". That is
only true if evidence is a first-class value carried alongside every computed
figure — not a log line written next to it.

An EvidenceRef is deliberately dumb: a pointer plus a human-readable locator.
It must stay serialisable, because it ends up inside a signed JSON-LD passport
that an auditor may open years later without our code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    kind: str            # "bom_line" | "sds" | "supplier_doc" | "rule"
    locator: str         # e.g. "bom_line:812-044" or "rules/circularity.v3.yaml#joints"
    detail: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "locator": self.locator, "detail": self.detail}

    def __str__(self) -> str:
        return self.locator


@dataclass(frozen=True, slots=True)
class Evidence:
    refs: tuple[EvidenceRef, ...] = ()

    @classmethod
    def merge(cls, groups: Iterable[Sequence[EvidenceRef]]) -> "Evidence":
        """Flatten and de-duplicate while preserving first-seen order.

        Order stability matters: passports are hashed and compared across
        replays, so a set here would make identical runs look different.
        """
        seen: dict[tuple[str, str, str], EvidenceRef] = {}
        for group in groups:
            for ref in group:
                seen.setdefault((ref.kind, ref.locator, ref.detail), ref)
        return cls(tuple(seen.values()))

    def of_kind(self, kind: str) -> tuple[EvidenceRef, ...]:
        return tuple(r for r in self.refs if r.kind == kind)

    def as_list(self) -> list[dict[str, Any]]:
        return [r.as_dict() for r in self.refs]

    def __len__(self) -> int:
        return len(self.refs)
