"""FastMCP server factory."""

from fastmcp import FastMCP

from .clients.emby_client import EmbyClient
from .clients.emby_database import EmbyDatabase
from .config import AppConfig


def create_server(
    config: AppConfig, client: EmbyClient, database: EmbyDatabase
) -> FastMCP:
    """Create and configure the FastMCP server with all tools."""
    mcp = FastMCP(
        "Emby MCP Server",
        instructions=(
            "Provides complete Emby management: server status, user management, "
            "library operations, media browsing, playlist management, "
            "database inspection and safety-gated writes, reporting, and diagnostics."
        ),
    )

    # Import and register tools — imports are deferred to avoid circular deps
    # and to allow tool modules to be added incrementally
    try:
        from .tools.server_tools import register_server_tools
        register_server_tools(mcp, client, config)
    except ImportError:
        pass

    try:
        from .tools.user_tools import register_user_tools
        register_user_tools(mcp, client)
    except ImportError:
        pass

    try:
        from .tools.library_tools import register_library_tools
        register_library_tools(mcp, client)
    except ImportError:
        pass

    try:
        from .tools.item_tools import register_item_tools
        register_item_tools(mcp, client)
    except ImportError:
        pass

    try:
        from .tools.playlist_tools import register_playlist_tools
        register_playlist_tools(mcp, client, database)
    except ImportError:
        pass

    try:
        from .tools.database_tools import register_database_tools
        register_database_tools(mcp, client, database, config)
    except ImportError:
        pass

    try:
        from .tools.reporting_tools import register_reporting_tools
        register_reporting_tools(mcp, client, database, config)
    except ImportError:
        pass

    try:
        from .tools.diagnostic_tools import register_diagnostic_tools
        register_diagnostic_tools(mcp, client, database, config)
    except ImportError:
        pass

    return mcp
