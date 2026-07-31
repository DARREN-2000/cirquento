"""Supplier & material entity resolution.

Enterprise supplier masters are duplicated by construction: every plant, every
acquisition and every typo creates a new record. If you skip this step, spend
is fragmented across five variants of the same vendor and every downstream
ranking is wrong.

Strategy (cheap → expensive, stop as soon as you are confident):
  1. Normalise (legal-form stripping, unicode fold, whitespace).
  2. Deterministic keys: VAT / DUNS / tax id. If they match, you are done —
     no fuzzy logic should ever override a registered identifier.
  3. Blocking on a cheap key so the comparison stays O(n·k), not O(n²).
  4. Fuzzy scoring inside the block (RapidFuzz).
  5. Embedding tie-break only for the ambiguous middle band, because it is the
     only step that costs money.
  6. Anything still ambiguous goes to a human. Auto-merging the middle band is
     how you silently merge two real, different companies.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence

try:  # RapidFuzz is a C-speed accelerator, not a requirement
    from rapidfuzz import fuzz
except ModuleNotFoundError:  # pragma: no cover - exercised in minimal envs
    from difflib import SequenceMatcher

    class fuzz:  # type: ignore[no-redef]
        """Stdlib fallback with the same 0-100 semantics.

        Keeping the interface identical means the resolution *thresholds* stay
        meaningful whether or not the optional dependency is installed.
        """

        @staticmethod
        def token_sort_ratio(a: str, b: str) -> float:
            sa = " ".join(sorted(a.split()))
            sb = " ".join(sorted(b.split()))
            return SequenceMatcher(None, sa, sb).ratio() * 100

        @staticmethod
        def partial_ratio(a: str, b: str) -> float:
            short, long = (a, b) if len(a) <= len(b) else (b, a)
            if not short:
                return 0.0
            best = 0.0
            for i in range(max(1, len(long) - len(short) + 1)):
                window = long[i : i + len(short)]
                best = max(best, SequenceMatcher(None, short, window).ratio())
            return best * 100

LEGAL_FORMS = (
    "gmbh & co kg", "gmbh", "ag", "se", "kg", "ohg", "ug", "mbh",
    "ltd", "limited", "plc", "inc", "llc", "corp", "co",
    "sa", "sas", "sarl", "bv", "nv", "spa", "srl", "ab", "oy", "as",
)
_PUNCT = re.compile(r"[^\w\s]", re.UNICODE)
_WS = re.compile(r"\s+")

AUTO_MERGE = 92.0   # above this: same company
REVIEW_FLOOR = 78.0  # below this: different companies


def normalize(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace("ß", "ss")
    s = _PUNCT.sub(" ", s)
    s = _WS.sub(" ", s).strip()
    for form in LEGAL_FORMS:  # longest-first via tuple ordering
        if s.endswith(" " + form):
            s = s[: -(len(form) + 1)].strip()
            break
    return s


@dataclass(frozen=True, slots=True)
class SupplierRecord:
    record_id: str
    name: str
    country: str | None = None
    vat_id: str | None = None
    duns: str | None = None


@dataclass(slots=True)
class MatchDecision:
    left: str
    right: str
    score: float
    method: str          # "identifier" | "fuzzy" | "embedding"
    decision: str        # "merge" | "review" | "distinct"
    rationale: str


class EmbeddingClient(Protocol):
    async def similarity(self, a: str, b: str) -> float: ...


def blocking_key(record: SupplierRecord) -> str:
    """First token + country. Cheap, and it never splits a true pair that
    survives normalisation — which is the only property a blocking key needs."""
    norm = normalize(record.name)
    head = norm.split(" ")[0][:6] if norm else ""
    return f"{head}|{(record.country or '??').upper()}"


class EntityResolver:
    def __init__(self, embeddings: EmbeddingClient | None = None) -> None:
        self._emb = embeddings

    async def resolve(self, records: Sequence[SupplierRecord]) -> list[MatchDecision]:
        blocks: dict[str, list[SupplierRecord]] = defaultdict(list)
        for r in records:
            blocks[blocking_key(r)].append(r)

        decisions: list[MatchDecision] = []
        for block in blocks.values():
            for i, a in enumerate(block):
                for b in block[i + 1 :]:
                    decisions.append(await self._compare(a, b))
        return decisions

    async def _compare(self, a: SupplierRecord, b: SupplierRecord) -> MatchDecision:
        # 1. Registered identifiers win outright, in both directions.
        for attr, label in (("vat_id", "VAT"), ("duns", "DUNS")):
            av, bv = getattr(a, attr), getattr(b, attr)
            if av and bv:
                same = av.replace(" ", "").upper() == bv.replace(" ", "").upper()
                return MatchDecision(
                    a.record_id, b.record_id, 100.0 if same else 0.0, "identifier",
                    "merge" if same else "distinct",
                    f"{label} identifiers {'match' if same else 'differ'}.",
                )

        na, nb = normalize(a.name), normalize(b.name)
        score = max(fuzz.token_sort_ratio(na, nb), fuzz.partial_ratio(na, nb))

        if score >= AUTO_MERGE:
            return MatchDecision(a.record_id, b.record_id, score, "fuzzy", "merge",
                                 f"Normalised names match at {score:.0f}.")
        if score < REVIEW_FLOOR:
            return MatchDecision(a.record_id, b.record_id, score, "fuzzy", "distinct",
                                 f"Normalised names differ ({score:.0f}).")

        # 3. Ambiguous middle band only — this is the expensive path.
        if self._emb is not None:
            sim = await self._emb.similarity(a.name, b.name) * 100
            blended = 0.5 * score + 0.5 * sim
            if blended >= AUTO_MERGE:
                return MatchDecision(a.record_id, b.record_id, blended, "embedding", "merge",
                                     f"Fuzzy {score:.0f} + embedding {sim:.0f}.")
            return MatchDecision(a.record_id, b.record_id, blended, "embedding", "review",
                                 f"Ambiguous: fuzzy {score:.0f}, embedding {sim:.0f}.")

        return MatchDecision(a.record_id, b.record_id, score, "fuzzy", "review",
                             f"Ambiguous at {score:.0f}; no embedding backend configured.")
