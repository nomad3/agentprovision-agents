"""Tests for ``apps/api/scripts/seed_animaldoctor_agent_fleet.py``.

The Agent model uses ``JSONB`` + pgvector + a graph of FK relationships
that don't load on SQLite, so we don't run the seed against a real DB
here. Instead we exercise the script's public surface
(``upsert_agent``, ``seed_fleet``) against a lightweight fake
``Session`` that mirrors the methods the script actually calls
(``query / filter / first``, ``add``, ``commit``, ``rollback``). This
matches the MagicMock pattern in
``apps/api/tests/api/v1/internal/test_agent_tokens_mint.py`` but makes
state inspection ergonomic.

Verified contract:
1. First run creates 5 agents, all on TENANT_ID, all production v1.
2. Re-running is a no-op (every result is "unchanged").
3. Mutating a persona_prompt mid-test → next run reports "updated"
   and writes the spec value back.
4. Every seeded agent has non-empty persona_prompt + capabilities +
   tool_groups.
"""
from __future__ import annotations

import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

# Make app + scripts importable when pytest is invoked from various cwds.
_API_ROOT = Path(__file__).resolve().parents[2]  # apps/api
if str(_API_ROOT) not in sys.path:
    sys.path.insert(0, str(_API_ROOT))


# We can't ``from scripts import seed_animaldoctor_agent_fleet`` because
# this test file lives in ``tests/scripts/`` and that empty package
# shadows the real ``apps/api/scripts/`` (same basename). Instead we
# load the script by file path under a unique module name. This also
# means we don't depend on ``apps/api/scripts/__init__.py`` existing or
# its namespace being writable.
_SEED_PATH = _API_ROOT / "scripts" / "seed_animaldoctor_agent_fleet.py"
_spec = importlib.util.spec_from_file_location(
    "seed_animaldoctor_agent_fleet_under_test",
    _SEED_PATH,
)
seed = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
assert _spec is not None and _spec.loader is not None
_spec.loader.exec_module(seed)


# ── fake session ─────────────────────────────────────────────────────


class _FakeColumn:
    """Tiny stand-in for an SQLAlchemy ``InstrumentedAttribute``.

    The seed uses ``Agent.tenant_id == X`` and ``Agent.name == Y`` to
    build filter predicates. SA returns a ``BinaryExpression`` whose
    ``.left.key`` is the column name and ``.right.value`` is the
    literal. We mimic just that interface so ``_FakeQuery.filter`` can
    extract ``(col_name, literal)`` from each predicate.
    """

    def __init__(self, name: str):
        self._name = name

    def __eq__(self, other):
        return _FakeBinary(self, other)

    # Avoid hashing surprises if a test ever does set/dict ops on these.
    def __hash__(self):
        return hash(("_FakeColumn", self._name))


class _FakeBinary:
    def __init__(self, left: _FakeColumn, right_value: object):
        # Match SA's BinaryExpression shape: left.key, right.value.
        self.left = type("_L", (), {"key": left._name})()
        self.right = type("_R", (), {"value": right_value})()


class _FakeAgent:
    """Stand-in for ``app.models.agent.Agent`` rows.

    Only the columns the seed reads/writes are tracked. ``id`` and
    ``tenant_id`` are populated by the caller (or by the seed when it
    creates a new row), all managed columns default to None so a
    "created" row visibly differs from an existing-but-drifted row.
    """

    # Class-level "columns" — match the SA expression API the seed
    # builds in ``upsert_agent``: ``Agent.tenant_id == TENANT_ID`` and
    # ``Agent.name == name``.
    tenant_id = _FakeColumn("tenant_id")
    name = _FakeColumn("name")

    def __init__(self, **kwargs):
        # Defaults — every column the seed touches.
        self.id = kwargs.get("id")
        self.tenant_id = kwargs.get("tenant_id")
        self.name = kwargs.get("name")
        self.role = kwargs.get("role")
        self.description = kwargs.get("description")
        self.capabilities = kwargs.get("capabilities")
        self.personality = kwargs.get("personality")
        self.persona_prompt = kwargs.get("persona_prompt")
        self.tool_groups = kwargs.get("tool_groups")
        self.default_model_tier = kwargs.get("default_model_tier")
        self.autonomy_level = kwargs.get("autonomy_level")
        self.max_delegation_depth = kwargs.get("max_delegation_depth")
        self.status = kwargs.get("status")
        self.version = kwargs.get("version")


