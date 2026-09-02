from __future__ import annotations

from matrixsolo.admin.models import AgentProfile
from matrixsolo.admin.store import get_profile_store


def load_profile(role: str) -> AgentProfile:
    return get_profile_store().get(role)


def require_tool(profile: AgentProfile, tool_key: str) -> bool:
    return profile.enabled and profile.has_tool(tool_key)
