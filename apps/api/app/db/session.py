import logging
import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

logger = logging.getLogger(__name__)

# In tests, we still want Postgres.
# If running locally (not in Docker), 'db' hostname won't resolve,
# so we fallback to localhost:8003 and use a dedicated test database.
#
# Safety: both TESTING=True AND PYTEST_CURRENT_TEST must be set. The
# PYTEST_CURRENT_TEST env var is injected automatically by pytest per-test,
# so stray TESTING=True in a prod container cannot cause a silent redirect
# to a non-existent test DB.
db_url = settings.DATABASE_URL
if os.environ.get("TESTING") == "True" and os.environ.get("PYTEST_CURRENT_TEST"):
    if "@db:5432" in db_url:
        db_url = db_url.replace("@db:5432", "@localhost:8003")
    # Always use the dedicated test database when pytest is actively running.
    if "/agentprovision" in db_url and not db_url.endswith("_test"):
        db_url = db_url.replace("/agentprovision", "/agentprovision_test")

engine = create_engine(
    db_url,
    pool_pre_ping=True,
    pool_size=20,
    max_overflow=10,
    # Belt for the suspenders below: explicitly request that the pool
    # issue ROLLBACK on every checkin. This is the documented default
    # but we set it explicitly so the intent survives any future config
    # tweak.
    pool_reset_on_return="rollback",
)


@event.listens_for(engine, "checkin")
def _force_rollback_on_checkin(dbapi_connection, connection_record):
    """Defensive rollback on every pool checkin.

    Background — production was emitting a cascade of
    `psycopg2.errors.InFailedSqlTransaction: current transaction is
    aborted, commands ignored until end of transaction block`. The
    cascade was rooted in workflow activity code paths that use the
    pattern

        db = SessionLocal()
        try:
            ...query that raises...
        finally:
            db.close()

    `db.close()` returns the underlying psycopg2 connection to the
    pool. SQLAlchemy's default `pool_reset_on_return='rollback'`
    SHOULD issue a ROLLBACK at that point and clear the aborted txn,
    but in the production async + heartbeat path it was observed to
    silently skip — the connection landed in the pool with the
    transaction still in `IDLE IN TRANSACTION (aborted)` state and
    the next pickup cascaded.

    PR #363 patched 6 explicit call sites in `dynamic_step.py` and
    PR-follow-up patched 19 more across `activities/`. This event
    listener is the **systemic defense**: every checkin issues an
    explicit `ROLLBACK` on the DBAPI connection regardless of how
    we got here. Idempotent — ROLLBACK on a clean connection is a
    no-op. Safe — wrapped in try/except so a bad connection doesn't
    take down the pool.
    """
    try:
        dbapi_connection.rollback()
    except Exception as e:  # pragma: no cover — defensive
        logger.debug("checkin rollback failed (non-fatal): %s", e)


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
