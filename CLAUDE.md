# ASTraM Nexus — CLAUDE.md

> Convention in this doc: **[VERIFIED]** = checked against data/code this session. **[⚠️ ASSUMPTION]** = design idea not yet validated — confirm before relying on it.

## Context

**Hackathon**: Flipkart Gridlock Hackathon 2.0 — Round 2 (Prototype Phase)
**Theme**: Theme 2 — Event-Driven Congestion (Planned & Unplanned)
**Round 2 window (per PDF)**: **Jun 15 – Jun 21, 2026**, ends 11:59 PM Asia/Kolkata. **[⚠️ VERIFY on HackerEarth]** — the PDF cover shows this window; confirm the exact submission cutoff. (An earlier draft of this file said "Jun 27" with no source — that was wrong.)
**Goal**: Forecast event-related traffic impact and recommend manpower, barricading, and diversion plans using historical + real-time data.

---

## Implementation Status (BUILT — 2026-06-20)

All 9 fixes + 3 recommended additions are implemented and verified end-to-end (backend tests pass, frontend builds, both servers run).

**Run it:**
```bash
cd backend && pip install -r requirements.txt && python preprocess.py && python main.py   # :8000
cd frontend && npm install && npm run dev                                                  # :5173
python backend/eval/validate_data.py      # data-quality spike (credibility artifact)
python backend/eval/eval_duration.py      # baselines vs model, temporal split
python backend/test_forecast.py           # integration + lambda sensitivity
```

**New/changed endpoints:** `POST /forecast` (proactive), `POST /allocate` (R2 budget split), `POST|GET /feedback` (R1 learning loop), `GET /events?status=active` (R3 real-time). `/analyze` now branches planned→forecast / unplanned→reactive framing.

**Key deviations from the plan (intentional):**
- **RAG uses in-process TF-IDF, not ChromaDB.** ChromaDB needs sqlite3>=3.35 which the system Python 3.9 lacks. TF-IDF (sklearn) is lighter, dependency-free here, and honestly matches B1 (lexical+metadata, not dense "causal" embeddings). `requirements.txt` updated (chromadb removed; scikit-learn/numpy/pandas added).
- **Fixed a latent Py3.9 bug:** `integrations.py` used `str | None` (3.10+ syntax) → switched to `Optional[str]`. The original app never ran on this machine because of it.
- **Fix 1 corrected mid-build:** planned `end_datetime` is a scheduled permit window (median 11.7h, 41% garbage), NOT clearance. It's now an INPUT feature `scheduled_duration_mins` (cleaned to [15min,24h]); clearance OUTPUT stays from resolved/closed. Eval runs on unplanned (rich), planned flagged low-n.
- **Forecast presents a clearance BAND + confidence, not a point** (eval shows clearance is high-variance; global median is a hard baseline).
- Honest framing throughout: manpower = documented heuristic (no ground truth), diversion = approximate incident-graph routing, counterfactual = heuristic, road-closure contrast = confounded.

**New data files (from preprocess):** `forecast_priors.json` (hourly_weights + clearance_priors w/ backoff), `junction_stats.json` (B8 perf). **New code:** `feature_utils.py` (shared supertype/severity), `agents` refactored to param cores, `frontend/src/ForecastPanel.jsx`, `frontend/src/lib/stream.js`, `backend/eval/`, `backend/test_forecast.py`.

---

## Problem Statement (Theme 2)

**Operational Challenge**: Political rallies, festivals, sports events, construction activities, and sudden gatherings create localized traffic breakdowns.

**Why it's hard today**:
- Event impact is not quantified in advance
- Resource deployment is experience-driven (no data backing)
- No post-event learning system

**Core question**: How can historical and real-time data forecast event-related traffic impact and recommend optimal manpower, barricading, and diversion plans?

**Two distinct workflows required**:
1. **Planned events** → pre-event forecast + proactive deployment plan
2. **Unplanned events** → real-time trigger → reactive response (existing pipeline handles this reasonably)

---

## Dataset

**File**: `Astram event data_anonymized - Astram event data_anonymizedb40ac87.csv`
**Size**: **8,173 CSV rows → 8,170 events after preprocessing** (3 `test_demo` dropped) | Nov 2023 – Apr 2024 (~5 months). **[VERIFIED]**

**Event split [VERIFIED]**: Planned 467 (5.7%) | Unplanned 7,703 (94.3%) — matches served `/stats`
**Planned causes [VERIFIED]**: construction 311, public_event 84, procession 38, vip_movement 20, protest 8 (+ 6 stragglers)
**36% of planned events require road closure (169/467) [VERIFIED]**

