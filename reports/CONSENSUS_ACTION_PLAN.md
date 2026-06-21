# ASTraM Nexus — Consensus Action Plan
**Synthesis of four independent adversarial reviews** (`report_3.5_flash`, `report_3.1_pro`, `report_gpt5.5`, `report_opus4.8_xh`)
**Compiled:** 2026-06-21 · Flipkart Gridlock 2.0, Round 2 (deadline window Jun 15–21) · Theme 2

> This is the document the `reports/` folder was missing: it reconciles all four model reviews into one prioritized, deadline-ranked punch-list. Where the reviews agree, the fix is near-certain. Where they disagree (exactly one place), the decision is recorded with its rationale.

---

## 1. Scorecard matrix (4 models × 6 dimensions)

| Dimension | 3.5 Flash | 3.1 Pro | GPT-5.5 | Opus 4.8 xh | Consensus read |
|---|:--:|:--:|:--:|:--:|---|
| Problem–solution fit | 8 | 7 | 5 | 6 | **6.5** — both workflows exist, but the unplanned half is a record browser, not a detector |
| Technical depth & correctness | 6 | 6 | 5 | 5 | **5.5** — clean plumbing; real bugs in load-bearing features |
| Data rigor & scientific honesty | 7 | 8 | 6 | 6 | **6.75** — genuinely strong eval, undercut by an over-claiming UI |
| Operational realism | 7 | 6 | 4 | 5 | **5.5** — scarcity-allocation is the right idea; routing/graph are not real |
| Demo impact / narrative | 8 | 5 | 6 | 6 | **6.25** — one real wow (allocation), buried under scaffolding |
| Scalability / productionization | 7 | 7 | 5 | 6 | **6.25** — fast & swappable, but static snapshot + stub integrations |
| **Average** | **7.2** | **6.2** | **5.2** | **5.67** | **≈6.1** |
| **Verdict** | Maybe | Maybe | **No** | Maybe→No | **Maybe, leans No until the scrub** |

**The pattern every report converges on:** the engineering and the *scientific honesty in the code* are real and rare; the **UI marketing contradicts the code** on the one screen judges see first. The submission's biggest risk is self-inflicted, and therefore cheap to fix.

---

## 2. Where all four agree (consensus fixes)

Tagged with the reports backing each. Items 1–4 are unanimous and cheap.

