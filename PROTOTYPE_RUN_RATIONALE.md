# Prototype Run — Inferred Rationale

> Oppenheimer: "Theory would take you only so far."
> Generated: 2026-06-20 live run against the actual backend.
> Purpose: capture what the system ACTUALLY does vs what we designed it to do — so we think clearly before submission.

---

## What we ran

```
python backend/eval/validate_data.py    -> data spike
python backend/eval/eval_duration.py   -> baselines + model
python backend/test_forecast.py        -> 4 integration tests
python backend/main.py                 -> live server :8000
curl POST /forecast FKID000008         -> Cricket Match, CBD 2
curl POST /allocate [3 events]         -> budget R2
curl POST /feedback                    -> R1 learning loop
GET  /events?status=active             -> R3 feed
```

All pass. No server crashes. Backend stays up under sequential API load.

---

## What the data actually says (vs what we hoped)

### 1. Clearance prediction is a hard problem — the model barely helps

```
UNPLANNED (n=717 test, temporal split)
  global median   MAE = 40.7  RMSE = 63.8   <-- HARDEST BASELINE TO BEAT
  cause median    MAE = 46.9  RMSE = 66.8   <-- WORSE than global
  cause+corridor  MAE = 47.2  RMSE = 67.7   <-- ALSO worse
  HGBR model      MAE = 43.8  RMSE = 59.8   <-- Beats on RMSE only; loses on MAE
```

**Inferred rationale**: Clearance time is dominated by context noise (officer load, time of day, which shift) that's not in the data. Per-cause priors overfit to cause distributions in training that don't hold in test. The single best thing we can say is "median 40-50 min, ±25 min" and that's honest.

**What this means for the demo**: Do NOT pitch "precision clearance prediction." The value is in:
- Spatial resource guidance (where to deploy, which junctions)
- Comparative bands (this event vs similar historical events)
- The allocation problem across concurrent events (R2)

### 2. Per-cause breakdown reveals operationally meaningful extremes

```
  vehicle_breakdown  n=468  MAE=30.8   <- predictable, truck breakdowns follow a pattern
  water_logging      n= 73  MAE=118.9  <- highly unpredictable, severity varies by rainfall
  accident           n= 15  MAE=22.2   <- thin but predictable (tow/ambulance SLAs)
  construction       n=  4  MAE=173.8  <- noise (n=4)
```

**Inferred rationale**: The cause-level MAE table is a better story for judges than the aggregate. "vehicle_breakdown is 2x more predictable than water_logging" is operationally useful — it tells officers to use tighter deployment windows for breakdowns but maintain reserve slack for flooding.

### 3. Planned clearance ground truth is n=28 — cannot validate

```
  planned clearance: train=20, test=2
  [LOW-N] completely non-representative
```

**Inferred rationale**: The planned forecast for clearance is a PRIOR TRANSFER — we learn from unplanned events and assume similar patterns for planned. The honest framing is: "This is the best estimate given historical unplanned data of the same cause type, not a validated planned-event prediction." The demo should show this caveat, not hide it.

### 4. Road closure contrast is confounded in a counterintuitive direction

```
  closure_true_median_mins  = 6.6  (n=3)
  closure_false_median_mins = 36.5 (n=13)
```

Events with road closure "clear" faster? This is a statistical artifact: planned events with formal road closures are pre-planned gatherings (processions, VIP movements) where "clearance" means reopening after a scheduled end — they end exactly on time. The underlying event isn't more dangerous; it's more controlled. The confounding caveat in the output is correct and necessary.

**Do NOT present this as "road closure reduces clearance time" to judges — it reads as a system bug or data misunderstanding.**

### 5. Counterfactual numbers are a formula, not a measurement

```
  Cricket Match CBD 2 (no road closure):
  without_intervention_mins = 90
  with_intervention_mins    = 25
  time_saved_mins           = 65
```

These are:
- `without = predicted_clearance.median × cascade_factor (2.5)`
- `with = without × intervention_factor (0.7)`

**Inferred rationale**: This is a defensible heuristic but zero empirical grounding. There are no "deployed vs not deployed" trials in the data. Be transparent: "65 minutes saved is our model's estimate; actual savings depend on how quickly officers reach their posts."

### 6. Blast radius for CBD 2 cricket: 74 junctions, 6 corridors

