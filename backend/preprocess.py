"""
ASTraM Nexus — Data Preprocessing Pipeline
Transforms raw CSV into structured JSON + junction graph.
Run once before starting the backend.
"""

import csv
import json
import math
import os
import sys
from collections import defaultdict
from datetime import datetime

# Paths
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
CSV_PATH = os.path.join(
    PROJECT_ROOT,
    "Astram event data_anonymized - Astram event data_anonymizedb40ac87.csv",
)
DATA_DIR = os.path.join(SCRIPT_DIR, "data")

os.makedirs(DATA_DIR, exist_ok=True)


def haversine_km(lat1, lon1, lat2, lon2):
    """Calculate distance between two points in km."""
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


def parse_datetime(dt_str):
    """Parse datetime string from CSV, handling various formats."""
    if not dt_str or dt_str == "NULL":
        return None
    try:
        # Remove timezone offset for simpler parsing
        clean = dt_str.replace("+00", "").replace("+05:30", "").strip()
        # Try multiple formats
        for fmt in [
            "%Y-%m-%d %H:%M:%S.%f",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S.%f",
            "%Y-%m-%dT%H:%M:%S",
        ]:
            try:
                return datetime.strptime(clean, fmt)
            except ValueError:
                continue
    except Exception:
        pass
    return None


def compute_severity_score(row):
    """
    Derive a 1-10 severity score from event attributes.
    This is our 'causal weight' for the spatial engine.
    """
    score = 5  # baseline

    # Event cause weights
    cause_weights = {
        "accident": 3,
        "tree_fall": 2,
        "water_logging": 2,
        "vip_movement": 2,
        "procession": 2,
        "protest": 3,
        "public_event": 1,
        "congestion": 1,
        "construction": 1,
        "vehicle_breakdown": 0,
        "pot_holes": 0,
        "road_conditions": 0,
        "others": 0,
        "Debris": 1,
        "test_demo": -5,
    }
    score += cause_weights.get(row["event_cause"], 0)

    # Priority
    if row["priority"] == "High":
        score += 1

    # Road closure required
    if row["requires_road_closure"] == "TRUE":
        score += 2

    # Clamp to 1-10
    return max(1, min(10, score))


def compute_clearance_time(row):
    """Calculate clearance time in minutes from start to resolution."""
    start = parse_datetime(row["start_datetime"])

    # Try resolved_datetime first, then closed_datetime
    end = parse_datetime(row["resolved_datetime"]) or parse_datetime(
        row["closed_datetime"]
    )

    if start and end:
        diff_mins = (end - start).total_seconds() / 60
        if 0 < diff_mins < 10000:  # Filter out garbage
            return round(diff_mins, 1)
    return None


def process_events(rows):
    """Process raw CSV rows into structured event dicts."""
    events = []
    for row in rows:
        lat = float(row["latitude"]) if row["latitude"] else 0
        lon = float(row["longitude"]) if row["longitude"] else 0

        if lat == 0 or lon == 0:
            continue

        # Skip test events
        if row["event_cause"] == "test_demo":
            continue

        clearance = compute_clearance_time(row)
        severity = compute_severity_score(row)

        event = {
            "id": row["id"],
            "event_type": row["event_type"],
            "latitude": lat,
            "longitude": lon,
            "address": row["address"].strip('"') if row["address"] else "",
            "event_cause": row["event_cause"],
            "requires_road_closure": row["requires_road_closure"] == "TRUE",
            "start_datetime": row["start_datetime"],
            "status": row["status"],
            "description": row["description"].strip('"') if row["description"] else "",
            "veh_type": row.get("veh_type", ""),
            "corridor": row["corridor"],
            "priority": row["priority"],
            "police_station": row.get("police_station", ""),
            "zone": row.get("zone", ""),
            "junction": row.get("junction", ""),
            "severity_score": severity,
            "clearance_time_mins": clearance,
            "comment": row.get("comment", ""),
        }
        events.append(event)

    return events


