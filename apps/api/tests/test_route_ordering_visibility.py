"""Pin the route-ordering invariant for the visibility tier endpoints.

Bug history (2026-05-03 hotfix): PR #263 mounted insights_fleet_health
*after* agents.router, both under /agents. agents.router has
GET /{agent_id}, which matched "fleet-health" as a UUID path param,
returned 422 with a Pydantic validation array, and the frontend page
choked rendering that array as a React child (error #31), crashing
the whole tree.

Fix: insights_fleet_health mounts BEFORE agents.router. FastAPI matches
in registration order — specific routes must come first.

This test asserts the registration order so a future router-mount
reshuffle doesn't silently re-introduce the bug.
"""
from app.api.v1 import routes as v1_routes


def test_fleet_health_mounts_before_generic_agents_route():
    """insights_fleet_health.router must be registered on the v1 router
    BEFORE agents.router. Otherwise GET /agents/fleet-health hits the
    /{agent_id} catchall in agents.router and Pydantic 422s on
    "fleet-health" failing UUID parse.
    """
    # Walk v1_routes.router.routes in order, find which file each
    # /agents/<...> mount came from. Match by inspecting the underlying
    # endpoint module path.
    fleet_health_idx = None
    agents_router_idx = None

    for i, route in enumerate(v1_routes.router.routes):
        # Each include_router call expands into multiple route objects;
        # check the route's endpoint module to identify the source.
        endpoint = getattr(route, "endpoint", None)
        module = getattr(endpoint, "__module__", "") if endpoint else ""
        path = getattr(route, "path", "")

        if "insights_fleet_health" in module and fleet_health_idx is None:
            fleet_health_idx = i
        # The /{agent_id} catchall lives in app.api.v1.agents
        if (
            module == "app.api.v1.agents"
            and "{agent_id}" in path
            and agents_router_idx is None
        ):
            agents_router_idx = i

    assert fleet_health_idx is not None, (
        "Could not find an insights_fleet_health route. Did the module "
        "rename or the include_router call get removed?"
    )
    assert agents_router_idx is not None, (
        "Could not find a /{agent_id} route in app.api.v1.agents. If "
        "the catchall was removed this test is no longer load-bearing "
        "and can be deleted."
    )
    assert fleet_health_idx < agents_router_idx, (
        f"Route ordering regression: insights_fleet_health is at index "
        f"{fleet_health_idx} but agents.router /{{agent_id}} is at "
        f"{agents_router_idx}. The specific /agents/fleet-health route "
        f"must come first or it gets shadowed by the UUID path param."
    )


def test_fleet_health_path_resolves_to_correct_endpoint():
    """End-to-end check: the path '/agents/fleet-health' resolved via
    FastAPI's router matches the insights_fleet_health endpoint, NOT
    the agents.router /{agent_id} catchall."""
    # Find a route whose path matches /agents/fleet-health.
    matched = None
    for route in v1_routes.router.routes:
        path = getattr(route, "path", "")
        if path == "/agents/fleet-health":
            matched = route
            break

    assert matched is not None, "No route registered for /agents/fleet-health"
    module = getattr(matched.endpoint, "__module__", "")
    assert "insights_fleet_health" in module, (
        f"/agents/fleet-health resolved to {module}, not "
        "insights_fleet_health. Route ordering is broken."
    )
