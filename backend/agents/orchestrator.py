"""
Agent Orchestrator: Coordinates the 3-agent pipeline.

Pipeline:
1. Agent 1 (Spatial) + Agent 2 (RAG) run in PARALLEL
2. Both results feed into Agent 3 (Command Synthesizer)
3. Agent 3 streams response via SSE

This is the CDF-RAG feedback loop adapted for traffic:
Query → Causal Retrieval + Spatial Analysis → Synthesis → Validation
"""

import asyncio
import json
import time
from typing import AsyncGenerator

from agents.spatial_engine import compute_blast_radius
from agents.rag_core import retrieve_historical_context
from agents.command_synthesizer import synthesize_command


async def run_spatial_agent(event_id: str) -> dict:
    """Run Agent 1 in a thread (CPU-bound computation)."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(None, compute_blast_radius, event_id)
    return result


async def run_rag_agent(event_id: str, spatial_data: dict = None) -> dict:
    """Run Agent 2 in a thread (I/O-bound ChromaDB query)."""
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None, retrieve_historical_context, event_id, spatial_data
    )
    return result


async def run_full_pipeline(event_id: str) -> AsyncGenerator[dict, None]:
    """
    Execute the full 3-agent pipeline with streaming output.

    Yields status updates and final streamed command:
    {"type": "status", "agent": "spatial", "status": "running"}
    {"type": "spatial_result", "data": {...}}
    {"type": "rag_result", "data": {...}}
    {"type": "command_chunk", "text": "..."}
    {"type": "complete"}
    """
    start_time = time.time()

    # === Phase 1: Parallel execution of Agent 1 + Agent 2 ===
    yield {"type": "status", "agent": "spatial", "status": "running", "message": "Computing blast radius..."}
    yield {"type": "status", "agent": "rag", "status": "running", "message": "Searching historical incidents..."}

    # Run both agents in parallel
    spatial_result, rag_result = await asyncio.gather(
        run_spatial_agent(event_id),
        run_rag_agent(event_id),
    )

    spatial_time = time.time() - start_time

    # Send Agent 1 result
    yield {
        "type": "spatial_result",
        "data": spatial_result,
        "elapsed_ms": int(spatial_time * 1000),
    }

    # Send Agent 2 result
    yield {
        "type": "rag_result",
        "data": rag_result,
        "elapsed_ms": int((time.time() - start_time) * 1000),
    }

    # === Phase 2: Agent 3 synthesis with streaming ===
    yield {
        "type": "status",
        "agent": "command",
        "status": "running",
        "message": "Generating operational command...",
    }

    # Check for errors
    if "error" in spatial_result or "error" in rag_result:
        yield {
            "type": "error",
            "message": spatial_result.get("error", "") or rag_result.get("error", ""),
        }
        return

    # Stream Agent 3 output
    async for chunk in synthesize_command(spatial_result, rag_result, stream=True):
        yield {"type": "command_chunk", "text": chunk}

    total_time = time.time() - start_time
    yield {
        "type": "complete",
        "total_elapsed_ms": int(total_time * 1000),
        "agents_summary": {
            "spatial": {
                "affected_junctions": spatial_result.get("blast_radius", {}).get(
                    "total_affected_junctions", 0
                ),
                "critical_junctions": spatial_result.get("blast_radius", {}).get(
                    "critical_junctions", 0
                ),
            },
            "rag": {
                "matches_found": rag_result.get("pattern_analysis", {}).get(
                    "total_similar_events_found", 0
                ),
                "avg_clearance": rag_result.get("pattern_analysis", {}).get(
                    "avg_clearance_time_mins"
                ),
            },
        },
    }


async def run_spatial_only(event_id: str) -> dict:
    """Run only Agent 1 for quick blast radius visualization."""
    return await run_spatial_agent(event_id)


async def run_rag_only(event_id: str) -> dict:
    """Run only Agent 2 for historical context."""
    return await run_rag_agent(event_id)
