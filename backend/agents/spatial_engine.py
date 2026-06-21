"""
Agent 1: The Spatial Engine (The Simulator)

A spatial PROPAGATION HEURISTIC, not causal inference. We estimate how an event's
impact spreads across nearby junctions using BFS over an adjacency graph with
exponential distance decay:  impact(j) = severity * exp(-lambda * d(epicenter, j)).

This is a tractable, transparent approximation — NOT do-calculus (B1). The only
data-grounded causal-flavoured contrast we expose is the road-closure quasi-
experiment in the counterfactual (closure vs no-closure clearance), and that is
confounded and labelled as such.

The same core powers two flows:
  - reactive analysis of an existing event   -> compute_blast_radius(event_id)
  - proactive forecast of a future event     -> compute_blast_radius_core(lat, lon, ...)
"""

import json
import math
import os
from datetime import datetime
from heapq import heappush, heappop

from feature_utils import supertype_of

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# --- Tunable model parameters (echoed in output as params_used for transparency, B5) ---
DECAY_LAMBDA = 0.5                       # distance decay rate (1/km)
CONGESTION_PROPAGATION_SPEED_KM_PER_MIN = 0.5
# Inclusion gate: the incident graph is dense (avg degree ~33, 3km straight-line
# edges, B7), so without a floor a single event "reaches" most of the city. Only
# junctions with impact >= this are reported as affected.
MIN_IMPACT_INCLUDE = 0.15               # ~ within 1.9km at lambda=0.5
CASCADE_PER_NODE = 0.08                  # queue-spillback multiplier per high-impact node
CASCADE_CAP = 2.5                        # keep the counterfactual credible on a dense graph
DIVERSION_BLOCK_IMPACT = 0.5            # only the high-impact core is closed for routing
INTERVENTION_FACTOR = 0.7               # heuristic: deployment clears ~30% faster (NOT measured)
PRIOR_MIN_SAMPLES = 8                    # backoff threshold for clearance priors

# Cache loaded data (loaded once; B8 performance)
_graph_cache = None
_events_cache = None
_events_index = None
_priors_cache = None
_junction_stats_cache = None
_corridor_stats_cache = None


def _load_json(name):
    path = os.path.join(DATA_DIR, name)
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_graph():
    global _graph_cache
    if _graph_cache is None:
        _graph_cache = _load_json("junction_graph.json") or {"nodes": {}, "adjacency": {}}
    return _graph_cache


def _load_events():
    global _events_cache, _events_index
    if _events_cache is None:
        _events_cache = _load_json("events.json") or []
        _events_index = {e["id"]: e for e in _events_cache}
    return _events_cache, _events_index


def _load_priors():
    global _priors_cache
    if _priors_cache is None:
        _priors_cache = _load_json("forecast_priors.json") or {"hourly_weights": {}, "clearance_priors": {}}
    return _priors_cache


def _load_junction_stats():
    global _junction_stats_cache
    if _junction_stats_cache is None:
        _junction_stats_cache = _load_json("junction_stats.json") or {}
    return _junction_stats_cache


def _load_corridor_stats():
    global _corridor_stats_cache
    if _corridor_stats_cache is None:
        _corridor_stats_cache = _load_json("corridor_stats.json") or {}
    return _corridor_stats_cache


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


def _hour_of(start_datetime):
    """Hour-of-day from a start_datetime string, or None.

    The stored clock is read AS-IS and treated as local Bengaluru time (IST). The
    dataset stamps a '+00' suffix, but that is a mislabel: the diurnal volume
    pattern peaks at stored-hour 19-22 and bottoms out at 14-16, which only matches
    real traffic as LOCAL time (evening rush / afternoon lull). Read as true UTC it
    would imply a 00:30-03:30 IST peak and a 19:30-21:30 IST trough, which is
    backwards — so we do NOT apply a +5:30 conversion (it would corrupt the weights).
    """
    if not start_datetime or start_datetime == "NULL":
        return None
    s = str(start_datetime).replace("+00", "").replace("+05:30", "").strip()
    if "." in s:
        s = s[: s.index(".")]
    try:
        return datetime.fromisoformat(s).hour
    except ValueError:
        return None


def _time_weight(start_datetime) -> float:
    """
    Time-of-day weight from empirical hourly event volume (Fix 4).

    Keyed on the stored local (IST) hour — see _hour_of for why the '+00' suffix is
    treated as a mislabel rather than converted. Derived from the volume histogram
    normalized to mean 1.0. ~1.0 = average hour, >1.2 = peak, <0.8 = quiet.
    """
    hw = _load_priors().get("hourly_weights", {})
    hour = _hour_of(start_datetime)
    if hour is None:
        return 1.0
    return float(hw.get(str(hour), 1.0))


