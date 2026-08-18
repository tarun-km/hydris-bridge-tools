"""In-memory factory-grant store.

No caching: is_authorized() re-evaluates live state on every call, so a
revocation takes effect on the very next call rather than after some TTL
(BRIDGE-2 AC-3). This is the answer to open item O1 - see docs/decisions.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class ReadOnlyGrants(Protocol):
    """The view every tool handler actually needs (currently only
    list_factories' handler uses it at all, for O9). Deliberately omits
    `grant`/`revoke`: GrantStore below satisfies this protocol
    structurally, but typing ToolContext.grants as ReadOnlyGrants rather
    than GrantStore (see registry/pipeline.py) means a handler that tries
    to call `context.grants.grant(...)` or `.revoke(...)` - which would
    silently violate BRIDGE-1's read-only guarantee - fails a type check
    instead of quietly compiling.
    """

    def is_authorized(self, user_id: str, factory_id: str) -> bool: ...

    def granted_factories(self, user_id: str) -> frozenset[str]: ...


@dataclass
class GrantStore:
    _grants: dict[str, set[str]] = field(default_factory=dict)

    def grant(self, user_id: str, factory_id: str) -> None:
        self._grants.setdefault(user_id, set()).add(factory_id)

    def revoke(self, user_id: str, factory_id: str) -> None:
        self._grants.get(user_id, set()).discard(factory_id)

    def is_authorized(self, user_id: str, factory_id: str) -> bool:
        """True only if this user holds a live grant for this factory.

        Deliberately identical whether factory_id is unknown to the fleet
        or simply not granted to this user - see
        auth/errors.py:AuthorizationDenied and open item O3.
        """
        return factory_id in self._grants.get(user_id, set())

    def granted_factories(self, user_id: str) -> frozenset[str]:
        """Every factory this user currently holds a live grant for.

        The only place `list_factories` (O9) is allowed to read grant
        state from - it must never fall back to "everything the service
        token can read", which would widen access exactly the way BRIDGE-2
        forbids for every other tool.
        """
        return frozenset(self._grants.get(user_id, set()))


def seeded_grant_store() -> GrantStore:
    """The exact fixtures the source docs name: u-ops-alpha granted
    fx-mbr-01 only (org-alpha); u-ops-beta granted fx-beta-01 (org-beta) -
    the cross-tenant pair TC-BRIDGE-2.2 and TC-NFR-4.2 probe against.
    """
    store = GrantStore()
    store.grant("u-ops-alpha", "fx-mbr-01")
    store.grant("u-ops-beta", "fx-beta-01")
    return store
