from typing import Any, Dict, List, Optional
import uuid
import datetime
import json
from pathlib import Path
from cirquento.review.queue import ReviewQueue

DATA_DIR = Path(".data")
RUN_OUTPUT_PATH = DATA_DIR / "run_output.json"
DEMO_BOM_PATH = DATA_DIR / "demo_bom.json"
REVIEW_QUEUE_PATH = DATA_DIR / "review_queue.jsonl"

def _load_run_data() -> Dict[str, Any]:
    if RUN_OUTPUT_PATH.exists():
        return json.loads(RUN_OUTPUT_PATH.read_text(encoding="utf-8"))
    return {}

class PipelineService:
    async def submit(self, source_uri: str, dataset: str, requested_by: str) -> Dict[str, Any]:
        # Return a mock run structure to satisfy immediate async request
        # The background task in main.py will actually invoke the CLI logic
        return {
            "id": f"run_{uuid.uuid4().hex[:8]}",
            "status": "pending",
            "source_uri": str(source_uri),
            "dataset": dataset,
            "requested_by": requested_by,
            "run_hash": None,
            "passports_generated": 0,
            "created_at": datetime.datetime.now().isoformat()
        }
        
    async def get(self, run_id: str) -> Optional[Dict[str, Any]]:
        # In a real DB, we'd fetch by run_id. Here we just read the latest run
        run_data = _load_run_data()
        if not run_data:
            return None
            
        return {
            "id": run_id,
            "status": "completed",
            "source_uri": "https://example.com/data",
            "dataset": "demo",
            "requested_by": "system",
            "run_hash": run_data.get("runContentHash"),
            "passports_generated": len(run_data.get("passports", [])),
            "created_at": datetime.datetime.now().isoformat()
        }

class PassportsService:
    async def build(self, product_id: str, as_of: Optional[str] = None, include_evidence: bool = True) -> Optional[Dict[str, Any]]:
        run_data = _load_run_data()
        for p in run_data.get("passports", []):
            if p.get("productId") == product_id:
                # Wrap the raw LD in our PassportOut schema
                return {
                    "product_id": product_id,
                    "circularity_score": p.get("circularityScore", 0.0),
                    "content_hash": p.get("contentHash", ""),
                    "body": p,
                    "evidence": [] # Extracted from DB in real implementation
                }
        return None
        
    async def jsonld(self, product_id: str) -> Optional[Dict[str, Any]]:
        run_data = _load_run_data()
        for p in run_data.get("passports", []):
            if p.get("productId") == product_id:
                return p
        return None

class SuppliersService:
    async def signals(self, limit: int, min_spend_eur: float) -> List[Dict[str, Any]]:
        # Aggregate supplier data from demo_bom.json
        if not DEMO_BOM_PATH.exists():
            return []
            
        bom = json.loads(DEMO_BOM_PATH.read_text(encoding="utf-8"))
        suppliers = bom.get("suppliers", [])
        
        results = []
        for s in suppliers:
            # Map the basic fields over. In reality, exposure_score would be calculated.
            results.append({
                "supplier_id": s.get("supplier_id", ""),
                "supplier_name": s.get("name", ""),
                "exposure_score": 75.0, # Placeholder until the data pipeline pushes real scores
                "spend_eur": float(s.get("revenue_eur", 0)),
                "recommended_action": "review"
            })
            
        # Filter and sort
        results = [r for r in results if r["spend_eur"] >= min_spend_eur]
        results.sort(key=lambda x: x["spend_eur"], reverse=True)
        return results[:limit]

class ReviewService:
    async def resolve(self, item_id: str, code: str, reviewer: str, note: Optional[str]) -> None:
        queue = ReviewQueue(REVIEW_QUEUE_PATH)
        queue.resolve(item_id, code, reviewer)

class Services:
    def __init__(self):
        self.pipeline = PipelineService()
        self.passports = PassportsService()
        self.suppliers = SuppliersService()
        self.review = ReviewService()
        
    @classmethod
    async def create(cls) -> "Services":
        return cls()
        
    async def aclose(self) -> None:
        pass

async def get_services() -> Services:
    from cirquento.api.main import app
    return app.state.services
