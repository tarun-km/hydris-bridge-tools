"""The auth + authorization + audit pipeline - BRIDGE-2, BRIDGE-5 and
NFR-4 are all enforced right here, once, for every tool call.

Deliberately has no dependency on the MCP SDK or HTTP: it takes plain
headers and an arguments dict and returns a result or raises. server.py's
adapter is the only code that knows about FastMCP/streamable-HTTP, which
is what makes this function directly unit-testable (see tests/) and keeps
the auth logic stable across MCP SDK versions.

Decisions encoded here (see docs/decisions.md for the full writeup):
  O1 - no grant caching; every call re-checks live state, so revocation
       latency is effectively zero.
  O2 - an audit-sink failure fails the call closed rather than proceeding
       with a gap in the trail.
  O3 - one AuthorizationDenied for "no such factory" and "not granted".
  O9 - `list_factories` is the one documented tool that runs with
       requires_factory_scope=False (see registry/tool_registry.py). Its
       equivalent authorization guarantee is enforced here: the handler
       receives a ToolContext carrying a read-only view of live grant
       state (services/grants.py::ReadOnlyGrants) and must filter to the
       caller's own grants itself. The service token is never consulted
       for this decision either way.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError

from diagnostic_mcp.audit.models import AuditRecord, Outcome
from diagnostic_mcp.audit.sink import AuditSink, AuditSinkUnavailable
from diagnostic_mcp.auth.errors import AuthenticationError, AuthorizationDenied
from diagnostic_mcp.auth.service_principal import verify_service_token
from diagnostic_mcp.auth.user_context import verify_user_context_token
from diagnostic_mcp.registry.tool_registry import ToolSpec
from diagnostic_mcp.services.grants import ReadOnlyGrants

logger = logging.getLogger("diagnostic_mcp.audit")


@dataclass(frozen=True)
class ToolContext:
    """Passed to every handler alongside its validated arguments. Most
    handlers ignore it; it exists so a factory-scope-exempt tool
    (currently only list_factories) can still enforce a per-caller
    authorization decision itself, from live grant state, without the
    pipeline having to special-case that one tool's business logic.

    `grants` is typed as the read-only view (services/grants.py::
    ReadOnlyGrants), not the mutable GrantStore, on purpose: every one of
    the eight tools here is structurally read-only (BRIDGE-1), and handing
    every handler a store with public `grant`/`revoke` methods would be a
    foot-gun a future handler could exploit - by accident or otherwise -
    with nothing catching it. list_factories' handler only ever calls
    `is_authorized`/`granted_factories`, so it loses nothing.
    """

    user_id: str
    org_id: str
    pulse_session_id: str
    grants: ReadOnlyGrants


async def run_tool_call(
    *,
    headers: Mapping[str, str],
    raw_arguments: dict[str, Any],
    spec: ToolSpec,
    service_token_secret: str,
    user_context_secret: str,
    grants: ReadOnlyGrants,
    audit_sink: AuditSink,
) -> dict[str, Any]:
    start = time.monotonic()
    session_id = headers.get("x-pulse-session-id") or "unknown-session"
    user_id: str | None = None
    factory_id: str | None = None

    async def emit(outcome: Outcome, detail: str | None = None) -> None:
        record = AuditRecord(
            pulse_session_id=session_id,
            user_id=user_id,
            factory_id=factory_id,
            tool_name=spec.name,
            arguments=raw_arguments,
            outcome=outcome,
            latency_ms=(time.monotonic() - start) * 1000,
            detail=detail,
        )
        try:
            await audit_sink.write(record)
        except AuditSinkUnavailable:
            logger.critical(
                "audit sink unavailable, failing call closed (session=%s tool=%s)",
                session_id,
                spec.name,
            )
            raise

    # Identity 1: service principal. Independent of, and checked before, the
    # user's own grants (NFR-4). Fails closed on any invalid/expired token
    # or non-read-only scope - no fallback to a cached credential.
    auth_header = headers.get("authorization", "")
    service_token = auth_header[7:] if auth_header.lower().startswith("bearer ") else auth_header
    try:
        verify_service_token(service_token, service_token_secret)
    except AuthenticationError as exc:
        await emit("rejected", f"service_principal_invalid: {exc}")
        raise

    # Identity 2: the calling user, resolved independently of the service token.
    user_ctx_header = headers.get("x-pulse-user-context", "")
    try:
        user_identity = verify_user_context_token(user_ctx_header, user_context_secret)
    except AuthenticationError as exc:
        await emit("rejected", f"user_context_invalid: {exc}")
        raise
    user_id = user_identity.user_id

    # Argument validation happens in our own code (not left to the transport
    # layer) so that a bad-argument call is audit-logged just like any other
    # rejection (BRIDGE-5 AC-2), while BRIDGE-2 AC-1's "mandatory factory-scope
    # argument" is still enforced - just here, uniformly, for every tool that
    # requires one.
    try:
        args = spec.argument_model.model_validate(raw_arguments)
    except ValidationError as exc:
        await emit("rejected", f"bad_arguments: {exc.errors()!r}")
        raise

    if spec.requires_factory_scope:
        factory_id = getattr(args, "factory_id", None) or None

        # Per-call authorization, evaluated fresh every time (open item O1).
        # A missing factory_id and a not-granted factory_id get the identical
        # generic denial (open item O3) - the service token is never consulted
        # for this decision, so it can never widen access.
        if not factory_id or not grants.is_authorized(user_id, factory_id):
            await emit("rejected", "authorization_denied")
            raise AuthorizationDenied()
    # else: a factory-scope-exempt tool (O9). No single factory to check
    # here - the handler is responsible for filtering to this user's live
    # grants via the ToolContext below, which is the equivalent guarantee.

    context = ToolContext(
        user_id=user_id,
        org_id=user_identity.org_id,
        pulse_session_id=session_id,
        grants=grants,
    )

    try:
        result = await spec.handler(args, context)
    except BaseException as exc:
        # BaseException, not Exception: asyncio.CancelledError has derived
        # from BaseException (not Exception) since Python 3.8, and a
        # cancelled call - a client disconnect or a transport timeout
        # mid-handler - must still get an audit record. BRIDGE-5's "no
        # silent drops" applies to every outcome, not just the ones that
        # happen to subclass Exception; emit() re-raises on its own
        # failure, and the bare `raise` below preserves cancellation
        # semantics for the caller either way.
        await emit("error", str(exc))
        raise

    await emit("success")
    return result
