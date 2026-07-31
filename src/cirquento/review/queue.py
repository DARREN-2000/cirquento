"""The review queue: where abstentions and ambiguous merges go to be decided.

Design choices worth defending:

* **Append-only JSONL.** A resolution never overwrites the original item; it is
  appended as a new event. Regulatory work needs to answer "who decided this,
  when, and what did it look like before", and a mutable row cannot.
* **Deterministic item IDs.** The ID is a hash of (kind, subject), so re-running
  the pipeline over the same data produces the same IDs and already-resolved
  items stay resolved. Random UUIDs would resurrect every decision on each run.
* **Resolutions feed the golden set.** A human decision is the highest-quality
  label available, so `export_labels()` turns resolutions into eval rows. The
  review queue is the training-data flywheel, not a dead-letter box.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

KIND_CLASSIFICATION = "classification"
KIND_SUPPLIER_MERGE = "supplier_merge"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def item_id(kind: str, subject: str) -> str:
    digest = hashlib.sha256(f"{kind}\x00{subject}".encode("utf-8")).hexdigest()
    return f"{kind[:4]}-{digest[:12]}"


@dataclass(slots=True)
class ReviewItem:
    id: str
    kind: str
    subject: str
    reason: str
    context: dict[str, Any] = field(default_factory=dict)
    status: str = "open"  # "open" | "resolved"
    resolution: str | None = None
    resolved_by: str | None = None
    resolved_at: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "subject": self.subject,
            "reason": self.reason,
            "context": self.context,
            "status": self.status,
            "resolution": self.resolution,
            "resolvedBy": self.resolved_by,
            "resolvedAt": self.resolved_at,
        }


class ReviewQueue:
    def __init__(self, path: str | Path = ".data/review_queue.jsonl") -> None:
        self.path = Path(path)

    # -- persistence -----------------------------------------------------------

    def _events(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                yield json.loads(line)

    def _append(self, event: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event, sort_keys=True) + "\n")

    def _state(self) -> dict[str, ReviewItem]:
        """Fold the append-only log into current state."""
        items: dict[str, ReviewItem] = {}
        for event in self._events():
            eid = event["id"]
            if event.get("event") == "resolved":
                existing = items.get(eid)
                if existing:
                    existing.status = "resolved"
                    existing.resolution = event.get("resolution")
                    existing.resolved_by = event.get("resolvedBy")
                    existing.resolved_at = event.get("resolvedAt")
            else:
                if eid not in items:  # first sighting wins; re-runs don't reopen
                    items[eid] = ReviewItem(
                        id=eid,
                        kind=event["kind"],
                        subject=event["subject"],
                        reason=event.get("reason", ""),
                        context=event.get("context", {}),
                    )
        return items

    # -- writing ---------------------------------------------------------------

    def enqueue(
        self, kind: str, subject: str, reason: str, context: dict[str, Any] | None = None
    ) -> ReviewItem:
        eid = item_id(kind, subject)
        known = self._state()
        if eid in known:
            return known[eid]  # idempotent: re-running the pipeline is not new work
        self._append(
            {
                "event": "opened",
                "id": eid,
                "kind": kind,
                "subject": subject,
                "reason": reason,
                "context": context or {},
                "openedAt": _now(),
            }
        )
        return ReviewItem(id=eid, kind=kind, subject=subject, reason=reason, context=context or {})

    def resolve(self, eid: str, resolution: str, resolved_by: str) -> ReviewItem:
        items = self._state()
        if eid not in items:
            raise KeyError(f"No review item {eid!r}.")
        if items[eid].status == "resolved":
            raise ValueError(
                f"Item {eid} is already resolved as {items[eid].resolution!r}. "
                "Re-resolving would silently rewrite an audit trail."
            )
        self._append(
            {
                "event": "resolved",
                "id": eid,
                "resolution": resolution,
                "resolvedBy": resolved_by,
                "resolvedAt": _now(),
            }
        )
        item = items[eid]
        item.status = "resolved"
        item.resolution = resolution
        item.resolved_by = resolved_by
        return item

    def enqueue_abstentions(self, outcomes: Iterable[tuple[str, Any]]) -> int:
        """Park every abstained/low-confidence classification.

        Deduplicated by *description*, not by line: 812 BOM lines collapse to a
        handful of distinct unknown descriptions, and asking a human the same
        question 135 times is how a review queue gets abandoned.
        """
        added = 0
        seen: set[str] = set()
        for description, outcome in outcomes:
            if not (getattr(outcome, "abstained", False) or getattr(outcome, "needs_review", False)):
                continue
            if description in seen:
                continue
            seen.add(description)
            before = len(self._state())
            self.enqueue(
                KIND_CLASSIFICATION,
                description,
                reason=(
                    "Below the confidence floor; classified as abstain rather than guessed."
                ),
                context={
                    "confidence": float(getattr(outcome, "confidence", 0.0) or 0.0),
                    "proposed": getattr(getattr(outcome, "code", None), "value", None),
                },
            )
            if len(self._state()) > before:
                added += 1
        return added

    def enqueue_supplier_reviews(self, decisions: Sequence[Any]) -> int:
        added = 0
        for d in decisions:
            if getattr(d, "decision", "") != "review":
                continue
            subject = f"{d.left}~{d.right}"
            before = len(self._state())
            self.enqueue(
                KIND_SUPPLIER_MERGE,
                subject,
                reason=(
                    "Similarity landed between the review floor and the auto-merge "
                    "threshold; a wrong merge corrupts spend attribution irreversibly."
                ),
                context={"score": float(getattr(d, "score", 0.0) or 0.0), "method": getattr(d, "method", "")},
            )
            if len(self._state()) > before:
                added += 1
        return added

    # -- reading ---------------------------------------------------------------

    def list(self, *, status: str | None = None, kind: str | None = None) -> list[ReviewItem]:
        items = list(self._state().values())
        if status:
            items = [i for i in items if i.status == status]
        if kind:
            items = [i for i in items if i.kind == kind]
        return sorted(items, key=lambda i: (i.kind, i.subject))

    def stats(self) -> dict[str, int]:
        items = list(self._state().values())
        return {
            "total": len(items),
            "open": sum(1 for i in items if i.status == "open"),
            "resolved": sum(1 for i in items if i.status == "resolved"),
        }

    def export_labels(self) -> list[dict[str, Any]]:
        """Resolved classifications become golden-set rows.

        `null` is a legitimate label: a human confirming "this genuinely cannot
        be classified from the description" teaches the eval that abstaining was
        correct, which is the only way abstention rate stays honest.
        """
        rows = []
        for item in self.list(status="resolved", kind=KIND_CLASSIFICATION):
            resolution = item.resolution
            rows.append(
                {
                    "description": item.subject,
                    "label": None if resolution in {"", "none", "unclassifiable"} else resolution,
                    "source": "human_review",
                    "reviewer": item.resolved_by,
                }
            )
        return rows
