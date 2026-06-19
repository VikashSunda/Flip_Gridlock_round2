"""
Agent 3: The Command Synthesizer (The Chief)

Takes Agent 1 (spatial-causal) and Agent 2 (RAG historical) outputs
and generates military-grade prescriptive commands for traffic officers.

Uses Gemini for synthesis with a carefully engineered system prompt
that produces specific, actionable, location-aware commands — not
generic ChatGPT fluff.
"""

import json
import os
from typing import Optional, AsyncGenerator

# Will be initialized with API key
_model = None


def _get_model():
    global _model
    if _model is None:
        try:
            import google.generativeai as genai
            from dotenv import load_dotenv
        except ImportError:
            return None

        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return None
        model_name = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
        genai.configure(api_key=api_key)
        _model = genai.GenerativeModel(model_name)
    return _model


def _fmt(value, fallback="unknown"):
    if value is None or value == "" or value == "NULL":
        return fallback
    return value


def _fallback_command(spatial_data: dict, rag_data: dict) -> str:
    """Deterministic command output for demos when the LLM is unavailable."""
    event_cause = str(spatial_data.get("event_cause", "incident")).replace("_", " ").title()
    event_type = str(spatial_data.get("event_type", "event")).title()
    severity = spatial_data.get("severity_score", 5)
    epicenter = spatial_data.get("epicenter", {})
    event_details = spatial_data.get("event_details", {})
    blast_radius = spatial_data.get("blast_radius", {})
    counterfactual = spatial_data.get("counterfactual", {})
    deployment = spatial_data.get("deployment_recommendation", {})
    pattern = rag_data.get("pattern_analysis", {})
    causal_context = rag_data.get("causal_context", {})

    location = _fmt(
        epicenter.get("nearest_junction"),
        _fmt(epicenter.get("address"), "reported location"),
    )
    priority = "Immediate" if severity >= 8 else "Urgent" if severity >= 6 else "Standard"
    priority_junctions = deployment.get("priority_junctions") or [
        node.get("junction")
        for node in blast_radius.get("affected_nodes", [])[:3]
        if node.get("junction")
    ]
    top_nodes = blast_radius.get("affected_nodes", [])[:5]
    units = deployment.get("astram_units_needed", max(2, min(6, len(priority_junctions) + 1)))
    station = _fmt(event_details.get("police_station"), "nearest traffic station")
    corridor = _fmt(event_details.get("corridor"), "local corridor")
    avg_clearance = pattern.get("avg_clearance_time_mins") or "not enough historical"
    same_corridor = causal_context.get("same_corridor_matches", 0)
    matches = pattern.get("total_similar_events_found", 0)
    complications = pattern.get("known_complications", [])[:2]

    node_lines = []
    for node in top_nodes:
        impact = int(round(node.get("causal_impact_probability", 0) * 100))
        node_lines.append(
            f"- {node.get('junction', 'Adjacent junction')}: {impact}% impact probability, "
            f"spillover in {node.get('estimated_time_to_impact_mins', 0)} minutes"
        )
    if not node_lines:
        node_lines.append("- No connected junctions crossed the critical impact threshold.")

    first_junction = priority_junctions[0] if priority_junctions else location
    second_junction = priority_junctions[1] if len(priority_junctions) > 1 else corridor
    third_junction = priority_junctions[2] if len(priority_junctions) > 2 else "the nearest parallel corridor"

    complications_text = (
        "\n".join(f"- {item}" for item in complications)
        if complications
        else "- No recurring hidden complication surfaced in the top matches."
    )

    return f"""## ALERT: {event_type} {event_cause} at {location}

**Priority:** {priority} | **Severity:** {severity}/10 | **Commander view:** prescriptive deployment, not passive monitoring

### Situation Assessment
The reported {event_cause.lower()} is anchored near {location} on {corridor}. The spatial-causal engine predicts {blast_radius.get('total_affected_junctions', 0)} affected junctions inside a {blast_radius.get('max_radius_km', 0)} km blast radius.

### Blast Radius
{chr(10).join(node_lines)}

### Historical Intelligence
The RAG core found {matches} causally similar incidents, including {same_corridor} same-corridor matches. Average clearance for the retrieved pattern is {avg_clearance} minutes.
{complications_text}

### Deployment Order
1. **Deploy** {units} ASTraM units: 2 to {location}, then split remaining units across {", ".join(priority_junctions[:3]) or second_junction}.
2. **Hold** {first_junction} immediately to stop queue spillback at the highest-probability node.
3. **Divert** excess flow toward {third_junction}; keep {second_junction} open for emergency and towing access.
4. **Alert** {station} for barricade support and clearance coordination.

### Counterfactual
- Without intervention: {counterfactual.get('without_intervention_mins', 'unknown')} minutes
- With this deployment: {counterfactual.get('with_intervention_mins', 'unknown')} minutes
- Estimated time saved: {counterfactual.get('time_saved_mins', 'unknown')} minutes

*ASTraM Nexus deterministic command fallback | Confidence: HIGH when spatial and RAG agents complete*
"""


