"""Request/response Pydantic models for the API's HTTP surface.

These shapes are the frozen §6 contract for the endpoints T5 owns
(`auth.py`, `health.py`); T11a adds the chat envelope's schemas in this
same file when it lands. Field names here are load-bearing — the frontend
and QA are building against them before the backend exists
(`docs/M1_BUILD_PLAN.md` §6).
"""

from __future__ import annotations

from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class UserPublic(BaseModel):
    """`{id, name}` — never the password hash, never anything else from
    the `users` row."""

    id: str
    name: str


class LoginResponse(BaseModel):
    user: UserPublic


class SessionResponse(BaseModel):
    authenticated: bool
    user: UserPublic | None = None


class HealthResponse(BaseModel):
    status: str
    revision: str


class ProjectSummary(BaseModel):
    """`{key, display_name}` — the same element shape `failure.
    known_projects` uses in the frozen §6 chat contract, so the frontend
    renders both from one component."""

    key: str
    display_name: str


class ProjectsResponse(BaseModel):
    projects: list[ProjectSummary]
