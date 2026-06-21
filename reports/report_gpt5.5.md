# Adversarial Evaluation Report — ASTraM Nexus

## 1. Verdict

**No, not top-3 as-is.** The prototype is functional and polished, but the four words a judge will test—**forecast, optimal, real-time, and learning**—are not yet backed by the runtime: clearance is an uncalibrated median band, allocation is proportional rounding over non-concurrent examples, “live” is a static archive, and feedback never changes a forecast. The deciding factor is the gap between unusually honest backend comments and a live UI that still says “causal,” assigns invented confidence percentages, and presents assumed minutes saved as an outcome.

*Verification basis: the current backend integration tests pass, the frontend production build succeeds, and the evaluation reproduces global-median MAE 40.7 versus HGBR MAE 43.8 on 717 held-out unplanned events. The supplied evidence also mixes raw and processed counts: 8,173 raw rows = 467 planned + 7,706 unplanned; after dropping three `test_demo` rows, the runtime has 8,170 events = 467 planned + 7,703 unplanned and 1,006 active records.*

## 2. Scorecard

| Dimension | Score | One-line justification | Single highest-leverage fix |
|---|---:|---|---|
| **Problem–solution fit** | **5/10** | Planned and reactive screens exist, but there is no real-time trigger, no validated “optimal” plan, and no learning update. | Replace the static Live tab with an explicitly labelled historical-replay trigger that automatically launches the reactive workflow. |
| **Technical depth & correctness** | **5/10** | FastAPI, SSE, parallel execution, caching, and tests are sound; the core intelligence remains unvalidated heuristics with several misleading semantics. | Make runtime decisions follow temporal validation: global baseline by default, specialized priors only where they beat it out-of-time. |
| **Data rigor & scientific honesty** | **6/10** | The temporal evaluation and low-N disclosure are strong, but the UI exposes uncalibrated bands, leaky retrospective comparisons, and unsupported confidence/counterfactual claims. | Generate as-of-time predictions and empirical residual intervals, then report held-out interval coverage. |
| **Operational realism** | **4/10** | Scarce-force allocation is the right problem, but the demo events are months apart, “units” are undefined, and incident-graph paths are not usable diversions. | Pin genuinely overlapping events and present a constrained policy allocation with editable officer-team assumptions. |
| **Demo impact / narrative** | **6/10** | The three workflows and streaming command look polished, but the strongest visual claims are the easiest ones to disprove. | Center the demo on one truthful alert-to-allocation replay, with provenance and uncertainty visible at every step. |
| **Scalability / productionization** | **5/10** | The lightweight stack comfortably handles 8K records, but there is no ingestion pipeline, road network, durable state, authorization, or multi-worker-safe feedback path. | Show and implement one ingestion adapter contract separating replay data from a future live event source. |

## 3. Hard answers

### B1. The “causal” framing

**Drop causal language entirely from the product and pitch.** The road-closure comparison is not a quasi-experiment: treatment is not exogenous, there is no identification strategy, and the relevant closure sample can be only `n=3`. At most it is a confounded descriptive contrast suitable for an appendix.

Dropping “causal” strengthens the submission with a research judge. The backend already admits this, but the UI still says “causal nodes,” “road dependencies,” “Causal impact path,” and “Spatial-Causal Engine” (`frontend/src/App.jsx:360–364, 572, 652`). That inconsistency is worse than simply presenting a transparent **spatial stress-propagation heuristic**.

Also rename `impact_probability`. In `spatial_engine.py`, it is `exp(-0.5 × distance)`, not an estimated probability. Severity and event cause do not affect whether a junction enters the blast radius; two events at the same coordinates can produce the same affected-junction count regardless of severity. Call it a **relative impact score**, then include normalized severity and time weight in the score if those are meant to change spatial extent.

### B2. The forecasting claim under a 40-minute MAE

**Do not claim accurate clearance forecasting.** The HGBR loses to the global median on MAE, median absolute error, and ±15-minute accuracy; it wins only RMSE. More importantly, HGBR is evaluation-only—the live `/forecast` path uses median priors from `forecast_priors.json`.

The strongest defensible framing is:

> **A pre-event impact scenario and historical planning-range estimator, with evidence strength and explicit uncertainty.**

The current team both over- and under-claims:

- It **over-claims** by calling `[0.6 × median, 1.6 × median]` a confidence band without measuring coverage, and by deriving “high/medium/low confidence” only from sample count.
- It **under-claims** the sound engineering decision not to deploy a model that loses the primary baseline. Do not serialize HGBR merely to say “ML.” Use the global median unless a subgroup method proves better on an out-of-time split.

The unedited-preset “predicted vs actual” display is not a valid backtest. Priors and the RAG index are built from the full dataset, including events after the selected historical event and potentially the event itself in the prior. Either compute all evidence using only records before the preset timestamp or label it “retrospective replay,” not scoring.

