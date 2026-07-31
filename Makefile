.PHONY: help verify demo run replay test eval console lint up down clean \
        recommend export passport review ingest

PY ?= python3
export PYTHONPATH := src

help:
	@echo "verify  - seed, run, replay, test and gate the whole thing offline"
	@echo "demo    - seed the deterministic dataset and run the pipeline"
	@echo "replay  - run twice and assert byte-identical passports"
	@echo "test    - pytest if available, otherwise the stdlib runner"
	@echo "eval    - classification eval + CI gate"
	@echo "console - regenerate docs/data.js from the latest run"
	@echo "recommend - rank counterfactual improvements per product"
	@echo "export  - material-facts contract for a carbon platform"
	@echo "passport- render a sealed passport PDF, then verify the seal"
	@echo "review  - queue abstentions and ambiguous merges for a human"
	@echo "ingest  - load the messy example CSV under the schema contract"
	@echo "up      - docker compose up (api + postgres)"

# The single command a reviewer should run. Everything here works with no API
# key, no network and no third-party packages installed.
verify: demo replay test eval recommend export passport review ingest console
	@echo ""
	@echo "All checks passed: pipeline ran, replay was byte-identical, tests and eval"
	@echo "gate green, and recommend/export/passport/review/ingest all executed."

demo:
	$(PY) -m cirquento.demo.seed
	$(PY) -m cirquento.cli run

run:
	$(PY) -m cirquento.cli run

replay:
	$(PY) -m cirquento.cli replay

# Prefer pytest, fall back to the zero-dependency runner so a bare interpreter
# can still prove the rule engine is correct.
test:
	@$(PY) -c "import pytest" 2>/dev/null && pytest -q || $(PY) tests/run_all.py

eval:
	$(PY) evals/run.py
	$(PY) evals/gate.py --report .data/eval_report.json

recommend:
	$(PY) -m cirquento.cli recommend

# The material-facts contract handed to a carbon platform. Deliberately carries
# no emissions figure; see src/cirquento/export/carbon.py for why.
export:
	$(PY) -m cirquento.cli export

# Sealing uses a throwaway key here. A real deployment injects one, and the CLI
# refuses to invent a default rather than produce a seal that proves nothing.
passport:
	CIRQUENTO_SEAL_KEY=$${CIRQUENTO_SEAL_KEY:-local-dev-key} \
		$(PY) -m cirquento.cli passport --product CM-4470-B --out .data/passport.pdf --seal
	CIRQUENTO_SEAL_KEY=$${CIRQUENTO_SEAL_KEY:-local-dev-key} \
		$(PY) -m cirquento.cli verify --product CM-4470-B --seal-file .data/passport.seal.json

review:
	$(PY) -m cirquento.cli review sync
	$(PY) -m cirquento.cli review list --status open

ingest:
	$(PY) -m cirquento.cli ingest --file examples/messy_bom.csv

console:
	$(PY) scripts/export_console_data.py
	$(PY) scripts/build_standalone.py

lint:
	@$(PY) -c "import ruff" 2>/dev/null && ruff check src tests evals scripts || echo "ruff not installed, skipping"
	@$(PY) -m compileall -q src tests evals scripts && echo "compileall ok"

up:
	docker compose up --build

down:
	docker compose down -v

clean:
	rm -rf .data .pytest_cache **/__pycache__
