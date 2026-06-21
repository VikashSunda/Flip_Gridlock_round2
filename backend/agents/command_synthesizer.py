"""
Agent 3: The Command Synthesizer (The Chief)

Fuses Agent 1 (spatial) + Agent 2 (RAG) outputs into a prescriptive command.

Two modes (Fix 3):
  - "reactive": incident response for an unplanned event happening now
  - "forecast": pre-event deployment plan for a planned/future event

Uses Gemini if a key + valid model are configured; otherwise a deterministic
fallback that always works (the demo never depends on the LLM).
"""

import json
import os
from typing import AsyncGenerator

_model = None


def _get_model():
    """Return (client, model_name) for the current google-genai SDK, or None.

    None triggers the deterministic fallback, so a missing/placeholder key or an
    uninstalled SDK silently degrades — the demo never errors on a live call.
    """
    global _model
    if _model is None:
        try:
            from google import genai
            from dotenv import load_dotenv
        except ImportError:
            return None

        load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key or api_key == "your_gemini_api_key":
            return None
        # Use a current model id; "gemini-3.5-flash" (old default) does not exist.
        model_name = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
        _model = (genai.Client(api_key=api_key), model_name)
    return _model


def _fmt(value, fallback="unknown"):
    if value is None or value == "" or value == "NULL":
        return fallback
    return value


def _fallback_command(spatial_data: dict, rag_data: dict, mode: str = "reactive") -> str:
    """Deterministic command output (defensive .get throughout — contract-safe)."""
    is_forecast = mode == "forecast"
    event_cause = str(spatial_data.get("event_cause", "incident")).replace("_", " ").title()
    event_type = str(spatial_data.get("event_type", "event")).title()
    severity = spatial_data.get("severity_score", 5)
    epicenter = spatial_data.get("epicenter", {}) or {}
    event_details = spatial_data.get("event_details", {}) or {}
    blast_radius = spatial_data.get("blast_radius", {}) or {}
    counterfactual = spatial_data.get("counterfactual", {}) or {}
    deployment = spatial_data.get("deployment_recommendation", {}) or {}
    manpower = deployment.get("manpower", {}) or {}
    predicted = spatial_data.get("predicted_clearance", {}) or {}
    pattern = rag_data.get("pattern_analysis", {}) or {}
    match_context = rag_data.get("match_context", {}) or {}

    location = _fmt(epicenter.get("nearest_junction"), _fmt(epicenter.get("address"), "reported location"))
    priority = "Immediate" if severity >= 8 else "Urgent" if severity >= 6 else "Standard"
    priority_junctions = deployment.get("priority_junctions") or [
        n.get("junction") for n in blast_radius.get("affected_nodes", [])[:3] if n.get("junction")
    ]
    barricade_points = deployment.get("barricade_points") or priority_junctions[:3]
    diversion_routes = deployment.get("diversion_routes", []) or []
    units = manpower.get("units", max(2, len(priority_junctions) + 1))
    station = _fmt(event_details.get("police_station"), "nearest traffic station")
    corridor = _fmt(event_details.get("corridor"), "local corridor")
    matches = pattern.get("total_similar_events_found", 0)
    same_corridor = match_context.get("same_corridor_matches", 0)
    complications = pattern.get("known_complications", [])[:2]

    node_lines = []
    for node in blast_radius.get("affected_nodes", [])[:5]:
        impact = int(round(node.get("relative_impact_score", 0) * 100))
        node_lines.append(
            f"- {node.get('junction', 'Adjacent junction')}: {impact}% impact, "
            f"spillover in ~{node.get('estimated_time_to_impact_mins', 0)} min"
        )
    if not node_lines:
        node_lines.append("- No connected junctions crossed the impact threshold.")

    manpower_lines = [f"- {b['factor'].replace('_', ' ')}: +{b['units']}" for b in manpower.get("breakdown", [])]
    manpower_text = "\n".join(manpower_lines) if manpower_lines else f"- {units} units (baseline)"

    diversion_text = "\n".join(
        f"- Divert toward {d.get('to')} via {' -> '.join(d.get('via', [])[:4])} (~{d.get('distance_km')} km, approximate)"
        for d in diversion_routes[:2]
    ) or "- No clear alternate route on the incident graph; hold and meter at source."

    pred_band = (
        f"{predicted.get('median_mins','?')} min (band {predicted.get('range_mins',['?','?'])[0]}-"
        f"{predicted.get('range_mins',['?','?'])[1]}, confidence {predicted.get('confidence','low')})"
    )
    actual_line = ""
    if predicted.get("actual_mins") is not None:
        actual_line = f"\n- Actual clearance for this event: {predicted['actual_mins']} min (predicted-vs-actual)"

    header = "PRE-EVENT DEPLOYMENT PLAN" if is_forecast else "INCIDENT RESPONSE"
    verb = "Stage ahead of the event" if is_forecast else "Deploy now"
    barricade_verb = "Pre-position barricades at" if is_forecast else "Barricade"

    return f"""## {header}: {event_type} {event_cause} at {location}

**Priority:** {priority} | **Severity:** {severity}/10 | **Mode:** {mode}

### Situation
{event_cause} anchored near {location} on {corridor}. Spatial engine projects {blast_radius.get('total_affected_junctions', 0)} affected junctions ({blast_radius.get('critical_junctions', 0)} critical) within {blast_radius.get('max_radius_km', 0)} km.

### Projected spillover
{chr(10).join(node_lines)}

### Historical intelligence
{matches} similar past events ({same_corridor} same-corridor). Predicted clearance: {pred_band}.{actual_line}
{chr(10).join(f"- Watch: {c}" for c in complications) if complications else "- No recurring complication surfaced."}

### Deployment order ({units} units)
{manpower_text}
1. **{verb}**: {units} units — concentrate at {", ".join(priority_junctions[:3]) or location}.
2. **{barricade_verb}**: {", ".join(barricade_points) or location} to stop inflow at the highest-impact nodes.
{diversion_text}
3. **Alert** {station} for barricade support and clearance coordination.

### Counterfactual (heuristic)
- Without intervention: {counterfactual.get('without_intervention_mins', '?')} min
- With this deployment: {counterfactual.get('with_intervention_mins', '?')} min
- Estimated time saved: {counterfactual.get('time_saved_mins', '?')} min

*ASTraM Nexus deterministic command | manpower is a documented heuristic (no deployment ground truth)*
"""


