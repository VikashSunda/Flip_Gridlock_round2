"""
Historical-replay trigger — the "sudden-gathering" detector (R10).

This closes the most-cited gap across all four adversarial reviews: the Live tab
was a static record browser that never polled, detected, or auto-triggered, so the
*unplanned* half of Theme 2 ("detect a developing situation in real time") did not
exist. This module replays the historical snapshot (Nov 2023 - Apr 2024) in
chronological order and fires a transparent space-time SURGE alert when a cluster
of high-severity incidents appears close together in a short window — the trigger
the frontend then uses to auto-launch the existing 3-agent /analyze pipeline.

HONEST FRAMING: this is a replay of stored history, NOT a live external feed. The
detection RULE, however, is exactly what a real-time pipeline would run over a live
stream; only the source is historical.

Detection rule (transparent + tunable, echoed to the UI):
  SURGE = >= MIN_CLUSTER unplanned events with severity >= SEV_MIN that fall within
  RADIUS_KM and WINDOW_MIN of an anchor event.

De-dup: the raw snapshot contains a synthetic bulk-insert (52 identical-timestamp
'accident' rows at one location, 2024-01-16). We drop exact
(start_datetime, rounded-loc) duplicates so the detector reflects genuine
spatiotemporal bursts, not a data artifact.
"""

from collections import Counter
from datetime import datetime, timedelta

from agents.spatial_engine import haversine_km

# Default replay window: a validated storm-morning (water-logging + tree-fall +
# congestion) that contains several genuine spatiotemporal surges.
DEFAULT_WINDOW = "2024-03-07"

# Detection parameters (returned in the payload so the UI can show the rule).
SEV_MIN = 7        # "high-severity" floor on the 1-10 severity_score scale
RADIUS_KM = 1.5    # spatial closeness for cluster membership
WINDOW_MIN = 25    # temporal closeness for cluster membership
MIN_CLUSTER = 3    # incidents needed to declare a surge

# Default replay focuses on the storm-morning band so the clock starts near the
# action instead of after hours of dead time (the rule itself spans the whole day).
DEFAULT_START_HOUR = 5
DEFAULT_END_HOUR = 9

_timeline_cache = {}


def _parse_dt(s):
    """Parse a snapshot start_datetime -> naive datetime, or None.

    Mirrors preprocess.parse_datetime / spatial_engine._hour_of: the stored clock
    is treated as-is (local Bengaluru time; the '+00' suffix is a mislabel).
    """
    if not s or s == "NULL":
        return None
    s = str(s).replace("+05:30", "").replace("+00", "").strip()
    if "." in s:
        s = s[: s.index(".")]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _detect_surges(events, sev_min, radius_km, window_min, min_cluster):
    """Forward sliding-window spatiotemporal clustering.

    Greedy + non-overlapping: once an event joins a fired surge it is consumed, so
    each genuine burst is reported once rather than as many shifted near-duplicates.
    `events` must be sorted ascending by `_t`.
    """
    surges = []
    consumed = set()
    n = len(events)
    for i, anchor in enumerate(events):
        if anchor["id"] in consumed or (anchor.get("severity_score") or 0) < sev_min:
            continue
        members = [anchor]
        t0 = anchor["_t"]
        for j in range(i + 1, n):
            b = events[j]
            if (b["_t"] - t0).total_seconds() / 60.0 > window_min:
                break
            if b["id"] in consumed or (b.get("severity_score") or 0) < sev_min:
                continue
            if haversine_km(anchor["latitude"], anchor["longitude"],
                            b["latitude"], b["longitude"]) <= radius_km:
                members.append(b)
        if len(members) >= min_cluster:
            for m in members:
                consumed.add(m["id"])
            surges.append(members)
    return surges