### ⚠️ Data Reality Check — fill rates that constrain what's buildable [VERIFIED]

This table is the single most important thing in this doc. Several "obvious" features are blocked by missing data.

| Column | Overall fill | Planned fill | Implication |
|---|---|---|---|
| `corridor` | 99.8% | 100% | Safe to key features on this |
| `police_station` | 100% | 100% | Safe (but see manpower caveat below) |
| `start_datetime` | ~100% | ~100% | Safe |
| `end_datetime` | **6.0%** | **99.8%** (466/467) | **Use for PLANNED duration. Nearly empty for unplanned.** |
| `junction` | 30.7% | 26.1% | Graph built from ~30% of events; nearest-junction fallback covers the rest |
| `route_path` | 1.7% | 19.9% (93) | Enrichment only — too sparse to be a core feature |
| `direction` | 0.5% | 3.4% (16) | **Effectively noise. Do not build on it.** |
| clearance via `resolved`/`closed` | 39.3% | **n≈23** | Current clearance logic (see Fix 1) misses ~95% of planned events |

**No manpower ground truth exists.** There is NO "officers deployed" / "units" column. `police_station` (100%) is only *which* station; `assigned_to_police_id` is 1.6% filled (62 unique = individual officers). You **cannot** derive or validate "optimal manpower" from this data — it must be an explicit heuristic. See Fix 6.

**Timezone caveat.** `start_datetime` is stamped `+00` (UTC). Hourly histogram shows two surges: UTC 04–06 (IST 09:30–11:30) and UTC 19–22 (IST 00:30–03:30 if read as UTC). The night surge is plausibly real (dataset is 60% `vehicle_breakdown`, truck-heavy; Bengaluru bans heavy vehicles in daytime → night highway breakdowns). **Confirm whether timestamps are truly UTC or local before hardcoding any time-of-day logic.** See Fix 4.

---

## Architecture

```
backend/
  main.py                  FastAPI server, startup, all HTTP endpoints
  preprocess.py            CSV → events.json + junction_graph.json + corridor_stats.json (run once)
  integrations.py          Gemini + MapmyIndia status checks
  agents/
    spatial_engine.py      Agent 1: BFS blast radius propagation on junction graph
    rag_core.py            Agent 2: ChromaDB CDF-RAG causal retrieval
    command_synthesizer.py Agent 3: Gemini synthesis → prescriptive command (SSE stream)
    orchestrator.py        Runs Agent 1+2 in parallel → Agent 3

frontend/
  src/
    App.jsx                Single 830-line component (all UI, map, filters, stream display)
    index.css              24KB dark-theme styles
    main.jsx               Vite entry
```

