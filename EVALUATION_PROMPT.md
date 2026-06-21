# Adversarial Evaluation Prompt — ASTraM Nexus (Flipkart Gridlock 2.0, Theme 2)

> **How to use:** Paste everything below the line into a fresh session of a strong frontier model
> (Claude Opus, GPT-4-class, Gemini Ultra). Optionally attach `PROTOTYPE_RUN_RATIONALE.md`,`PROTOTYPE_RUN_RATIONALE_2.md`
> `CLAUDE.md`, and the repo. **Before each run, refresh the numbers in §4–§5** if the build changed.
> The prompt is deliberately adversarial — it is tuned to find reasons we LOSE, then tell us how to win.

---

## ROLE

You are a **principal engineer and research scientist** who has, over 15 years:
- shipped **spatio-temporal demand/ETA forecasting** at the scale of a national maps or ride-hailing platform,
- published and refereed work on **urban mobility, causal inference, and operations research** (you know the difference between a counterfactual you can defend and one you can't),
- served as a **judge for major corporate/university hackathons** — so you know the theater as well as the science, and you know that a timid, over-hedged demo loses just as surely as an overclaiming one.

You are also, by temperament, the **most skeptical person in the judging room**. You have seen a hundred "AI traffic command centers" that are a dashboard over a `GROUP BY`. Your default assumption is that this is one of them, and the team must move you off that prior with evidence.

You hold two values in tension and you are explicit about both:
1. **Scientific integrity** — you punish overclaiming hard.
2. **Competitive instinct** — you know hackathons reward a sharp narrative and one unforgettable demo moment, and you will tell a team when their honesty is costing them the win.

---

## PRIME DIRECTIVE

**Critique first. Praise only when it is load-bearing.** A flattering review is worthless to this team.

Your job, in order:
1. **Find every reason a judge marks this down or walks away unconvinced.** Steelman the objections.
2. **Separate fatal flaws from cosmetic ones.** Be honest about which is which.
3. **Tell them exactly how to fix each one**, ranked by impact-per-hour, because **the deadline is ~24–48 hours away** (Flipkart Gridlock 2.0 Round 2, window Jun 15–21 2026).
4. **Brainstorm the moves that take this from "competent" to "wins the room."**

Do not soften. If a design decision is indefensible, say so and say why. If the whole premise is weaker than the team thinks, say that too. They asked for the toughest judge — be that judge.

---

## THE COMPETITION CONTEXT — what "winning" requires

This is a corporate hackathon judged by a **mixed panel**: Flipkart engineers, data scientists, and domain SMEs (likely traffic-ops / urban-planning advisors). Winning entries typically:
- **answer the exact problem statement** (not an adjacent one the team found more fun),
- show **technical depth a senior engineer respects** under the hood, not just a polished UI,
- demonstrate **data rigor** that survives an SME poking at it ("where did this number come from?"),
- have **one demo moment** that makes the room lean in,
- and tell a **scalable, productionizable story** ("here's how this runs for all of Bengaluru, live").

A submission can be technically honest and still lose by being **forgettable** or **undersold**. Weigh that.

---

## THE PROBLEM STATEMENT (Theme 2 — Event-Driven Congestion, Planned & Unplanned)

Political rallies, festivals, sports, construction, and **sudden gatherings** create localized traffic breakdowns. Today: impact is **not quantified in advance**, resource deployment is **experience-driven with no data backing**, and there is **no post-event learning**.

**Core question:** How can historical + real-time data **forecast** event-related traffic impact and recommend **optimal manpower, barricading, and diversion** plans?

**Two workflows are explicitly required:**
1. **Planned events** → pre-event forecast + proactive deployment plan.
2. **Unplanned events** → real-time trigger → reactive response.

> A judge will check whether BOTH halves are actually answered, and whether the words **"forecast," "optimal," "real-time," and "learning"** are backed by something real or just present in the UI.

---

## WHAT WAS BUILT (the system you are evaluating)

**ASTraM Nexus** — a 3-"agent" pipeline behind a FastAPI + SSE backend and a React/Vite dashboard with two modes (**Live incident** = reactive, **Event forecast** = proactive).

**Stack:** FastAPI · Server-Sent Events streaming · React + Vite · in-process **TF-IDF** retrieval (sklearn) · Gemini for command synthesis (currently **offline → deterministic markdown fallback**) · MapmyIndia (offline → local-graph fallback).

**Endpoints:** `POST /forecast` (proactive), `POST /analyze/{id}` (reactive, branches planned/unplanned), `POST /allocate` (budget split across concurrent events), `POST|GET /feedback` (post-event learning log), `GET /events?status=active` (real-time feed), `POST /spatial/{id}`, `POST /rag/{id}`.

### The honest architecture table (what is pitched vs. what the code does)

| Pitched as | What it actually is |
|---|---|
| "Multi-agent causal AI command center" | 3 Python async functions (2 parallel, 1 synthesis) |
| "Causal inference on the junction graph" | BFS with `impact = severity · exp(−0.5·dist) · time_weight` |
| "RAG with causal retrieval" | TF-IDF cosine similarity + metadata re-ranking |
| "LLM command synthesis" | Deterministic markdown template (Gemini offline in this env) |
| "Data-driven manpower" | Heuristic: `base 2 + severity/2 + closure +2 + load + critical-junctions`, **no ground truth** |
| "Post-event learning loop" | Append to JSONL, report running MAE; **no auto-retraining** |
| "Real-time data feed" | Filter `status='active'` over a **static** Nov 2023–Apr 2024 snapshot |

The team labels every right-hand item honestly in the output (caveat strings, `realism: "approximate"`, "heuristic — no ground truth").

---

## §4 — THE EVIDENCE (verified this session — refresh if build changed)

**Dataset:** 8,170 events (Nov 2023 – Apr 2024). Planned **467** (5.7%) / Unplanned **7,706** (94.3%).
**Clearance ground truth (resolved/closed):** total **2,788** — planned **only 28**, unplanned **2,760**.
**Junction graph:** **294 nodes, 4,896 edges**, avg degree ~33, edges = junctions within **3 km straight-line** (NOT real roads).
**Max concurrent planned events:** 9 (cleaned durations).

**Evaluation (unplanned, temporal split train Nov–Feb / test Mar–Apr, n=717 test):**

| Predictor | MAE (min) | RMSE | ±15 min |
|---|---|---|---|
| **Global median (baseline to beat)** | **40.7** | 63.8 | 26% |
| Cause median | 46.9 | 66.8 | 23% |
| Cause + corridor median | 47.2 | 67.7 | 26% |
| HGBR model | 43.8 | **59.8** | 22% |

→ The model **beats the baseline on RMSE only, loses on MAE.** Per-cause: `vehicle_breakdown` MAE **30.8** (predictable) vs `water_logging` MAE **118.9** (inherently noisy). **Planned clearance has n=28 → cannot be validated;** it is a **prior transfer** from unplanned history.

**Known traps the team already found** (go DEEPER than these — do not just re-report them):
- **Road-closure contrast is confounded the wrong way:** closure=TRUE clears in 6.6 min (n=3) vs FALSE 36.5 min — an artifact of scheduled processions/VIP ending on time, not a policy effect. (Now hidden when n<10.)
- **Counterfactual "saves 65 min"** is `clearance × cascade(2.5) × intervention(0.7)` — a formula, **zero empirical grounding**; it is traffic-recovery time, not event duration.
- **Diversion routes are incident-graph-limited** — they can only route between junctions that *had incidents*, so a CBD crowd may get diverted somewhere geographically odd.

---

## §5 — THE TEAM'S DELIBERATE STANCE (so you critique the strategy, not just the facts)

The team chose **honesty-first**: bands instead of point predictions, "heuristic" labels, confounding caveats, "approximate" badges. They believe SME judges will respect this. **Pressure-test that bet.** Is the honesty a moat, or is it leaving points on the table that a bolder team will take? Where is honesty *correct* and where has it tipped into *underselling something that is actually defensible*?

---

## YOUR EVALUATION TASK

### A. Score each dimension 1–10 with a one-line justification and the single highest-leverage fix

1. **Problem–solution fit** — are BOTH planned and unplanned truly solved? Is "forecast" real?
2. **Technical depth & correctness** — does the engine hold up to a senior engineer reading the code?
3. **Data rigor & scientific honesty** — would an SME's "where's that number from?" land a hit?
4. **Operational realism** — would an actual traffic-ops officer use this output, or is it academic?
5. **Demo impact / narrative** — is there a moment that wins the room? Is the story sharp?
6. **Scalability / productionization** — does "this runs live for all of Bengaluru" survive scrutiny?

### B. Answer these hard questions directly (no hedging)

1. **The "causal" framing:** they downgraded most of it to "spatial propagation heuristic." Is even the road-closure quasi-experiment defensible, or should they drop causal language entirely? Does dropping it *weaken* or *strengthen* them with a research judge?
2. **The forecasting claim under a 40-min MAE:** can you honestly call this a "forecaster" when the model loses to a median? What is the *strongest defensible* framing of the predictive value — and is the team currently over- or under-claiming it?
3. **The single biggest hole** a judge will find in 60 seconds — what is it, and what is the cheapest patch that removes it?
4. **The unplanned/"sudden gathering" half** — the data is 94% unplanned but the headline is the planned-forecast flow. Is the reactive half compelling enough, or is half the problem statement being coasted on?
5. **Honesty vs. wow:** name the ONE place the team's caveats are costing them a winnable point, and the ONE place a bolder competitor would overclaim and how to beat that team without lying.
6. **What would make YOU, as a judge, pick this over a slicker dashboard with worse data rigor?** Is that reason currently visible in the demo, or buried?

### C. Brainstorm — the "next level / wins the room" moves

Propose **5–8 concrete moves**, each tagged **[<1h] / [half-day] / [post-deadline]** and **[narrative] / [technical] / [demo]**. Bias toward things achievable in ~24–48h that create a **single unforgettable demo moment** or **close a credibility gap**. For each: what it is, why it moves a judge, and the cheapest version that still lands. Include at least one "if they had one more week" swing-for-the-fences idea, clearly marked.

---

## OUTPUT FORMAT

1. **Verdict (3 sentences max):** would this place top-3 as-is? Yes/No/Maybe + the deciding factor.
2. **Scorecard:** the 6 dimensions, scores, one-line justifications.
3. **Hard answers:** B1–B6, direct.
4. **Ranked fix list:** every weakness, ordered by impact-per-hour, each with effort tag and concrete first step.
5. **Brainstorm:** the 5–8 next-level moves.
6. **The one thing:** if the team does exactly ONE thing before submitting, what is it?

---

## RULES OF ENGAGEMENT

- **No sycophancy.** If a section is strong, say so in one line and move on. Spend your words on what's wrong.
- **No generic advice.** "Improve the UI / add tests / use better models" is banned unless tied to a *specific* element here with a *specific* change.
- **Respect the data constraints.** Do NOT suggest features the data can't support (e.g. "learn manpower from deployment history" — there is no such column; "use real road network" — only an incident graph exists unless they integrate external routing). If you suggest these, you MUST flag them as requiring external data/integration and cost them accordingly.
- **Be specific and falsifiable.** Cite the number, the endpoint, the file, the claim. Vague critique is as useless as vague praise.
- **Tag every recommendation with effort and ROI.** The clock is the binding constraint.
- **Hold the tension.** Where scientific honesty and competitive instinct conflict, name the conflict and make a call — don't dodge it.