SYSTEM_PROMPT = """You are ASTraM Nexus Command AI for the Bengaluru Traffic Police.

You receive two intelligence reports:
1. SPATIAL ANALYSIS: a distance-decay propagation estimate of which junctions will be impacted (this is a heuristic, not causal proof).
2. HISTORICAL INTELLIGENCE: similar past events, clearance bands, known complications.

Generate ONE prescriptive command for the Traffic Commander, in markdown.

If MODE is "forecast": write a PRE-EVENT DEPLOYMENT PLAN (stage units ahead, pre-position barricades, set advance diversions before the event starts).
If MODE is "reactive": write an INCIDENT RESPONSE (deploy now, clear the active incident).

Use this structure:
## [PRE-EVENT DEPLOYMENT PLAN | INCIDENT RESPONSE]: [Event] at [Junction]
**Priority:** ... | **Severity:** x/10

### Situation
[2-3 sentences referencing exact junction/corridor names.]

### Projected spillover
[Top 3-5 affected junctions with impact % and time-to-impact.]

### Historical intelligence
[Clearance band (state it is a band, not a point), known complications, same-corridor count.]

### Deployment order ([N] units)
[Cite the manpower breakdown. Numbered actions: stage/deploy units at named junctions; pre-position/place barricades; set diversion via the named route (note it is approximate).]

### Counterfactual (heuristic)
[Without vs with intervention minutes, time saved — label as heuristic.]

RULES:
- Use EXACT junction/corridor names from the data.
- Manpower is a documented heuristic (no deployment ground truth) — do not present it as learned/optimal.
- Clearance is a planning band, not a precise prediction.
- If description has Kannada text, translate key operational details.
- Be precise and authoritative. Max 380 words.
"""


