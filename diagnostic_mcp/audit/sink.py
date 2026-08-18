"""Audit sinks. AuditSinkUnavailable is how a sink signals it could not
durably persist a record; the pipeline (registry/pipeline.py) treats that
as fail-closed - the tool call fails rather than proceeding with a gap in
the audit trail (open item O2, TC-BRIDGE-5.4)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from diagnostic_mcp.audit.models import AuditRecord


class AuditSinkUnavailable(Exception):
    """The sink could not persist a record. Fail-closed, not silently dropped."""


class AuditSink(Protocol):
    async def write(self, record: AuditRecord) -> None: ...

    async def query_by_session(self, pulse_session_id: str) -> list[AuditRecord]: ...


class FileAuditSink:
    """Append-only JSONL sink. Local/dev default - a real Lite deployment
    swaps this for its own audit store; see docs/scope.md."""

    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)

    async def write(self, record: AuditRecord) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as f:
                f.write(record.model_dump_json() + "\n")
        except OSError as exc:
            raise AuditSinkUnavailable(str(exc)) from exc

    async def query_by_session(self, pulse_session_id: str) -> list[AuditRecord]:
        if not self._path.exists():
            return []
        records: list[AuditRecord] = []
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                record = AuditRecord.model_validate_json(line)
                if record.pulse_session_id == pulse_session_id:
                    records.append(record)
        return records


class InMemoryAuditSink:
    """Test double. Also the basis for BrokenAuditSink below."""

    def __init__(self) -> None:
        self.records: list[AuditRecord] = []

    async def write(self, record: AuditRecord) -> None:
        self.records.append(record)

    async def query_by_session(self, pulse_session_id: str) -> list[AuditRecord]:
        return [r for r in self.records if r.pulse_session_id == pulse_session_id]


class BrokenAuditSink:
    """Always fails. Used to prove fail-closed behaviour (TC-BRIDGE-5.4)."""

    async def write(self, record: AuditRecord) -> None:
        raise AuditSinkUnavailable("simulated audit sink outage")

    async def query_by_session(self, pulse_session_id: str) -> list[AuditRecord]:
        raise AuditSinkUnavailable("simulated audit sink outage")
