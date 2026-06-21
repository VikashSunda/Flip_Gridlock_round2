"""
ASTraM Nexus Backend — FastAPI Server

Endpoints:
  GET  /                     → Health check
  GET  /events               → All events (paginated, filterable)
  GET  /events/{id}          → Single event details
  GET  /junctions            → Junction graph for map rendering
  GET  /corridors            → Corridor statistics
  POST /analyze/{event_id}   → Trigger full 3-agent pipeline (SSE stream)
  POST /spatial/{event_id}   → Agent 1 only (blast radius)
  POST /rag/{event_id}       → Agent 2 only (historical context)
"""

import json
import os
import sys
from typing import List, Optional

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

# Add backend dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.orchestrator import (
    run_full_pipeline,
    run_forecast_pipeline,
    run_spatial_only,
    run_rag_only,
)
from integrations import get_integration_status


class ForecastRequest(BaseModel):
    """Future/planned event to forecast (preset-populated or free-form)."""
    event_cause: str
    latitude: float
    longitude: float
    corridor: str = ""
    junction: str = ""
    start_datetime: Optional[str] = None
    scheduled_duration_mins: Optional[float] = None
    priority: str = ""
    requires_road_closure: bool = False
    description: str = ""
    severity: Optional[int] = None
    source_event_id: Optional[str] = None  # set when forecasting a real preset
    edited: bool = False                    # true once the user tweaks a preset


class FeedbackRequest(BaseModel):
    """Post-event outcome reported back to close the learning loop (R1)."""
    event_id: Optional[str] = None
    event_cause: str = ""
    corridor: str = ""
    predicted_mins: Optional[float] = None
    actual_mins: float
    notes: str = ""


class AllocateRequest(BaseModel):
    """Allocate a finite officer budget across concurrent events (R2)."""
    event_ids: List[str]
    total_officers: int = 20

# Load pre-processed data
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def load_json(filename):
    filepath = os.path.join(DATA_DIR, filename)
    if not os.path.exists(filepath):
        return None
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


# Initialize app
app = FastAPI(
    title="ASTraM Nexus",
    description="Multi-Agent Causal AI Command Center for Bengaluru Traffic Police",
    version="1.0.0",
)

# CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Load data on startup
events_data = None
events_index = None
junction_graph = None
corridor_stats = None


@app.on_event("startup")
async def startup():
    global events_data, events_index, junction_graph, corridor_stats
    print("Loading pre-processed data...")
    events_data = load_json("events.json") or []
    events_index = {e["id"]: e for e in events_data}
    junction_graph = load_json("junction_graph.json") or {}
    corridor_stats = load_json("corridor_stats.json") or {}
    print(f"  Events: {len(events_data)}")
    print(f"  Junctions: {len(junction_graph.get('nodes', {}))}")
    print(f"  Corridors: {len(corridor_stats)}")

    # Build the in-process TF-IDF retrieval index
    print("Building retrieval index...")
    from agents.rag_core import build_vector_store
    build_vector_store()
    # Warm engine caches (priors + junction stats) so the first request is fast
    from agents.spatial_engine import _load_priors, _load_junction_stats
    _load_priors()
    _load_junction_stats()
    print("ASTraM Nexus backend ready.")


# ============================================
# Health Check
# ============================================

@app.get("/")
async def root():
    return {
        "service": "ASTraM Nexus",
        "status": "operational",
        "events_loaded": len(events_data) if events_data else 0,
        "junctions": len(junction_graph.get("nodes", {})) if junction_graph else 0,
        "integrations": get_integration_status(),
    }


@app.get("/integrations")
async def integrations():
    """Get third-party provider readiness without exposing secrets."""
    return get_integration_status()


# ============================================
# Events Endpoints
# ============================================

@app.get("/events")
async def get_events(
    event_type: str = Query(None, description="Filter by event_type"),
    event_cause: str = Query(None, description="Filter by event_cause"),
    corridor: str = Query(None, description="Filter by corridor"),
    priority: str = Query(None, description="Filter by priority"),
    zone: str = Query(None, description="Filter by zone"),
    junction: str = Query(None, description="Filter by junction"),
    status: str = Query(None, description="Filter by status (e.g. active) — R3 real-time feed"),
    limit: int = Query(100, ge=1, le=8200),
    offset: int = Query(0, ge=0),
):
    """Get events with optional filtering."""
    filtered = events_data

    if event_type:
        filtered = [e for e in filtered if e["event_type"] == event_type]
    if event_cause:
        filtered = [e for e in filtered if e["event_cause"] == event_cause]
    if corridor:
        filtered = [e for e in filtered if e["corridor"] == corridor]
    if priority:
        filtered = [e for e in filtered if e["priority"] == priority]
    if zone:
        filtered = [e for e in filtered if e.get("zone") == zone]
    if junction:
        filtered = [e for e in filtered if e.get("junction") == junction]
    if status:
        filtered = [e for e in filtered if e.get("status") == status]

    total = len(filtered)
    paginated = filtered[offset: offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "events": paginated,
    }