def build_junction_graph(events):
    """
    Build a spatial adjacency graph of junctions.
    Nodes = junctions with averaged coordinates.
    Edges = junctions within 3km of each other (road proximity).
    """
    # Aggregate junction data
    junction_data = defaultdict(lambda: {"lats": [], "lons": [], "events": []})

    for event in events:
        junc = event.get("junction", "")
        if junc and junc != "NULL" and junc.strip():
            junction_data[junc]["lats"].append(event["latitude"])
            junction_data[junc]["lons"].append(event["longitude"])
            junction_data[junc]["events"].append(event["id"])

    # Build nodes with averaged positions
    nodes = {}
    for junc_name, data in junction_data.items():
        avg_lat = sum(data["lats"]) / len(data["lats"])
        avg_lon = sum(data["lons"]) / len(data["lons"])
        nodes[junc_name] = {
            "name": junc_name,
            "latitude": round(avg_lat, 7),
            "longitude": round(avg_lon, 7),
            "event_count": len(data["events"]),
            "event_ids": data["events"][:10],  # Keep first 10 for reference
        }

    # Build edges (junctions within 3km)
    ADJACENCY_RADIUS_KM = 3.0
    edges = []
    junction_names = list(nodes.keys())

    for i, j1 in enumerate(junction_names):
        for j2 in junction_names[i + 1 :]:
            dist = haversine_km(
                nodes[j1]["latitude"],
                nodes[j1]["longitude"],
                nodes[j2]["latitude"],
                nodes[j2]["longitude"],
            )
            if dist <= ADJACENCY_RADIUS_KM:
                edges.append(
                    {
                        "from": j1,
                        "to": j2,
                        "distance_km": round(dist, 2),
                    }
                )

    # Build adjacency list
    adjacency = defaultdict(list)
    for edge in edges:
        adjacency[edge["from"]].append(
            {"junction": edge["to"], "distance_km": edge["distance_km"]}
        )
        adjacency[edge["to"]].append(
            {"junction": edge["from"], "distance_km": edge["distance_km"]}
        )

    return {
        "nodes": nodes,
        "edges": edges,
        "adjacency": dict(adjacency),
        "stats": {
            "total_junctions": len(nodes),
            "total_edges": len(edges),
            "avg_connections": round(
                len(edges) * 2 / max(len(nodes), 1), 1
            ),
        },
    }


def build_corridor_stats(events):
    """Compute per-corridor statistics for quick lookups."""
    corridor_data = defaultdict(
        lambda: {
            "event_count": 0,
            "clearance_times": [],
            "causes": defaultdict(int),
            "severity_sum": 0,
        }
    )

    for event in events:
        corr = event["corridor"]
        if not corr or corr == "Non-corridor":
            continue
        corridor_data[corr]["event_count"] += 1
        corridor_data[corr]["causes"][event["event_cause"]] += 1
        corridor_data[corr]["severity_sum"] += event["severity_score"]
        if event["clearance_time_mins"]:
            corridor_data[corr]["clearance_times"].append(
                event["clearance_time_mins"]
            )

    stats = {}
    for corr, data in corridor_data.items():
        ct = sorted(data["clearance_times"])
        stats[corr] = {
            "event_count": data["event_count"],
            "avg_severity": round(data["severity_sum"] / data["event_count"], 1),
            "median_clearance_mins": ct[len(ct) // 2] if ct else None,
            "top_causes": dict(
                sorted(data["causes"].items(), key=lambda x: -x[1])[:5]
            ),
        }

    return stats


def main():
    print("=" * 60)
    print("ASTraM Nexus — Data Preprocessing Pipeline")
    print("=" * 60)

    # Load CSV
    print("\n[1/5] Loading CSV...")
    with open(CSV_PATH, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    print(f"  Loaded {len(rows)} raw rows")

    # Process events
    print("\n[2/5] Processing events...")
    events = process_events(rows)
    print(f"  Processed {len(events)} valid events")
    print(
        f"  Event types: {len(set(e['event_type'] for e in events))} unique"
    )
    print(
        f"  Event causes: {len(set(e['event_cause'] for e in events))} unique"
    )

    with_clearance = [e for e in events if e["clearance_time_mins"]]
    print(f"  Events with clearance time: {len(with_clearance)}")

    # Build junction graph
    print("\n[3/5] Building junction adjacency graph...")
    junction_graph = build_junction_graph(events)
    print(
        f"  Junctions: {junction_graph['stats']['total_junctions']}"
    )
    print(f"  Edges: {junction_graph['stats']['total_edges']}")
    print(
        f"  Avg connections per junction: {junction_graph['stats']['avg_connections']}"
    )

    # Build corridor stats
    print("\n[4/5] Computing corridor statistics...")
    corridor_stats = build_corridor_stats(events)
    print(f"  Corridors analyzed: {len(corridor_stats)}")

    # Save outputs
    print("\n[5/5] Saving processed data...")

    with open(os.path.join(DATA_DIR, "events.json"), "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)
    print(f"  → data/events.json ({len(events)} events)")

    with open(os.path.join(DATA_DIR, "junction_graph.json"), "w", encoding="utf-8") as f:
        json.dump(junction_graph, f, ensure_ascii=False, indent=2)
    print(f"  → data/junction_graph.json")

    with open(os.path.join(DATA_DIR, "corridor_stats.json"), "w", encoding="utf-8") as f:
        json.dump(corridor_stats, f, ensure_ascii=False, indent=2)
    print(f"  → data/corridor_stats.json")

    # Summary
    print("\n" + "=" * 60)
    print("PREPROCESSING COMPLETE")
    print("=" * 60)
    print(f"  Total events: {len(events)}")
    print(
        f"  Junctions in graph: {junction_graph['stats']['total_junctions']}"
    )
    print(f"  Spatial edges: {junction_graph['stats']['total_edges']}")
    print(f"  Corridors: {len(corridor_stats)}")
    print(f"\n  Output directory: {DATA_DIR}")


if __name__ == "__main__":
    main()
