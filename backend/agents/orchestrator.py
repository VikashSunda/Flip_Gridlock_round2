"""
Agent Orchestrator: coordinates the agent pipeline for two flows.

Reactive (existing event):   run_full_pipeline(event_id)
Proactive (future event):    run_forecast_pipeline(forecast_input)

Both run Agent 1 (spatial) + Agent 2 (RAG) in parallel, then stream Agent 3
(command synthesis). The synthesizer is told whether this is a pre-event plan
or an incident response via `mode` (Fix 3: planned vs unplanned).
"""

import asyncio
import time
from typing import AsyncGenerator

from agents.spatial_engine import (
    compute_blast_radius,
    compute_blast_radius_core,
    _load_events,
)
from agents.rag_core import (
    retrieve_historical_context,
    retrieve_historical_context_params,
)
from agents.command_synthesizer import synthesize_command
from feature_utils import estimate_severity


# ============================================
# Reactive flow (existing event)
# ============================================

async def run_spatial_agent(event_id: str) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, compute_blast_radius, event_id)


async def run_rag_agent(event_id: str, spatial_data: dict = None) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None, retrieve_historical_context, event_id, spatial_data
    )


def _mode_for_event_type(event_type: str) -> str:
    """Fix 3: planned events get pre-event deployment framing; unplanned = reactive."""
    return "forecast" if event_type == "planned" else "reactive"


async def run_full_pipeline(event_id: str) -> AsyncGenerator[dict, None]:
    """Reactive 3-agent pipeline for an existing event (SSE updates)."""
    start_time = time.time()

    _, idx = _load_events()
    event = idx.get(event_id, {})
    mode = _mode_for_event_type(event.get("event_type", "unplanned"))

    yield {"type": "status", "agent": "spatial", "status": "running", "message": "Computing blast radius..."}
    yield {"type": "status", "agent": "rag", "status": "running", "message": "Searching historical incidents..."}

    spatial_result, rag_result = await asyncio.gather(
        run_spatial_agent(event_id),
        run_rag_agent(event_id),
    )

    yield {"type": "spatial_result", "data": spatial_result, "elapsed_ms": int((time.time() - start_time) * 1000)}
    yield {"type": "rag_result", "data": rag_result, "elapsed_ms": int((time.time() - start_time) * 1000)}

    yield {"type": "status", "agent": "command", "status": "running", "message": "Generating operational command..."}

    if "error" in spatial_result or "error" in rag_result:
        yield {"type": "error", "message": spatial_result.get("error", "") or rag_result.get("error", "")}
        return

    async for chunk in synthesize_command(spatial_result, rag_result, stream=True, mode=mode):
        yield {"type": "command_chunk", "text": chunk}

    yield _completion_event(spatial_result, rag_result, start_time, mode)


# ============================================
# Proactive flow (forecast a future event)
# ============================================

async def run_spatial_forecast(fi: dict) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: compute_blast_radius_core(
        lat=fi["latitude"],
        lon=fi["longitude"],
        severity=fi["severity"],
        event_cause=fi["event_cause"],
        event_type="planned",
        corridor=fi.get("corridor", ""),
        start_datetime=fi.get("start_datetime"),
        scheduled_duration_mins=fi.get("scheduled_duration_mins"),
        requires_road_closure=fi.get("requires_road_closure", False),
        description=fi.get("description", ""),
        priority=fi.get("priority", ""),
        address=fi.get("address", ""),
        source_event_id=fi.get("source_event_id"),
    ))


async def run_rag_forecast(fi: dict) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: retrieve_historical_context_params(
        event_cause=fi["event_cause"],
        junction=fi.get("junction", ""),
        corridor=fi.get("corridor", ""),
        event_type="planned",
        description=fi.get("description", ""),
    ))


async def run_forecast_pipeline(forecast_input: dict) -> AsyncGenerator[dict, None]:
    """Proactive forecast pipeline for a planned/future event (same SSE contract)."""
    start_time = time.time()
    fi = dict(forecast_input)

    # Severity prior if the caller didn't supply one (shared estimator).
    if not fi.get("severity"):
        fi["severity"] = estimate_severity(
            fi.get("event_cause", "others"), fi.get("priority", ""), fi.get("requires_road_closure", False)
        )

    yield {"type": "status", "agent": "spatial", "status": "running", "message": "Forecasting blast radius..."}
    yield {"type": "status", "agent": "rag", "status": "running", "message": "Retrieving similar past events..."}

    spatial_result, rag_result = await asyncio.gather(
        run_spatial_forecast(fi),
        run_rag_forecast(fi),
    )

    # Predicted-vs-actual: only meaningful for an UNEDITED preset (B3).
    if fi.get("source_event_id") and not fi.get("edited"):
        _, idx = _load_events()
        src = idx.get(fi["source_event_id"])
        if src and src.get("clearance_time_mins") and isinstance(spatial_result.get("predicted_clearance"), dict):
            spatial_result["predicted_clearance"]["actual_mins"] = src["clearance_time_mins"]

    yield {"type": "spatial_result", "data": spatial_result, "elapsed_ms": int((time.time() - start_time) * 1000)}
    yield {"type": "rag_result", "data": rag_result, "elapsed_ms": int((time.time() - start_time) * 1000)}

    yield {"type": "status", "agent": "command", "status": "running", "message": "Generating deployment plan..."}

    if "error" in spatial_result:
        yield {"type": "error", "message": spatial_result.get("error", "forecast failed")}
        return

    async for chunk in synthesize_command(spatial_result, rag_result, stream=True, mode="forecast"):
        yield {"type": "command_chunk", "text": chunk}

    yield _completion_event(spatial_result, rag_result, start_time, "forecast")


def _completion_event(spatial_result, rag_result, start_time, mode):
    return {
        "type": "complete",
        "mode": mode,
        "total_elapsed_ms": int((time.time() - start_time) * 1000),
        "agents_summary": {
            "spatial": {
                "affected_junctions": spatial_result.get("blast_radius", {}).get("total_affected_junctions", 0),
                "critical_junctions": spatial_result.get("blast_radius", {}).get("critical_junctions", 0),
                "units": spatial_result.get("deployment_recommendation", {}).get("manpower", {}).get("units"),
            },
            "rag": {
                "matches_found": rag_result.get("pattern_analysis", {}).get("total_similar_events_found", 0),
                "avg_clearance": rag_result.get("pattern_analysis", {}).get("avg_clearance_time_mins"),
            },
        },
    }


# ============================================
# Single-agent helpers (unchanged API)
# ============================================

async def run_spatial_only(event_id: str) -> dict:
    return await run_spatial_agent(event_id)


async def run_rag_only(event_id: str) -> dict:
    return await run_rag_agent(event_id)