class _FakeQuery:
    """Mimics the chain ``db.query(Agent).filter(...).first()``.

    SQLAlchemy's ``filter`` accepts arbitrary BinaryExpression args. We
    don't try to parse them — we re-implement the lookup the seed does
    (``tenant_id == TENANT_ID AND name == <spec name>``) by inspecting
    the spec list and the fake DB's stored rows. The trick: we capture
    each ``filter`` call's args as opaque expressions and resolve them
    via a helper that knows how to extract the comparator value.
    """

    def __init__(self, store: list[_FakeAgent]):
        self._store = store
        self._predicates: list[tuple[str, object]] = []

    def filter(self, *exprs):
        # SQLAlchemy column comparisons stringify reliably enough for
        # this test — but to keep the test independent of SA internals
        # we look at ``.left.key`` (column name) and ``.right.value``
        # (literal). Both are stable on SA 1.4 + 2.0.
        for e in exprs:
            try:
                col = e.left.key
                val = e.right.value
            except AttributeError:
                # Fall back: stringify and ignore. The seed only filters
                # on tenant_id + name, so a missing predicate would
                # broaden the match — which the assertions below would
                # catch immediately.
                continue
            self._predicates.append((col, val))
        return self

    def first(self):
        for row in self._store:
            if all(getattr(row, col) == val for col, val in self._predicates):
                return row
        return None


class FakeSession:
    """Just enough of ``sqlalchemy.orm.Session`` for the seed script."""

    def __init__(self):
        self._store: list[_FakeAgent] = []
        self._pending: list[_FakeAgent] = []
        self.commits = 0
        self.rollbacks = 0

    # The seed only ever calls ``db.query(Agent)`` — we don't care which
    # model class it's given.
    def query(self, _model):
        return _FakeQuery(self._store)

    def add(self, row):
        # Attach to store on first add so subsequent queries see it.
        if row not in self._store:
            self._store.append(row)
        if row not in self._pending:
            self._pending.append(row)

    def commit(self):
        self.commits += 1
        self._pending.clear()

    def rollback(self):
        self.rollbacks += 1
        # Drop pending rows that hadn't been committed yet — mirrors
        # SA's behaviour for the seed's exception path.
        for row in list(self._pending):
            if row in self._store:
                self._store.remove(row)
        self._pending.clear()


# ── monkeypatch the Agent class the seed instantiates ────────────────


@pytest.fixture(autouse=True)
def _patch_agent(monkeypatch):
    """The seed does ``Agent(id=..., tenant_id=..., **desired)`` to
    construct new rows. Replace the imported ``Agent`` symbol with our
    ``_FakeAgent`` so the seed never touches SA's mapper machinery.

    We also stub ``Agent`` on the model's ``query()`` codepath via the
    FakeSession's ``query()`` ignoring its argument — but the
    constructor call still happens, hence this patch.
    """
    monkeypatch.setattr(seed, "Agent", _FakeAgent)
    yield


@pytest.fixture
def db():
    return FakeSession()


# ── tests ────────────────────────────────────────────────────────────


def test_first_run_creates_five_agents(db):
    counts = seed.seed_fleet(db)
    assert counts == {"created": 5, "updated": 0, "unchanged": 0}
    assert len(db._store) == 5
    assert db.commits == 1


def test_every_seeded_agent_has_correct_tenant_id(db):
    seed.seed_fleet(db)
    for row in db._store:
        assert row.tenant_id == seed.TENANT_ID


