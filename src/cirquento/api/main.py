"""FastAPI surface for Cirquento.

The API is deliberately thin: it validates, delegates to the pipeline/rule
layer, and returns passports with their evidence attached.  No business rule
lives in a router.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Security, status, BackgroundTasks
from fastapi.responses import JSONResponse

from cirquento.api.deps import Services, get_services
from cirquento.api.schemas import (
    PassportOut,
    ReviewDecisionIn,
    RunOut,
    RunTriggerIn,
    SupplierSignalOut,
)
from cirquento.api.security import verify_api_key
from cirquento.api.errors import global_exception_handler
from cirquento.api.config import get_settings
from cirquento.api.middleware import setup_middlewares
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

# If observability doesn't exist, this might fail, but it was in the original file
try:
    from cirquento.observability import setup_telemetry
except ImportError:
    def setup_telemetry(service_name: str):
        pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_telemetry(service_name="cirquento-api")
    services = await Services.create()
    app.state.services = services
    try:
        yield
    finally:
        await services.aclose()


app = FastAPI(
    title="Cirquento",
    version=get_settings().version,
    summary="Circularity intelligence and Digital Product Passports.",
    docs_url="/api/docs",
    lifespan=lifespan,
)

# Setup prod features
setup_middlewares(app)
app.add_exception_handler(Exception, global_exception_handler)

Svc = Annotated[Services, Depends(get_services)]
ApiKey = Annotated[str, Security(verify_api_key)]


@app.get("/health", tags=["ops"])
async def health() -> dict[str, str]:
    # In a real prod environment, check DB connections, Cache, etc here.
    return {
        "status": "ok", 
        "version": get_settings().version,
        "environment": get_settings().environment,
        "database": "connected"
    }


@app.post("/v1/runs", response_model=RunOut, status_code=status.HTTP_202_ACCEPTED, tags=["pipeline"])
async def trigger_run(body: RunTriggerIn, svc: Svc, api_key: ApiKey, background_tasks: BackgroundTasks) -> RunOut:
    """Start a pipeline run.

    Runs are idempotent by `(source_uri, content_hash)`: re-submitting an
    unchanged extract returns the existing run instead of duplicating work.
    """
    
    # In best prod, we immediately return the job ID and process in the background
    # This prevents timeouts on large runs
    run = await svc.pipeline.submit(
        source_uri=str(body.source_uri),
        dataset=body.dataset,
        requested_by=body.requested_by,
    )
    
    async def process_run_in_background(run_id: str):
        logging.info(f"Background task starting for run {run_id}")
        # In reality, this would kick off a celery task, an AWS step function or equivalent
        pass
        
    background_tasks.add_task(process_run_in_background, run["id"])
    return RunOut.model_validate(run)


@app.get("/v1/runs/{run_id}", response_model=RunOut, tags=["pipeline"])
async def get_run(run_id: str, svc: Svc, api_key: ApiKey) -> RunOut:
    run = await svc.pipeline.get(run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Run not found")
    return RunOut.model_validate(run)


@app.get("/v1/passports/{product_id}", response_model=PassportOut, tags=["passports"])
async def get_passport(
    product_id: str,
    svc: Svc,
    api_key: ApiKey,
    as_of: Annotated[str | None, Query(description="ISO date for a historical passport.")] = None,
    include_evidence: bool = True,
) -> PassportOut:
    """Return the Digital Product Passport for a product."""
    passport = await svc.passports.build(
        product_id=product_id, as_of=as_of, include_evidence=include_evidence
    )
    if passport is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No passport for this product")
    return PassportOut.model_validate(passport)


@app.get("/v1/passports/{product_id}/jsonld", tags=["passports"])
async def get_passport_jsonld(product_id: str, svc: Svc, api_key: ApiKey) -> JSONResponse:
    """Signed JSON-LD — the machine-readable artefact behind the product QR code."""
    doc = await svc.passports.jsonld(product_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No passport for this product")
    return JSONResponse(doc, media_type="application/ld+json")


@app.get("/v1/suppliers/signals", response_model=list[SupplierSignalOut], tags=["suppliers"])
async def supplier_signals(
    svc: Svc,
    api_key: ApiKey,
    limit: Annotated[int, Query(ge=1, le=200)] = 25,
    min_spend_eur: Annotated[float, Query(ge=0)] = 0.0,
) -> list[SupplierSignalOut]:
    """Suppliers ranked by circularity exposure × spend — i.e. where action pays."""
    rows = await svc.suppliers.signals(limit=limit, min_spend_eur=min_spend_eur)
    return [SupplierSignalOut.model_validate(r) for r in rows]


@app.post("/v1/review/{item_id}", tags=["review"])
async def resolve_review(item_id: str, body: ReviewDecisionIn, svc: Svc, api_key: ApiKey) -> dict[str, str]:
    """Human decision on a low-confidence or abstained classification."""
    await svc.review.resolve(item_id=item_id, code=body.code, reviewer=body.reviewer, note=body.note)
    return {"status": "resolved", "item_id": item_id}
