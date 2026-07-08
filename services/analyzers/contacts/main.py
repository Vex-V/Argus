"""C12 — Contacts Analyzer service (port 8014)."""
from fastapi import FastAPI

from shared.cors import add_cors

from shared.evidence import capture_provenance
from shared.schemas import ContactsRequest, ServiceResponse

from .analyzer import analyze_contacts

app = FastAPI(
    title="Argus — Contacts Analyzer",
    version="0.1.0",
    description="C12: Jaccard + weighted interaction overlap between social networks.",
)


add_cors(app)

@app.post("/analyze/contacts", response_model=ServiceResponse, tags=["analyzer"])
def contacts(request: ContactsRequest) -> ServiceResponse:
    result = analyze_contacts(
        [c.model_dump() for c in request.contacts_a],
        [c.model_dump() for c in request.contacts_b],
    )
    return ServiceResponse(results=[result], provenance=capture_provenance("contacts_analyzer"))


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "service": "contacts_analyzer"}