def _clearance_prior(event_cause: str, corridor: str) -> dict:
    """
    Clearance prior with backoff: (cause,corridor) -> cause -> supertype -> global.

    Returns the most specific tier meeting PRIOR_MIN_SAMPLES, tagged with
    prior_source and sample count so confidence is visible downstream (Fix 7).
    """
    cp = _load_priors().get("clearance_priors", {})
    glob = cp.get("global", {"median": 45, "n": 0})
    supertype = supertype_of(event_cause)
    candidates = [
        ("cause_corridor", cp.get("by_cause_corridor", {}).get(f"{event_cause}|{corridor}")),
        ("cause", cp.get("by_cause", {}).get(event_cause)),
        ("supertype", cp.get("by_supertype", {}).get(supertype)),
    ]
    for source, rec in candidates:
        if rec and rec.get("n", 0) >= PRIOR_MIN_SAMPLES and rec.get("median") is not None:
            return {**rec, "prior_source": source}
    return {**glob, "prior_source": "global"}


def predict_clearance(event_cause: str, corridor: str, requires_road_closure: bool) -> dict:
    """
    Predicted clearance as a PLANNING BAND, not a point estimate.

    The eval harness shows clearance is high-variance (global median is a hard
    baseline; per-cause MAE ranges 31->119 min), so we return a median plus a
    wide band and an explicit confidence/caveat rather than false precision.
    """
    prior = _clearance_prior(event_cause, corridor)
    n = prior.get("n", 0)
    if requires_road_closure and prior.get("closure_true_median") and prior.get("n_true", 0) >= 5:
        median = prior["closure_true_median"]
        basis = f"closure_true@{prior['prior_source']}"
    elif (not requires_road_closure) and prior.get("closure_false_median") and prior.get("n_false", 0) >= 5:
        median = prior["closure_false_median"]
        basis = f"closure_false@{prior['prior_source']}"
    else:
        median = prior.get("median") or 45
        basis = prior["prior_source"]
    confidence = "high" if n >= 30 else "medium" if n >= PRIOR_MIN_SAMPLES else "low"
    return {
        "median_mins": int(round(median)),
        "range_mins": [int(round(median * 0.6)), int(round(median * 1.6))],
        "basis": basis,
        "sample_size": n,
        "confidence": confidence,
        "caveat": "Clearance is high-variance; use as a planning band, not a point estimate.",
    }


def recommend_manpower(
    severity, requires_road_closure, corridor_load_tier,
    scheduled_duration_mins, time_weight, num_critical,
) -> dict:
    """
    Transparent manpower heuristic (Fix 6).

    IMPORTANT: the dataset has NO officers-deployed / units field, so this cannot
    be learned or validated against ground truth (B-note). It is a documented
    rule-of-thumb; every term is itemized so an officer can see the reasoning.
    """
    breakdown = []

    def add(factor, units):
        if units:
            breakdown.append({"factor": factor, "units": units})

    total = 2
    add("base", 2)
    sev = round(severity / 2)
    total += sev
    add("severity", sev)
    if requires_road_closure:
        total += 2
        add("road_closure", 2)
    if corridor_load_tier == "high":
        total += 1
        add("high_load_corridor", 1)
    if scheduled_duration_mins and scheduled_duration_mins > 120:
        total += 1
        add("long_duration", 1)
    crit = min(int(num_critical), 4)
    total += crit
    add("critical_junctions", crit)
    if time_weight > 1.2:
        total += 1
        add("peak_hour", 1)

    total = max(2, min(12, total))
    return {
        "units": total,
        "breakdown": breakdown,
        "note": "Heuristic — no deployment-size ground truth in the dataset; calibrate with field data.",
    }


def find_diversion_route(origin, blocked_nodes, graph, junction_stats, top_n=2) -> list:
    """
    Approximate diversion routes via Dijkstra over the junction graph, skipping
    the blast-radius nodes (Fix 5).

    HONEST LIMITATION (B7): the graph is built from incident locations with
    straight-line <=3km edges, NOT a real road network. So routes can only pass
    through junctions that have historically had incidents, and distances are
    as-the-crow-flies. Output is flagged accordingly; real routing needs
    Mappls/OSM.
    """
    adjacency = graph.get("adjacency", {})
    blocked = set(blocked_nodes) - {origin}
    if origin not in adjacency:
        return []

    dist = {origin: 0.0}
    prev = {}
    pq = [(0.0, origin)]
    while pq:
        d, u = heappop(pq)
        if d > dist.get(u, float("inf")):
            continue
        for nb in adjacency.get(u, []):
            v = nb["junction"]
            if v in blocked:
                continue
            nd = d + nb["distance_km"]
            if nd < dist.get(v, float("inf")):
                dist[v] = nd
                prev[v] = u
                heappush(pq, (nd, v))

    # Prefer high-traffic, reachable junctions as diversion anchors.
    cands = [(j, junction_stats.get(j, {}).get("event_count", 0))
             for j in dist if j != origin]
    cands.sort(key=lambda x: -x[1])

    routes = []
    for j, _ in cands[:top_n]:
        path = [j]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        routes.append({
            "to": j,
            "via": path,
            "distance_km": round(dist[j], 2),
            "realism": "approximate_incident_graph",
        })
    return routes


