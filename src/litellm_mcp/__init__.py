def main() -> None:
    """Console-script entry point for the litellm-mcp server."""
    from .server import mcp

    mcp.run(transport="stdio")
