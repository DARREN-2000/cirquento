"""Bronze → silver → gold pipeline.

The whole platform rests on one property: **a run is a pure function of its
inputs**. Same extracts + same ruleset version = byte-identical passports.
That is what lets an auditor replay a 2027 passport in 2030, and what makes the
LLM cache safe to reuse.

How that is enforced:
  * bronze rows are keyed by sha256(source_uri, payload) — re-loading is a no-op
  * nothing is ever mutated in place; corrections create a new version
  * the ruleset version is pinned into the run record, not read from disk later
  * wall-clock time never enters a computation; `as_of` is an explicit input
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Awaitable, Callable, Sequence

from cirquento.observability import tracer

try:  # DuckDB is the production engine
    import duckdb

    _ENGINE = "duckdb"
except ModuleNotFoundError:  # pragma: no cover - minimal environments
    duckdb = None  # type: ignore[assignment]
    _ENGINE = "sqlite"


def connect(path: str = ":memory:") -> Any:
    """Open the analytical store.

    DuckDB is what this runs on in production — columnar scans over millions of
    BOM lines are the workload. SQLite is a drop-in for the demo, CI and
    laptops: both speak the same SQL subset used here, including
    ``ON CONFLICT DO NOTHING``, which is the only clever thing in the schema.
    """
    if _ENGINE == "duckdb":
        return duckdb.connect(path)
    import sqlite3

    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys = ON")
    return con


class Stage(StrEnum):
    INGEST = "ingest"
    BRONZE = "bronze"
    RESOLVE = "resolve"
    CLASSIFY = "classify"
    SCORE = "score"
    PASSPORT = "passport"


@dataclass(slots=True)
class StageResult:
    stage: Stage
    rows_in: int
    rows_out: int
    duration_ms: float
    warnings: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunRecord:
    run_id: str
    dataset: str
    source_uri: str
    content_hash: str
    ruleset_version: str
    started_at: datetime
    finished_at: datetime | None = None
    stages: list[StageResult] = field(default_factory=list)
    status: str = "running"


def content_hash(source_uri: str, payload: bytes) -> str:
    h = hashlib.sha256()
    h.update(source_uri.encode("utf-8"))
    h.update(b"\x00")
    h.update(payload)
    return h.hexdigest()


def row_key(source_uri: str, row: dict[str, Any]) -> str:
    """Stable per-row identity.

    `sort_keys=True` matters more than it looks: without it, a column-order
    change in an ERP export would rewrite every key and duplicate the entire
    dataset on the next load.
    """
    canonical = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return content_hash(source_uri, canonical.encode("utf-8"))


BRONZE_DDL = """
CREATE TABLE IF NOT EXISTS bronze_bom (
    row_key      VARCHAR PRIMARY KEY,   -- content hash => replay is a no-op
    run_id       VARCHAR NOT NULL,
    source_uri   VARCHAR NOT NULL,
    ingested_at  TIMESTAMP NOT NULL,
    payload      JSON NOT NULL          -- raw, unmodified: the audit anchor
);
CREATE TABLE IF NOT EXISTS silver_component (
    component_id VARCHAR PRIMARY KEY,
    row_key      VARCHAR NOT NULL REFERENCES bronze_bom(row_key),
    product_id   VARCHAR NOT NULL,
    supplier_id  VARCHAR,
    description  VARCHAR NOT NULL,
    mass_kg      DECIMAL(18,6),
    joining_method VARCHAR
);
CREATE TABLE IF NOT EXISTS gold_material_fact (
    component_id     VARCHAR PRIMARY KEY REFERENCES silver_component(component_id),
    material_code    VARCHAR,
    recycled_fraction DECIMAL(5,4),
    confidence       DECIMAL(5,4),
    needs_review     BOOLEAN NOT NULL DEFAULT FALSE,
    evidence         JSON NOT NULL
);
"""


class Pipeline:
    def __init__(self, con: Any | None = None, ruleset_version: str = "unknown") -> None:
        self._con = con if con is not None else connect()
        self._ruleset_version = ruleset_version
        # Statement-at-a-time: sqlite3.execute() refuses multi-statement SQL,
        # and splitting here keeps one DDL definition for both engines.
        for statement in (s.strip() for s in BRONZE_DDL.split(";")):
            if statement:
                self._con.execute(statement)

    async def run(
        self,
        *,
        run_id: str,
        dataset: str,
        source_uri: str,
        payload: bytes,
        stages: Sequence[tuple[Stage, Callable[[], Awaitable[StageResult]]]],
    ) -> RunRecord:
        record = RunRecord(
            run_id=run_id,
            dataset=dataset,
            source_uri=source_uri,
            content_hash=content_hash(source_uri, payload),
            ruleset_version=self._ruleset_version,
            started_at=datetime.now(timezone.utc),
        )
        with tracer.start_as_current_span("pipeline.run") as span:
            span.set_attribute("cirquento.run_id", run_id)
            span.set_attribute("cirquento.content_hash", record.content_hash)
            for stage, fn in stages:
                with tracer.start_as_current_span(f"pipeline.{stage}"):
                    result = await fn()
                    record.stages.append(result)
                    # A stage that drops rows without warning is a silent data
                    # loss bug; surface it in the run record, not in a log line.
                    if result.rows_out < result.rows_in and not result.warnings:
                        result.warnings.append(
                            f"{result.rows_in - result.rows_out} row(s) dropped without an explanation."
                        )
            record.finished_at = datetime.now(timezone.utc)
            record.status = "succeeded"
        return record

    def insert_bronze(self, run_id: str, source_uri: str, rows: Sequence[dict[str, Any]]) -> int:
        """Idempotent load. ON CONFLICT DO NOTHING is the whole replay story."""
        # ISO strings rather than datetime objects: SQLite dropped implicit
        # datetime adaptation in 3.12, and DuckDB casts the string happily.
        now = datetime.now(timezone.utc).isoformat()
        params = [
            (row_key(source_uri, r), run_id, source_uri, now, json.dumps(r, default=str))
            for r in rows
        ]
        before = self._con.execute("SELECT count(*) FROM bronze_bom").fetchone()[0]
        self._con.executemany(
            "INSERT INTO bronze_bom VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING", params
        )
        after = self._con.execute("SELECT count(*) FROM bronze_bom").fetchone()[0]
        return after - before
