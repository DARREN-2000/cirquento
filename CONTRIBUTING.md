# Contributing to Cirquento

The project has one hard rule, and everything below follows from it:

> **A number that reaches a user must be traceable to something that executed.**

A circularity score ends up in a regulatory filing and in a supplier
negotiation. A plausible number is worse than a missing one, because a missing
number gets chased and a plausible number gets cited.

## Before you open a PR

```bash
make verify
```

This seeds the demo dataset, runs the pipeline twice and asserts the passports
are byte-identical, runs the tests, runs the classification eval against its
gate, then exercises `recommend`, `export`, `passport --seal`, `verify`,
`review` and `ingest`, and finally regenerates the console data. It needs no
network, no API key and no third-party packages.

CI runs the same target and additionally runs `git diff --exit-code -- docs/data.js`.
If your change alters any published figure, commit the regenerated `docs/data.js`
in the same PR. That check exists because the published console once carried
hand-written numbers while the engine returned something else entirely.

## Rules that are not negotiable

**Never hand-write a figure into `docs/`, `README.md`, or a screenshot.**
Every figure comes from `scripts/export_console_data.py`, which can only read
from an executed run.

**Never let a model produce a score.** The LLM proposes a *material
classification* against a closed taxonomy and must cite an evidence span from
the input text. Scoring is done by the deterministic rule engine in
`src/cirquento/rules/`. If you find yourself asking a model for a number,
you are in the wrong module.

**Prefer abstention to a guess.** Below `CONFIDENCE_FLOOR` the classifier
abstains and the line goes to the review queue. An unclassified line is
reported as a data gap; it is never quietly averaged, defaulted or dropped.
Missing recycled content counts as 0% *and* is surfaced as missing — never
imputed from a peer average.

**Fail closed.** Unknown seal algorithm, unmappable required column, a
composition that does not sum to 100%, a score outside 0..100: raise. Do not
clamp, coerce, or return a falsy value that is indistinguishable from a
legitimate negative result.

**Do not guess column meanings.** `src/cirquento/ingest/readers.py` maps
headers by exact alias only. Fuzzy header matching was deliberately rejected:
silently binding the wrong column to `mass_kg` produces a confident wrong
answer. Add an alias instead.

## Adding a rule or changing weights

Rulesets are versioned YAML in `rules/`. **Never edit a published ruleset in
place** — scores must remain reproducible for any passport already issued.
Create `circularity.vN+1.yaml`, and note in the PR which scores move and why.
Every `CircularityResult` records the ruleset version that produced it.

## Tests

`tests/` runs under either pytest or the stdlib runner in `tests/run_all.py`,
so a bare interpreter can still prove the engine correct. Write tests that pin
*behaviour that is easy to regress into looking correct*, not line coverage.
Good examples already in the suite:

- one potted joint caps the whole assembly (disassembly is a `min()`)
- an empty BOM scores 0 rather than dividing by zero
- unknown recycled content counts as 0, not as the average
- a tampered passport fails seal verification
- the exporter refuses to emit a CO₂e field

## Changing the classifier

Run `make eval`. The gate enforces min F1 0.91, an abstention rate between
0.03 and 0.18, zero off-taxonomy outputs, and a zero evidence-fabrication rate.
If you raise F1 by driving abstention to zero, the gate will fail, and it is
right to.

The golden set lives in `evals/golden.jsonl`. It is small and known to be
small; growing it with genuinely hard negatives is the single most valuable
contribution to this repo. `cirquento review export-labels` emits
human-resolved labels in the right shape, including `null` for descriptions a
human judged unclassifiable.

## Style

Comments explain *why*, especially where the obvious implementation is wrong
(see the column-locale detection in `readers.py` or the joint bundling in
`recommend.py`). Type hints on public functions. `make lint` runs ruff when
it is installed and `compileall` when it is not.
