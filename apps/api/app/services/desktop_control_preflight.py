"""Startup helper for desktop-control signing readiness."""
import logging


async def startup_desktop_control_preflight():
    """Log desktop-control signing readiness without blocking API startup.

    ``alpha desktop preflight run`` is the operator-facing gate. Startup must not
    take the API down just because the native-control signing key is absent:
    without a valid Ed25519 key, the command-claim path denies native control
    fail-closed and emits an audit row before any envelope can be built.
    """
    log = logging.getLogger(__name__)
    try:
        from app.services.desktop_control_service import run_desktop_preflight

        result = run_desktop_preflight()
    except Exception as exc:  # never let an unexpected preflight error block startup
        log.warning("desktop-control preflight skipped (unexpected error): %s", exc)
        return
    if result["ok"]:
        log.info("desktop-control preflight ok (algorithm=%s)", result["algorithm"])
        return
    log.warning(
        "desktop-control preflight failed (native control fail-closed, algorithm=%s): %s",
        result["algorithm"], result["error"],
    )