def build_replay_timeline(events_data, window=DEFAULT_WINDOW, sev_min=SEV_MIN,
                          radius_km=RADIUS_KM, window_min=WINDOW_MIN,
                          min_cluster=MIN_CLUSTER, start_hour=DEFAULT_START_HOUR,
                          end_hour=DEFAULT_END_HOUR):
    """Build the chronological event timeline + precomputed surge alerts for a day.

    `start_hour`/`end_hour` restrict the replay to a [start_hour, end_hour) local
    clock band (keeps the demo tight); pass 0/24 for the whole day. Returns a
    JSON-serializable dict the frontend animates over a virtual clock;
    alert.anchor_event_id feeds the existing /analyze/{id} pipeline unchanged.
    """
    try:
        day_start = datetime.strptime(window, "%Y-%m-%d")
    except ValueError:
        day_start = datetime.strptime(DEFAULT_WINDOW, "%Y-%m-%d")
        window = DEFAULT_WINDOW
    band_start = day_start + timedelta(hours=start_hour)
    band_end = day_start + timedelta(hours=end_hour)

    seen = set()
    rows = []
    for e in events_data or []:
        if e.get("event_type") != "unplanned":
            continue
        t = _parse_dt(e.get("start_datetime"))
        if t is None or not (band_start <= t < band_end):
            continue
        try:
            lat = float(e["latitude"]); lon = float(e["longitude"])
        except (KeyError, TypeError, ValueError):
            continue
        key = (e.get("start_datetime"), round(lat, 3), round(lon, 3))
        if key in seen:                      # drop the synthetic bulk-insert artifact
            continue
        seen.add(key)
        rows.append({
            "id": e["id"], "_t": t, "latitude": lat, "longitude": lon,
            "severity_score": e.get("severity_score", 0),
            "event_cause": e.get("event_cause", ""),
            "corridor": e.get("corridor", ""),
            "junction": e.get("junction", ""),
            "police_station": e.get("police_station", ""),
            "priority": e.get("priority", ""),
        })
    rows.sort(key=lambda r: r["_t"])

    rule_text = (f">= {min_cluster} unplanned incidents with severity >= {sev_min} "
                 f"within {radius_km} km and {window_min} min")
    params = {"sev_min": sev_min, "radius_km": radius_km,
              "window_min": window_min, "min_cluster": min_cluster,
              "start_hour": start_hour, "end_hour": end_hour}

    if not rows:
        return {
            "window": window, "window_label": f"Historical replay ({window} snapshot) "
            "— not a live external feed", "rule_text": rule_text, "params": params,
            "duration_sec": 0, "total_events": 0, "events": [], "alerts": [],
        }

    t0 = rows[0]["_t"]
    surges = _detect_surges(rows, sev_min, radius_km, window_min, min_cluster)

    alerts = []
    for members in surges:
        anchor = max(members, key=lambda m: m["severity_score"])
        times = [m["_t"] for m in members]
        fire = max(times)                     # alert fires once the cluster completes
        alerts.append({
            "fire_at_offset_sec": int((fire - t0).total_seconds()),
            "fire_at_clock": fire.strftime("%H:%M"),
            "anchor_event_id": anchor["id"],
            "anchor_severity": anchor["severity_score"],
            "member_ids": [m["id"] for m in members],
            "n": len(members),
            "radius_km": radius_km,
            "span_mins": round((max(times) - min(times)).total_seconds() / 60.0, 1),
            "dominant_cause": Counter(m["event_cause"] for m in members).most_common(1)[0][0],
            "centroid": {
                "latitude": round(sum(m["latitude"] for m in members) / len(members), 5),
                "longitude": round(sum(m["longitude"] for m in members) / len(members), 5),
            },
            "police_station": anchor["police_station"],
        })
    alerts.sort(key=lambda a: a["fire_at_offset_sec"])

    events_out = [{
        "id": r["id"],
        "t_offset_sec": int((r["_t"] - t0).total_seconds()),
        "clock": r["_t"].strftime("%H:%M"),
        "latitude": r["latitude"], "longitude": r["longitude"],
        "severity_score": r["severity_score"], "event_cause": r["event_cause"],
        "corridor": r["corridor"], "junction": r["junction"],
        "police_station": r["police_station"], "priority": r["priority"],
    } for r in rows]

    return {
        "window": window,
        "window_label": f"Historical replay ({window} snapshot) — not a live external feed",
        "rule_text": rule_text,
        "params": params,
        "duration_sec": events_out[-1]["t_offset_sec"],
        "total_events": len(events_out),
        "events": events_out,
        "alerts": alerts,
    }


def get_replay_timeline(events_data, window=DEFAULT_WINDOW,
                        start_hour=DEFAULT_START_HOUR, end_hour=DEFAULT_END_HOUR):
    """Cached accessor (the timeline for a window+band is deterministic)."""
    key = (window, start_hour, end_hour)
    if key not in _timeline_cache:
        _timeline_cache[key] = build_replay_timeline(
            events_data, window, start_hour=start_hour, end_hour=end_hour)
    return _timeline_cache[key]
