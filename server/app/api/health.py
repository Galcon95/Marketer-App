"""Basic endpoints: smoke tests, health of the API and its services, LLM usage and costs."""

from fastapi import APIRouter, Query

from app.core import llm, usage
from app.core.schemas import Health, ServiceStatus, UsageReport
from app.rag import vectorstore

router = APIRouter()


@router.get("/")
def root():
    """Smoke-test endpoint: returns a fixed greeting to show the server is reachable."""
    return {"message": "Hello, World!"}


@router.get("/test")
def test():
    """Second smoke-test endpoint used by the client to check the connection."""
    return {"message": "Hello, Server World!"}


@router.get("/health", response_model=Health)
def health():
    """Report the status of the API and its dependencies.

    The vector database is reported with its vector count and embedding model, the LLM with its
    model and whether LangSmith tracing is on (both down if no API key is set). Overall `ok`
    reflects only the API itself.
    """
    vector_ok, vector_detail = vectorstore.health()
    llm_ok, llm_detail = llm.health()
    services = [
        ServiceStatus(name="api", ok=True, detail="running"),
        ServiceStatus(name="vector_db", ok=vector_ok, detail=vector_detail),
        ServiceStatus(name="llm", ok=llm_ok, detail=llm_detail),
    ]
    return Health(ok=services[0].ok, services=services)


@router.get("/usage", response_model=UsageReport)
def get_usage(limit: int = Query(50, ge=1, le=1000)):
    """Tokens and costs of all model calls so far (see usage.py).

    Args:
        limit: Number of latest calls to include (query parameter, 1-1000).

    Returns:
        Totals (input/output tokens and costs, all costs), totals per operation, latest calls.
    """
    return usage.report(limit)