def compute_blast_radius_core(
    lat, lon, severity, event_cause,
    event_type="unplanned", corridor="", start_datetime=None,
    scheduled_duration_mins=None, requires_road_closure=False,
    description="", priority="", police_station="", address="",
    source_event_id=None, max_hops=2, max_radius_km=3.0,
) -> dict:
    """
    Core spatial-propagation computation, parameterized (powers /forecast and /analyze).

    Estimates impact(j) = severity * exp(-lambda * d) over the junction graph via
    Dijkstra BFS, scaled by a time-of-day weight, then derives manpower,
    barricade points, diversion routes, a clearance band, and a counterfactual.
    """
    graph = _load_graph()
    junction_stats = _load_junction_stats()
    corridor_stats = _load_corridor_stats()

    try:
        from integrations import get_integration_status
        mapmyindia_status = get_integration_status()["mapmyindia"]
    except Exception:
        mapmyindia_status = {"status": "offline_fallback"}

    if not graph.get("nodes"):
        return {"error": "junction graph not loaded — run preprocess.py"}

    epicenter_junction, epicenter_dist = find_nearest_junction(lat, lon, graph)
    time_weight = _time_weight(start_datetime)

    # === Spatial propagation (BFS with exponential distance decay) ===
    affected = {}
    visited = set()
    queue = [(0.0, epicenter_junction, 0)]
    while queue:
        dist, junction, hops = heappop(queue)
        if junction in visited:
            continue
        visited.add(junction)
        if hops > max_hops or dist > max_radius_km:
            continue

        relative_impact = math.exp(-DECAY_LAMBDA * dist)

        # Keep exploring neighbours regardless, but only RECORD meaningfully
        # impacted junctions (epicenter always recorded).
        if relative_impact >= MIN_IMPACT_INCLUDE or dist == 0:
            # time_weight nudges capacity reduction up at peak hours, down when quiet
            capacity_reduction = min(95, int(severity * relative_impact * time_weight * 10))
            time_to_impact = round(dist / CONGESTION_PROPAGATION_SPEED_KM_PER_MIN, 1) if dist > 0 else 0
            node_data = graph["nodes"].get(junction, {})
            jstat = junction_stats.get(junction, {})  # O(1) lookup (B8)
            affected[junction] = {
                "junction": junction,
                "latitude": node_data.get("latitude", 0),
                "longitude": node_data.get("longitude", 0),
                "distance_km": round(dist, 2),
                "hops_from_epicenter": hops,
                "relative_impact_score": round(relative_impact, 3),
                "capacity_reduction_pct": capacity_reduction,
                "estimated_time_to_impact_mins": time_to_impact,
                "historical_event_count": jstat.get("event_count", 0),
                "historical_avg_clearance_mins": jstat.get("avg_clearance_mins"),
                "historical_top_causes": jstat.get("top_causes", {}),
            }

        for neighbor in graph.get("adjacency", {}).get(junction, []):
            if neighbor["junction"] not in visited:
                heappush(queue, (dist + neighbor["distance_km"], neighbor["junction"], hops + 1))

    affected_list = sorted(affected.values(), key=lambda x: x["relative_impact_score"], reverse=True)

    critical_junctions = [n for n in affected_list if n["relative_impact_score"] > 0.4]
    # Barricade where inflow must be stopped: high-impact nodes within 1 hop.
    barricade_points = [
        n["junction"] for n in affected_list
        if n["relative_impact_score"] > 0.4 and n["hops_from_epicenter"] <= 1
    ][:5]

    # Affected corridors via O(1) junction->corridor lookup (B8; was nodes x events)
    affected_corridors = set()
    for node in affected_list:
        corr = junction_stats.get(node["junction"], {}).get("corridor")
        if corr:
            affected_corridors.add(corr)
    if corridor and corridor != "Non-corridor":
        affected_corridors.add(corridor)

    # === Clearance band + counterfactual (Fix 7) ===
    clearance = predict_clearance(event_cause, corridor, requires_road_closure)
    pred = clearance["median_mins"]
    n_high = len([n for n in affected_list if n["relative_impact_score"] > 0.3])
    cascade_factor = min(CASCADE_CAP, 1 + n_high * CASCADE_PER_NODE)
    without_intervention = int(pred * cascade_factor)
    with_intervention = int(pred * INTERVENTION_FACTOR)

    prior = _clearance_prior(event_cause, corridor)
    road_closure_contrast = {
        "closure_true_median_mins": prior.get("closure_true_median"),
        "n_true": prior.get("n_true", 0),
        "closure_false_median_mins": prior.get("closure_false_median"),
        "n_false": prior.get("n_false", 0),
        "prior_source": prior.get("prior_source"),
        "caveat": "Observational, confounded (closures occur on more severe events). Not a controlled effect.",
    }

    corridor_load_tier = corridor_stats.get(corridor, {}).get("load_tier", "medium")
    manpower = recommend_manpower(
        severity, requires_road_closure, corridor_load_tier,
        scheduled_duration_mins, time_weight, len(critical_junctions),
    )

    # Only the high-impact core is "closed" for routing, so there is room to
    # route around it on a dense graph (otherwise every neighbour is blocked).
    divert_block = {n["junction"] for n in affected_list if n["relative_impact_score"] > DIVERSION_BLOCK_IMPACT}
    diversion_routes = find_diversion_route(
        epicenter_junction, divert_block, graph, junction_stats, top_n=2,
    )

    result = {
        "event_id": source_event_id,
        "event_type": event_type,
        "event_cause": event_cause,
        "severity_score": severity,
        "epicenter": {
            "latitude": lat,
            "longitude": lon,
            "address": address,
            "nearest_junction": epicenter_junction,
            "junction_distance_km": round(epicenter_dist, 2),
        },
        "blast_radius": {
            "total_affected_junctions": len(affected_list),
            "max_radius_km": round(max((n["distance_km"] for n in affected_list), default=0), 2),
            "critical_junctions": len(critical_junctions),
            "affected_nodes": affected_list[:15],
        },
        "model": {
            "method": "Spatial propagation heuristic: impact = severity * exp(-lambda*d) * time_weight",
            "note": "Transparent distance-decay heuristic, not causal do-calculus (B1).",
            "params_used": {
                "decay_lambda": DECAY_LAMBDA,
                "propagation_speed_km_per_min": CONGESTION_PROPAGATION_SPEED_KM_PER_MIN,
                "time_weight": round(time_weight, 3),
                "cascade_per_node": CASCADE_PER_NODE,
                "intervention_factor": INTERVENTION_FACTOR,
            },
            "routing_provider": "Offline incident-graph fallback"
            if mapmyindia_status.get("status") != "connected"
            else "MapmyIndia/Mappls + local graph",
        },
        "predicted_clearance": clearance,
        "counterfactual": {
            "without_intervention_mins": without_intervention,
            "with_intervention_mins": with_intervention,
            "time_saved_mins": without_intervention - with_intervention,
            "cascade_factor": round(cascade_factor, 2),
            "basis": "heuristic — intervention effect is assumed, not measured (no controlled trials in data)",
        },
        "road_closure_contrast": road_closure_contrast,
        "deployment_recommendation": {
            "manpower": manpower,
            "priority_junctions": [n["junction"] for n in critical_junctions[:5]],
            "barricade_points": barricade_points,
            "diversion_routes": diversion_routes,
        },
        "affected_corridors": sorted(affected_corridors),
        "event_details": {
            "description": description,
            "priority": priority,
            "corridor": corridor,
            "police_station": police_station,
            "requires_road_closure": requires_road_closure,
            "scheduled_duration_mins": scheduled_duration_mins,
        },
    }
    return result


def compute_blast_radius(event_id: str, max_hops: int = 2, max_radius_km: float = 3.0) -> dict:
    """Reactive entry point: load an existing event and run the core (backward compatible)."""
    _, events_index = _load_events()
    event = events_index.get(event_id)
    if not event:
        return {"error": f"Event {event_id} not found"}

    result = compute_blast_radius_core(
        lat=event["latitude"],
        lon=event["longitude"],
        severity=event["severity_score"],
        event_cause=event["event_cause"],
        event_type=event.get("event_type", "unplanned"),
        corridor=event.get("corridor", ""),
        start_datetime=event.get("start_datetime"),
        scheduled_duration_mins=event.get("scheduled_duration_mins"),
        requires_road_closure=event.get("requires_road_closure", False),
        description=event.get("description", ""),
        priority=event.get("priority", ""),
        police_station=event.get("police_station", ""),
        address=event.get("address", ""),
        source_event_id=event_id,
        max_hops=max_hops,
        max_radius_km=max_radius_km,
    )
    # Predicted-vs-actual: attach the real observed clearance when available (B3).
    if event.get("clearance_time_mins"):
        result["predicted_clearance"]["actual_mins"] = event["clearance_time_mins"]
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
