import os

# Long enough to avoid PyJWT's InsecureKeyLengthWarning (>= 32 bytes), and
# set before diagnostic_mcp is imported anywhere so Settings.from_env() has
# something to read if a test exercises it.
os.environ.setdefault("LITE_MCP_SERVICE_TOKEN_SECRET", "test-service-secret-0123456789abcdef")
os.environ.setdefault("LITE_MCP_USER_CONTEXT_SECRET", "test-user-context-secret-0123456789ab")

import pytest

from diagnostic_mcp.audit.sink import InMemoryAuditSink
from diagnostic_mcp.auth.service_principal import issue_service_token
from diagnostic_mcp.auth.user_context import issue_user_context_token
from diagnostic_mcp.server import build_registry
from diagnostic_mcp.services.grants import seeded_grant_store

SERVICE_SECRET = os.environ["LITE_MCP_SERVICE_TOKEN_SECRET"]
USER_SECRET = os.environ["LITE_MCP_USER_CONTEXT_SECRET"]

DEFAULT_SESSION_ID = "sess-test-1"


def headers_for(
    user_id: str,
    org_id: str = "org-alpha",
    session_id: str = DEFAULT_SESSION_ID,
    service_token_override: str | None = None,
) -> dict[str, str]:
    return {
        "authorization": f"Bearer {service_token_override or issue_service_token(SERVICE_SECRET)}",
        "x-pulse-user-context": issue_user_context_token(USER_SECRET, user_id, org_id),
        "x-pulse-session-id": session_id,
    }


@pytest.fixture
def grants():
    return seeded_grant_store()


@pytest.fixture
def audit_sink():
    return InMemoryAuditSink()


@pytest.fixture
def registry():
    return build_registry()