1. **Scrub the marketing the code itself refutes from the live landing screen** — *ALL 4, top fix.*
   `causal nodes` / `road dependencies` ([App.jsx:360,364](../frontend/src/App.jsx#L360)), `Causal impact path` ([:572](../frontend/src/App.jsx#L572)), `Spatial-Causal Engine` ([:652](../frontend/src/App.jsx#L652)), backend `"causal graph"` ([integrations.py:39](../backend/integrations.py#L39)). Remove the fabricated **"Command confidence 68–96%"** ([App.jsx:239–247, 673–698](../frontend/src/App.jsx#L239)) and the **"+8 min Surge response"** scenario ([App.jsx:262–266](../frontend/src/App.jsx#L262)). Render the honest `model.note` the backend already returns.

2. **Stop presenting the counterfactual as proof** — *GPT-5.5, Opus, 3.1.* The Live tab sells "Saves X min" under **"Counterfactual outcome / Judge-friendly proof"** ([App.jsx:742–762](../frontend/src/App.jsx#L742)) caveat-free, while [ForecastPanel.jsx:299–301](../frontend/src/ForecastPanel.jsx#L299) hedges the identical number. Copy the caveats; drop "proof."

3. **Surface the genuinely-strong, invisible eval** — *Opus, GPT-5.5, 3.1.* The leak-free temporal-holdout eval (baseline MAE **40.7**, ±15min **26%**, HGBR **loses** on MAE) lives only in CLI stdout. Add a static "Validation / provenance" panel so the rigor is on screen. *(GPT-5.5's "provenance strip" is the cheapest form.)*

4. **Fix `/allocate` — data and code** — *GPT-5.5 #3/#5, Opus #3.* Demo events are months apart (Jan/Feb/Mar), not concurrent. The split is **demand-proportional, not severity-proportional** despite the label; round-down leaves officers idle under oversubscription; `budget < #events` yields `1,0,0`, breaking the "≥1 each" promise.

5. **The real-time / "sudden-gathering" trigger does not exist** *(half-day, biggest functional gap)* — *GPT-5.5 One Thing, Opus B4, 3.5 #4, 3.1 #4.* Live tab is a static browser over `/events?limit=8200`; it never polls/detects/triggers. Add a **historical-replay trigger** (chronological release + transparent space-time rule → auto-`/analyze`), labeled "historical replay — not a live external feed."

6. **Feedback is logging, not learning** — *GPT-5.5 #2, 3.5 #3.* `feedback.jsonl` is never read by preprocess/inference. Minimum: rename to "Outcome logging." Better: a residual calibrator with a min-sample gate.

7. **`time_weight` keyed on UTC while users think IST** — *Opus #5, 3.5 #5.* Peak shifted 5.5h.

8. **Show median + n, never mean; add a RAG score threshold; rename "diversions"** — *GPT-5.5 #10/#11/#12, Opus #9.*

9. **`impact_probability` is misnamed** (`exp(-0.5·d)`, severity doesn't affect extent) — *GPT-5.5 B1.* → "relative impact score."

10. **Reconcile deck vs served counts** (docs 7,706/1,007/2,788 vs runtime 7,703/1,006/2,786) — *GPT-5.5 #13, Opus #10.*

---

## 3. The one disagreement — and the decision

**Fork: do we ship an ML model?**
- **Gemini 3.5 Flash** — *serialize HGBR and serve it in `predict_clearance`* (its #1 fix and "One Thing"), to give "forecasting" ML teeth.
- **Opus 4.8, GPT-5.5, 3.1 Pro** — *do NOT*: HGBR **loses** to the global median on MAE (**43.8 vs 40.7**); deploying it only to "say ML" is the wrong move. Re-pitch the served median prior as "calibrated planning bands" and surface the eval.

**DECISION → Honest reframe (3 of 4, incl. the deepest audit).** Rationale: a data-literate judge will ask for held-out error; shipping a model that loses its own baseline *invites* the attack, whereas "we tested an HGBR, it didn't beat the baseline on MAE, so we ship the simpler auditable prior" *is* the rigor that wins Theme-2 judges. Do not serialize HGBR.

---

## 4. Deadline-ranked punch-list (impact-per-hour)

| # | Fix | Effort | ROI | First step | Source |
|--:|---|---|---|---|---|
| 1 | Scrub causal/road labels + fabricated confidence + surge + scaffolding off `App.jsx`; render `model.note` | **<1h** | **Critical** | Edit `App.jsx:232–266,360–364,394–415,572,652,673–698`; `integrations.py:39` | all 4 |
| 2 | Add counterfactual caveats to Live tab; drop "proof" | **<1h** | Critical | Copy `ForecastPanel.jsx:299–301` into `App.jsx:742–762` | GPT-5.5/Opus/3.1 |
| 3 | Honest forecast framing + static **Validation/provenance** panel | **<1h** | Critical | Reword "forecaster/model"→"planning band"; add panel with MAE 40.7/±15=26% | Opus/GPT-5.5/3.1 |
| 4 | `/allocate`: redistribute leftover, severity-weight share, validate budget, fix `num_critical=0` | **<1h** | Very high | `main.py:342,357–364` | GPT-5.5/Opus |
| 5 | Pin a genuinely **concurrent** allocation demo triple | **<1h** | Very high | Overlap query over `events.json`; hardcode IDs in `AllocationPanel.jsx:18,47–57` | GPT-5.5 |
| 6 | Rename feedback → "Outcome logging" (it's never read) | **<1h** | High | `ForecastPanel.jsx` feedback card + `main.py:300` | GPT-5.5/3.5 |
| 7 | `time_weight` UTC/IST: convert or label "(UTC)" consistently | **30m–1h** | High | `spatial_engine.py:120–145` | Opus/3.5 |
| 8 | Median+n (never mean); RAG min-score threshold; "diversions"→"metering anchors"; rename `impact_probability` | **~1h** | High | `rag_core.py`, `spatial_engine.py`, panels | GPT-5.5/Opus |
| 9 | Reconcile deck counts to served `/stats` (7,703/1,006/2,786) | **15m** | Medium | deck + any hardcoded copy | GPT-5.5/Opus |
| 10 | **Historical-replay real-time trigger** (closes the missing workflow) | **half-day** | Very high (if time) | cursor endpoint + Live-tab poll + space-time rule | all 4 |
| 11 | Production-story slide (ingestion adapter, road graph, model registry, auth) | post-deadline | Medium now / high later | README/deck | GPT-5.5/3.5 |

### Status — deferred items now DONE (2026-06-21)

Items 1–9 were implemented earlier; the remaining deferred work is now complete and verified:

- **#10 Historical-replay trigger — DONE.** New `backend/replay.py` + `GET /replay/timeline` precompute a chronological unplanned-event timeline and space-time **surge alerts** (`>= 3 incidents, severity >= 7, within 1.5 km / 25 min`) over the 2024-03-07 storm-morning band. The Live tab now has a **play/pause/restart + speed** replay control: incidents stream onto the map, the **first detected surge auto-launches the existing 3-agent `/analyze`**, and the rest land in a clickable **Surge log**. De-dups the synthetic 52-row identical-timestamp artifact. Labeled "historical replay — not a live external feed."
- **#7 time_weight — DONE as evidence-based relabel, NOT a +5:30 conversion.** The stored clock's diurnal pattern (peak 19–22, trough 14–16) only makes sense as **local IST**; reading it as true UTC would put the peak at 00:30–03:30 (nonsense). So converting would *corrupt* the heuristic. Fix: treat/label time as IST (forecast form now "Start (IST)", `+00` stripped from values) — fixes the real user bug (entering 18:00 now maps to the evening-peak weight) with **no math change**.
- **#8 RAG floor + rename — DONE.** Added `MIN_COMBINED_SCORE = 0.05` in `rag_core.py` (calibrated: real matches ≥0.2, garbage ~0.025) — garbage queries now return "no strong match." Renamed the misnamed output key `impact_probability` → `relative_impact_score` across backend + frontend; relabeled "diversions" → "metering anchors (approximate)."
- **#9 Counts — DONE.** Reconciled `CLAUDE.md` + `PROTOTYPE_RUN_RATIONALE.md` to served `/stats`: unplanned **7,703**, clearance **2,786**, active **1,006**.

**Verification:** `test_replay.py` PASS · `test_forecast.py` PASS · `eval_duration.py` unchanged (MAE **40.7** / HGBR 43.8) · frontend build OK · greps clean (`impact_probability` 0 in src, only the one honest "not causal inference" disclaimer remains). Only #11 (production-story slide) remains, post-deadline.

---

## 5. Demo-day talking points (turn honesty into the moat)

- **Auditability moat:** *"Every number on screen traces to a data tier and a sample size, and we publish a held-out eval that shows where our own model fails. Ask a 'causal AI' team to show you their held-out error and their model's failure mode — they can't; we can."*
- **Provenance strip (always visible):** `Source: historical replay · Spatial: proximity heuristic · Clearance: global median / n=… · Routing: incident graph (offline) · Learning: outcome logging`.
- **Lead with the 94% half:** open on an *unplanned* replay → detection → scarce-force decision, then show the planned forecast — don't open on the weaker forecasting claim.
- **The scarcity moment:** drive the officer budget down live and watch the force pull off the lower-severity event — the one thing a slicker, infinite-resources dashboard can't show.
- **Never say:** "causal," "we predict to X minutes," "live MapmyIndia routing," "saves 65 minutes" (as fact), or quote the 516-min mean.

---

## 6. The one thing (consensus)

**Make the screen tell the truth the backend already tells.** Three of four reports' "One Thing" reduce to the same move from different angles (scrub the contradictions / surface the eval / lead with the honest unplanned replay). In ~90 minutes the team can delete the handful of words that hand a skeptical judge the rope ("causal," "proof," "connected," "submission ready") and surface the one artifact no rival can produce (a held-out eval that admits its own model lost). That single move flips the verdict from "Maybe/No" toward top-3 without building anything new.
