"""`GET /api/v1/projects` — session-required, `{projects: [{key,
display_name}]}` (the same element shape `failure.known_projects` uses in
the frozen §6 chat contract).

T16 deleted its hard-coded `FALLBACK_KNOWN_PROJECTS` and fetches this
endpoint for the empty-state chips (A-14, §11.5); if this call fails, the
frontend renders the empty state with no chips rather than a stale list.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from sunil.api.deps import require_owner_session
from sunil.api.schemas import ProjectsResponse

router = APIRouter(prefix="/api/v1", tags=["projects"])


@router.get("/projects", response_model=ProjectsResponse)
async def list_projects(
    request: Request,
    user_id: str = Depends(require_owner_session),
) -> ProjectsResponse:
    """The configured projects (`config/projects.yaml`, loaded once at
    startup into `app.state.registries` — ADR-016, no hot reload).
    Read-only and session-required like every other authenticated GET;
    `require_owner_session` is the same 401 gate `/api/v1/auth/session`
    would use if it required one.
    """
    del user_id  # only the auth check matters here, not the identity
    known = request.app.state.registries.projects.known_projects()
    return ProjectsResponse(projects=known)
