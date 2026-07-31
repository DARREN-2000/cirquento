import time
import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware
import logging

logger = logging.getLogger("cirquento.api.requests")

class RequestTracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", str(uuid.uuid4()))
        request.state.request_id = request_id
        
        start_time = time.time()
        
        # Log request start
        logger.info(f"Started {request.method} {request.url.path} - ID: {request_id}")
        
        response = await call_next(request)
        
        process_time = time.time() - start_time
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Process-Time"] = str(process_time)
        
        # Log request completion
        logger.info(f"Completed {request.method} {request.url.path} - Status: {response.status_code} - Time: {process_time:.4f}s - ID: {request_id}")
        
        return response

def setup_middlewares(app):
    app.add_middleware(RequestTracingMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # Should be restricted in real prod via settings
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-Id", "X-Process-Time"]
    )
