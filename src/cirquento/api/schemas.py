from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field, HttpUrl

class RunTriggerIn(BaseModel):
    source_uri: HttpUrl = Field(..., description="URI of the data source")
    dataset: str = Field(default="demo", description="Name of the dataset")
    requested_by: str = Field(..., description="User or system requesting the run")

class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    status: str
    source_uri: HttpUrl
    dataset: str
    requested_by: str
    run_hash: Optional[str] = None
    passports_generated: int = 0
    created_at: str

class PassportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: str
    circularity_score: float
    content_hash: str
    body: Dict[str, Any]
    evidence: Optional[List[Dict[str, Any]]] = None

class SupplierSignalOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    supplier_id: str
    supplier_name: str
    exposure_score: float
    spend_eur: float
    recommended_action: str

class ReviewDecisionIn(BaseModel):
    code: str = Field(..., description="The resolution code/decision")
    reviewer: str = Field(..., description="ID of the reviewer")
    note: Optional[str] = Field(None, description="Optional reasoning note")
