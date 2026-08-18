"""Identity 1: the service principal Pulse authenticates to Lite as.

Carries read-only scopes only, verified independently on every call
(NFR-4). The service token never widens access - see
diagnostic_mcp/registry/pipeline.py for how this identity and the user's
own grants (auth/user_context.py, services/grants.py) are kept separate.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import jwt

from diagnostic_mcp.auth.errors import AuthenticationError

SERVICE_PRINCIPAL_SUBJECT = "pulse-service-principal"

# The 15-tool surface from [PRD] Appendix 1. Tools 1-8 (this repo, Work
# Item 2) plus 9-15 (W2 proper), named together so the minimum read-scope
# inventory (NFR-4 AC-1) is produced once against the full fleet rather
# than re-derived per work item.
TOOL_NAMES: tuple[str, ...] = (
    "list_factories",
    "get_plant_overview",
    "get_unit_detail",
    "get_current_scores",
    "explain_score",
    "get_parameter_history",
    "get_active_alerts",
    "get_compliance_status",
    "get_recent_events",
    "get_measurement_coverage",
    "get_kb_reference",
    "get_topology_path",
    "get_analytics",
    "compare_periods",
    "get_operations_context",
)

MINIMUM_READ_SCOPES: frozenset[str] = frozenset(f"lite.read:{name}" for name in TOOL_NAMES)


@dataclass(frozen=True)
class ServicePrincipalIdentity:
    subject: str
    scopes: frozenset[str]


def issue_service_token(
    secret: str,
    scopes: frozenset[str] = MINIMUM_READ_SCOPES,
    *,
    ttl_seconds: int = 3600,
) -> str:
    """Mint a service-principal token. Test/dev use only - production issuance
    is Lite's own token service, out of scope for this skeleton."""
    now = int(time.time())
    payload = {
        "sub": SERVICE_PRINCIPAL_SUBJECT,
        "scopes": sorted(scopes),
        "iat": now,
        "exp": now + ttl_seconds,
    }
    return jwt.encode(payload, secret, algorithm="HS256")


def verify_service_token(token: str, secret: str) -> ServicePrincipalIdentity:
    """Verify signature, expiry, and that every scope is read-only.

    Fails closed (NFR-4 AC-2/AC-4, TC-NFR-4.5): any verification problem
    raises AuthenticationError with no fallback to a cached or broader
    credential.
    """
    try:
        payload = jwt.decode(token, secret, algorithms=["HS256"])
    except jwt.PyJWTError as exc:
        raise AuthenticationError(f"Invalid service-principal token: {exc}") from exc

    scopes = frozenset(payload.get("scopes", []))
    if not scopes:
        raise AuthenticationError("Service-principal token carries no scopes.")

    write_scopes = {s for s in scopes if not s.startswith("lite.read:")}
    if write_scopes:
        raise AuthenticationError(
            f"Service-principal token carries non-read scope(s): {sorted(write_scopes)}"
        )

    subject = payload.get("sub")
    if not subject:
        raise AuthenticationError("Service-principal token missing subject.")

    return ServicePrincipalIdentity(subject=subject, scopes=scopes)
