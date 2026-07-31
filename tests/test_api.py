from fastapi.testclient import TestClient
from cirquento.api.main import app
from cirquento.api.config import get_settings

from cirquento.api.deps import get_services, Services

app.dependency_overrides[get_services] = lambda: Services()
client = TestClient(app)
settings = get_settings()
headers = {
    "X-API-Key": settings.api_key
}

def test_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"

def test_missing_api_key():
    response = client.get("/v1/runs/123")
    assert response.status_code == 401

def test_trigger_run():
    payload = {
        "source_uri": "https://example.com/test.csv",
        "dataset": "demo",
        "requested_by": "tester"
    }
    response = client.post("/v1/runs", json=payload, headers=headers)
    assert response.status_code == 202
    data = response.json()
    assert "id" in data
    assert data["status"] == "pending"

def test_get_passport():
    response = client.get("/v1/passports/BR-2210-A", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["product_id"] == "BR-2210-A"

def test_supplier_signals():
    response = client.get("/v1/suppliers/signals?limit=2&min_spend_eur=0", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert len(data) > 0
    assert "supplier_id" in data[0]
    
def test_resolve_review():
    # Enqueue a fake item directly via the ReviewQueue first so it exists
    from cirquento.review.queue import ReviewQueue
    queue = ReviewQueue(".data/review_queue.jsonl")
    item = queue.enqueue(kind="classification", subject="test_material", reason="test")
    
    payload = {
        "code": "accept",
        "reviewer": "admin"
    }
    response = client.post(f"/v1/review/{item.id}", json=payload, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