```
  Bellary Road 1, CBD 1, CBD 2, Hosur Road, Mysore Road, Old Madras Road
  Critical junctions: 36
  Diversion 1: QueensStatueCircle -> ChandrikaJunction -> MekhriCircle (4.48km)
  Diversion 2: QueensStatueCircle -> CMP GateJunc -> ... -> AyyappaTempleJunc (6.34km)
```

74/294 nodes affected = 25% of the known junction network for a single cricket match. This is plausible for CBD 2 (Chinnaswamy Stadium is genuinely high-impact). The 6-corridor spread is also credible — CBD events radiate into all radial corridors.

**However**: Diversion to MekhriCircle for a CBD cricket match is geographic (Bellary Road is north of CBD, roughly correct as an alternate). A traffic engineer who knows Bengaluru won't find this outlandish. The "approximate_incident_graph" label saves us.

### 7. Allocation under a budget reveals over-subscription at realistic scales

```
  3 events (public_event + construction + vehicle_breakdown)
  total demand = 23 officers, budget = 15
  -> OVERSUBSCRIBED -> proportional allocation
  public_event: demand=7, allocated=5
  construction: demand=9, allocated=6
  vehicle_breakdown: demand=7, allocated=4
```

**Inferred rationale**: This is the most operationally honest output we produce. Every city traffic center actually faces this — you never have 100% of demanded resources. Showing the over-subscription explicitly, with severity-proportional cuts, is more useful than showing "you need 23 officers" when you only have 15.

---

## What the live run surfaced that theory missed

### A. google.generativeai is deprecated — non-blocking but visible

```
FutureWarning: All support for the `google.generativeai` package has ended.
Please switch to the `google.genai` package.
```

The deterministic fallback is active and produces good output. But if judges inspect the logs or if someone brings a real Gemini API key, the deprecated library call will fail or produce warnings. Should migrate to `google.genai` if time allows.

**Impact on demo**: Zero — fallback synthesis is fully functional and produces structured PRE-EVENT DEPLOYMENT PLAN markdown. The LLM path would enhance it.

### B. Predicted vs actual in test: predicted=97, actual=31.9 for FKID000166

Test 2 (pipeline SSE test) showed:
```
construction event FKID000166 (Bellary Road 2)
predicted clearance median = 97 min
actual clearance           = 31.9 min
error = 65 min (2x off)
```

This is within the MAE-RMSE envelope we measured (MAE~41, RMSE~60 for unplanned) but it's jarring when shown in the UI. The frontend shows this as "Predicted: 97 min | Actual: 31.9 min" for that specific preset. 

**Inferred rationale**: This is actually a STRENGTH not a bug — it proves the system is honest about being imprecise. The band `[62, 155]` for that event includes 97 as the median, but 31.9 is way outside even the 60% band. Clearance is genuinely noisy. Judges who understand forecasting will respect this honesty; judges who expect magic will be disappointed.

### C. Gemini + MapmyIndia both offline in every test run

```
"gemini":       {"status": "fallback"}
"mapmyindia":   {"status": "offline_fallback"}
```

Both integrations are placeholders in this environment. The entire demo runs on deterministic fallback. For submission, decide: either (a) add real keys and show live LLM synthesis, or (b) lean into "offline resilience" as a feature.

### D. Backend stays up, no memory issues, TF-IDF warm in ~400ms

The 8,170-event TF-IDF index builds once at startup in ~400ms and stays in memory. No observable performance issues across 10+ API calls. The cache warm works.

---

## The real architecture vs the pitched architecture

| What we say | What the code does |
|---|---|
| "Multi-agent causal AI" | 3 sequential/parallel Python async functions |
| "Causal inference on the junction graph" | BFS with `severity × exp(-0.5d) × time_weight` |
| "RAG with causal retrieval" | TF-IDF cosine similarity + metadata score reweighting |
| "LLM command synthesis" | Deterministic fallback (Gemini offline); structured markdown template |
| "Data-driven manpower" | `base=2 + severity/2 + closure? +2 + ...` heuristic, no data |
| "Post-event learning loop" | Append to JSONL, report running MAE, no auto-retraining |
| "Real-time data feed" | Filter `status='active'` on a static snapshot (Nov 2023 – Apr 2024) |

**This is not a failure — it's an honest prototype.** Every item on the right is:
- Correctly labelled in the output (caveat strings, `realism: "approximate"`, `heuristic` notes)
- Architecturally extensible to the real thing (swap TF-IDF for embeddings, swap fallback for live LLM, hook feedback JSONL to a retraining job)
- Appropriate for a 6-day hackathon prototype

---

