"""Source adapters register at startup; recall + ingest validate via registry."""
import pytest

def test_register_and_lookup_adapter():
    from app.memory.adapters.registry import register_adapter, get_adapter, list_source_types
    from app.memory.adapters.protocol import SourceAdapter

    class FakeAdapter:
        source_type = "test_fake"
        async def ingest(self, raw, source_metadata, tenant_id):
            return []
        def deduplication_key(self, raw):
            return f"fake:{raw}"

    register_adapter(FakeAdapter())
    assert "test_fake" in list_source_types()
    assert get_adapter("test_fake").source_type == "test_fake"

def test_unknown_adapter_raises():
    from app.memory.adapters.registry import get_adapter
    with pytest.raises(KeyError):
        get_adapter("nonexistent_source_type_xyz")
