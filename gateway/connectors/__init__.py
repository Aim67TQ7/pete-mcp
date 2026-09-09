"""Connector adapter framework.

Adapters hold provider credentials server-side and report one of four honest
states — never simulated success, never raw auth errors or secret values:

  connected        probe succeeded with live provider evidence
  unconfigured     required env vars are absent on this host
  reauth_required  provider rejected the stored credential (401/403)
  unavailable      provider unreachable, timed out, or 5xx
"""
from dataclasses import dataclass, field


@dataclass
class ConnectorStatus:
    name: str
    state: str  # connected | unconfigured | reauth_required | unavailable
    detail: str = ""
    instances: dict[str, str] = field(default_factory=dict)  # instance -> state


class ConnectorError(Exception):
    """Safe-to-return connector failure (no secrets, no raw provider bodies)."""

    def __init__(self, state: str, message: str):
        self.state = state
        super().__init__(message)


def classify_http(status_code: int) -> str:
    if status_code in (401, 403):
        return "reauth_required"
    if status_code >= 500 or status_code == 429:
        return "unavailable"
    return "connected"
