# ASTraM Nexus Demo Runbook

## Run Locally

Backend:

```bash
.venv/bin/python backend/main.py
```

Frontend:

```bash
cd frontend
npm run dev
```

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
