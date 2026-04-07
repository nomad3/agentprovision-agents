"""Smoke test: the memory package and its public API are importable."""

def test_memory_package_imports():
    from app.memory import recall, record_observation, record_commitment
    from app.memory import ingest_events
    from app.memory.types import (
        MemoryEvent, RecallRequest, RecallResponse,
        EntitySummary, CommitmentSummary, EpisodeSummary,
    )
    assert callable(recall)
    assert callable(record_observation)
    assert callable(record_commitment)
    assert callable(ingest_events)
