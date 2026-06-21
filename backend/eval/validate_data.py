"""
Data-validation spike (Step 0 of the Theme-2 plan).

Purpose: lock down the data-quality facts that justify the preprocessing and
modelling choices made elsewhere. This is a *credibility artifact* — it is
meant to be run and shown, not hidden. It reads the raw CSV directly so it has
no dependency on the preprocessing pipeline.

Key questions answered:
  B2  Is planned `end_datetime` an observed clearance time or a scheduled
      permit window? (Answer drives Fix 1.)
  B3  How much real clearance ground truth exists (resolved/closed) for
      planned vs unplanned?
  B6  How sparse are (cause, corridor) cells? (Drives backoff + supertype.)
  B10 Do planned events overlap in time? (Motivates budget-constrained
      manpower allocation.)
  B9  How many events are `active` (the real-time feed)?

Run:  python backend/eval/validate_data.py
"""

import csv
import os
import statistics
from collections import Counter, defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(os.path.dirname(SCRIPT_DIR))
CSV_PATH = os.path.join(
    PROJECT_ROOT,
    "Astram event data_anonymized - Astram event data_anonymizedb40ac87.csv",
)

# Cleaning bounds reused by preprocess.py for scheduled_duration_mins.
MIN_SCHEDULED_MINS = 15
MAX_SCHEDULED_MINS = 24 * 60  # 24h

GATHERING_CAUSES = {"public_event", "procession", "protest", "vip_movement"}


def parse_dt(s):
    if not s or s == "NULL":
        return None
    s = s.replace("+00", "").replace("+05:30", "").strip()
    if "." in s:
        s = s[: s.index(".")]
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def clearance_mins(row):
    """Observed clearance from resolved/closed (the real OUTPUT signal)."""
    start = parse_dt(row["start_datetime"])
    end = parse_dt(row["resolved_datetime"]) or parse_dt(row["closed_datetime"])
    if start and end:
        d = (end - start).total_seconds() / 60
        if 0 < d < 10000:
            return d
    return None


def scheduled_mins(row):
    """Scheduled window from start->end_datetime (the INPUT feature)."""
    start = parse_dt(row["start_datetime"])
    end = parse_dt(row["end_datetime"])
    if start and end and end > start:
        return (end - start).total_seconds() / 60
    return None


def hr(title):
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def main():
    with open(CSV_PATH, encoding="utf-8", errors="replace") as f:
        rows = list(csv.DictReader(f))
    planned = [r for r in rows if r["event_type"] == "planned"]
    unplanned = [r for r in rows if r["event_type"] == "unplanned"]

    hr("OVERVIEW")
    print(f"  total rows           : {len(rows)}")
    print(f"  planned / unplanned  : {len(planned)} / {len(unplanned)}")
    print(f"  active (B9 realtime)  : {sum(1 for r in rows if r['status']=='active')}")

    # --- B3: real clearance ground truth ---
    hr("B3  Clearance ground truth (resolved/closed) — the real OUTPUT")
    cl_all = [r for r in rows if clearance_mins(r) is not None]
    cl_p = [r for r in planned if clearance_mins(r) is not None]
    cl_u = [r for r in unplanned if clearance_mins(r) is not None]
    print(f"  with clearance: all={len(cl_all)}  planned={len(cl_p)}  unplanned={len(cl_u)}")
    print(f"  => planned clearance is THIN ({len(cl_p)}); validate on unplanned, transfer to planned.")
    if cl_u:
        vals = [clearance_mins(r) for r in cl_u]
        print(f"  unplanned clearance mins: median={statistics.median(vals):.0f} mean={statistics.mean(vals):.0f}")

    # --- B2: is planned end_datetime scheduled or observed? ---
    hr("B2  Planned end_datetime: scheduled permit window or observed clearance?")
    sched = [scheduled_mins(r) for r in planned]
    sched = [s for s in sched if s is not None]
    sched_sorted = sorted(sched)
    on_hour = sum(1 for s in sched if s > 0 and s % 60 == 0)
    garbage = sum(1 for s in sched if s < MIN_SCHEDULED_MINS or s > MAX_SCHEDULED_MINS)
    print(f"  n={len(sched)}  min={sched_sorted[0]:.0f}  median={statistics.median(sched):.0f}  max={sched_sorted[-1]:.0f}")
    print(f"  exactly-on-the-hour : {on_hour}/{len(sched)} ({100*on_hour/len(sched):.0f}%)  <- high => scheduled, not observed")
    print(f"  out-of-range garbage: {garbage}/{len(sched)} ({100*garbage/len(sched):.0f}%) outside [{MIN_SCHEDULED_MINS},{MAX_SCHEDULED_MINS}] min")
    print(f"  top durations (mins): {Counter(int(s) for s in sched).most_common(6)}")
    cleaned = [s for s in sched if MIN_SCHEDULED_MINS <= s <= MAX_SCHEDULED_MINS]
    print(f"  CLEANED scheduled_duration: n={len(cleaned)} median={statistics.median(cleaned):.0f} min  (use as INPUT feature)")

    # --- B6: (cause, corridor) sparsity ---
    hr("B6  (cause, corridor) cell sparsity for planned (drives backoff)")
    cells = Counter((r["event_cause"], r["corridor"]) for r in planned)
    sizes = list(cells.values())
    print(f"  non-empty cells={len(cells)}  n==1: {sum(1 for v in sizes if v==1)} ({100*sum(1 for v in sizes if v==1)/len(cells):.0f}%)  n>=10: {sum(1 for v in sizes if v>=10)}")
    print(f"  planned cause counts: {Counter(r['event_cause'] for r in planned).most_common()}")
    gath = sum(1 for r in planned if r["event_cause"] in GATHERING_CAUSES)
    print(f"  'gathering' supertype {sorted(GATHERING_CAUSES)} pools to n={gath} (vs scattered rare classes)")

    # --- B10: concurrency of planned events ---
    hr("B10 Concurrency of planned events (motivates budget allocation)")
    for label, lo, hi in [("raw (all durations)", 0, 10**9), (f"cleaned [{MIN_SCHEDULED_MINS},{MAX_SCHEDULED_MINS}]m", MIN_SCHEDULED_MINS, MAX_SCHEDULED_MINS)]:
        ints = []
        for r in planned:
            s = parse_dt(r["start_datetime"])
            d = scheduled_mins(r)
            if s and d is not None and lo <= d <= hi:
                ints.append((s, s.timestamp() + d * 60))
        maxover = 0
        for s, _ in ints:
            t = s.timestamp()
            over = sum(1 for (s2, e2) in ints if s2.timestamp() <= t < e2)
            maxover = max(maxover, over)
        print(f"  {label:32s}: n={len(ints):4d}  max simultaneously-active={maxover}")
    print("  => isolated per-event manpower can over-commit a finite force.")

    hr("DONE — these numbers justify the cleaning/backoff/allocation choices in the plan.")


if __name__ == "__main__":
    main()
