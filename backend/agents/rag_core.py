"""
Agent 2: The RAG Intelligence Core (The Historian)

Implements CDF-RAG inspired causal retrieval (arxiv:2504.12560):
1. Query Refinement: Enriches the event query with causal context
2. Semantic Retrieval: ChromaDB vector search on historical incidents  
3. Causal Filtering: Filters results by causal relevance (same junction,
   same corridor, same cause type — not just semantic similarity)
4. Knowledge Synthesis: Gemini synthesizes historical patterns

Unlike vanilla RAG, we don't just retrieve semantically similar documents.
We retrieve causally relevant ones — events at the same junction or corridor
that share causal mechanisms (same event_cause, similar time of day, etc.)
"""

import json
import os
from typing import Optional
import chromadb
from chromadb.config import Settings

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
CHROMA_DIR = os.path.join(DATA_DIR, "chroma_db")

# Cache
_collection = None
_events_cache = None


def _get_collection():
    """Get or create the ChromaDB collection."""
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=CHROMA_DIR)
        _collection = client.get_or_create_collection(
            name="astram_events",
            metadata={"hnsw:space": "cosine"},
        )
    return _collection


def _load_events():
    global _events_cache
    if _events_cache is None:
        with open(os.path.join(DATA_DIR, "events.json"), "r") as f:
            _events_cache = json.load(f)
    return _events_cache


def build_vector_store():
    """
    One-time indexing: embed all event descriptions into ChromaDB.
    Uses ChromaDB's built-in embedding (all-MiniLM-L6-v2).
    """
    events = _load_events()
    collection = _get_collection()

    # Check if already populated
    if collection.count() > 0:
        print(f"  ChromaDB already has {collection.count()} documents. Skipping.")
        return collection.count()

    # Prepare documents for embedding
    documents = []
    metadatas = []
    ids = []

    for event in events:
        # Build a rich document combining all text fields for embedding
        doc_parts = []
        if event.get("description"):
            doc_parts.append(event["description"])
        if event.get("address"):
            doc_parts.append(f"Location: {event['address']}")
        if event.get("event_cause"):
            doc_parts.append(f"Cause: {event['event_cause']}")
        if event.get("corridor"):
            doc_parts.append(f"Corridor: {event['corridor']}")
        if event.get("junction"):
            doc_parts.append(f"Junction: {event['junction']}")
        if event.get("comment"):
            doc_parts.append(f"Comment: {event['comment']}")

        doc_text = " | ".join(doc_parts) if doc_parts else f"{event['event_cause']} at {event.get('address', 'unknown')}"

        # Skip empty docs
        if not doc_text.strip():
            continue

        documents.append(doc_text)
        metadatas.append({
            "event_id": event["id"],
            "event_cause": event.get("event_cause", ""),
            "junction": event.get("junction", ""),
            "corridor": event.get("corridor", ""),
            "severity_score": event.get("severity_score", 5),
            "priority": event.get("priority", ""),
            "police_station": event.get("police_station", ""),
            "clearance_time_mins": event.get("clearance_time_mins") or -1,
            "latitude": event.get("latitude", 0),
            "longitude": event.get("longitude", 0),
        })
        ids.append(event["id"])

    # Batch insert (ChromaDB has a batch limit of ~5000)
    BATCH_SIZE = 500
    total = 0
    for i in range(0, len(documents), BATCH_SIZE):
        batch_docs = documents[i : i + BATCH_SIZE]
        batch_metas = metadatas[i : i + BATCH_SIZE]
        batch_ids = ids[i : i + BATCH_SIZE]
        collection.add(documents=batch_docs, metadatas=batch_metas, ids=batch_ids)
        total += len(batch_docs)
        print(f"  Indexed {total}/{len(documents)} events...")

    print(f"  ChromaDB indexing complete: {total} documents")
    return total


