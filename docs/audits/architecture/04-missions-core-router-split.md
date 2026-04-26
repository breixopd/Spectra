# Missions `core.py` split — candidate structure

`app/api/routers/missions/core.py` is the largest mission router module. The package already splits **artifacts**, **export**, and **feedback**; `core` still bundles list/summary, presets, chain CRUD, and lifecycle (stop/pause/resume/delete).

## Target layout (no backward-compat shims)

- **`presets.py`** (or keep in `core` if tiny): `GET /presets`, any playbook/preset read-only data.
- **`summary_list.py`**: `GET /summary` and list endpoints with pagination, if you want a thinner `core` focused on ID routes.
- **`mission_lifecycle.py`**: `DELETE`, `POST .../stop|pause|resume` — all admin/control paths that touch `mission_manager` + rate limits.
- **`mission_detail.py`**: `GET|DELETE?` single mission by id — the dynamic `/{mission_id}` routes; keep a single `/{mission_id}` tree to avoid FastAPI `include_router` empty-prefix issues (see `missions/__init__.py`).

## Integration

Wire new routers in `app/api/routers/missions/__init__.py` by `router.routes.extend` in a stable order (static paths before `/{mission_id}`).

## Risk

- Route order: more-specific paths must register before `/{mission_id}`.
- Shared imports (`mission_manager`, `MissionRepository`, audit) — extract small internal helpers in `app/api/routers/missions/_deps.py` only if duplication appears.

**Status:** documented for a follow-up PR; not applied in the same change set as behavioral fixes.