SYSTEM_PROMPT = """You are ASTraM Nexus Command AI — the autonomous command center for Bengaluru Traffic Police.

You receive two intelligence reports:
1. SPATIAL-CAUSAL ANALYSIS: Mathematical blast radius computation showing which junctions will be impacted, with causal probabilities and time estimates.
2. HISTORICAL RAG INTELLIGENCE: Past similar events at same/nearby locations, clearance times, known complications.

Your job: Generate a SINGLE prescriptive operational command for the Traffic Commander.

FORMAT YOUR RESPONSE EXACTLY LIKE THIS (use markdown):

## ⚠️ ALERT: [Event Type] at [Location]

**Severity:** [CRITICAL/HIGH/MODERATE] | **Priority:** [Immediate/Urgent/Standard]

---

### 📍 Situation Assessment
[2-3 sentences: What happened, where, and immediate impact. Reference the causal analysis data. Use exact junction names.]

### 🔴 Blast Radius — Causal Impact Chain
[List the top 3-5 affected junctions with their impact probability and estimated time to impact. Format as a clear cascade chain showing cause→effect.]

### 📊 Historical Intelligence
[What the RAG data tells us: average clearance time for similar events, known complications, hidden variables from past incidents. Reference specific past event IDs if available.]

### 🎯 DEPLOYMENT ORDER
[Specific, numbered action items:]
1. **DEPLOY** [X] ASTraM units to [specific junction] — [reason]
2. **BARRICADE** [specific road/junction] — [reason]
3. **DIVERT** traffic via [specific alternate route] — [reason]
4. **ALERT** [specific police station] for backup — [reason]

### ⏱️ Counterfactual Analysis
- **Without intervention:** Estimated clearance in [X] minutes, cascading to [Y] junctions
- **With this deployment plan:** Estimated clearance in [Z] minutes, saving [W] minutes
- **Time saved for commuters:** ~[estimate] person-hours

---
*ASTraM Nexus v1.0 | Causal AI Engine | Confidence: [HIGH/MEDIUM]*

RULES:
- Use EXACT junction names from the data (e.g., "SilkBoardJunc", "MekhriCircle")
- Use EXACT corridor names (e.g., "ORR East 1", "Bellary Road 1")
- Reference specific past event IDs when available (e.g., "FKID000123")
- Be specific about unit counts (derive from severity and blast radius)
- Include time estimates in minutes
- If description contains Kannada text, translate the key operational details
- Sound authoritative and precise — this is a military-grade command, not a suggestion
- Keep it concise. Maximum 400 words.
"""


