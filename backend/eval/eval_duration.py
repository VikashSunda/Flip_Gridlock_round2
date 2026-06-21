"""
Clearance-duration evaluation harness (Step 0 of the Theme-2 plan).

Why this exists (B4): a "forecaster" with no held-out test and no baselines is
not defensible in front of subject-matter judges. This script establishes:
  - a proper TEMPORAL train/test split (it is time-series; no random shuffle),
  - naive baselines the model must beat (these baselines ARE the clearance_priors
    lookup, so the lookup is honestly framed as a baseline),
  - MAE / RMSE / median-AE / % within +-15 min, reported per cause,
  - a separate read on the data-rich UNPLANNED set vs the thin PLANNED set (B3).

Reads data/events.json (run preprocess.py first).
Run:  python backend/eval/eval_duration.py
"""

import json
import os
from datetime import datetime

import numpy as np
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Operational cap: clearance beyond this is treated as an outlier for the
# modelling task (median ~53 min, but a long tail to multi-day records skews
# RMSE and is not operationally meaningful to predict). Reported explicitly.
TARGET_CAP_MINS = 480
SPLIT_DATE = datetime(2024, 3, 1)  # train: < Mar 2024, test: >= Mar 2024
CAT_FEATURES = ["event_cause", "corridor", "zone", "priority"]
NUM_FEATURES = ["hour", "requires_road_closure", "scheduled_duration_mins", "severity_score"]


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


def to_features(e):
    dt = parse_dt(e["start_datetime"])
    return {
        "event_cause": e.get("event_cause") or "unknown",
        "corridor": e.get("corridor") or "Non-corridor",
        "zone": e.get("zone") or "NULL",
        "priority": e.get("priority") or "NULL",
        "hour": dt.hour if dt else -1,
        "requires_road_closure": 1 if e.get("requires_road_closure") else 0,
        "scheduled_duration_mins": e.get("scheduled_duration_mins") or -1,
        "severity_score": e.get("severity_score", 5),
        "_target": e.get("clearance_time_mins"),
        "_dt": dt,
    }


def metrics(y_true, y_pred):
    y_true, y_pred = np.asarray(y_true, float), np.asarray(y_pred, float)
    err = y_pred - y_true
    return {
        "n": len(y_true),
        "MAE": float(np.mean(np.abs(err))),
        "RMSE": float(np.sqrt(np.mean(err ** 2))),
        "MedAE": float(np.median(np.abs(err))),
        "within15%": float(100 * np.mean(np.abs(err) <= 15)),
    }


def row(name, m):
    return f"  {name:24s} n={m['n']:4d}  MAE={m['MAE']:6.1f}  RMSE={m['RMSE']:6.1f}  MedAE={m['MedAE']:6.1f}  +-15min={m['within15%']:4.0f}%"


def build_baselines(train):
    """Median-lookup baselines with backoff: (cause,corridor) -> cause -> global."""
    g = np.median([r["_target"] for r in train])
    by_cause, by_cc = {}, {}
    for r in train:
        by_cause.setdefault(r["event_cause"], []).append(r["_target"])
        by_cc.setdefault((r["event_cause"], r["corridor"]), []).append(r["_target"])
    by_cause = {k: float(np.median(v)) for k, v in by_cause.items()}
    by_cc = {k: float(np.median(v)) for k, v in by_cc.items() if len(v) >= 5}

    def pred_global(r):
        return g

    def pred_cause(r):
        return by_cause.get(r["event_cause"], g)

    def pred_cc(r):
        return by_cc.get((r["event_cause"], r["corridor"]), by_cause.get(r["event_cause"], g))

    return {
        "baseline: global median": pred_global,
        "baseline: cause median": pred_cause,
        "baseline: cause+corridor": pred_cc,
    }


def evaluate(events, label):
    rows = [to_features(e) for e in events if e.get("clearance_time_mins")]
    rows = [r for r in rows if r["_dt"] and r["_target"] <= TARGET_CAP_MINS]
    train = [r for r in rows if r["_dt"] < SPLIT_DATE]
    test = [r for r in rows if r["_dt"] >= SPLIT_DATE]

    print("\n" + "=" * 78)
    print(f"{label}   (target capped at {TARGET_CAP_MINS} min; temporal split at {SPLIT_DATE.date()})")
    print("=" * 78)
    print(f"  train={len(train)}  test={len(test)}")
    if len(train) < 30 or len(test) < 10:
        print("  [LOW-N] too few samples for a trustworthy split — treat as indicative only.")
        if not test:
            return

    y_test = [r["_target"] for r in test]

    # --- Baselines ---
    for name, fn in build_baselines(train).items():
        print(row(name, metrics(y_test, [fn(r) for r in test])))

    # --- Model (only credible if it beats cause+corridor) ---
    if len(train) >= 50:
        pre = ColumnTransformer([
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CAT_FEATURES),
            ("num", "passthrough", NUM_FEATURES),
        ])
        model = Pipeline([("pre", pre), ("gbr", HistGradientBoostingRegressor(
            max_iter=300, learning_rate=0.06, max_depth=4, random_state=0))])
        Xtr = [{k: r[k] for k in CAT_FEATURES + NUM_FEATURES} for r in train]
        Xte = [{k: r[k] for k in CAT_FEATURES + NUM_FEATURES} for r in test]
        import pandas as pd  # local import; only needed for the model path
        model.fit(pd.DataFrame(Xtr), [r["_target"] for r in train])
        preds = model.predict(pd.DataFrame(Xte))
        print(row("model: HGBR", metrics(y_test, preds)))

    # --- Per-cause MAE (cause-median baseline) for the test set ---
    print("  per-cause (cause-median baseline):")
    base = build_baselines(train)["baseline: cause median"]
    by_cause = {}
    for r in test:
        by_cause.setdefault(r["event_cause"], []).append(r)
    for cause, rs in sorted(by_cause.items(), key=lambda x: -len(x[1]))[:8]:
        m = metrics([r["_target"] for r in rs], [base(r) for r in rs])
        print(f"      {cause:20s} n={m['n']:4d}  MAE={m['MAE']:6.1f}  MedAE={m['MedAE']:6.1f}")


def main():
    try:
        import sys
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    events = json.load(open(os.path.join(DATA_DIR, "events.json"), encoding="utf-8"))
    unplanned = [e for e in events if e["event_type"] == "unplanned"]
    planned = [e for e in events if e["event_type"] == "planned"]

    # Primary eval on the data-rich set; planned reported separately with caveat.
    evaluate(unplanned, "UNPLANNED (rich ground truth — primary credibility set)")
    evaluate(planned, "PLANNED (thin ground truth — B3; indicative only)")

    print("\nTakeaway: report the best baseline the model must beat; lead with UNPLANNED.")


if __name__ == "__main__":
    main()