### B3. The single biggest hole

**The required real-time trigger does not exist.** The Live tab fetches all 8,170 records once from `/events?limit=8200` (`App.jsx:173`); it does not use `/events?status=active`, poll, subscribe, ingest, detect, or automatically trigger analysis. The newest record is from April 8, 2024.

The cheapest credible patch is a **historical replay mode**:

1. Filter unplanned records by timestamp.
2. Release them through a cursor/poll endpoint in chronological order.
3. Show “Historical replay — not a live external feed.”
4. Automatically raise an alert and launch `/analyze/{id}` when a new high-severity record or spatial cluster appears.

That directly demonstrates “unplanned event → real-time trigger → reactive response” without lying about external data.

### B4. The unplanned / sudden-gathering half

**It is not compelling enough.** The dataset is 94.3% unplanned, yet the UI treats those records as a sortable archive requiring manual selection. There is no sudden-gathering detector, no event-ingestion boundary, no alert latency, and no evidence that the reactive plan changes as new observations arrive.

Make the reactive half the opening, not the appendix: replay an incoming event, detect a simple and explainable condition such as “three high-severity reports within 1 km and 20 minutes,” issue the response, then move to scarce-force allocation. Clearly call the trigger a rule-based prototype unless it is evaluated.

### B5. Honesty versus wow

The caveat costing a winnable point is the repeated bare label **“manpower (heuristic)”**. Keep the scientific disclosure, but present the result as an **editable policy baseline**: define whether one unit is one officer or one team, show the rule, and let the commander override it. That sounds operational rather than apologetic without changing the truth.

A bolder competitor will claim “our intervention saves 65 minutes.” Beat that team by refusing the fake causal number and showing a better artifact: an uncertainty-aware no-action scenario versus a policy scenario, with every assumption visible. The current Live tab instead says “Saves X minutes,” invents a “Surge response” that always saves another eight minutes, and creates a 68–96% “Command confidence” score from hand-set UI arithmetic (`App.jsx:239–265, 673–695`). Those must be removed before making honesty the differentiator.

### B6. Why I would pick this over a slicker dashboard

The winning reason is **resource allocation under scarcity with visible provenance**. Most teams will recommend resources event by event as though the city has infinite officers; ASTraM at least recognizes that simultaneous events compete for a finite force.

That reason is currently visible but not yet true enough to win:

- “Load demo scenario” selects the first public event, construction event, and breakdown, not overlapping events.
- The selected records are closed events from January 30, February 12, and March 7, 2024.
- The API uses proportional rounding, not optimization; severity only determines processing order.
- With a budget of one for three events, the API allocates `1, 0, 0` while the UI promises every event receives at least one unit.

Pin genuinely concurrent records from the verified maximum-overlap set, validate the budget, define the objective, and call it a **policy allocation** unless an actual optimization problem is solved.

## 4. Ranked fix list