def _briefing(spatial_data: dict, rag_data: dict, mode: str) -> str:
    deployment = spatial_data.get("deployment_recommendation", {}) or {}
    return f"""MODE: {mode}

=== SPATIAL ANALYSIS (Agent 1) ===
Event: {spatial_data.get('event_id')} | {spatial_data.get('event_type')} / {spatial_data.get('event_cause')} | Severity {spatial_data.get('severity_score')}/10
Epicenter: {json.dumps(spatial_data.get('epicenter', {}))}
Affected junctions: {spatial_data.get('blast_radius', {}).get('total_affected_junctions', 0)} ({spatial_data.get('blast_radius', {}).get('critical_junctions', 0)} critical)
Top nodes: {json.dumps(spatial_data.get('blast_radius', {}).get('affected_nodes', [])[:5])}
Manpower (heuristic): {json.dumps(deployment.get('manpower', {}))}
Priority junctions: {json.dumps(deployment.get('priority_junctions', []))}
Barricade points: {json.dumps(deployment.get('barricade_points', []))}
Diversion routes (approximate): {json.dumps(deployment.get('diversion_routes', []))}
Predicted clearance (band): {json.dumps(spatial_data.get('predicted_clearance', {}))}
Counterfactual (heuristic): {json.dumps(spatial_data.get('counterfactual', {}))}
Road-closure contrast (confounded): {json.dumps(spatial_data.get('road_closure_contrast', {}))}
Affected corridors: {spatial_data.get('affected_corridors', [])}
Description: {spatial_data.get('event_details', {}).get('description', '')}
Police station: {spatial_data.get('event_details', {}).get('police_station', '')}

=== HISTORICAL INTELLIGENCE (Agent 2) ===
Method: {rag_data.get('retrieval_method', 'retrieval')}
Similar events: {rag_data.get('pattern_analysis', {}).get('total_similar_events_found', 0)}
Clearance (avg/median): {rag_data.get('pattern_analysis', {}).get('avg_clearance_time_mins')} / {rag_data.get('pattern_analysis', {}).get('median_clearance_time_mins')} min
Complications: {json.dumps(rag_data.get('pattern_analysis', {}).get('known_complications', []))}
Context: {json.dumps(rag_data.get('match_context', {}))}
Top matches: {json.dumps(rag_data.get('historical_matches', [])[:3])}

=== GENERATE THE COMMAND NOW ===
"""


async def synthesize_command(
    spatial_data: dict,
    rag_data: dict,
    stream: bool = True,
    mode: str = "reactive",
) -> AsyncGenerator[str, None]:
    """Generate a prescriptive command; yields chunks for SSE streaming."""
    model = _get_model()
    if model is None:
        fallback = _fallback_command(spatial_data, rag_data, mode)
        if stream:
            for i in range(0, len(fallback), 180):
                yield fallback[i : i + 180]
        else:
            yield fallback
        return

    client, model_name = model
    prompt = SYSTEM_PROMPT + "\n\n" + _briefing(spatial_data, rag_data, mode)
    try:
        if stream:
            for chunk in client.models.generate_content_stream(model=model_name, contents=prompt):
                if chunk.text:
                    yield chunk.text
        else:
            response = client.models.generate_content(model=model_name, contents=prompt)
            yield response.text
    except Exception:
        fallback = _fallback_command(spatial_data, rag_data, mode)
        if stream:
            for i in range(0, len(fallback), 180):
                yield fallback[i : i + 180]
        else:
            yield fallback


def synthesize_command_sync(spatial_data: dict, rag_data: dict, mode: str = "reactive") -> str:
    """Non-streaming version for testing."""
    model = _get_model()
    if model is None:
        return _fallback_command(spatial_data, rag_data, mode)
    try:
        client, model_name = model
        prompt = SYSTEM_PROMPT + "\n\n" + _briefing(spatial_data, rag_data, mode)
        response = client.models.generate_content(model=model_name, contents=prompt)
        return response.text
    except Exception:
        return _fallback_command(spatial_data, rag_data, mode)
