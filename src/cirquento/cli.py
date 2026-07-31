"""Cirquento CLI — the offline path that CI, the demo and `make` all use.

Deliberately runs the *same* pipeline code as the API. If the demo used a
shortcut implementation, the demo would stop proving anything about the
product.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Sequence

from cirquento.classify.cache import ClassificationCache
from cirquento.classify.classifier import MaterialClassifier
from cirquento.classify.offline import OfflineLLM
from cirquento.classify.taxonomy import Taxonomy
from cirquento.demo import seed as demo_seed
from cirquento.evidence import EvidenceRef
from cirquento.passport.builder import PassportBuilder
from cirquento.pipeline.dag import content_hash, row_key
from cirquento.resolve.entities import EntityResolver, SupplierRecord
from cirquento.export import carbon as carbon_export
from cirquento.ingest.readers import read_rows, to_dataset
from cirquento.passport import pdf as passport_pdf
from cirquento.passport import seal as passport_seal
from cirquento.review.queue import KIND_CLASSIFICATION, ReviewQueue
from cirquento.rules.engine import Component, RuleEngine
from cirquento.rules.recommend import Recommender
from cirquento.rules.spec import RuleSet

DEFAULT_RULESET = "rules/circularity.v3.yaml"
DEFAULT_DATA = Path(".data/demo_bom.json")


def _load_dataset(path: Path) -> dict[str, Any]:
    if not path.exists():
        payload = demo_seed.build()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        return payload
    return json.loads(path.read_text(encoding="utf-8"))


async def _classify_all(
    rows: Sequence[dict[str, Any]], cache_path: Path | None
) -> tuple[dict[str, Any], dict[str, int]]:
    classifier = MaterialClassifier(
        llm=OfflineLLM(fixture="evals/fixtures/responses.jsonl"),
        taxonomy=Taxonomy(),
        cache=ClassificationCache(cache_path),
    )
    results: dict[str, Any] = {}
    stats = {"deterministic": 0, "cache": 0, "model": 0, "review": 0, "abstained": 0}

    for row in rows:
        outcome = await classifier.classify(row["description"])
        results[row["line_id"]] = outcome
        stats[outcome.source] = stats.get(outcome.source, 0) + 1
        if outcome.needs_review:
            stats["review"] += 1
        if outcome.abstained:
            stats["abstained"] += 1
    return results, stats


def _components(rows: Sequence[dict[str, Any]], classified: dict[str, Any]) -> list[Component]:
    out: list[Component] = []
    for row in rows:
        outcome = classified[row["line_id"]]
        out.append(
            Component(
                line_id=row["line_id"],
                material_code=outcome.code.value if outcome.code else "",
                mass_kg=Decimal(str(row["mass_kg"])),
                recycled_fraction=(
                    None
                    if row["recycled_fraction"] is None
                    else Decimal(str(row["recycled_fraction"]))
                ),
                joining_method=row["joining_method"],
                substances=tuple(row.get("substances", ())),
                supplier_id=row.get("supplier_id"),
                evidence=(
                    EvidenceRef(
                        kind="bom_line",
                        locator=f"bom_line:{row['line_id']}",
                        detail=row["description"],
                    ),
                ),
            )
        )
    return out


async def cmd_run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    data = _load_dataset(Path(args.data))
    rows = data["rows"]
    ruleset = RuleSet.load(args.ruleset)
    engine = RuleEngine(ruleset)

    payload = json.dumps(data, sort_keys=True).encode("utf-8")
    run_hash = content_hash(data["source_uri"], payload)
    keys = {row_key(data["source_uri"], r) for r in rows}

    classified, stats = await _classify_all(rows, Path(args.cache) if args.cache else None)

    resolver = EntityResolver()
    decisions = await resolver.resolve(
        [SupplierRecord(**s) for s in data["suppliers"]]
    )
    merges = [d for d in decisions if d.decision == "merge"]
    reviews = [d for d in decisions if d.decision == "review"]

    builder = PassportBuilder()
    passports = []
    by_product: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_product.setdefault(row["product_id"], []).append(row)

    for product_id, product_rows in sorted(by_product.items()):
        comps = _components(product_rows, classified)
        result = engine.score(comps)
        unresolved = [c.line_id for c in comps if not c.material_code]
        passports.append(
            builder.build(
                product_id=product_id,
                product_name=product_rows[0]["product_name"],
                components=comps,
                result=result,
                unresolved_lines=unresolved,
            )
        )

    elapsed = (time.perf_counter() - started) * 1000
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "runContentHash": run_hash,
                "rulesetVersion": ruleset.version,
                "bomLines": len(rows),
                "distinctRowKeys": len(keys),
                "classification": stats,
                "supplierMerges": [f"{d.left}={d.right} ({d.method})" for d in merges],
                "supplierReviews": [f"{d.left}?{d.right}" for d in reviews],
                "passports": [p.to_jsonld() for p in passports],
            },
            indent=2,
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    print(f"run hash        {run_hash[:16]}…  ruleset {ruleset.version}")
    print(f"bom lines       {len(rows)} ({len(keys)} distinct row keys)")
    print(
        "classification  "
        f"deterministic={stats.get('deterministic', 0)} "
        f"model={stats.get('model', 0)} cache={stats.get('cache', 0)} "
        f"review={stats['review']} abstained={stats['abstained']}"
    )
    print(f"suppliers       {len(merges)} merged, {len(reviews)} to review")
    for p in passports:
        print(
            f"  {p.product_id:<12} score {p.body['circularityScore']:>3.0f}  "
            f"hash {p.content_hash[:12]}…  {p.body['explanation'][:72]}"
        )
    print(f"elapsed         {elapsed:.0f} ms → {out}")
    return 0


def _load_run(path: str) -> dict[str, Any]:
    p = Path(path)
    if not p.exists():
        raise SystemExit(
            f"No run output at {p}. Run `cirquento run` first — these commands "
            "deliberately operate on a real executed run, never on freshly invented data."
        )
    return json.loads(p.read_text(encoding="utf-8"))


def _find_passport(run: dict[str, Any], product_id: str | None) -> dict[str, Any]:
    passports = run.get("passports", [])
    if not passports:
        raise SystemExit("Run output contains no passports.")
    if not product_id:
        return passports[0]
    for p in passports:
        if p.get("productId") == product_id:
            return p
    known = ", ".join(sorted(str(p.get("productId")) for p in passports))
    raise SystemExit(f"No passport for {product_id!r}. Available: {known}")


async def _components_for(args: argparse.Namespace) -> tuple[dict[str, list[Component]], RuleSet]:
    data = _load_dataset(Path(args.data))
    ruleset = RuleSet.load(args.ruleset)
    classified, _ = await _classify_all(data["rows"], None)
    by_product: dict[str, list[dict[str, Any]]] = {}
    for row in data["rows"]:
        by_product.setdefault(row["product_id"], []).append(row)
    return (
        {pid: _components(rows, classified) for pid, rows in sorted(by_product.items())},
        ruleset,
    )


async def cmd_recommend(args: argparse.Namespace) -> int:
    """Rank the changes that would actually move the score."""
    grouped, ruleset = await _components_for(args)
    engine = RuleEngine(ruleset)
    recommender = Recommender(engine, ruleset)

    products = [args.product] if args.product else list(grouped)
    payload: dict[str, Any] = {"rulesetVersion": ruleset.version, "products": {}}

    for pid in products:
        comps = grouped.get(pid)
        if comps is None:
            raise SystemExit(f"Unknown product {pid!r}. Known: {', '.join(grouped)}")
        items = recommender.recommend(comps, top_n=args.top)
        payload["products"][pid] = [r.as_dict() for r in items]

        base = engine.score(comps).score
        print(f"\n{pid}  current score {base:.0f}/100")
        if not items:
            print("  no change modelled would improve the score")
            continue
        for r in items:
            tag = "conditional" if r.conditional else "design"
            print(f"  +{r.delta:>3.0f} → {r.score_after:>3.0f}  [{tag:^11}] {r.action}")
            print(f"            {r.rationale}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(f"\nwrote {out}")
    return 0


async def cmd_export(args: argparse.Namespace) -> int:
    """Emit the material-facts contract for a carbon platform."""
    run = _load_run(args.run_output)
    batch = carbon_export.build_batch(
        run.get("passports", []), run_content_hash=run.get("runContentHash")
    )
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(batch, indent=2, sort_keys=True), encoding="utf-8")
    print(f"contract        {batch['contract']}")
    print(f"products        {batch['productCount']}")
    for product in batch["products"]:
        print(
            f"  {product['productId']:<12} {product['totalMassKg']:>10.3f} kg  "
            f"{len(product['materials'])} materials  "
            f"recycled {product['recycledContentPct']:.1f}%"
        )
    print("excludes        emissions figures (owned by the receiving platform)")
    print(f"wrote           {out}")
    return 0


async def cmd_passport(args: argparse.Namespace) -> int:
    """Render a passport to PDF, optionally sealed."""
    run = _load_run(args.run_output)
    doc = _find_passport(run, args.product)

    seal_dict = None
    if args.seal:
        seal_dict = passport_seal.seal_document(doc, key=args.key).as_dict()
        seal_path = Path(args.out).with_suffix(".seal.json")
        seal_path.write_text(json.dumps(seal_dict, indent=2, sort_keys=True), encoding="utf-8")
        print(f"seal            {seal_dict['algorithm']} {seal_dict['keyId']} → {seal_path}")

    recs: list[dict[str, Any]] = []
    rec_path = Path(".data/recommendations.json")
    if rec_path.exists():
        recs = json.loads(rec_path.read_text()).get("products", {}).get(doc.get("productId"), [])

    blob = passport_pdf.render_passport(doc, seal=seal_dict, recommendations=recs)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(blob)
    print(f"passport        {doc.get('productId')} score {doc.get('circularityScore'):.0f}")
    print(f"pdf             {len(blob):,} bytes → {out}")
    return 0


async def cmd_verify(args: argparse.Namespace) -> int:
    """Verify a seal against a passport's recomputed content hash."""
    run = _load_run(args.run_output)
    doc = _find_passport(run, args.product)
    seal_doc = json.loads(Path(args.seal_file).read_text(encoding="utf-8"))

    recomputed = passport_seal.seal_document(doc, key=args.key).content_hash
    ok = passport_seal.verify(seal_doc, recomputed, key=args.key)
    print(f"passport        {doc.get('productId')}")
    print(f"content hash    {recomputed[:32]}…")
    print(f"seal            {'VALID' if ok else 'INVALID'}")
    if not ok:
        print("  The document does not match the seal. Treat it as untrusted.")
    return 0 if ok else 1


