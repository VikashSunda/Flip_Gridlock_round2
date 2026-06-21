"""
Shared feature/grouping helpers used by both the offline preprocessing pipeline
and the online engine, so the definitions never drift apart.
"""

# Rare event-driven causes pooled together so per-group stats are usable (B6).
GATHERING_CAUSES = {"public_event", "procession", "protest", "vip_movement"}


def supertype_of(cause: str) -> str:
    """Coarse cause grouping used for clearance-prior backoff."""
    if cause in GATHERING_CAUSES:
        return "gathering"
    if cause in {"construction", "road_conditions", "pot_holes"}:
        return "roadworks"
    if cause in {"water_logging", "tree_fall", "Fog / Low Visibility", "Debris", "debris"}:
        return "weather_hazard"
    return cause


# Hand-assigned severity weights (an input prior, not a measured outcome — B5).
CAUSE_SEVERITY_WEIGHTS = {
    "accident": 3, "tree_fall": 2, "water_logging": 2, "vip_movement": 2,
    "procession": 2, "protest": 3, "public_event": 1, "congestion": 1,
    "construction": 1, "vehicle_breakdown": 0, "pot_holes": 0,
    "road_conditions": 0, "others": 0, "Debris": 1, "test_demo": -5,
}


def estimate_severity(event_cause: str, priority: str = "", requires_road_closure: bool = False) -> int:
    """1-10 severity prior from event attributes (shared by preprocess + forecast)."""
    score = 5 + CAUSE_SEVERITY_WEIGHTS.get(event_cause, 0)
    if priority == "High":
        score += 1
    if requires_road_closure:
        score += 2
    return max(1, min(10, score))
