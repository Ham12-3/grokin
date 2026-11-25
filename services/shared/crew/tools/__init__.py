"""Tool registry and tool implementations."""

from crew.tools.files import make_file_tools
from crew.tools.net import Resolver, system_resolver
from crew.tools.registry import ToolRegistry
from crew.tools.web import make_web_fetch, make_web_search


def default_registry(resolver: Resolver = system_resolver) -> ToolRegistry:
    """The tools every Bot has in this phase."""
    registry = ToolRegistry()
    registry.register(make_web_search())
    registry.register(make_web_fetch(resolver))
    for tool in make_file_tools():
        registry.register(tool)
    return registry


__all__ = ["default_registry"]
