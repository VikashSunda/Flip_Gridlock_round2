"""
Agent 2: The RAG Intelligence Core (The Historian)

Honest framing (B1): this is retrieval-augmented historical evidence, NOT causal
inference. Two stages:
  1. Lexical retrieval: TF-IDF cosine over event documents (in-process; no heavy
     embedding model). On these short, templated, partly-Kannada strings, lexical
     similarity is about as useful as dense embeddings here — and far lighter.
  2. Operational re-ranking: boost hits sharing junction / corridor / cause /
     event_type / police-station (the relevance signal that actually matters to a
     traffic officer).

We use TF-IDF rather than ChromaDB to avoid a heavy native dependency
(ChromaDB needs sqlite3>=3.35 which the system Python lacks) and to keep the
component transparent and fast for ~8k short docs.
"""

import json
import os
from typing import Optional

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

# Relevance floor for retrieved matches (B-fix): calibrated on real-vs-garbage
# queries — genuine matches score >= ~0.2, noise scores ~0.02-0.03, so 0.05 cleanly
# separates them. Below this we return "no strong match" instead of confident noise.
MIN_COMBINED_SCORE = 0.05

# In-memory index (rebuilt at startup; fast for ~8k docs, no persistence needed)
_events_cache = None
_events_index = None
_vectorizer = None
_doc_matrix = None     # TF-IDF matrix, L2-normalized rows
_doc_metas = None      # list[dict] aligned with matrix rows


def _load_events():
    global _events_cache, _events_index
    if _events_cache is None:
        with open(os.path.join(DATA_DIR, "events.json"), "r", encoding="utf-8") as f:
            _events_cache = json.load(f)
        _events_index = {e["id"]: e for e in _events_cache}
    return _events_cache


def _event_by_id(event_id):
    """O(1) full-event lookup (B8: replaces per-candidate linear scans)."""
    if _events_index is None:
        _load_events()
    return _events_index.get(event_id)


def _doc_text(event: dict) -> str:
    """Compose the searchable document for an event."""
    parts = []
    if event.get("description"):
        parts.append(event["description"])
    if event.get("address"):
        parts.append(f"Location: {event['address']}")
    if event.get("event_cause"):
        parts.append(f"Cause: {event['event_cause']}")
    if event.get("corridor"):
        parts.append(f"Corridor: {event['corridor']}")
    if event.get("junction"):
        parts.append(f"Junction: {event['junction']}")
    if event.get("comment") and event["comment"] != "NULL":
        parts.append(f"Comment: {event['comment']}")
    return " | ".join(parts) if parts else f"{event.get('event_cause','')} at {event.get('address','unknown')}"


def build_vector_store():
    """
    Build the in-process TF-IDF index over all event documents.

    Idempotent and fast (a few hundred ms for ~8k docs); rebuilt fresh each start.
    """
    global _vectorizer, _doc_matrix, _doc_metas
    if _doc_matrix is not None:
        return _doc_matrix.shape[0]

    events = _load_events()
    docs, metas = [], []
    for e in events:
        docs.append(_doc_text(e))
        metas.append({
            "event_id": e["id"],
            "event_cause": e.get("event_cause", ""),
            "event_type": e.get("event_type", ""),   # Fix 8
            "junction": e.get("junction", ""),
            "corridor": e.get("corridor", ""),
            "priority": e.get("priority", ""),
            "police_station": e.get("police_station", ""),
            "clearance_time_mins": e.get("clearance_time_mins") or -1,
        })

    _vectorizer = TfidfVectorizer(max_features=20000, ngram_range=(1, 2), min_df=2)
    _doc_matrix = _vectorizer.fit_transform(docs)  # rows are L2-normalized
    _doc_metas = metas
    print(f"  TF-IDF index built: {_doc_matrix.shape[0]} docs, {_doc_matrix.shape[1]} features")
    return _doc_matrix.shape[0]


