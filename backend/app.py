from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.api.schemas import StartCallRequest, TranscriptRequest
from backend.domain.auth import AuthorizationError
from backend.orchestration.realtime import ConflictError, NotFoundError, Platform, PlatformError


ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = os.getenv("DATABASE_PATH", str(ROOT / "data" / "platform.db"))
platform = Platform()
platform.store.close()
# Re-open with the configured path after construction so the app has durable local state.
from backend.adapters.persistence.sqlite import SQLiteStore  # noqa: E402
from backend.adapters.llm.azure_openai import AzureOpenAIExplanationAdapter  # noqa: E402
from backend.adapters.llm.fake import DeterministicExplanationAdapter  # noqa: E402

platform.store = SQLiteStore(DATABASE_PATH)
platform.traces.store = platform.store
if os.getenv("LLM_PROVIDER", "fake").lower() in {"azure", "azure_openai"}:
    platform.llm = AzureOpenAIExplanationAdapter()
else:
    platform.llm = DeterministicExplanationAdapter()
platform.registry.register(
    "demo-agent",
    permissions={"READ_CALL", "SUBSCRIBE_CALL", "INGEST_TRANSCRIPT", "UPDATE_COMPLAINT", "END_CALL", "RUN_POSTCALL", "DELETE_DERIVED"},
    allowed_customer_ids={"C001", "C002"},
    roles=("agent", "supervisor"),
)
platform.registry.register(
    "readonly-agent",
    permissions={"READ_CALL", "SUBSCRIBE_CALL"},
    allowed_customer_ids={"C001"},
    roles=("reader",),
)

app = FastAPI(title="Customer Intelligence Platform", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=str(ROOT / "frontend")), name="static")


def get_auth(x_principal_id: str = Header(default="demo-agent")):
    try:
        return platform.registry.current_for(x_principal_id)
    except AuthorizationError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


def _handle(exc: Exception) -> HTTPException:
    if isinstance(exc, (AuthorizationError, PermissionError)):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, NotFoundError):
        return HTTPException(status_code=404, detail=str(exc))
    if isinstance(exc, ConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, (PlatformError, ValueError)):
        return HTTPException(status_code=422, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


@app.get("/", include_in_schema=False)
async def index():
    return FileResponse(ROOT / "frontend" / "index.html")


@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": "local-reference"}


@app.get("/api/demo/scenario")
async def demo_scenario():
    from backend.services.scenario import load_demo_scenario

    return load_demo_scenario()


@app.get("/api/demo/scenarios")
async def demo_scenarios():
    from backend.services.scenario import load_demo_scenarios

    return {"scenarios": load_demo_scenarios()}


@app.post("/api/calls")
async def start_call(payload: StartCallRequest, auth=Depends(get_auth)):
    try:
        return await platform.start_call(auth, payload.customer_id)
    except Exception as exc:
        raise _handle(exc) from exc


@app.get("/api/calls/{call_id}")
async def get_call(call_id: str, auth=Depends(get_auth)):
    try:
        return await platform.get_view(auth, call_id)
    except Exception as exc:
        raise _handle(exc) from exc


@app.post("/api/calls/{call_id}/transcript")
async def ingest(call_id: str, payload: TranscriptRequest, auth=Depends(get_auth)):
    try:
        return await platform.ingest_segment(auth, call_id, **payload.model_dump())
    except Exception as exc:
        raise _handle(exc) from exc


@app.post("/api/calls/{call_id}/decisions/commercial")
async def commercial(call_id: str, auth=Depends(get_auth)):
    try:
        return await platform.request_commercial(auth, call_id)
    except Exception as exc:
        raise _handle(exc) from exc


@app.post("/api/calls/{call_id}/complaint/resolve")
async def resolve(call_id: str, auth=Depends(get_auth)):
    try:
        return await platform.resolve_complaint(auth, call_id)
    except Exception as exc:
        raise _handle(exc) from exc


@app.post("/api/calls/{call_id}/end")
async def end(call_id: str, auth=Depends(get_auth)):
    try:
        return await platform.end_call(auth, call_id)
    except Exception as exc:
        raise _handle(exc) from exc


@app.post("/api/calls/{call_id}/post-call")
async def post_call(call_id: str, auth=Depends(get_auth)):
    try:
        return await platform.post_call(auth, call_id)
    except Exception as exc:
        raise _handle(exc) from exc


@app.delete("/api/calls/{call_id}/derived")
async def delete_derived(call_id: str, auth=Depends(get_auth)):
    try:
        return await platform.delete_derived(auth, call_id)
    except Exception as exc:
        raise _handle(exc) from exc


@app.post("/api/calls/{call_id}/decisions/{decision_id}/server-published")
async def server_published(call_id: str, decision_id: str, auth=Depends(get_auth)):
    try:
        return await platform.mark_server_published(auth, call_id, decision_id)
    except Exception as exc:
        raise _handle(exc) from exc


@app.post("/api/calls/{call_id}/decisions/{decision_id}/ack")
async def acknowledged(call_id: str, decision_id: str, auth=Depends(get_auth)):
    try:
        return await platform.acknowledge(auth, call_id, decision_id)
    except Exception as exc:
        raise _handle(exc) from exc


@app.get("/api/calls/{call_id}/traces")
async def traces(call_id: str, auth=Depends(get_auth)):
    try:
        return await platform.get_traces(auth, call_id)
    except Exception as exc:
        raise _handle(exc) from exc


@app.get("/api/customers/{customer_id}/history")
async def history(customer_id: str, auth=Depends(get_auth)):
    try:
        return {"customer_id": customer_id, "records": platform.get_history(auth, customer_id)}
    except Exception as exc:
        raise _handle(exc) from exc


@app.get("/api/supervisor/interactions")
async def supervisor_interactions(auth=Depends(get_auth)):
    """Enumerate authorized interaction records and their assistance evidence."""
    try:
        records = []
        for customer_id in sorted(auth.allowed_customer_ids):
            for record in platform.get_history(auth, customer_id):
                traces = platform.store.traces(record["call_id"])
                assistance = {
                    "outcomes": [
                        trace["output_ref"]
                        for trace in traces
                        if trace["stage"] == "commercial_policy" and trace.get("output_ref")
                    ],
                    "propensity_refs": [
                        trace["output_ref"]
                        for trace in traces
                        if trace["stage"] == "propensity" and trace.get("output_ref")
                    ],
                    "guidance_refs": [
                        trace["output_ref"]
                        for trace in traces
                        if trace["stage"] == "guidance_retrieval" and trace.get("output_ref")
                    ],
                    "lifecycle": [
                        {
                            "stage": trace["stage"],
                            "status": trace["status"],
                            "output_ref": trace.get("output_ref"),
                        }
                        for trace in traces
                        if trace["stage"] in {"commercial_publication", "call_ended"}
                    ],
                }
                records.append({**record, "assistance": assistance, "traces": traces})
        records.sort(key=lambda item: item["created_at"], reverse=True)
        outcome_counts: dict[str, int] = {}
        for record in records:
            for outcome in record["assistance"]["outcomes"]:
                outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        return {
            "records": records,
            "summary": {
                "interaction_count": len(records),
                "customer_count": len({record["customer_id"] for record in records}),
                "outcome_counts": outcome_counts,
                "evidence_coverage": sum(
                    bool(json.loads(record["evidence_refs_json"]))
                    for record in records
                ),
            },
        }
    except Exception as exc:
        raise _handle(exc) from exc
