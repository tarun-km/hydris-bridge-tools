"""Settings resolved only from environment variables - the managed-secret-
store seam (NFR-4 AC-3). No secret is ever hardcoded or read from a file
checked into the repo; a real deployment points these same env vars at
whatever the managed secret store injects.

`llm_api_key` is a separate seam (see diagnostic_mcp/providers/): it is
never read by the MCP server itself (the bridge has no model dependency,
EXT-4/PD-13), only by the generic-MCP-client demo agent in
examples/run_diagnostic_session.py that exercises the tools end to end.
"""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    service_token_secret: str
    user_context_secret: str
    audit_log_path: str
    host: str
    port: int

    @classmethod
    def from_env(cls) -> Settings:
        try:
            service_secret = os.environ["LITE_MCP_SERVICE_TOKEN_SECRET"]
            user_secret = os.environ["LITE_MCP_USER_CONTEXT_SECRET"]
        except KeyError as exc:
            raise RuntimeError(
                f"Missing required secret env var {exc}. See .env.example - in "
                "production these resolve from the managed secret store, never "
                "from a file in the image."
            ) from exc

        return cls(
            service_token_secret=service_secret,
            user_context_secret=user_secret,
            audit_log_path=os.environ.get("LITE_MCP_AUDIT_LOG_PATH", "./audit.jsonl"),
            host=os.environ.get("LITE_MCP_HOST", "127.0.0.1"),
            port=int(os.environ.get("LITE_MCP_PORT", "8765")),
        )
