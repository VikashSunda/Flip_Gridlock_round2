"""
ASTraM Nexus — Data Preprocessing Pipeline
Transforms raw CSV into structured JSON + junction graph.
Run once before starting the backend.
"""

import csv
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
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

# --- Theme-2 modelling constants ---
# `gathering`/supertype grouping lives in feature_utils so the engine uses the
# exact same definitions (B6: procession=38, protest=8 etc. are individually too
# sparse and get pooled).
from feature_utils import supertype_of

# scheduled_duration is the start->end_datetime window for PLANNED events. It is
# a permit/schedule window (B2: 41% of values are out of range, many land exactly
# on the hour), NOT observed clearance — so we clean it and use it only as an
# INPUT feature, never as the prediction target.
MIN_SCHEDULED_MINS = 15
MAX_SCHEDULED_MINS = 24 * 60


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
    """Derive a 1-10 severity prior from event attributes (shared with forecast path)."""
    from feature_utils import estimate_severity
    return estimate_severity(
        row["event_cause"], row["priority"], row["requires_road_closure"] == "TRUE"
    )


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


def compute_scheduled_duration(row):
    """
    Cleaned start->end_datetime window in minutes (INPUT feature, planned events).

    Returns None when the window is missing or out of the sane [15min, 24h] band.
    See B2: ~41% of raw planned windows are garbage (0/1-min noise, multi-day
    permits, 3.9-year outliers), so this is deliberately conservative.
    """
    start = parse_datetime(row["start_datetime"])
    end = parse_datetime(row["end_datetime"])
    if start and end and end > start:
        mins = (end - start).total_seconds() / 60
        if MIN_SCHEDULED_MINS <= mins <= MAX_SCHEDULED_MINS:
            return round(mins, 1)
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
        scheduled_duration = compute_scheduled_duration(row)

        def _clean(value):
            return value if value and value != "NULL" else ""

        event = {
            "id": row["id"],
            "event_type": row["event_type"],
            "latitude": lat,
            "longitude": lon,
            "address": row["address"].strip('"') if row["address"] else "",
            "event_cause": row["event_cause"],
            "supertype": supertype_of(row["event_cause"]),
            "requires_road_closure": row["requires_road_closure"] == "TRUE",
            "start_datetime": row["start_datetime"],
            "end_datetime": _clean(row.get("end_datetime")),  # restored (B2: planned schedule window)
            "status": row["status"],
            "description": row["description"].strip('"') if row["description"] else "",
            "veh_type": row.get("veh_type", ""),
            "corridor": row["corridor"],
            "priority": row["priority"],
            "police_station": row.get("police_station", ""),
            "zone": row.get("zone", ""),
            "junction": row.get("junction", ""),
            "route_path": _clean(row.get("route_path")),  # restored (enrichment, ~20% planned)
            "severity_score": severity,
            "clearance_time_mins": clearance,  # OUTPUT: observed, from resolved/closed
            # INPUT feature: cleaned schedule window (None when missing/garbage)
            "scheduled_duration_mins": scheduled_duration,
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

    # load_tier: quartile rank of event_count, used as the corridor-load term
    # in the manpower heuristic (Fix 6).
    counts = sorted(d["event_count"] for d in corridor_data.values())
    q1 = counts[len(counts) // 4] if counts else 0
    q3 = counts[(3 * len(counts)) // 4] if counts else 0

    def _tier(n):
        if n >= q3:
            return "high"
        if n <= q1:
            return "low"
        return "medium"

    stats = {}
    for corr, data in corridor_data.items():
        ct = sorted(data["clearance_times"])
        stats[corr] = {
            "event_count": data["event_count"],
            "avg_severity": round(data["severity_sum"] / data["event_count"], 1),
            "median_clearance_mins": ct[len(ct) // 2] if ct else None,
            "load_tier": _tier(data["event_count"]),
            "top_causes": dict(
                sorted(data["causes"].items(), key=lambda x: -x[1])[:5]
            ),
        }

    return stats


def _clearance_stats(subset):
    """Clearance summary for a subset, split by road-closure (Fix 7 quasi-experiment).

    Uses median (robust to the long right tail). closure_true vs closure_false is
    a CONFOUNDED comparison (closures happen on worse events) — surfaced with n
    so the engine/UI can show confidence and caveat it.
    """
    cl = [e["clearance_time_mins"] for e in subset if e.get("clearance_time_mins")]
    t = [e["clearance_time_mins"] for e in subset
         if e.get("clearance_time_mins") and e["requires_road_closure"]]
    f = [e["clearance_time_mins"] for e in subset
         if e.get("clearance_time_mins") and not e["requires_road_closure"]]
    return {
        "n": len(cl),
        "median": round(statistics.median(cl), 1) if cl else None,
        "mean": round(statistics.mean(cl), 1) if cl else None,
        "closure_true_median": round(statistics.median(t), 1) if t else None,
        "n_true": len(t),
        "closure_false_median": round(statistics.median(f), 1) if f else None,
        "n_false": len(f),
    }


def build_forecast_priors(events):
    """
    Forecast priors consumed by the spatial engine (Fixes 4 and 7).

    - hourly_weights: event volume per UTC hour, normalized to mean 1.0. Derived
      empirically so it is independent of the UTC/local timezone-label ambiguity.
    - clearance_priors: clearance summaries at four backoff tiers
      (by_cause_corridor -> by_cause -> by_supertype -> global). The engine walks
      from specific to general until it finds a tier with enough samples.
    """
    # Hourly volume weights
    hour_counts = defaultdict(int)
    for e in events:
        dt = parse_datetime(e["start_datetime"])
        if dt:
            hour_counts[dt.hour] += 1
    total = sum(hour_counts.values())
    mean_per_hour = total / 24 if total else 1
    hourly_weights = {
        str(h): round(hour_counts.get(h, 0) / mean_per_hour, 3) for h in range(24)
    }

    by_cause = defaultdict(list)
    by_supertype = defaultdict(list)
    by_cause_corridor = defaultdict(list)
    for e in events:
        by_cause[e["event_cause"]].append(e)
        by_supertype[e["supertype"]].append(e)
        if e["corridor"] and e["corridor"] != "Non-corridor":
            by_cause_corridor[f"{e['event_cause']}|{e['corridor']}"].append(e)

    return {
        "meta": {
            "hourly_weights_basis": "event volume per UTC hour, normalized to mean 1.0",
            "timezone_note": "start_datetime is +00 (UTC); weights are empirical so label-agnostic",
            "clearance_caveat": "closure_true vs closure_false is confounded; n provided for confidence",
        },
        "hourly_weights": hourly_weights,
        "clearance_priors": {
            "global": _clearance_stats(events),
            "by_cause": {k: _clearance_stats(v) for k, v in by_cause.items()},
            "by_supertype": {k: _clearance_stats(v) for k, v in by_supertype.items()},
            "by_cause_corridor": {k: _clearance_stats(v) for k, v in by_cause_corridor.items()},
        },
    }


def build_junction_stats(events):
    """
    Per-junction historical stats, precomputed once (B8 performance fix).

    The spatial engine previously scanned all ~8k events inside its BFS loop;
    this dict turns that into an O(1) lookup per junction.
    """
    by_junction = defaultdict(list)
    for e in events:
        j = e.get("junction")
        if j and j != "NULL" and j.strip():
            by_junction[j].append(e)

    stats = {}
    for junc, evs in by_junction.items():
        ct = [e["clearance_time_mins"] for e in evs if e.get("clearance_time_mins")]
        causes = Counter(e["event_cause"] for e in evs)
        corridors = Counter(
            e["corridor"] for e in evs if e["corridor"] and e["corridor"] != "Non-corridor"
        )
        stats[junc] = {
            "event_count": len(evs),
            "avg_clearance_mins": round(statistics.mean(ct), 1) if ct else None,
            "top_causes": dict(causes.most_common(3)),
            "corridor": corridors.most_common(1)[0][0] if corridors else None,
        }
    return stats


def main():
    # Windows consoles default to cp1252; keep non-ASCII output from crashing.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
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
    print("\n[4/6] Computing corridor statistics...")
    corridor_stats = build_corridor_stats(events)
    print(f"  Corridors analyzed: {len(corridor_stats)}")

    # Build forecast priors + junction stats (Theme-2 additions)
    print("\n[5/6] Building forecast priors and junction stats...")
    forecast_priors = build_forecast_priors(events)
    junction_stats = build_junction_stats(events)
    gp = forecast_priors["clearance_priors"]["global"]
    print(f"  Forecast priors: global clearance n={gp['n']} median={gp['median']}min "
          f"(closure_true median={gp['closure_true_median']} n={gp['n_true']} | "
          f"closure_false median={gp['closure_false_median']} n={gp['n_false']})")
    print(f"  Junction stats: {len(junction_stats)} junctions")

    # Save outputs
    print("\n[6/6] Saving processed data...")

    with open(os.path.join(DATA_DIR, "events.json"), "w", encoding="utf-8") as f:
        json.dump(events, f, ensure_ascii=False, indent=2)
    print(f"  -> data/events.json ({len(events)} events)")

    with open(os.path.join(DATA_DIR, "junction_graph.json"), "w", encoding="utf-8") as f:
        json.dump(junction_graph, f, ensure_ascii=False, indent=2)
    print(f"  -> data/junction_graph.json")

    with open(os.path.join(DATA_DIR, "corridor_stats.json"), "w", encoding="utf-8") as f:
        json.dump(corridor_stats, f, ensure_ascii=False, indent=2)
    print(f"  -> data/corridor_stats.json")

    with open(os.path.join(DATA_DIR, "forecast_priors.json"), "w", encoding="utf-8") as f:
        json.dump(forecast_priors, f, ensure_ascii=False, indent=2)
    print(f"  -> data/forecast_priors.json")

    with open(os.path.join(DATA_DIR, "junction_stats.json"), "w", encoding="utf-8") as f:
        json.dump(junction_stats, f, ensure_ascii=False, indent=2)
    print(f"  -> data/junction_stats.json")

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