def _semantic_topn(query: str, n: int):
    """Return [(meta, similarity)] for the top-n TF-IDF matches to the query."""
    if _doc_matrix is None:
        build_vector_store()
    q = _vectorizer.transform([query])           # L2-normalized
    sims = (_doc_matrix @ q.T).toarray().ravel()  # cosine (both normalized)
    if n >= len(sims):
        idx = np.argsort(-sims)
    else:
        idx = np.argpartition(-sims, n)[:n]
        idx = idx[np.argsort(-sims[idx])]
    return [(_doc_metas[i], float(sims[i])) for i in idx]


def _extract_complications(matches):
    """Surface recurring hidden factors from match descriptions (EN + Kannada)."""
    complications = set()
    for m in matches:
        desc = m.get("description", "").lower()
        if any(w in desc for w in ["waterlogging", "water", "ಮಳೆ", "rain"]):
            complications.add("Waterlogging/rain frequent in this area")
        if any(w in desc for w in ["road work", "construction", "ಕಾಮಗಾರಿ", "white topping"]):
            complications.add("Road construction activity in area")
        if any(w in desc for w in ["flyover", "ಫ್ಲೈಓವರ್"]):
            complications.add("Flyover creates bottleneck at this junction")
        if any(w in desc for w in ["drainage", "manhole", "ಒಳಚರಂಡಿ"]):
            complications.add("Drainage/manhole issues reported in area")
    return sorted(complications)


def _build_target(event: dict) -> dict:
    """Normalize an event row into the retrieval target shape."""
    return {
        "id": event.get("id"),
        "description": event.get("description", ""),
        "event_cause": event.get("event_cause", ""),
        "event_type": event.get("event_type", ""),
        "junction": event.get("junction", ""),
        "corridor": event.get("corridor", ""),
        "police_station": event.get("police_station", ""),
        "address": event.get("address", ""),
    }


