# ASTraM Nexus Demo Runbook

## Run Locally

One-time setup (regenerates data + new forecast priors):

```bash
cd backend
pip install -r requirements.txt
python preprocess.py
```

Backend:

```bash
python backend/main.py            # http://localhost:8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev                        # http://localhost:5173
```

The header has two modes: **Live incident** (reactive) and **Event forecast** (proactive, Theme 2).

If port 8000 is occupied, run the backend on another port and point Vite at it:

```bash
cd frontend
VITE_API_BASE=http://localhost:8001 npm run dev
```

## 90-Second Pitch

1. "Bengaluru traffic control is reactive today. ASTraM Nexus turns an event into a command decision."
2. Open the first Best Demo Case.
3. Click "Run 3-agent forecast."
4. Show the map: epicenter, spillover paths, affected junctions.
5. Show confidence: spatial evidence, historical evidence, action evidence.
6. Show counterfactual: without intervention vs with deployment.
7. End with the operational command: "This tells officers where to deploy, where to hold, where to divert, and how much time is saved."

## Event Forecast Flow (Theme 2 — the headline)

1. Switch to **Event forecast** in the header.
2. Pick a real planned event from the preset dropdown — the form auto-fills.
3. Click **Run forecast**. Show, before the event happens:
   - **Predicted clearance band** (median + range + confidence — honest about variance).
   - **Manpower** with a transparent breakdown (severity, closure, corridor load, peak hour…).
   - **Barricade points** and **diversion routes** (labelled approximate — incident-graph routing).
   - **Counterfactual** + the data-grounded (confounded) road-closure contrast.
   - **Predicted-vs-actual** when the preset is unedited (credibility).
4. After the event, enter the **actual clearance** in "Post-event learning" → closes the loop (the system tracks prediction error).

## Credibility artifacts (have these ready for SME judges)

- `python backend/eval/validate_data.py` — proves the data caveats (planned clearance n≈28; end_datetime is a permit window; concurrency).
- `python backend/eval/eval_duration.py` — temporal train/test split; baselines the model must beat; per-cause MAE.
- `python backend/test_forecast.py` — lambda sensitivity (blast radius vs decay).
- `POST /allocate` — splits a finite officer budget across concurrent events (over-subscription handling).

## Judge Hooks

- Multi-agent system: Spatial-Causal Engine, RAG Intelligence Core, Command Synthesizer.
- Causal graph: estimates downstream junction impact, not just event severity.
- Historical proof: retrieves similar incidents and clearance patterns from ASTraM logs.
- Counterfactual value: quantifies minutes saved by the deployment plan.
- MapmyIndia-ready: OAuth credentials connected; local causal graph keeps the demo resilient.

## Best Demo Flow

Use the "Best demo cases" panel first:

- Critical now: highest severity, strong visual blast radius.
- ORR cascade: easiest traffic story for judges to understand.
- Planned event: proves the system handles planned and unplanned events.
- Rain risk: strongest RAG/history explanation.