async def cmd_ingest(args: argparse.Namespace) -> int:
    """Load a real CSV/TSV BOM extract under the schema contract."""
    result = read_rows(args.file, delimiter=args.delimiter)
    print(f"columns mapped  {len(result.column_mapping)}")
    for canonical, source in sorted(result.column_mapping.items()):
        print(f"  {canonical:<20} ← {source}")
    print(f"rows            {result.summary()}")
    for r in result.rejections[:10]:
        print(f"  row {r.row_number:<5} {r.field:<18} {r.value!r:<18} {r.reason}")
    if result.rejected > 10:
        print(f"  … and {result.rejected - 10} more")

    dataset = to_dataset(result, source_uri=f"file://{Path(args.file).resolve()}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(dataset, indent=2, sort_keys=True), encoding="utf-8")
    print(f"wrote           {out}")
    # A file that parsed nothing is a failure, not an empty success.
    return 0 if result.accepted else 1


async def cmd_review(args: argparse.Namespace) -> int:
    queue = ReviewQueue(args.queue)

    if args.review_command == "sync":
        data = _load_dataset(Path(args.data))
        classified, _ = await _classify_all(data["rows"], None)
        pairs = [(row["description"], classified[row["line_id"]]) for row in data["rows"]]
        added = queue.enqueue_abstentions(pairs)
        resolver = EntityResolver()
        decisions = await resolver.resolve([SupplierRecord(**s) for s in data["suppliers"]])
        added += queue.enqueue_supplier_reviews(decisions)
        stats = queue.stats()
        print(f"queued          {added} new item(s)")
        print(f"queue           {stats['open']} open / {stats['resolved']} resolved")
        return 0

    if args.review_command == "list":
        items = queue.list(status=args.status or None)
        if not items:
            print("review queue is empty")
            return 0
        for item in items:
            mark = "✓" if item.status == "resolved" else "·"
            print(f"{mark} {item.id}  [{item.kind}]  {item.subject[:58]}")
            print(f"    {item.reason}")
            if item.status == "resolved":
                print(f"    resolved as {item.resolution!r} by {item.resolved_by}")
        stats = queue.stats()
        print(f"\n{stats['open']} open / {stats['resolved']} resolved / {stats['total']} total")
        return 0

    if args.review_command == "resolve":
        item = queue.resolve(args.id, args.resolution, args.by)
        print(f"resolved        {item.id} as {item.resolution!r} by {item.resolved_by}")
        return 0

    if args.review_command == "export-labels":
        rows = queue.export_labels()
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, sort_keys=True) + "\n")
        print(f"exported        {len(rows)} human-reviewed label(s) → {out}")
        return 0

    raise SystemExit("unknown review subcommand")


