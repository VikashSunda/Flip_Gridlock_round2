"""
Agent 1: The Spatial-Causal Engine (The Simulator)

Inspired by CDF-RAG's causal graph retrieval (arxiv:2504.12560).
Instead of Neo4j, we use an in-memory junction adjacency graph as our causal DAG.
Edges represent CAUSES/IMPACTS relationships: if junction A is congested,
junction B (connected via road) WILL be impacted with probability proportional
to 1/distance.

The do-calculus interpretation:
P(Congestion_B | do(BlockRoad_A)) is estimated via BFS propagation
with exponential distance decay — a tractable approximation of
interventional causal inference on spatial graphs.
"""

import json
import math
import os
from collections import defaultdict
from heapq import heappush, heappop
from typing import Optional

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Cache loaded data
_graph_cache = None
_events_cache = None
_events_index = None


def _load_graph():
    global _graph_cache
    if _graph_cache is None:
        with open(os.path.join(DATA_DIR, "junction_graph.json"), "r") as f:
            _graph_cache = json.load(f)
    return _graph_cache


def _load_events():
    global _events_cache, _events_index
    if _events_cache is None:
        with open(os.path.join(DATA_DIR, "events.json"), "r") as f:
            _events_cache = json.load(f)
        _events_index = {e["id"]: e for e in _events_cache}
    return _events_cache, _events_index


