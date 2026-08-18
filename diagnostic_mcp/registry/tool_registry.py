"""BRIDGE-1: the registry rejects registration of anything not classified
read-only - a structural fact enforced before a tool is ever reachable,
not merely a check on the call path (TC-BRIDGE-1.4). BRIDGE-2 AC-1 is
enforced here too: a tool whose argument model has no required
`factory_id` field is rejected at registration, not at call time -
*unless* it is one of the small, explicitly documented set of tools that
declare `requires_factory_scope=False` (see docs/decisions.md, "O9").

W1 shipped this gate as unconditional. Work Item 2 needed exactly one
exception: `list_factories`'s whole purpose is enumerating factories
*before* any one factory is chosen, so it structurally cannot declare a
mandatory single-factory argument (the W1 doc's own note flags this
tension and defers it to whoever designs the tool). Rather than weaken
the gate for everyone, `requires_factory_scope` makes the exemption an
explicit, reviewable, per-tool opt-out that still defaults to the
strict W1 behaviour.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel

if TYPE_CHECKING:
    from diagnostic_mcp.registry.pipeline import ToolContext


class NonReadOnlyToolRejected(Exception):
    def __init__(self, tool_name: str, classification: str) -> None:
        super().__init__(
            f"Tool '{tool_name}' rejected at registration: "
            f"classification '{classification}' is not 'read_only'."
        )


class MissingFactoryScope(Exception):
    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"Tool '{tool_name}' rejected at registration: argument_model has "
            "no required 'factory_id' field (BRIDGE-2 AC-1), and "
            "requires_factory_scope was not explicitly set to False."
        )


class UnreviewedFactoryScopeExemption(Exception):
    """Raised when a tool sets requires_factory_scope=False without being
    on FACTORY_SCOPE_EXEMPT_TOOLS below. Without this check, the exemption
    is enforced only by convention - nothing stops a future tool from
    opting out of BRIDGE-2's per-factory authorization gate without also
    replicating list_factories' discipline of filtering every result to
    the caller's live grants (see tools/list_factories.py, docs/decisions.md
    O9). Adding a tool here must be a deliberate, reviewed, one-line change,
    not a side effect of setting a flag on its own ToolSpec.
    """

    def __init__(self, tool_name: str) -> None:
        super().__init__(
            f"Tool '{tool_name}' rejected at registration: requires_factory_scope=False "
            f"but '{tool_name}' is not in FACTORY_SCOPE_EXEMPT_TOOLS. See O9 in "
            "docs/decisions.md - add it there deliberately if this exemption is reviewed "
            "and intentional."
        )


# The only tools ever allowed to skip BRIDGE-2's mandatory factory-scope
# gate (O9, docs/decisions.md). Extending this set is itself the review
# gate: a PR that adds a name here is a PR that must show the new tool's
# handler filters to the caller's live grants the same way
# list_factories.py does.
FACTORY_SCOPE_EXEMPT_TOOLS: frozenset[str] = frozenset({"list_factories"})


@dataclass(frozen=True)
class ToolSpec:
    """`schema_fn` exists purely so FastMCP can introspect a real Python
    signature for `tools/list` (see server.py); it is never invoked -
    ToolRegistry.dispatch (via registry/pipeline.py) owns the actual call.
    """

    name: str
    description: str
    argument_model: type[BaseModel]
    # Typed as `Any` rather than the specific argument_model: each ToolSpec's
    # handler only ever receives an instance of its own argument_model (the
    # registry dispatches by construction), but the dataclass is shared
    # across tools with heterogeneous argument types, so a single covariant
    # signature can't be expressed without per-tool generics.
    handler: Callable[[Any, ToolContext], Awaitable[dict[str, Any]]]
    schema_fn: Callable[..., Awaitable[Any]]
    classification: Literal["read_only"] = "read_only"
    # BRIDGE-2 AC-1 default. False only for the documented, reviewed
    # exception (list_factories) - see the module docstring and O9.
    requires_factory_scope: bool = True


class ToolRegistry:
    """Register-time gate. See registry/pipeline.py for the call-time gate."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        if spec.classification != "read_only":
            raise NonReadOnlyToolRejected(spec.name, spec.classification)

        if spec.requires_factory_scope:
            factory_field = spec.argument_model.model_fields.get("factory_id")
            if factory_field is None or not factory_field.is_required():
                raise MissingFactoryScope(spec.name)
        elif spec.name not in FACTORY_SCOPE_EXEMPT_TOOLS:
            raise UnreviewedFactoryScopeExemption(spec.name)

        self._tools[spec.name] = spec

    def get(self, name: str) -> ToolSpec | None:
        return self._tools.get(name)

    def __iter__(self):
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)