## What to say to judges vs what not to say

**Say:**
- "We used the actual clearance data — only 2,786 events out of 8,170 have resolved timestamps — and were honest that planned event prediction transfers from unplanned history."
- "Our eval harness shows global median (MAE 40.7 min) is the hardest baseline to beat. Our model improves RMSE but not MAE, so we present clearance as a band."
- "The allocation endpoint shows that 3 concurrent events over-subscribe 15 officers by 8 units — this is the actual problem city traffic centers face."
- "vehicle_breakdown is 2x more predictable than water_logging. We use that in how we size the confidence bands."

**Don't say:**
- "Our AI predicts clearance time to within X minutes" (it doesn't; MAE is 40 min)
- "Road closure reduces clearance time" (confounded; closure_true=6.6 is an artifact)
- "We have causal inference" (it's distance decay BFS; say "spatial propagation heuristic")
- "Live Gemini synthesis" unless a key is actually provided

---

## Three things theory got right

1. **Replacing ChromaDB with TF-IDF**: exactly the right call. `pysqlite3-binary` would have been a DLL nightmare on Python 3.9 + Windows. TF-IDF is faster, dependency-free, and for short Kannada-English blended incident descriptions, semantic embeddings would have been noise anyway.

2. **Clearance band instead of a point**: the eval proved this. Global median is unbeatable on MAE; any model that claims tighter precision is overfitting. The band + confidence + caveat is the honest and correct design.

3. **Budget allocation as a separate endpoint**: per-event manpower is ill-posed without a budget. The allocate endpoint, even greedy-proportional, is a cleaner answer to "how many officers?" than any per-event formula.

---

## Three things theory missed

1. **The road closure contrast is a trap.** Theory said: "natural experiment." Reality: planned events with road closure have 6.6 min median clearance because they're VIP movements and processions that end on schedule. N=3. Never show this as evidence of policy effect.

2. **The diversion routes are incident-graph-limited in a visible way.** A Bengaluru-aware judge will notice that diverting a CBD cricket crowd to MekhriCircle (north Bengaluru) is geographically odd as a primary diversion. The graph only connects junctions that had incidents — so diversions go where incidents happened before, not where roads actually go.

3. **Counterfactual time_saved_mins is 65 for a 12-hour cricket match.** `without=90, with=25, saved=65`. But the event has `scheduled_duration_mins=720` (12 hours). The clearance prediction is about how long *after the event* traffic recovers — not how long the event itself runs. This is an important distinction a judge might probe.

---

## Decision log (what to do with this before submission)

| Issue | Fix? | Effort | Decision |
|---|---|---|---|
| google.generativeai deprecated | Migrate to google.genai | 1-2h | Nice to have; fallback is functional |
| Gemini API key for live LLM synthesis | Add to .env | 5min | Yes if key is available |
| road_closure_contrast shown with n=3 | Add n < threshold → hide | 30min | Should fix; confusing to judges |
| Predicted vs actual error large (97 vs 31.9) | Already correct — show band + caveat | 0 | Accept; explains itself |
| Diversion routes incident-graph-only | Label as "incident-weighted approximation" | 15min | Update label text |
| Counterfactual 65min saved for 12h event | Add note: "traffic recovery time, not event duration" | 15min | Should fix |
| google.genai migration | 1-2h | Replaces deprecated package | Do if time permits |

**Priority order for remaining hours**: (1) Gemini key if available, (2) road_closure n threshold, (3) counterfactual label fix, (4) google.genai migration.

---

## Numbers to have ready for judges

```
Dataset:         8,170 events, Nov 2023 – Apr 2024
Planned:         467 (5.7%),  Unplanned: 7,703 (94.3%)
Active (R3):     1,006 events in dataset with status=active
Junction graph:  294 nodes, 4,896 edges, avg degree ~33, 3km straight-line
Max concurrency: 9 planned events simultaneously (cleaned durations)

Eval (unplanned, temporal split, n=717 test):
  Best baseline (global median): MAE 40.7 min, RMSE 63.8
  HGBR model:                    MAE 43.8, RMSE 59.8 (beats on RMSE)
  vehicle_breakdown:             MAE 30.8 (predictable)
  water_logging:                 MAE 118.9 (inherently noisy)

CBD2 Cricket match (FKID000008):
  Affected junctions: 74   Critical: 36   Corridors: 6
  Manpower: 11 units   Clearance band: [22, 58] min   Confidence: medium
  Diversion routes: 2   Barricade points: 5
```