async def synthesize_command(
    spatial_data: dict,
    rag_data: dict,
    stream: bool = True,
) -> AsyncGenerator[str, None]:
    """
    Generate prescriptive command by synthesizing spatial + RAG intelligence.
    Yields chunks for SSE streaming.
    """
    # Build the intelligence briefing for Gemini
    prompt = f"""INTELLIGENCE BRIEFING FOR COMMAND SYNTHESIS:

=== SPATIAL-CAUSAL ANALYSIS (Agent 1) ===
Event ID: {spatial_data.get('event_id')}
Event Type: {spatial_data.get('event_type')} — Cause: {spatial_data.get('event_cause')}
Severity Score: {spatial_data.get('severity_score')}/10

Epicenter: {json.dumps(spatial_data.get('epicenter', {}), indent=2)}

Blast Radius: {spatial_data.get('blast_radius', {}).get('total_affected_junctions', 0)} junctions affected
Critical Junctions (P(impact) > 0.4): {json.dumps(spatial_data.get('deployment_recommendation', {}).get('priority_junctions', []))}

Top Affected Nodes:
{json.dumps(spatial_data.get('blast_radius', {}).get('affected_nodes', [])[:5], indent=2)}

Counterfactual:
- Without intervention: {spatial_data.get('counterfactual', {}).get('without_intervention_mins')} mins
- With intervention: {spatial_data.get('counterfactual', {}).get('with_intervention_mins')} mins
- Recommended ASTraM units: {spatial_data.get('deployment_recommendation', {}).get('astram_units_needed')}

Affected Corridors: {spatial_data.get('affected_corridors', [])}
Event Description: {spatial_data.get('event_details', {}).get('description', '')}
Police Station: {spatial_data.get('event_details', {}).get('police_station', '')}
Road Closure Required: {spatial_data.get('event_details', {}).get('requires_road_closure', False)}

=== HISTORICAL RAG INTELLIGENCE (Agent 2) ===
Retrieval Method: {rag_data.get('retrieval_method', 'CDF-RAG')}
Total Similar Events Found: {rag_data.get('pattern_analysis', {}).get('total_similar_events_found', 0)}

Clearance Time Stats:
- Average: {rag_data.get('pattern_analysis', {}).get('avg_clearance_time_mins')} mins
- Median: {rag_data.get('pattern_analysis', {}).get('median_clearance_time_mins')} mins

Known Complications: {json.dumps(rag_data.get('pattern_analysis', {}).get('known_complications', []))}
Cause Distribution: {json.dumps(rag_data.get('pattern_analysis', {}).get('cause_distribution', {}))}

Causal Context:
- Same junction matches: {rag_data.get('causal_context', {}).get('same_junction_matches', 0)}
- Same corridor matches: {rag_data.get('causal_context', {}).get('same_corridor_matches', 0)}

Top Historical Matches:
{json.dumps(rag_data.get('historical_matches', [])[:3], indent=2)}

=== GENERATE COMMAND NOW ===
"""

    model = _get_model()
    if model is None:
        fallback = _fallback_command(spatial_data, rag_data)
        if stream:
            for i in range(0, len(fallback), 180):
                yield fallback[i : i + 180]
        else:
            yield fallback
        return

    if stream:
        try:
            response = model.generate_content(
                [
                    {"role": "user", "parts": [SYSTEM_PROMPT + "\n\n" + prompt]},
                ],
                stream=True,
            )
            for chunk in response:
                if chunk.text:
                    yield chunk.text
        except Exception:
            fallback = _fallback_command(spatial_data, rag_data)
            for i in range(0, len(fallback), 180):
                yield fallback[i : i + 180]
    else:
        try:
            response = model.generate_content(
                [
                    {"role": "user", "parts": [SYSTEM_PROMPT + "\n\n" + prompt]},
                ],
            )
            yield response.text
        except Exception:
            yield _fallback_command(spatial_data, rag_data)


def synthesize_command_sync(spatial_data: dict, rag_data: dict) -> str:
    """Non-streaming version for testing."""
    model = _get_model()
    if model is None:
        return _fallback_command(spatial_data, rag_data)

    prompt = f"""INTELLIGENCE BRIEFING FOR COMMAND SYNTHESIS:

=== SPATIAL-CAUSAL ANALYSIS (Agent 1) ===
Event: {spatial_data.get('event_id')} | Type: {spatial_data.get('event_cause')} | Severity: {spatial_data.get('severity_score')}/10
Epicenter: {spatial_data.get('epicenter', {}).get('nearest_junction', 'Unknown')}
Blast Radius: {spatial_data.get('blast_radius', {}).get('total_affected_junctions', 0)} junctions
Priority Junctions: {spatial_data.get('deployment_recommendation', {}).get('priority_junctions', [])}
Without intervention: {spatial_data.get('counterfactual', {}).get('without_intervention_mins')} mins
With intervention: {spatial_data.get('counterfactual', {}).get('with_intervention_mins')} mins
Units needed: {spatial_data.get('deployment_recommendation', {}).get('astram_units_needed')}
Description: {spatial_data.get('event_details', {}).get('description', '')}

=== HISTORICAL RAG INTELLIGENCE (Agent 2) ===
Similar events: {rag_data.get('pattern_analysis', {}).get('total_similar_events_found', 0)}
Avg clearance: {rag_data.get('pattern_analysis', {}).get('avg_clearance_time_mins')} mins
Complications: {rag_data.get('pattern_analysis', {}).get('known_complications', [])}

=== GENERATE COMMAND ===
"""

    try:
        response = model.generate_content(
            [{"role": "user", "parts": [SYSTEM_PROMPT + "\n\n" + prompt]}],
        )
        return response.text
    except Exception:
        return _fallback_command(spatial_data, rag_data)
