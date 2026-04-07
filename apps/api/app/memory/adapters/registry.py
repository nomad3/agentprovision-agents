"""Runtime registry of source adapters.

Adapters register themselves at import time. Unknown source_type strings
in MemoryEvents fail-fast at ingest_events(). This is the open/closed
extension point — adding a source means writing one adapter file and
importing it from app.memory.adapters.__init__.
"""
from app.memory.adapters.protocol import SourceAdapter

_REGISTRY: dict[str, SourceAdapter] = {}


def register_adapter(adapter: SourceAdapter) -> None:
    if not adapter.source_type:
        raise ValueError("adapter.source_type must be a non-empty string")
    _REGISTRY[adapter.source_type] = adapter


def get_adapter(source_type: str) -> SourceAdapter:
    if source_type not in _REGISTRY:
        raise KeyError(f"No adapter registered for source_type={source_type!r}")
    return _REGISTRY[source_type]


def list_source_types() -> list[str]:
    return sorted(_REGISTRY.keys())