async def cmd_replay(args: argparse.Namespace) -> int:
    """Prove determinism: run twice, compare passport hashes."""
    first = Path(".data/replay_a.json")
    second = Path(".data/replay_b.json")
    for target in (first, second):
        ns = argparse.Namespace(
            data=args.data, ruleset=args.ruleset, cache=None, out=str(target)
        )
        await cmd_run(ns)

    a = json.loads(first.read_text())
    b = json.loads(second.read_text())
    ha = [p["contentHash"] for p in a["passports"]]
    hb = [p["contentHash"] for p in b["passports"]]
    identical = ha == hb
    print("\nreplay determinism:", "IDENTICAL" if identical else "DIVERGED")
    for x, y in zip(ha, hb):
        print(f"  {x[:16]}…  {'==' if x == y else '!='}  {y[:16]}…")
    return 0 if identical else 1


def main() -> int:
    p = argparse.ArgumentParser(prog="cirquento")
    sub = p.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Run the full offline pipeline.")
    run.add_argument("--dataset", default="demo")
    run.add_argument("--data", default=str(DEFAULT_DATA))
    run.add_argument("--ruleset", default=DEFAULT_RULESET)
    run.add_argument("--cache", default=".data/classification_cache.jsonl")
    run.add_argument("--out", default=".data/run_output.json")
    run.add_argument("--offline", action="store_true")
    run.set_defaults(func=cmd_run)

    rep = sub.add_parser("replay", help="Run twice and assert identical passports.")
    rep.add_argument("--data", default=str(DEFAULT_DATA))
    rep.add_argument("--ruleset", default=DEFAULT_RULESET)
    rep.add_argument("--run", default="")
    rep.add_argument("--assert-identical", action="store_true")
    rep.set_defaults(func=cmd_replay)

    rec = sub.add_parser("recommend", help="Rank counterfactual improvements.")
    rec.add_argument("--data", default=str(DEFAULT_DATA))
    rec.add_argument("--ruleset", default=DEFAULT_RULESET)
    rec.add_argument("--product", default="")
    rec.add_argument("--top", type=int, default=6)
    rec.add_argument("--out", default=".data/recommendations.json")
    rec.set_defaults(func=cmd_recommend)

    exp = sub.add_parser("export", help="Export material facts for a carbon platform.")
    exp.add_argument("--run-output", default=".data/run_output.json")
    exp.add_argument("--out", default=".data/carbon_export.json")
    exp.set_defaults(func=cmd_export)

    pas = sub.add_parser("passport", help="Render a passport PDF.")
    pas.add_argument("--run-output", default=".data/run_output.json")
    pas.add_argument("--product", default="")
    pas.add_argument("--out", default=".data/passport.pdf")
    pas.add_argument("--seal", action="store_true", help="Also write a detached HMAC seal.")
    pas.add_argument("--key", default=None)
    pas.set_defaults(func=cmd_passport)

    ver = sub.add_parser("verify", help="Verify a passport seal.")
    ver.add_argument("--run-output", default=".data/run_output.json")
    ver.add_argument("--product", default="")
    ver.add_argument("--seal-file", dest="seal_file", default=".data/passport.seal.json")
    ver.add_argument("--key", default=None)
    ver.set_defaults(func=cmd_verify)

    ing = sub.add_parser("ingest", help="Ingest a CSV/TSV BOM extract.")
    ing.add_argument("--file", required=True)
    ing.add_argument("--delimiter", default=None)
    ing.add_argument("--out", default=".data/ingested.json")
    ing.set_defaults(func=cmd_ingest)

    rev = sub.add_parser("review", help="Work the human review queue.")
    rev.add_argument("--queue", default=".data/review_queue.jsonl")
    rev_sub = rev.add_subparsers(dest="review_command", required=True)

    rv_sync = rev_sub.add_parser("sync", help="Queue abstentions and ambiguous merges.")
    rv_sync.add_argument("--data", default=str(DEFAULT_DATA))
    rv_sync.add_argument("--ruleset", default=DEFAULT_RULESET)

    rv_list = rev_sub.add_parser("list", help="List review items.")
    rv_list.add_argument("--status", default="", choices=["", "open", "resolved"])

    rv_res = rev_sub.add_parser("resolve", help="Record a human decision.")
    rv_res.add_argument("--id", required=True)
    rv_res.add_argument("--resolution", required=True)
    rv_res.add_argument("--by", required=True)

    rv_exp = rev_sub.add_parser("export-labels", help="Turn decisions into golden-set rows.")
    rv_exp.add_argument("--out", default=".data/reviewed_labels.jsonl")

    rev.set_defaults(func=cmd_review)

    args = p.parse_args()
    return asyncio.run(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
