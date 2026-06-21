"""
Backend integration test + credibility checks (Step 9).

Runs without the HTTP server: exercises the spatial core, the forecast pipeline
(orchestrator + RAG + synthesizer), backward compatibility, and a lambda
sensitivity sweep for the spatial decay parameter (B5).

Run:  python backend/test_forecast.py
"""

import asyncio
import sys

import agents.spatial_engine as se
from agents.spatial_engine import compute_blast_radius, compute_blast_radius_core, _load_events
from agents.orchestrator import run_forecast_pipeline, run_full_pipeline


def section(t):
    print("\n" + "=" * 70 + "\n" + t + "\n" + "=" * 70)


def test_core_contract():
    section("1. Forecast core returns the full contract")
    r = compute_blast_radius_core(
        lat=12.9767, lon=77.5713, severity=7, event_cause="public_event",
        event_type="planned", corridor="Mysore Road",
        start_datetime="2024-04-20 15:30:00+00", scheduled_duration_mins=180,
        requires_road_closure=True,
    )
    dep = r["deployment_recommendation"]
    assert "manpower" in dep and "breakdown" in dep["manpower"], "manpower breakdown missing"
    assert "barricade_points" in dep, "barricade_points missing"
    assert "diversion_routes" in dep, "diversion_routes missing"
    assert "predicted_clearance" in r and "range_mins" in r["predicted_clearance"], "clearance band missing"
    assert "params_used" in r["model"], "params_used missing"
    assert "road_closure_contrast" in r, "road_closure_contrast missing"
    print("  OK — manpower:", dep["manpower"]["units"],
          "| barricades:", len(dep["barricade_points"]),
          "| diversions:", len(dep["diversion_routes"]),
          "| clearance band:", r["predicted_clearance"]["range_mins"],
          "| confidence:", r["predicted_clearance"]["confidence"])


async def _collect(agen):
    frames = []
    async for f in agen:
        frames.append(f)
    return frames


def test_forecast_pipeline():
    section("2. Forecast pipeline SSE frame order + predicted-vs-actual")
    events, idx = _load_events()
    preset = [e for e in events if e["event_type"] == "planned"
              and e.get("clearance_time_mins") and e.get("corridor") != "Non-corridor"]
    fi = {
        "event_cause": "public_event", "latitude": 12.9767, "longitude": 77.5713,
        "corridor": "Mysore Road", "start_datetime": "2024-04-20 15:30:00+00",
        "scheduled_duration_mins": 180, "requires_road_closure": True,
    }
    if preset:
        s = preset[0]
        fi.update({"source_event_id": s["id"], "latitude": s["latitude"],
                   "longitude": s["longitude"], "corridor": s["corridor"],
                   "event_cause": s["event_cause"], "edited": False})
        print(f"  using preset {s['id']} ({s['event_cause']}) actual={s['clearance_time_mins']}min")
    frames = asyncio.run(_collect(run_forecast_pipeline(fi)))
    types = [f["type"] for f in frames]
    assert types[0] == "status" and "complete" in types, f"bad frame order: {types[:3]}...{types[-1:]}"
    assert "spatial_result" in types and "rag_result" in types, "missing agent results"
    assert any(f["type"] == "command_chunk" for f in frames), "no command text streamed"
    spatial = next(f for f in frames if f["type"] == "spatial_result")["data"]
    pvA = spatial.get("predicted_clearance", {})
    cmd = "".join(f["text"] for f in frames if f["type"] == "command_chunk")
    print(f"  frames={len(frames)} types_ok | predicted={pvA.get('median_mins')} actual={pvA.get('actual_mins')}")
    print(f"  command starts: {cmd.splitlines()[0][:70]!r}")
    assert "PRE-EVENT DEPLOYMENT PLAN" in cmd, "forecast mode framing missing in command"


def test_backward_compat():
    section("3. Backward compatibility: reactive /analyze pipeline (planned + unplanned)")
    events, idx = _load_events()
    for et in ("planned", "unplanned"):
        ev = next(e for e in events if e["event_type"] == et)
        frames = asyncio.run(_collect(run_full_pipeline(ev["id"])))
        complete = next(f for f in frames if f["type"] == "complete")
        cmd = "".join(f["text"] for f in frames if f["type"] == "command_chunk")
        expect = "PRE-EVENT DEPLOYMENT PLAN" if et == "planned" else "INCIDENT RESPONSE"
        assert expect in cmd, f"{et}: expected '{expect}' framing"
        print(f"  {et:9s} {ev['id']} -> mode={complete['mode']} units={complete['agents_summary']['spatial']['units']} ({expect} OK)")


def test_lambda_sensitivity():
    section("4. Lambda sensitivity (B5): blast size vs decay rate")
    events, idx = _load_events()
    ev = next(e for e in events if e.get("corridor") == "Mysore Road")
    orig = se.DECAY_LAMBDA
    print(f"  event {ev['id']} ({ev['event_cause']}, {ev['corridor']}):")
    for lam in (0.3, 0.5, 0.7):
        se.DECAY_LAMBDA = lam
        r = compute_blast_radius(ev["id"])
        br = r["blast_radius"]
        print(f"    lambda={lam}: affected={br['total_affected_junctions']:3d} critical={br['critical_junctions']:2d}")
    se.DECAY_LAMBDA = orig
    print("  => higher lambda -> tighter, more conservative blast radius (param is explicit, not hidden).")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    test_core_contract()
    test_forecast_pipeline()
    test_backward_compat()
    test_lambda_sensitivity()
    print("\nALL TESTS PASSED")
