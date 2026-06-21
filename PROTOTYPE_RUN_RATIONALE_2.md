# Prototype Run #2 — Inferred Rationale (post Allocation-UI + google-genai migration)

> Oppenheimer: "Theory will only take you so far."
> Generated: 2026-06-20, second live run — after building the Force-Allocation UI, migrating
> off the deprecated `google.generativeai` package, and adding the counterfactual recovery note.
> Purpose: capture what the system ACTUALLY does now vs what we changed it to do — so we keep
> thinking from evidence, not from the design doc. Companion to `PROTOTYPE_RUN_RATIONALE.md`
> (run #1); read that first for the deeper data caveats, this for what moved.

---

## What we ran this time

```
python backend/eval/validate_data.py      -> data spike (B2/B3/B6/B9/B10)
python backend/eval/eval_duration.py      -> baselines + HGBR model
python backend/test_forecast.py           -> 4 integration tests
python backend/main.py                    -> live server :8000
curl GET  /                               -> health + integrations
curl GET  /stats                          -> dashboard aggregates
curl GET  /events?status=active           -> R3 realtime feed
curl POST /forecast  (public_event CBD 2) -> SSE, 16 frames
curl POST /allocate  [3 events, budget 15]-> R2 oversubscription
curl POST /feedback + GET /feedback       -> R1 learning loop
npx vite build                            -> frontend compiles (176 modules)
```

All pass. No crashes. Server warm in ~1s. **No `google.generativeai` FutureWarning anymore** —
the deprecation surfaced in run #1 (§A) is gone.

---

## The headline: nothing in the data/model layer moved — and that's the point

Run #2's eval numbers are **identical** to run #1:

```
UNPLANNED (n=717 test, temporal split)
  global median   MAE = 40.7  RMSE = 63.8   <- still the baseline to beat
  HGBR model      MAE = 43.8  RMSE = 59.8   <- still wins RMSE only, loses MAE
  vehicle_breakdown MAE = 30.8 | water_logging MAE = 118.9
PLANNED clearance ground truth: train=20 test=2  -> still [LOW-N], transfer-only
```

**Inferred rationale**: the three changes we made (Allocation UI, SDK migration, a counterfactual
caption) were deliberately confined to the *presentation* and *integration* layers. The forecasting
honesty story from run #1 is untouched, so every "say/don't-say" line still holds. This is a feature,
not an accident — we did not chase model accuracy, because run #1 proved the global-median baseline is
near-unbeatable. We spent the effort where the rubric pays (covering all of Theme 2 visibly), not where
it doesn't (a 2nd-decimal MAE).

---

## New empirical surprises (what this run surfaced that the design didn't)

### 1. Mean clearance is 516 min; median is 52.7 — a 10× gap

```
/stats clearance_stats: events_with_data=2786  avg_mins=516.1  median_mins=52.7
```

**Inferred rationale**: the mean is dominated by a long tail of multi-day events (construction,
water-logging). A 10× mean-vs-median gap is the sharpest possible argument for why we present a
**median + band**, never a mean. If a judge ever sees "516 min average clearance" they'll think the
system is broken. **Never surface the mean anywhere in the UI or pitch — median only.**

### 2. The allocation demo's "demand" is scenario-dependent — 19, not the 23 from run #1

```
/allocate [FKID000008 public_event, FKID000040 construction, FKID000000 vehicle_breakdown], budget 15
  -> OVERSUBSCRIBED  total_demand=19  budget=15
     public_event   demand 7 -> allocated 6
     construction   demand 6 -> allocated 5
     vehicle_breakdown demand 6 -> allocated 4
```

Run #1's rationale quoted a 23-demand / 5-6-4 scenario. This run, picking the *first event of each
cause*, gives 19-demand / 6-5-4. **The over-subscription STORY is robust; the exact numbers depend on
which concurrent events you select.** 

**Decision for the pitch**: do NOT memorize "23 officers." Say "these three concurrent events demand
more than the budget — watch the force split by severity." If we want a fixed number on stage, hardcode
the demo to a specific event triple and quote *that* triple's numbers. The new "Load demo scenario"
button picks first-of-cause, so it currently yields 19/15 — update the script to match, or pin the IDs.

### 3. The allocation feature now has its empirical justification visible

```
B10 concurrency (cleaned [15,1440]m): max simultaneously-active planned = 9
```

**Inferred rationale**: run #1 computed "max 9 concurrent planned events" but it lived only in an eval
script. Now the Allocation tab makes that abstract stat operationally real — you can select concurrent
events and watch a 15-officer budget fail to cover them. The data point and the UI finally point at the
same thing. This is the single highest-leverage thing we added: it converts an invisible backend
endpoint into the "real-world impact" moment the rubric rewards.

### 4. Forecast for a fresh public_event @ CBD 2 (not the cricket preset)

```
POST /forecast public_event, CBD 2, road closure, 180 min:
  affected junctions = 65  critical = 29
  manpower = 12  [base 2, severity 4, road_closure 2, long_duration 1, critical_junctions 4]
  clearance band = [21, 55] min  confidence = medium
  counterfactual = without 85 / with 23 / saves 62  (cascade_factor 2.5)
  road_closure_contrast: n_true=3  -> SUPPRESSED in UI (threshold n>=10)
```

**Inferred rationale**: a free-typed CBD 2 public_event yields 65/29 (vs the cricket *preset* FKID000008's
74/36 in run #1) — slightly smaller because the epicenter/severity differ. Both are plausible. Critically,
`road_closure_contrast` came back with **n_true=3**, and the UI guard (`n>=10`) correctly hides it — so the
confounded 6.6-min artifact from run #1 §4 never reaches a judge's eyes. The polish fix is verified working
on a live, fresh input, not just in theory.

### 5. The feedback loop accumulates and reports error live

```
POST /feedback (predicted 34, actual 41)  -> recorded, count=3
GET  /feedback                            -> running MAE = 10.7 min
```

**Inferred rationale**: the R1 loop is genuinely closing — feedback.jsonl persists across runs (count was
already >0) and GET recomputes a running MAE. The 10.7 figure is meaningless at n=3 (it's whatever we
typed), so **don't quote the running MAE as a system metric** — present it as "the loop is wired and will
sharpen priors as real outcomes arrive," not as evidence of accuracy.

---

## Integration / migration reality

### google-genai migration is clean and demo-safe

```
/integrations -> gemini: {status: "fallback", model: "gemini-2.0-flash"}
server log     -> NO FutureWarning, NO google.generativeai reference
```

**Inferred rationale**: we replaced `import google.generativeai` + `GenerativeModel` with the new
`from google import genai` client (`generate_content_stream`). Because `google-genai` isn't installed in
this environment AND no key is set, `_get_model()` returns None and the deterministic fallback runs —
exactly as designed. The migration cannot break the demo: worst case is the same offline fallback we've
been running all along. To show live LLM, `pip install -r requirements.txt` (now pins `google-genai`) and
set `GEMINI_API_KEY`; the badge will flip to "connected" only when the key actually resolves.

### Still offline in this environment

```
gemini:     fallback (no key)
mapmyindia: offline_fallback (no credentials)
```

Same posture as run #1. The entire demo path is deterministic and reproducible. Decision unchanged:
either add real keys for the live wow-factor, or lean into "runs with zero external dependencies" as a
feasibility selling point. Both are defensible; the fallback is the guaranteed path.

---

## The real architecture vs the pitched architecture (updated)

| What we say | What the code does (run #2) |
|---|---|
| "Forecast + manpower + barricade + diversion + allocation" | All five are now reachable in the UI (Allocation tab added) |
| "Resource allocation under scarcity" | Greedy severity-proportional split; live oversubscribed 19 vs 15 |
| "LLM command synthesis" | google-genai client wired; deterministic fallback is the active path (no key) |
| "Post-event learning loop" | feedback.jsonl append + running-MAE GET; no auto-retrain |
| "Data-driven manpower" | itemized heuristic (base 2 + severity/2 + closure + load + duration + critical + peak), no ground truth |

Still an honest prototype. The new row (allocation) is the one that most changes the demo's ceiling.

---

## Decision log — what to do before submission (updated from run #1)

| Issue | Status after run #2 | Decision |
|---|---|---|
| google.generativeai deprecated | ✅ Migrated to google-genai; warning gone | Done |
| Allocation endpoint had no UI | ✅ Force-Allocation tab built + live-verified | Done |
| Counterfactual "recovery vs duration" ambiguity | ✅ Caption added in ForecastPanel | Done |
| road_closure low-n artifact | ✅ Confirmed suppressed live (n_true=3 hidden) | Done |
| Mean clearance (516) could leak into UI | ⚠️ Audit UI — ensure only median is ever shown | Quick check before demo |
| Allocation demo number not fixed (19 vs 23) | ⚠️ Pin demo event IDs or update script wording | Decide before demo |
| Running MAE (10.7 @ n=3) is not a real metric | ⚠️ Frame as "loop wired," never quote as accuracy | Script discipline |
| Gemini key for live synthesis | ◻️ Optional; fallback guaranteed | Add if available |

**Priority for remaining hours**: (1) pin/relabel the allocation demo scenario, (2) UI audit that no mean
clearance is shown, (3) add Gemini key if we want live synthesis.

---

## Numbers to have ready (run #2, verified live)

```
Dataset:      8,170 events | planned 467 / unplanned 7,703 | active feed 1,006
Clearance:    median 52.7 min  (NEVER quote mean 516 — outlier-dominated)
Graph:        294 nodes, 4,896 edges
Eval (unplanned, n=717): global-median MAE 40.7 / RMSE 63.8 ; HGBR MAE 43.8 / RMSE 59.8
              vehicle_breakdown MAE 30.8 (predictable) | water_logging MAE 118.9 (noisy)
Planned concurrency: max 9 simultaneous (cleaned) -> motivates allocation
Forecast (public_event CBD 2): 65 affected / 29 critical ; 12 units ; band [21,55] ; saves ~62 min
Allocation (3 events, budget 15): OVERSUBSCRIBED, demand 19, split 6/5/4
Feedback loop: live, running MAE recomputed on each GET (don't quote the value)
Frontend: vite build OK, 176 modules
```

---

## One-paragraph takeaway

Theory said "build the forecast pillar and reframe manpower as optimization." The live run says the
forecast/model layer was already honest and stable — so the win came from *exposing* what existed: the
allocation-under-scarcity story is now on screen, the deprecated SDK is gone, and the confounded
road-closure artifact stays hidden on real input. The two things to stay disciplined about are both
about *what we say*, not what the code does: never show the 516-min mean, and never quote a feedback MAE
or a fixed allocation number as if it were a validated result. The system is most credible exactly where
it refuses to overclaim.