def test_every_seeded_agent_has_required_fields(db):
    seed.seed_fleet(db)
    expected_names = {
        "Front Desk Agent",
        "SOAP Note Agent",
        "Billing Agent",
        "Cardiac Specialist Agent",
        "Inventory & Pharma Agent",
    }
    actual_names = {row.name for row in db._store}
    assert actual_names == expected_names

    for row in db._store:
        # Non-empty persona / capabilities / tool_groups
        assert row.persona_prompt and row.persona_prompt.strip(), (
            f"{row.name}: empty persona_prompt"
        )
        assert isinstance(row.capabilities, list) and len(row.capabilities) >= 1, (
            f"{row.name}: capabilities must be non-empty list"
        )
        assert isinstance(row.tool_groups, list) and len(row.tool_groups) >= 1, (
            f"{row.name}: tool_groups must be non-empty list"
        )
        # Lifecycle defaults from the spec
        assert row.status == "production", f"{row.name}: wrong status"
        assert row.version == 1, f"{row.name}: wrong version"
        assert row.autonomy_level == "supervised", f"{row.name}: wrong autonomy_level"
        assert row.max_delegation_depth == 2, f"{row.name}: wrong delegation depth"
        assert row.default_model_tier in {"light", "full"}, (
            f"{row.name}: model tier must be light or full"
        )
        # ID populated by the upsert
        assert isinstance(row.id, uuid.UUID), f"{row.name}: id must be a UUID"


def test_idempotent_second_run_reports_unchanged(db):
    first = seed.seed_fleet(db)
    assert first == {"created": 5, "updated": 0, "unchanged": 0}

    # Same state, re-run → all unchanged, no duplicate rows.
    second = seed.seed_fleet(db)
    assert second == {"created": 0, "updated": 0, "unchanged": 5}
    assert len(db._store) == 5  # no duplicates
    assert db.commits == 2  # one per run


def test_persona_drift_resets_to_seed_value(db):
    seed.seed_fleet(db)

    # Mutate one row's persona_prompt as if a human edited it in prod.
    target = next(r for r in db._store if r.name == "SOAP Note Agent")
    original_persona = target.persona_prompt
    target.persona_prompt = "tampered — drift sentinel"

    # Also drift a non-persona managed field to prove they all reset.
    other = next(r for r in db._store if r.name == "Billing Agent")
    other.tool_groups = ["only_one"]

    counts = seed.seed_fleet(db)
    # Two rows drifted, three did not.
    assert counts == {"created": 0, "updated": 2, "unchanged": 3}, counts

    # Persona reset to the spec value.
    assert target.persona_prompt == original_persona
    assert "tampered" not in target.persona_prompt
    # tool_groups reset on the Billing Agent.
    assert other.tool_groups == ["bookkeeper_export", "pulse", "ads"]


def test_role_drift_is_detected_and_reset(db):
    seed.seed_fleet(db)

    # Wrong role on Cardiac Specialist (somebody re-typed it as 'cardiologist'
    # — it's a managed field, must converge back to 'specialist').
    cardiac = next(r for r in db._store if r.name == "Cardiac Specialist Agent")
    cardiac.role = "cardiologist"

    counts = seed.seed_fleet(db)
    assert counts["updated"] == 1
    assert counts["unchanged"] == 4
    assert cardiac.role == "specialist"


def test_no_duplicate_rows_across_three_runs(db):
    for _ in range(3):
        seed.seed_fleet(db)

    # Exactly one row per spec name, never more.
    by_name: dict[str, int] = {}
    for row in db._store:
        by_name[row.name] = by_name.get(row.name, 0) + 1
    assert all(count == 1 for count in by_name.values()), by_name
    assert len(db._store) == 5


def test_default_model_tier_assignments_match_spec(db):
    seed.seed_fleet(db)
    by_name = {row.name: row for row in db._store}
    assert by_name["Front Desk Agent"].default_model_tier == "light"
    assert by_name["SOAP Note Agent"].default_model_tier == "full"
    assert by_name["Billing Agent"].default_model_tier == "light"
    assert by_name["Cardiac Specialist Agent"].default_model_tier == "full"
    assert by_name["Inventory & Pharma Agent"].default_model_tier == "light"


def test_tool_groups_match_spec(db):
    seed.seed_fleet(db)
    by_name = {row.name: row for row in db._store}
    assert by_name["Front Desk Agent"].tool_groups == [
        "calendar",
        "communication",
        "patient_records",
    ]
    assert by_name["SOAP Note Agent"].tool_groups == [
        "scribblevet",
        "patient_records",
        "knowledge",
    ]
    assert by_name["Cardiac Specialist Agent"].tool_groups == [
        "scribblevet",
        "patient_records",
        "drive",
        "knowledge",
        "calendar",
    ]
    assert by_name["Inventory & Pharma Agent"].tool_groups == [
        "pulse",
        "knowledge",
        "communication",
    ]
