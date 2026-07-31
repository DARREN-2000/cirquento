"""Tracing that degrades instead of failing.

OpenTelemetry is the production path, but the demo, the tests and CI must run
with zero collectors configured. So the tracer falls back to a no-op with the
same surface: instrumentation should never be the reason a build breaks.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator


class _NoopSpan:
    def set_attribute(self, key: str, value: Any) -> None:  # noqa: D102
        return None

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        return None

    def record_exception(self, exc: BaseException) -> None:
        return None


class _NoopTracer:
    @contextmanager
    def start_as_current_span(self, name: str) -> Iterator[_NoopSpan]:
        yield _NoopSpan()


try:  # pragma: no cover - exercised only when OTel is installed
    from opentelemetry import trace as _otel_trace

    tracer: Any = _otel_trace.get_tracer("cirquento")
except ModuleNotFoundError:
    tracer = _NoopTracer()


def setup_telemetry(service_name: str = "cirquento") -> None:
    """Wire up OTLP export when the SDK and an endpoint are both present."""
    try:  # pragma: no cover
        import os

        if not os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
            return
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
    except ModuleNotFoundError:
        return


__all__ = ["tracer", "setup_telemetry"]
