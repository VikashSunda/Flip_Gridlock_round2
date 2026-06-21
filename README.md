# ASTraM Nexus — Bengaluru Traffic Command Center

> Event-driven congestion intelligence for traffic police: forecast the spillover of planned & unplanned events, then issue a prescriptive deployment plan — every number tagged with its data source and sample size.

**Flipkart Gridlock Hackathon 2.0 · Round 2 · Theme 2 (Event-Driven Congestion)**

![React](https://img.shields.io/badge/React-19-61DAFB?logo=react&logoColor=white)
![Vite](https://img.shields.io/badge/Vite-8-646CFF?logo=vite&logoColor=white)
![Leaflet](https://img.shields.io/badge/Leaflet-1.9-199900?logo=leaflet&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?logo=fastapi&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.9+-3776AB?logo=python&logoColor=white)
![scikit-learn](https://img.shields.io/badge/scikit--learn-RAG-F7931E?logo=scikitlearn&logoColor=white)

---

## Overview

Political rallies, festivals, construction, VIP movement, and sudden gatherings create localized traffic breakdowns. Today their impact isn't quantified in advance and deployment is experience-driven. **ASTraM Nexus** turns a historical incident dataset into decision support across two workflows:

- **Unplanned incidents →** real-time-style reactive response (spillover, evidence, field order)
- **Planned events →** pre-event forecast + proactive manpower / barricading / diversion plan

A three-agent pipeline runs per event and streams results to the UI:

| Agent | Role |
| --- | --- |
| **Spatial Propagation Engine** | Distance-decay spillover over a junction proximity graph → blast radius + affected junctions |
| **RAG Intelligence Core** | TF-IDF + metadata retrieval of similar historical incidents → clearance patterns |
| **Command Synthesizer** | Turns the evidence into a prescriptive deployment order (Gemini, with a deterministic offline fallback) |

## Features

- 🗺️ **Live incident** — real dark map (Leaflet) of Bengaluru, glowing severity markers, click an incident to fly to it and run the 3-agent pipeline (streamed via SSE). Includes a historical-replay surge detector.
- 📅 **Event forecast** — plan a future event; get a predicted clearance **band** (with confidence), manpower heuristic breakdown, barricade/metering anchors, and a counterfactual.
- 👮 **Force allocation** — split a finite officer budget across concurrent events by severity (water-fill), surfacing oversubscription honestly.
- 📊 **Analytics** — client-side dashboard: incidents by hour, cause mix, clearance-time spread, top corridors, median clearance by cause, severity distribution, status mix, and a day × hour heatmap.

## Tech stack

**Frontend** — React 19 · Vite 8 · Leaflet + react-leaflet 5 · Recharts 3 · Framer Motion 12 · lucide-react · react-markdown · hand-rolled CSS design system (no UI framework).

**Backend** — FastAPI · Uvicorn · scikit-learn (TF-IDF retrieval) · NumPy · pandas · google-genai (optional). Server-Sent Events for streaming agent output.

## Architecture

```
CSV (raw, not committed)
   │  preprocess.py
   ▼
events.json · junction_graph.json · corridor_stats.json · forecast_priors.json · junction_stats.json
   │  FastAPI (main.py)  ── TF-IDF index (rag_core) · proximity graph (spatial_engine) · synthesis (command_synthesizer)
   ▼
React + Vite UI  ──  fetch /events,/stats  ·  SSE POST /analyze, /forecast
```

```
gridlock/
├── backend/
│   ├── main.py                 FastAPI app + all HTTP/SSE endpoints
│   ├── preprocess.py           CSV → JSON artifacts (run once, needs the raw CSV)
│   ├── feature_utils.py        shared supertype / severity helpers
│   ├── integrations.py         Gemini + MapmyIndia status checks
│   ├── replay.py               historical-replay timeline builder
│   ├── agents/                 spatial_engine · rag_core · command_synthesizer · orchestrator
│   ├── data/                   preprocessed JSON (committed; CSV is gitignored)
│   └── eval/                   validate_data.py · eval_duration.py
└── frontend/
    └── src/
        ├── App.jsx             live-incident view + map + agent pipeline
        ├── MapView.jsx         Leaflet dark map
        ├── ForecastPanel.jsx   proactive forecast view
        ├── AllocationPanel.jsx force-allocation view
        ├── AnalyticsPanel.jsx  charts dashboard
        ├── index.css           dark command-center design system
        └── lib/stream.js       shared SSE reader
```

## Getting started

**Prerequisites:** Python 3.9+ and Node.js 18+.

The preprocessed data JSON is committed, so the backend runs **without** the raw dataset — `preprocess.py` is only needed if you have the original CSV and want to regenerate.

### 1. Backend (`:8000`)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Optional LLM synthesis: copy `.env.example` → `.env` and set `GEMINI_API_KEY`. The system runs fully offline without it (deterministic fallback in `command_synthesizer.py`).

### 2. Frontend (`:5173`)

```bash
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. The UI expects the API at `http://localhost:8000` (override with `VITE_API_BASE`).
#### demo link - flip-gridlock-round2.vercel.app
## API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/stats`, `/events`, `/integrations` | Dataset summary, incidents, integration status |
| `POST` | `/analyze/{event_id}` | Reactive 3-agent pipeline (SSE stream) |
| `POST` | `/forecast` | Proactive forecast for a future event (SSE stream) |
| `POST` | `/allocate` | Severity-weighted split of an officer budget across concurrent events |
| `POST` `GET` | `/feedback` | Log / read post-event actual clearance (outcome logging) |
| `GET` | `/replay/timeline` | Historical-replay timeline + surge alerts |

## Data & methodology

- **Dataset:** 8,170 anonymized incidents, Bengaluru, Nov 2023 – Apr 2024. Planned 467 (5.7%) / Unplanned 7,703. Proximity graph: 294 junctions, 4,896 edges. *(The raw CSV is excluded from the repo.)*
- **Retrieval is lexical:** TF-IDF + metadata over ~8K incident documents (scikit-learn), not dense embeddings — framed honestly as similarity retrieval.
- **Graph edges are geographic:** junctions within ≤3 km straight-line haversine, so diversion routes are *approximations*, not validated drivable roads.
- **Timestamps are UTC (`+00`);** IST ≈ UTC + 5:30 (the Analytics views label this).

### Honest limitations (by design)

This tool states what it can and can't prove:

- **No manpower ground truth** exists in the data, so the manpower recommendation is a **transparent heuristic**, not a learned/validated optimum.
- **Clearance time is high-variance.** On a held-out temporal split, the empirical-median prior gives **MAE ≈ 40.7 min** (within ±15 min only ~26% of the time). An HGBR was tested and did **not** beat the median baseline on MAE, so we ship the auditable prior and present clearance as a **band with confidence**, not a point.
- The counterfactual "time saved" is a **modeled** estimate (intervention effect assumed, not measured); road-closure contrasts are **confounded** and labeled as such.

The value is in spatial + resource guidance and provenance, not minute-precision prediction.

## Evaluation

```bash
python backend/eval/validate_data.py    # data-quality / fill-rate audit
python backend/eval/eval_duration.py     # baselines vs model on a temporal split
python backend/test_forecast.py          # forecast integration + lambda sensitivity
```

## License

Built for the Flipkart Gridlock Hackathon 2.0. Dataset is the property of the hackathon organizers and is not redistributed here.