**Data flow**: CSV → preprocess.py → events.json + junction_graph.json + corridor_stats.json → ChromaDB index → FastAPI serves → React consumes
**Streaming**: `POST /analyze/{event_id}` returns SSE; frontend renders markdown chunks progressively.
**Graph [VERIFIED]**: 294 nodes, 4,896 edges, ~33 avg degree. Edges = junctions within 3 km **straight-line haversine** ([preprocess.py:191](backend/preprocess.py#L191)) — NOT real road connectivity.

---

## What Was Correct in the Original System (keep)

- Spatial BFS blast-radius concept (correct, just needs to run pre-event)
- CDF-RAG causal retrieval with same-junction/corridor/cause scoring
- Junction graph construction; corridor statistics
- FastAPI + SSE streaming architecture
- React frontend structure, map visualization, real-time stream UI

---

## Implementation Plan

Ordered by priority. Each fix marks whether it's data-blocked or safe.

### Fix 1 — Preprocessing: fix clearance + restore the one column that matters (do first)
**[VERIFIED problem]** [preprocess.py:103](backend/preprocess.py#L103) computes clearance from `resolved_datetime`/`closed_datetime`, which are ~empty for planned events → only n≈23 planned clearances, silently dropping ~95%.
- **Compute planned duration from `start_datetime → end_datetime`** (`end_datetime` is 99.8% filled for planned). This turns the weak n=23 stat into n≈466.
- Keep `resolved`/`closed` for unplanned clearance.
- Restore `route_path` as optional enrichment (planned 20% — nice-to-have, not core).
- Skip `direction` (0.5% fill — noise).
- Rerun `python preprocess.py` after editing.

### Fix 2 — Add `POST /forecast` endpoint (planned-event flow)
Current `POST /analyze/{event_id}` needs an existing ID. Add `/forecast` taking future event params:
```json
{ "event_cause": "public_event", "latitude": 12.9767, "longitude": 77.5713,
  "corridor": "Mysore Road", "start_datetime": "2024-04-20T15:00:00",
  "expected_duration_hrs": 3, "priority": "High" }
```
Route through a spatial engine that accepts coordinates directly instead of an `event_id`.

### Fix 3 — Split planned vs unplanned in orchestrator.py
`event_type` is stored but never branched on. Add: `planned` → forecast pipeline (predictive); `unplanned` → existing `run_full_pipeline()` (reactive).

### Fix 4 — Time-of-day weighting **[⚠️ derive, don't hardcode]**
Do NOT hardcode IST windows — an earlier draft mapped the "evening peak" to UTC 12–14, which is actually the **daily trough**. Instead:
1. First confirm the timezone (see Data Reality Check).
2. Compute a per-hour event-volume weight directly from the histogram and apply it as the multiplier.
This makes the weighting self-justifying and immune to the tz ambiguity.

### Fix 5 — Diversion routing **[⚠️ edges are not roads]**
Add `find_diversion_route(origin, destination, blocked_nodes)` using `junction_graph["adjacency"]`, skipping blast-radius nodes.
**Caveat**: edges are straight-line ≤3 km (avg degree ~33), so raw output is a *geographic approximation*, not a drivable route, and many hops will be trivial. For a credible demo, either (a) label it clearly as approximate, or (b) enrich with `route_path` / MapmyIndia for the showcased cases.

### Fix 6 — Manpower recommendation **[⚠️ heuristic only — no ground truth]**
Replace the hardcoded formula at [spatial_engine.py:218](backend/agents/spatial_engine.py#L218). **There is no deployment-size data**, so frame this honestly as a transparent heuristic, e.g.:
`units = f(severity, requires_road_closure, corridor_load, expected_duration, peak_weight)`
Document the formula in the UI/output. Do NOT claim it's learned from historical deployments — it can't be validated.

### Fix 7 — Data-derived counterfactual **[⚠️ sparsity risk]**
Replace the hardcoded `* 0.65` at [spatial_engine.py:205](backend/agents/spatial_engine.py#L205). Compute, at preprocess time, avg clearance for `requires_road_closure` TRUE vs FALSE.
**Caveat**: only 39% of events have clearance times; splitting by cause × corridor × closure will be sparse. Use a **backoff**: (cause, corridor) → cause → global. Store with a confidence/sample-size flag.

### Fix 8 — Add `event_type` bonus in RAG scoring
[rag_core.py:186](backend/agents/rag_core.py#L186): add `causal_bonus += 0.15` when `meta["event_type"] == target["event_type"]` so planned queries prefer planned history. (Requires adding `event_type` to the ChromaDB metadata in `build_vector_store`.)

### Fix 9 — Forecast UI
Create `src/ForecastPanel.jsx` (do NOT extend the 830-line App.jsx). Form for future-event params → `/forecast` → render predicted impact + deployment plan. Mount as a tab in App.jsx.

---

## Development Workflow

```bash
cd backend
pip install -r requirements.txt
python preprocess.py        # rerun whenever CSV/columns change
python main.py              # :8000

cd frontend
npm install
npm run dev                 # :5173
```

**Env**: copy `.env.example` → `.env`, set `GEMINI_API_KEY`. System runs fully offline without it (deterministic fallback in command_synthesizer.py).

---

## Key Design Decisions

- **ChromaDB**: local, no API key, fast enough for ~8K docs.
- **BFS + exponential decay**: tractable approximation of do-calculus on the spatial graph.
- **SSE over WebSocket**: simpler, unidirectional, no connection state.
- **3km adjacency**: tuned to Bengaluru density (yields ~33 avg degree — see Fix 5 caveat).
- **Deterministic fallback is currently the ONLY working synth path**: default model in [command_synthesizer.py:33](backend/agents/command_synthesizer.py#L33) is `"gemini-3.5-flash"`, which is not a valid model ID — even with a key, the LLM call fails to the fallback. Fix the model ID (e.g. a current `gemini-*-flash`) before claiming live LLM synthesis.
- **Build upon existing, don't rewrite**: infrastructure (graph, RAG, streaming, frontend) is sound; all gaps are in the logic layer.
