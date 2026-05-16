# microservice chart

Generic chart shared by every AgentProvision service. Per-service values
live in `helm/values/<service>.yaml`.

## Volumes

Two independent persistent-volume blocks are supported:

- `persistence.*` — generic per-service data volume (default mount
  `/app/storage`). Used by the API for datasets.
- `workspaces.*` — per-tenant user workspace storage for the
  dashboard Files mode (PR #514). Default mount
  `/var/agentprovision/workspaces`. Off by default; flip
  `workspaces.enabled: true` in the api values to mount it.

The workspaces volume is the Helm mirror of the `workspaces:` named
volume in `docker-compose.yml` and the `WORKSPACES_ROOT` env var
consumed by `apps/api/app/api/v1/workspace.py`. Sized 10Gi by
default; bump via `workspaces.size`.

## Platform docs

The API image copies the repo's `/docs` tree to
`/opt/agentprovision/platform-docs` so the workspace `platform` scope
can serve a curated, read-only docs surface to super-admins without
exposing source. Set the `PLATFORM_DOCS_ROOT` env to override the
path (the api values file pins it to the default).
