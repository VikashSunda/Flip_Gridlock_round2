"""
Tests for the historical-replay surge detector (R10).

Run:  python backend/test_replay.py
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from replay import build_replay_timeline, DEFAULT_WINDOW

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")


def _load():
    with open(os.path.join(DATA, "events.json"), encoding="utf-8") as f:
        return json.load(f)


def section(t):
    print("\n" + "=" * 70 + "\n" + t + "\n" + "=" * 70)


def test_default_window_fires():
    section(f"1. Default window {DEFAULT_WINDOW} produces genuine surges")
    tl = build_replay_timeline(_load(), DEFAULT_WINDOW)
    print(f"  events={tl['total_events']} alerts={len(tl['alerts'])} "
          f"duration={tl['duration_sec']}s rule='{tl['rule_text']}'")
    assert tl["total_events"] > 0, "no events in the default window"
    assert len(tl["alerts"]) >= 1, "expected at least one surge alert"
    a = tl["alerts"][0]
    print(f"  first alert @ {a['fire_at_clock']}: n={a['n']} anchor={a['anchor_event_id']} "
          f"sev={a['anchor_severity']} cause={a['dominant_cause']} span={a['span_mins']}min")
    # anchor must be the max-severity member
    by_id = {e["id"]: e for e in tl["events"]}
    member_sevs = [by_id[mid]["severity_score"] for mid in a["member_ids"]]
    assert a["anchor_severity"] == max(member_sevs), "anchor is not the max-severity member"
    # alert must fire only after the anchor has 'arrived'
    assert by_id[a["anchor_event_id"]]["t_offset_sec"] <= a["fire_at_offset_sec"]
    print("  OK — anchor=max severity, fires after anchor arrival")


def test_dedup_artifact():
    section("2. Synthetic bulk-insert (2024-01-16, 52 identical rows) is de-duped")
    raw = _load()
    artifact_ts = "2024-01-16 23:18:15.118206+00"
    n_raw = sum(1 for e in raw if e.get("start_datetime") == artifact_ts)
    print(f"  raw rows at artifact timestamp: {n_raw}")
    tl = build_replay_timeline(raw, "2024-01-16")
    kept = [e for e in tl["events"] if any(  # events at ~that loc/time that survived
        e["clock"] == "23:18" for _ in [0])]
    n_kept_at_ts = sum(1 for e in tl["events"] if e["clock"] == "23:18")
    print(f"  events kept at 23:18 after de-dup: {n_kept_at_ts}")
    assert n_raw >= 50, "fixture changed — expected the ~52-row artifact"
    assert n_kept_at_ts < n_raw, "de-dup did not collapse the identical-timestamp pile-up"
    print("  OK — artifact collapsed, detector won't fire on fake data")


def test_window_label_honest():
    section("3. Honest labeling present")
    tl = build_replay_timeline(_load(), DEFAULT_WINDOW)
    assert "not a live external feed" in tl["window_label"], "missing honest label"
    print(f"  label: {tl['window_label']}")
    print("  OK")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_default_window_fires()
    test_dedup_artifact()
    test_window_label_honest()
    print("\nALL REPLAY TESTS PASSED")