@app.get("/events/{event_id}")
async def get_event(event_id: str):
    """Get single event by ID."""
    event = events_index.get(event_id)
    if not event:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    return event


# ============================================
# Junction Graph & Corridors
# ============================================

@app.get("/junctions")
async def get_junctions():
    """Get junction graph for map rendering."""
    return junction_graph


@app.get("/corridors")
async def get_corridors():
    """Get corridor statistics."""
    return corridor_stats


# ============================================
# Agent Pipeline Endpoints
# ============================================

@app.post("/analyze/{event_id}")
async def analyze_event(event_id: str):
    """
    Trigger the full 3-agent pipeline for an event.
    Returns Server-Sent Events (SSE) stream.
    """
    if event_id not in events_index:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")

    async def event_stream():
        async for update in run_full_pipeline(event_id):
            yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/forecast")
async def forecast(req: ForecastRequest):
    """
    Forecast a future/planned event (proactive flow).
    Returns the same SSE contract as /analyze.
    """
    async def event_stream():
        async for update in run_forecast_pipeline(req.model_dump()):
            yield f"data: {json.dumps(update)}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================
# Post-event learning loop (R1)
# ============================================

FEEDBACK_PATH = os.path.join(DATA_DIR, "feedback.jsonl")


def _read_feedback():
    if not os.path.exists(FEEDBACK_PATH):
        return []
    items = []
    with open(FEEDBACK_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    items.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return items


@app.post("/feedback")
async def submit_feedback(fb: FeedbackRequest):
    """Record an actual post-event outcome (closes the PS's 'no post-event learning' gap)."""
    import datetime as _dt
    rec = fb.model_dump()
    rec["ts"] = _dt.datetime.utcnow().isoformat() + "Z"
    with open(FEEDBACK_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    return {
        "status": "recorded",
        "count": len(_read_feedback()),
        "learning": "outcome logged and tracked as prediction error; priors are recalibrated on the next re-training run (not an automatic online update)",
    }


@app.get("/feedback")
async def list_feedback():
    """Feedback log + running prediction-error metric (demonstrates the loop is closed)."""
    items = _read_feedback()
    errs = [abs(r["actual_mins"] - r["predicted_mins"])
            for r in items if r.get("predicted_mins") is not None and r.get("actual_mins") is not None]
    return {
        "count": len(items),
        "mean_abs_error_mins": round(sum(errs) / len(errs), 1) if errs else None,
        "recent": items[-20:],
    }


# ============================================
# Multi-event manpower allocation under a budget (R2)
# ============================================

@app.post("/allocate")
async def allocate(req: AllocateRequest):
    """
    Allocate a finite officer budget across several (concurrent) events.

    Addresses B10: per-event manpower in isolation can over-commit a finite force.
    Demand per event reuses the SAME full forecast heuristic as /forecast (so the
    number matches the forecast tab, including the critical-junction term). When
    demand exceeds budget we water-fill a severity-weighted split, capped at each
    event's demand, with no officer left unallocated.
    """
    from agents.spatial_engine import compute_blast_radius

    if req.total_officers < 1:
        raise HTTPException(status_code=400, detail="total_officers must be >= 1")

    rows = []
    for eid in req.event_ids:
        ev = events_index.get(eid)
        if not ev:
            continue
        # Use the same blast-radius-derived manpower the forecast tab shows, so an
        # event does not appear to "need" fewer officers here than in its forecast.
        res = compute_blast_radius(eid)
        demand = (res.get("deployment_recommendation", {})
                     .get("manpower", {})
                     .get("units", 2))
        rows.append({
            "event_id": eid, "event_cause": ev["event_cause"],
            "corridor": ev.get("corridor"), "severity": ev["severity_score"],
            "demand": demand, "allocated": 0,
        })

    if not rows:
        raise HTTPException(status_code=404, detail="No valid events to allocate")

    budget = req.total_officers
    total_demand = sum(r["demand"] for r in rows)

    if total_demand <= budget:
        for r in rows:
            r["allocated"] = r["demand"]
        status = "sufficient"
    else:
        status = "oversubscribed"
        remaining = budget
        # 1) Guarantee >=1 per event in severity order while the budget lasts.
        #    If budget < event count, only the highest-severity events are funded
        #    (flagged below) rather than silently handing some events zero.
        for r in sorted(rows, key=lambda x: -x["severity"]):
            if remaining <= 0:
                break
            r["allocated"] = 1
            remaining -= 1
        # 2) Water-fill the remainder by severity-weighted demand, capped at each
        #    event's demand, looping until exhausted so no officer is left idle
        #    (fixes the round-down waste in the old single-pass split).
        while remaining > 0 and any(r["allocated"] < r["demand"] for r in rows):
            eligible = [r for r in rows if r["allocated"] < r["demand"]]
            wsum = sum(r["demand"] * r["severity"] for r in eligible) or 1
            progressed = False
            for r in sorted(eligible, key=lambda x: -(x["demand"] * x["severity"])):
                if remaining <= 0:
                    break
                want = max(1, round(remaining * (r["demand"] * r["severity"]) / wsum))
                give = min(want, r["demand"] - r["allocated"], remaining)
                if give > 0:
                    r["allocated"] += give
                    remaining -= give
                    progressed = True
            if not progressed:
                break

    allocated_total = sum(r["allocated"] for r in rows)
    unfunded = [r["event_id"] for r in rows if r["allocated"] == 0]

    return {
        "status": status,
        "budget": budget,
        "total_demand": total_demand,
        "allocated_total": allocated_total,
        "reserve": max(0, budget - allocated_total),
        "unfunded_events": unfunded,
        "events": len(rows),
        "allocations": sorted(rows, key=lambda x: -x["severity"]),
        "note": (
            "Severity-weighted water-fill of a finite force across concurrent events (R2); "
            "demand matches the per-event forecast heuristic (no deployment ground truth). "
            + ("Budget is below the event count, so only the highest-severity events are funded — "
               "the rest are flagged as unfunded."
               if unfunded else
               "Every funded event keeps at least one unit and no officer is left unallocated.")
        ),
    }


# ============================================
# Historical-replay trigger (R10) — sudden-gathering detector
# ============================================

@app.get("/replay/timeline")
async def replay_timeline(
    window: str = Query("2024-03-07", description="Replay day (YYYY-MM-DD). Default is a "
                        "validated storm-morning with genuine spatiotemporal surges."),
    start_hour: int = Query(5, ge=0, le=23, description="Replay band start hour (local)"),
    end_hour: int = Query(9, ge=1, le=24, description="Replay band end hour (local, exclusive)"),
):
    """
    Chronological unplanned-event timeline + precomputed space-time surge alerts.

    NOT a live feed: this replays the historical snapshot. The detection rule
    (>= N high-severity incidents within R km / T min) is what a real-time pipeline
    would run over a live stream; the frontend animates the timeline and uses each
    alert's anchor_event_id to auto-launch the existing /analyze pipeline.
    """
    from replay import get_replay_timeline
    return get_replay_timeline(events_data, window, start_hour, end_hour)


@app.post("/spatial/{event_id}")
async def spatial_analysis(event_id: str):
    """Run Agent 1 only — blast radius computation."""
    if event_id not in events_index:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    result = await run_spatial_only(event_id)
    return result


@app.post("/rag/{event_id}")
async def rag_analysis(event_id: str):
    """Run Agent 2 only — historical RAG retrieval."""
    if event_id not in events_index:
        raise HTTPException(status_code=404, detail=f"Event {event_id} not found")
    result = await run_rag_only(event_id)
    return result


# ============================================
# Event Statistics
# ============================================

@app.get("/stats")
async def get_stats():
    """Get aggregate statistics for the dashboard."""
    from collections import Counter

    causes = Counter(e["event_cause"] for e in events_data)
    types = Counter(e["event_type"] for e in events_data)
    priorities = Counter(e["priority"] for e in events_data)
    corridors = Counter(e["corridor"] for e in events_data if e["corridor"] != "Non-corridor")
    statuses = Counter(e["status"] for e in events_data)

    clearance_times = [
        e["clearance_time_mins"]
        for e in events_data
        if e.get("clearance_time_mins")
    ]

    return {
        "total_events": len(events_data),
        "event_types": dict(types),
        "event_causes": dict(causes.most_common(15)),
        "priorities": dict(priorities),
        "top_corridors": dict(corridors.most_common(10)),
        "statuses": dict(statuses),
        "clearance_stats": {
            "events_with_data": len(clearance_times),
            "avg_mins": round(sum(clearance_times) / len(clearance_times), 1)
            if clearance_times
            else None,
            "median_mins": sorted(clearance_times)[len(clearance_times) // 2]
            if clearance_times
            else None,
        },
        "junctions_in_graph": len(junction_graph.get("nodes", {})),
        "spatial_edges": len(junction_graph.get("edges", [])),
    }


if __name__ == "__main__":
    import uvicorn

    # reload disabled: the startup rebuilds the TF-IDF index, so auto-reload on
    # every file save is wasteful. Restart manually after backend changes.
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
