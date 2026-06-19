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

from fastapi import FastAPI, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import asyncio

# Add backend dir to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from agents.orchestrator import run_full_pipeline, run_spatial_only, run_rag_only
from integrations import get_integration_status

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

    # Build vector store if not exists
    print("Checking ChromaDB vector store...")
    from agents.rag_core import build_vector_store
    build_vector_store()
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

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
