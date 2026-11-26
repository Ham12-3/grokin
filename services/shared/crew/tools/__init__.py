"""Tool registry and tool implementations."""

from crew.tools.browser import make_browser_tools, make_takeover_tool
from crew.tools.files import make_file_tools
from crew.tools.handoff import make_handoff_tool
from crew.tools.library import make_library_tool
from crew.tools.memory import make_memory_tools
from crew.tools.net import Resolver, system_resolver
from crew.tools.registry import ToolRegistry
from crew.tools.skills import make_skill_tool
from crew.tools.terminal import make_terminal_tool
from crew.tools.web import make_web_fetch, make_web_search


def default_registry(resolver: Resolver = system_resolver) -> ToolRegistry:
    """The tools every Bot has. App tools are added per Bot: `connectors.registry_for_bot`."""
    registry = ToolRegistry()
    registry.register(make_web_search())
    registry.register(make_web_fetch(resolver))
    for tool in make_file_tools():
        registry.register(tool)
    registry.register(make_terminal_tool())
    for tool in make_browser_tools(resolver):
        registry.register(tool)
    registry.register(make_takeover_tool())
    for tool in make_memory_tools():
        registry.register(tool)
    registry.register(make_skill_tool())
    registry.register(make_library_tool())
    registry.register(make_handoff_tool())
    return registry


__all__ = ["default_registry"]
