"""Auth error types.

AuthorizationDenied is deliberately a single, generic error used for both
"the factory does not exist" and "the user is not granted this factory" -
the two must be indistinguishable to the caller (BRIDGE-2 TC-2.2, open
item O3 in docs/decisions.md). Never add a second, more specific error for
the "does not exist" case: that would recreate the leak this type exists
to prevent.
"""

from __future__ import annotations


class AuthenticationError(Exception):
    """A service-principal or user-context token failed to verify.

    Covers missing/invalid signature, expiry, and (for the service
    principal) any non-read-only scope. There is no fallback path: every
    caller of verify_* must treat this as a hard failure (NFR-4 AC-2/AC-4).
    """


class AuthorizationDenied(Exception):
    """The caller is not authorized to access the requested factory."""

    def __init__(self) -> None:
        super().__init__("Not authorized for the requested factory.")