def _retrieve(target: dict, top_k: int = 10) -> dict:
    """
    Faceted historical retrieval shared by both entry points.

    NOT vanilla semantic RAG: we re-rank TF-IDF cosine hits by metadata relevance
    (same junction/corridor/cause/event_type/station). This is faceted retrieval
    weighted toward operational relevance — described honestly, not as
    "causal inference" (B1).
    """
    target_id = target.get("id")

    # Query refinement
    query_parts = []
    if target.get("description"):
        query_parts.append(target["description"])
    query_parts.append(f"Cause: {target.get('event_cause', '')}")
    if target.get("junction"):
        query_parts.append(f"Junction: {target['junction']}")
    if target.get("corridor"):
        query_parts.append(f"Corridor: {target['corridor']}")
    if target.get("address"):
        query_parts.append(f"Near: {target['address'][:100]}")
    enriched_query = " | ".join(query_parts)

    hits = _semantic_topn(enriched_query, min(top_k * 3, 30))  # over-retrieve for re-ranking
    if not hits:
        return {
            "event_id": target_id,
            "historical_matches": [],
            "summary": "No historical matches found.",
            "pattern_analysis": {"total_similar_events_found": 0},
            "match_context": {},
        }

    candidates = []
    for meta, semantic_score in hits:
        doc_id = meta["event_id"]
        if target_id and doc_id == target_id:  # skip self
            continue

        relevance_bonus = 0.0
        if meta.get("junction") and meta["junction"] == target.get("junction"):
            relevance_bonus += 0.3       # same physical location
        if meta.get("corridor") and meta["corridor"] == target.get("corridor"):
            relevance_bonus += 0.15      # same traffic flow
        if meta.get("event_cause") == target.get("event_cause"):
            relevance_bonus += 0.2       # same mechanism
        if meta.get("event_type") and meta["event_type"] == target.get("event_type"):
            relevance_bonus += 0.15      # Fix 8: planned prefers planned history
        if target.get("police_station") and meta.get("police_station") == target.get("police_station"):
            relevance_bonus += 0.1       # same operational area

        combined_score = (semantic_score * 0.4) + (relevance_bonus * 0.6)
        full_event = _event_by_id(doc_id)  # B8: O(1) lookup
        candidates.append({
            "event_id": doc_id,
            "semantic_similarity": round(semantic_score, 3),
            "match_relevance": round(relevance_bonus, 3),
            "combined_score": round(combined_score, 3),
            "event_cause": meta.get("event_cause", ""),
            "event_type": meta.get("event_type", ""),
            "junction": meta.get("junction", ""),
            "corridor": meta.get("corridor", ""),
            "clearance_time_mins": meta.get("clearance_time_mins", -1),
            "description": full_event.get("description", "") if full_event else "",
            "address": full_event.get("address", "") if full_event else "",
            "priority": meta.get("priority", ""),
        })

    candidates.sort(key=lambda x: x["combined_score"], reverse=True)
    # Relevance floor: garbage / out-of-distribution queries score ~0.02-0.03 while
    # genuine matches score >= ~0.2 (calibrated on real-vs-nonsense queries). A 0.05
    # gate drops noise without dropping any legitimate match — so we stop returning
    # confident-looking "evidence" for queries that have none.
    strong = [c for c in candidates if c["combined_score"] >= MIN_COMBINED_SCORE]
    top_matches = strong[:top_k]

    if not top_matches:
        return {
            "event_id": target_id,
            "query_used": enriched_query,
            "retrieval_method": "Retrieval-augmented historical evidence (semantic + metadata re-ranking)",
            "historical_matches": [],
            "summary": "No sufficiently similar historical incidents (all candidates fell below "
                       f"the relevance floor of {MIN_COMBINED_SCORE}).",
            "pattern_analysis": {"total_similar_events_found": 0},
            "match_context": {},
        }

    clearance_times = [
        m["clearance_time_mins"] for m in top_matches
        if m["clearance_time_mins"] and m["clearance_time_mins"] > 0
    ]
    cause_distribution = {}
    for m in top_matches:
        cause_distribution[m["event_cause"]] = cause_distribution.get(m["event_cause"], 0) + 1

    return {
        "event_id": target_id,
        "query_used": enriched_query,
        "retrieval_method": "Retrieval-augmented historical evidence (semantic + metadata re-ranking)",
        "historical_matches": top_matches,
        "pattern_analysis": {
            "total_similar_events_found": len(strong),
            "avg_clearance_time_mins": round(sum(clearance_times) / len(clearance_times), 1)
            if clearance_times else None,
            "median_clearance_time_mins": sorted(clearance_times)[len(clearance_times) // 2]
            if clearance_times else None,
            "min_clearance_time_mins": min(clearance_times) if clearance_times else None,
            "max_clearance_time_mins": max(clearance_times) if clearance_times else None,
            "cause_distribution": cause_distribution,
            "known_complications": _extract_complications(top_matches),
        },
        "match_context": {
            "same_junction_matches": len([m for m in strong if m["junction"] == target.get("junction") and m["junction"]]),
            "same_corridor_matches": len([m for m in strong if m["corridor"] == target.get("corridor") and m["corridor"] != "Non-corridor"]),
            "same_cause_matches": len([m for m in strong if m["event_cause"] == target.get("event_cause")]),
            "same_event_type_matches": len([m for m in strong if m["event_type"] == target.get("event_type") and m["event_type"]]),
        },
    }


def retrieve_historical_context(
    event_id: str,
    spatial_data: Optional[dict] = None,  # kept for orchestrator call compatibility
    top_k: int = 10,
) -> dict:
    """Reactive entry point: retrieve history for an existing event id."""
    event = _event_by_id(event_id)
    if not event:
        return {"error": f"Event {event_id} not found"}
    return _retrieve(_build_target(event), top_k)


def retrieve_historical_context_params(
    event_cause: str,
    junction: str = "",
    corridor: str = "",
    event_type: str = "planned",
    description: str = "",
    top_k: int = 10,
) -> dict:
    """Forecast entry point: retrieve history for a hypothetical (no event id) event."""
    target = {
        "id": None,
        "description": description,
        "event_cause": event_cause,
        "event_type": event_type,
        "junction": junction,
        "corridor": corridor,
        "police_station": "",
        "address": "",
    }
    return _retrieve(target, top_k)