def retrieve_historical_context(
    event_id: str,
    spatial_data: Optional[dict] = None,
    top_k: int = 10,
) -> dict:
    """
    CDF-RAG inspired causal retrieval.

    Instead of just semantic similarity, we:
    1. Build a causally-enriched query from the event
    2. Retrieve top-K semantically similar events
    3. Apply causal filters (same junction, corridor, cause type)
    4. Score results by causal relevance, not just embedding distance
    5. Extract actionable patterns from historical data
    """
    events = _load_events()
    collection = _get_collection()

    # Find the target event
    target = None
    for e in events:
        if e["id"] == event_id:
            target = e
            break

    if not target:
        return {"error": f"Event {event_id} not found"}

    # === STEP 1: Build causally-enriched query (CDF-RAG Query Refinement) ===
    query_parts = []
    if target.get("description"):
        query_parts.append(target["description"])
    query_parts.append(f"Cause: {target['event_cause']}")
    if target.get("junction"):
        query_parts.append(f"Junction: {target['junction']}")
    if target.get("corridor"):
        query_parts.append(f"Corridor: {target['corridor']}")
    if target.get("address"):
        query_parts.append(f"Near: {target['address'][:100]}")

    enriched_query = " | ".join(query_parts)

    # === STEP 2: Semantic retrieval from ChromaDB ===
    results = collection.query(
        query_texts=[enriched_query],
        n_results=min(top_k * 3, 30),  # Over-retrieve for causal filtering
        include=["documents", "metadatas", "distances"],
    )

    if not results["ids"][0]:
        return {
            "event_id": event_id,
            "historical_matches": [],
            "summary": "No historical matches found.",
        }

    # === STEP 3: Causal filtering and scoring ===
    # CDF-RAG insight: not all semantically similar docs are causally relevant
    candidates = []
    for i, doc_id in enumerate(results["ids"][0]):
        if doc_id == event_id:  # Skip self
            continue

        meta = results["metadatas"][0][i]
        semantic_score = 1 - results["distances"][0][i]  # Convert distance to similarity

        # Causal relevance scoring
        causal_bonus = 0.0

        # Same junction = strong causal signal (same physical location)
        if meta.get("junction") and meta["junction"] == target.get("junction"):
            causal_bonus += 0.3

        # Same corridor = moderate causal signal (same traffic flow)
        if meta.get("corridor") and meta["corridor"] == target.get("corridor"):
            causal_bonus += 0.15

        # Same cause type = causal mechanism match
        if meta.get("event_cause") == target.get("event_cause"):
            causal_bonus += 0.2

        # Same police station = same operational area
        if meta.get("police_station") and meta["police_station"] == target.get("police_station"):
            causal_bonus += 0.1

        # Combined score: semantic + causal (CDF-RAG inspired)
        combined_score = (semantic_score * 0.4) + (causal_bonus * 0.6)

        # Find full event data for clearance time
        full_event = None
        for e in events:
            if e["id"] == doc_id:
                full_event = e
                break

        candidates.append({
            "event_id": doc_id,
            "semantic_similarity": round(semantic_score, 3),
            "causal_relevance": round(causal_bonus, 3),
            "combined_score": round(combined_score, 3),
            "event_cause": meta.get("event_cause", ""),
            "junction": meta.get("junction", ""),
            "corridor": meta.get("corridor", ""),
            "clearance_time_mins": meta.get("clearance_time_mins", -1),
            "description": full_event.get("description", "") if full_event else "",
            "address": full_event.get("address", "") if full_event else "",
            "priority": meta.get("priority", ""),
        })

    # Sort by combined causal+semantic score
    candidates.sort(key=lambda x: x["combined_score"], reverse=True)
    top_matches = candidates[:top_k]

    # === STEP 4: Extract patterns from historical data ===
    clearance_times = [
        m["clearance_time_mins"]
        for m in top_matches
        if m["clearance_time_mins"] and m["clearance_time_mins"] > 0
    ]

    cause_distribution = {}
    for m in top_matches:
        cause = m["event_cause"]
        cause_distribution[cause] = cause_distribution.get(cause, 0) + 1

    # Complications from the area (hidden variables in causal terms)
    complications = []
    for m in top_matches:
        desc = m.get("description", "").lower()
        if any(word in desc for word in ["waterlogging", "water", "ಮಳೆ", "rain"]):
            complications.append("Waterlogging/rain frequent in this area")
        if any(word in desc for word in ["road work", "construction", "ಕಾಮಗಾರಿ", "white topping"]):
            complications.append("Road construction activity in area")
        if any(word in desc for word in ["flyover", "ಫ್ಲೈಓವರ್"]):
            complications.append("Flyover creates bottleneck at this junction")
        if any(word in desc for word in ["drainage", "manhole", "ಒಳಚರಂಡಿ"]):
            complications.append("Drainage/manhole issues reported in area")

    # De-duplicate complications
    complications = list(set(complications))

    result = {
        "event_id": event_id,
        "query_used": enriched_query,
        "retrieval_method": "CDF-RAG (Causal Dynamic Feedback RAG)",
        "historical_matches": top_matches,
        "pattern_analysis": {
            "total_similar_events_found": len(candidates),
            "avg_clearance_time_mins": round(
                sum(clearance_times) / len(clearance_times), 1
            )
            if clearance_times
            else None,
            "median_clearance_time_mins": sorted(clearance_times)[len(clearance_times) // 2]
            if clearance_times
            else None,
            "min_clearance_time_mins": min(clearance_times) if clearance_times else None,
            "max_clearance_time_mins": max(clearance_times) if clearance_times else None,
            "cause_distribution": cause_distribution,
            "known_complications": complications,
        },
        "causal_context": {
            "same_junction_matches": len(
                [m for m in candidates if m["junction"] == target.get("junction") and m["junction"]]
            ),
            "same_corridor_matches": len(
                [m for m in candidates if m["corridor"] == target.get("corridor") and m["corridor"] != "Non-corridor"]
            ),
            "same_cause_matches": len(
                [m for m in candidates if m["event_cause"] == target.get("event_cause")]
            ),
        },
    }

    return result