| Rank | Weakness and fix | Effort | ROI | Concrete first step |
|---:|---|---|---|---|
| **1** | Remove unsupported live-screen claims: “causal,” “road dependencies,” numeric command confidence, hard minutes saved, and the arbitrary `+8 min` surge scenario. | **[<1h]** | **Critical** | Edit `App.jsx:239–265, 360–364, 572, 652, 673–759`; use “relative impact,” “proximity edges,” and “scenario assumption.” |
| **2** | Stop falsely claiming feedback refines priors. `feedback.jsonl` is never read by preprocessing or inference. | **[<1h copy fix] / [half-day real fix]** | **Critical** | Immediately rename it “Outcome logging”; then merge feedback outcomes into a residual calibrator with a minimum-sample gate. |
| **3** | Make the allocation demo use genuinely concurrent events. The current preset spans three different months. | **[<1h]** | **Very high** | Extract one overlap set from the 239 cleaned planned intervals and hardcode those IDs into the demo preset. |
| **4** | Implement an honest unplanned-event trigger using historical replay. | **[half-day]** | **Very high** | Add a replay cursor endpoint and poll it from the Live tab; auto-open the newest qualifying unplanned event. |
| **5** | Fix allocation correctness and terminology. It is not optimal, not directly severity-proportional, and does not guarantee one unit. | **[half-day]** | **Very high** | Add `total_officers >= 1`, reject impossible minimum allocations, define a utility objective, and solve the small integer allocation exactly or label it policy-based. |
| **6** | Make runtime predictor selection follow the temporal evaluation. Aggregate cause/corridor medians lose to the global median. | **[half-day]** | **High** | Persist per-segment out-of-time scores and use specialized priors only where they beat global by a declared margin and sample threshold. |
| **7** | Replace the hand-made 60–160% range with empirical intervals. | **[half-day]** | **High** | Store residual or target quantiles by backoff tier and report 80% interval coverage on the March–April holdout. |
| **8** | Remove temporal leakage from historical preset scoring. | **[half-day]** | **High** | For a preset at time `t`, filter prior and retrieval evidence to events with `start_datetime < t`; otherwise remove “scored against actual.” |
| **9** | Correct spatial semantics. Blast-radius inclusion currently ignores severity and calls distance decay a probability. | **[<1h rename] / [half-day logic]** | **High** | Rename the field and compute one normalized impact score from severity, time weight, and decay before applying thresholds. |
| **10** | Stop calling incident-graph paths diversions. The algorithm deliberately targets reachable high-incident junctions, which may route traffic toward another hotspot. | **[<1h]** | **High** | Rename them “candidate metering anchors” and remove route-distance claims until Mappls/OSM validates drivable paths. |
| **11** | Make RAG evidence auditable. It always takes the top candidates even when similarity is weak, and “matches found” is effectively the over-retrieval count. | **[<1h]** | **Medium-high** | Add a minimum combined-score threshold and show the top evidence rows with score, date, cause, corridor, clearance, and sample count. |
| **12** | Replace displayed average clearance with median plus `n`. Both `App.jsx` and `ForecastPanel.jsx` still show an average despite the documented 516-vs-53-minute skew. | **[<1h]** | **Medium-high** | Display `median_clearance_time_mins` and the number of matched records containing clearance data. |
| **13** | Reconcile raw versus processed counts everywhere. | **[<1h]** | **Medium** | State “8,173 raw rows; 8,170 production events after dropping three test records” and use 7,703 processed unplanned events in runtime claims. |
| **14** | Define operational units and human override. | **[<1h]** | **Medium** | Replace “ASTraM units” with “officer teams,” define team size, and add an editable override acknowledged in the command output. |
| **15** | Harden the production story. JSON/JSONL state, permissive CORS, unauthenticated commands, and in-process indexes are single-process prototype choices. | **[post-deadline]** | **Medium now / high later** | Document the migration path to authenticated APIs, durable event storage, a geospatial road graph, model registry, and stream ingestion. |

## 5. Brainstorm — moves that can win the room

1. **[<1h] [demo] The truthful scarcity showdown**  
   Load three events that actually overlap, set 15 available officer teams, and show the shortage. It moves a judge because it turns a generic recommendation dashboard into a command decision under a real constraint. Cheapest version: pin verified overlapping IDs and state the policy objective above the chart.

2. **[<1h] [narrative/demo] The provenance strip**  
   Put a compact strip above every result: `Source: historical replay`, `Spatial: proximity heuristic`, `Clearance: global median / n=...`, `Routing: incident graph`, `Learning: logging only`. It makes honesty visible as product design instead of scattered apology text. Cheapest version: static labels populated from fields already returned by the API.

3. **[half-day] [technical/demo] Sudden-gathering replay trigger**  
   Replay unplanned events chronologically and raise a red alert when a transparent space-time rule fires. This directly answers the missing half of the problem statement and creates the “room leans in” moment. Cheapest version: one deterministic replay sequence and one documented radius/time threshold.

4. **[half-day] [technical/demo] Learning that visibly changes one estimate**  
   Submit an actual outcome, update a cause/corridor residual adjustment, and rerun the same scenario with “before” and “after” shown side by side. It proves learning rather than logging. Cheapest credible version: require at least five feedback records and show the sample count; below that, display “insufficient evidence—no update.”

5. **[half-day] [technical] A real policy optimizer with officer override**  
   Maximize weighted coverage subject to the officer budget, event minimums, and per-event demand caps. It earns the word “optimal” relative to an explicit objective without pretending manpower demand is learned. Cheapest version: exhaustive search is sufficient for the three-to-nine-event demo scale.

6. **[half-day] [demo] Replace “65 minutes saved” with an uncertainty fan**  
   Animate the no-action impact envelope and the policy-scenario envelope across nearby junctions, showing assumptions rather than one fake causal total. It retains visual drama and is harder to attack. Cheapest version: two colored bands derived from declared low/base/high intervention factors, labelled scenario ranges.

7. **[post-deadline — one more week] [technical/demo] Real roads plus real ingestion**  
   Integrate Mappls/OSM road topology for drivable diversion validation and connect one genuine event source through an ingestion adapter. This closes the two largest operational gaps: fake road edges and static “live” data. Cheapest one-week version: support one showcased corridor and one feed source end to end rather than claiming city-wide coverage.

## 6. The one thing

If the team does exactly one thing, **replace the Live tab with a clearly labelled, auto-triggered historical replay of an unplanned event that flows directly into a truthful scarce-force decision**. That closes the missing required workflow, creates the strongest demo moment, and lets the team compete on operational judgment without depending on an inaccurate point forecast or fabricated causal savings.
