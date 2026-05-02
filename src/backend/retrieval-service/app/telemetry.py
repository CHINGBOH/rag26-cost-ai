"""
OpenTelemetry bootstrap for retrieval-service.

Activates only when OTEL_EXPORTER_OTLP_ENDPOINT is set. This keeps local-dev
runs zero-overhead while allowing prod / docker-compose-tracing to flip on
distributed tracing by simply exporting the env var.

Why opt-in:
  - OTEL grpc/proto stacks add ~50ms cold-start
  - dev machines without Tempo would otherwise spam connect errors
  - keeps tests deterministic

Wires (auto-instrumentation):
  - FastAPI request/response spans (with route templates)
  - httpx outbound calls (Qdrant, TEI, ES) become child spans
  - asyncpg (Postgres) queries become DB-attribute spans

Service-graph friendly: every outgoing httpx call is recorded as a
SpanKind=CLIENT with peer.service inferred from host, which Tempo's
metrics-generator turns into traces_service_graph_request_total{client,server}.
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def init_telemetry(app, *, service_name: str = "retrieval-service") -> bool:
    """Initialise OTEL if endpoint configured. Returns True iff activated."""
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get(
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"
    )
    if not endpoint:
        logger.info("OTEL disabled (set OTEL_EXPORTER_OTLP_ENDPOINT to enable)")
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import SERVICE_NAME, Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    except Exception as exc:
        logger.warning(f"OTEL packages not available: {exc}")
        return False

    resource = Resource.create({SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()

    try:
        from opentelemetry.instrumentation.asyncpg import AsyncPGInstrumentor

        AsyncPGInstrumentor().instrument()
    except Exception as exc:
        logger.debug(f"asyncpg instrumentor skipped: {exc}")

    logger.info(f"✅ OTEL active → {endpoint} (service={service_name})")
    return True
