"""BRIDGE-5: per-call audit logging."""

from __future__ import annotations

import asyncio

import pytest
from pydantic import BaseModel, Field, ValidationError

from diagnostic_mcp.audit.sink import AuditSinkUnavailable, BrokenAuditSink
from diagnostic_mcp.auth.errors import AuthenticationError, AuthorizationDenied
from diagnostic_mcp.registry.pipeline import run_tool_call
from diagnostic_mcp.registry.tool_registry import ToolSpec

from .conftest import SERVICE_SECRET, USER_SECRET, headers_for

MANDATED_FIELDS = (
    "pulse_session_id",
    "user_id",
    "factory_id",
    "tool_name",
    "arguments",
    "latency_ms",
)


async def _call(registry, grants, audit_sink, headers, arguments):
    spec = registry.get("get_plant_overview")
    return await run_tool_call(
        headers=headers,
        raw_arguments=arguments,
        spec=spec,
        service_token_secret=SERVICE_SECRET,
        user_context_secret=USER_SECRET,
        grants=grants,
        audit_sink=audit_sink,
    )


class TestBridge5AuditLogging:
    async def test_tc_bridge_5_1_field_completeness_on_success(self, registry, grants, audit_sink):
        headers = headers_for("u-ops-alpha")
        await _call(registry, grants, audit_sink, headers, {"factory_id": "fx-mbr-01"})

        records = await audit_sink.query_by_session("sess-test-1")
        assert len(records) == 1
        record = records[0]
        for field_name in MANDATED_FIELDS:
            assert getattr(record, field_name) is not None
        assert record.outcome == "success"

    async def test_tc_bridge_5_2_auth_failure_and_bad_argument_both_logged_rejected(
        self, registry, grants, audit_sink
    ):
        with pytest.raises(AuthenticationError):
            await _call(
                registry,
                grants,
                audit_sink,
                {**headers_for("u-ops-alpha"), "authorization": "Bearer not-a-real-token"},
                {"factory_id": "fx-mbr-01"},
            )

        with pytest.raises(ValidationError):
            headers = headers_for("u-ops-alpha")
            await _call(registry, grants, audit_sink, headers, {"factory_id": ""})

        records = await audit_sink.query_by_session("sess-test-1")
        assert len(records) == 2
        assert all(r.outcome == "rejected" for r in records)

    async def test_tc_bridge_5_3_session_reconstructible_by_session_id(
        self, registry, grants, audit_sink
    ):
        headers = headers_for("u-ops-alpha")
        sequence = ("fx-mbr-01", "fx-mbr-01", "fx-beta-01")
        for factory_id in sequence:
            try:
                await _call(registry, grants, audit_sink, headers, {"factory_id": factory_id})
            except AuthorizationDenied:
                pass

        records = await audit_sink.query_by_session("sess-test-1")
        assert [r.factory_id for r in records] == list(sequence)
        assert [r.outcome for r in records] == ["success", "success", "rejected"]

    async def test_tc_bridge_5_4_sink_failure_fails_closed_not_silently_dropped(
        self, registry, grants
    ):
        with pytest.raises(AuditSinkUnavailable):
            headers = headers_for("u-ops-alpha")
            await _call(registry, grants, BrokenAuditSink(), headers, {"factory_id": "fx-mbr-01"})

    async def test_cancelled_call_still_gets_an_audit_record(self, registry, grants, audit_sink):
        """Regression guard for a review finding: asyncio.CancelledError
        has derived from BaseException (not Exception) since Python 3.8,
        so a handler cancelled mid-call - a client disconnect or a
        transport timeout - must still be caught by the pipeline's
        handler try/except, or BRIDGE-5's "no silent drops" guarantee
        breaks for exactly the outcome it exists to cover."""

        class _CancelledArgs(BaseModel):
            factory_id: str = Field(...)

        async def _cancelling_handler(args, context):
            raise asyncio.CancelledError()

        async def _noop_schema_fn(factory_id: str):
            raise NotImplementedError

        spec = ToolSpec(
            name="cancelling_tool",
            description="synthetic: simulates a cancelled call mid-handler",
            argument_model=_CancelledArgs,
            handler=_cancelling_handler,
            schema_fn=_noop_schema_fn,
        )

        with pytest.raises(asyncio.CancelledError):
            await run_tool_call(
                headers=headers_for("u-ops-alpha"),
                raw_arguments={"factory_id": "fx-mbr-01"},
                spec=spec,
                service_token_secret=SERVICE_SECRET,
                user_context_secret=USER_SECRET,
                grants=grants,
                audit_sink=audit_sink,
            )

        records = await audit_sink.query_by_session("sess-test-1")
        assert len(records) == 1
        assert records[0].outcome == "error"
        assert records[0].tool_name == "cancelling_tool"

    async def test_list_factories_success_still_audited_with_null_factory_id(
        self, registry, grants, audit_sink
    ):
        """O9: a factory-scope-exempt tool's success is still one audit
        record with the six mandated fields - factory_id is legitimately
        None here (there is no single factory scope), not a sign the
        record was skipped (BRIDGE-5 AC-1/AC-2)."""
        spec = registry.get("list_factories")
        await run_tool_call(
            headers=headers_for("u-ops-alpha"),
            raw_arguments={},
            spec=spec,
            service_token_secret=SERVICE_SECRET,
            user_context_secret=USER_SECRET,
            grants=grants,
            audit_sink=audit_sink,
        )
        records = await audit_sink.query_by_session("sess-test-1")
        assert len(records) == 1
        assert records[0].outcome == "success"
        assert records[0].factory_id is None
        assert records[0].user_id == "u-ops-alpha"