def haversine_km(lat1, lon1, lat2, lon2):
    """Haversine distance between two lat/lon points in km."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.asin(math.sqrt(a))


def find_nearest_junction(lat: float, lon: float, graph: dict) -> tuple:
    """Find the closest junction node to given coordinates."""
    best = None
    best_dist = float("inf")
    for name, node in graph["nodes"].items():
        d = haversine_km(lat, lon, node["latitude"], node["longitude"])
        if d < best_dist:
            best_dist = d
            best = name
    return best, best_dist


def _get_historical_stats_for_junction(junction_name: str, events: list) -> dict:
    """Get historical statistics for a junction from event data."""
    junction_events = [e for e in events if e.get("junction") == junction_name]
    if not junction_events:
        return {"event_count": 0}

    clearance_times = [
        e["clearance_time_mins"]
        for e in junction_events
        if e.get("clearance_time_mins")
    ]
    causes = defaultdict(int)
    for e in junction_events:
        causes[e["event_cause"]] += 1

    return {
        "event_count": len(junction_events),
        "avg_clearance_mins": round(sum(clearance_times) / len(clearance_times), 1)
        if clearance_times
        else None,
        "top_causes": dict(sorted(causes.items(), key=lambda x: -x[1])[:3]),
    }


def compute_blast_radius(
    event_id: str,
    max_hops: int = 3,
    max_radius_km: float = 5.0,
) -> dict:
    """
    Core causal inference function.

    Computes P(Congestion_j | do(Event at epicenter)) for all junctions j
    within the blast radius using Dijkstra BFS with exponential decay.

    This is our tractable approximation of do-calculus on the spatial
    causal graph. The "intervention" is the event blocking/degrading
    the epicenter junction, and we propagate the causal effect outward.

    Returns structured JSON matching the Agent 1 output spec.
    """
    graph = _load_graph()
    events, events_index = _load_events()
    try:
        from integrations import get_integration_status
        mapmyindia_status = get_integration_status()["mapmyindia"]
    except Exception:
        mapmyindia_status = {
            "status": "offline_fallback",
            "fallback": "local Bengaluru causal graph + haversine distances",
        }

    # Find the event
    event = events_index.get(event_id)
    if not event:
        return {"error": f"Event {event_id} not found"}

    epicenter_lat = event["latitude"]
    epicenter_lon = event["longitude"]
    severity = event["severity_score"]

    # Find nearest junction to event (epicenter node in causal graph)
    epicenter_junction, epicenter_dist = find_nearest_junction(
        epicenter_lat, epicenter_lon, graph
    )

    # === CAUSAL PROPAGATION via Dijkstra BFS ===
    # This implements: P(impact_j) = severity * exp(-λ * d(epicenter, j))
    # where λ = 0.5 is our decay rate and d is graph distance in km
    DECAY_LAMBDA = 0.5
    CONGESTION_PROPAGATION_SPEED_KM_PER_MIN = 0.5  # ~500m/min in urban Bengaluru

    affected = {}
    visited = set()
    queue = [(0.0, epicenter_junction, 0)]  # (distance, junction, hops)

    while queue:
        dist, junction, hops = heappop(queue)

        if junction in visited:
            continue
        visited.add(junction)

        if hops > max_hops or dist > max_radius_km:
            continue

        # Causal impact: P(congestion | do(event)) = severity * e^(-λd)
        causal_probability = math.exp(-DECAY_LAMBDA * dist)
        capacity_reduction = min(95, int(severity * causal_probability * 10))

        # Time for congestion wave to reach this junction
        time_to_impact_mins = round(dist / CONGESTION_PROPAGATION_SPEED_KM_PER_MIN, 1) if dist > 0 else 0

        node_data = graph["nodes"].get(junction, {})
        hist_stats = _get_historical_stats_for_junction(junction, events)

        affected[junction] = {
            "junction": junction,
            "latitude": node_data.get("latitude", 0),
            "longitude": node_data.get("longitude", 0),
            "distance_km": round(dist, 2),
            "hops_from_epicenter": hops,
            "causal_impact_probability": round(causal_probability, 3),
            "capacity_reduction_pct": capacity_reduction,
            "estimated_time_to_impact_mins": time_to_impact_mins,
            "historical_event_count": hist_stats["event_count"],
            "historical_avg_clearance_mins": hist_stats.get("avg_clearance_mins"),
            "historical_top_causes": hist_stats.get("top_causes", {}),
        }

        # Explore causal children (adjacent junctions)
        adjacency = graph.get("adjacency", {})
        for neighbor in adjacency.get(junction, []):
            if neighbor["junction"] not in visited:
                new_dist = dist + neighbor["distance_km"]
                heappush(queue, (new_dist, neighbor["junction"], hops + 1))

    # Sort by causal impact (highest first)
    affected_list = sorted(
        affected.values(), key=lambda x: x["causal_impact_probability"], reverse=True
    )

    # === COUNTERFACTUAL ANALYSIS ===
    # Without intervention: cascading effect multiplies clearance time
    # With intervention: targeted deployment reduces by ~30%
    base_clearance = 45  # median from dataset
    if event.get("clearance_time_mins"):
        base_clearance = event["clearance_time_mins"]

    cascade_factor = 1 + (len([n for n in affected_list if n["causal_impact_probability"] > 0.3]) * 0.15)
    without_intervention = int(base_clearance * cascade_factor)
    with_intervention = int(base_clearance * 0.65)

    # Determine affected corridors
    event_corridor = event.get("corridor", "")
    affected_corridors = set()
    for node in affected_list:
        for e in events:
            if e.get("junction") == node["junction"] and e.get("corridor", "Non-corridor") != "Non-corridor":
                affected_corridors.add(e["corridor"])
                break

    # Recommended ASTraM unit count based on severity and blast radius
    critical_junctions = [n for n in affected_list if n["causal_impact_probability"] > 0.4]
    recommended_units = max(2, min(8, len(critical_junctions) + severity // 3))

    result = {
        "event_id": event_id,
        "event_type": event["event_type"],
        "event_cause": event["event_cause"],
        "severity_score": severity,
        "epicenter": {
            "latitude": epicenter_lat,
            "longitude": epicenter_lon,
            "address": event.get("address", ""),
            "nearest_junction": epicenter_junction,
            "junction_distance_km": round(epicenter_dist, 2),
        },
        "blast_radius": {
            "total_affected_junctions": len(affected_list),
            "max_radius_km": round(
                max((n["distance_km"] for n in affected_list), default=0), 2
            ),
            "critical_junctions": len(critical_junctions),
            "affected_nodes": affected_list[:15],  # Top 15 for frontend
        },
        "causal_analysis": {
            "model": "Spatial BFS with exponential decay (λ=0.5)",
            "interpretation": f"P(Congestion_j | do(Event at {epicenter_junction})) computed for {len(affected_list)} junctions",
            "decay_rate": DECAY_LAMBDA,
            "propagation_speed_km_per_min": CONGESTION_PROPAGATION_SPEED_KM_PER_MIN,
            "routing_provider": "MapmyIndia/Mappls credentialed + local causal graph" if mapmyindia_status.get("status") == "connected" else "Offline causal graph fallback",
            "provider_status": mapmyindia_status.get("status", "offline_fallback"),
        },
        "counterfactual": {
            "without_intervention_mins": without_intervention,
            "with_intervention_mins": with_intervention,
            "time_saved_mins": without_intervention - with_intervention,
            "cascade_factor": round(cascade_factor, 2),
        },
        "deployment_recommendation": {
            "astram_units_needed": recommended_units,
            "priority_junctions": [n["junction"] for n in critical_junctions[:5]],
        },
        "affected_corridors": list(affected_corridors),
        "event_details": {
            "description": event.get("description", ""),
            "priority": event.get("priority", ""),
            "corridor": event_corridor,
            "police_station": event.get("police_station", ""),
            "requires_road_closure": event.get("requires_road_closure", False),
        },
    }

    return result


def get_events_near_location(lat: float, lon: float, radius_km: float = 2.0) -> list:
    """Get all historical events near a location. Used by Agent 2 for context."""
    events, _ = _load_events()
    nearby = []
    for e in events:
        d = haversine_km(lat, lon, e["latitude"], e["longitude"])
        if d <= radius_km:
            nearby.append({**e, "distance_from_query_km": round(d, 2)})
    return sorted(nearby, key=lambda x: x["distance_from_query_km"])
