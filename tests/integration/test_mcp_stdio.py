"""Stdio MCP server. This opens a real subprocess and talks MCP, not a direct function call."""

from food_copilot.agents.mcp_host import McpHost


def test_stdio_server_discovers_tools_and_searches():
    host = McpHost()
    host.start(timeout=60)
    try:
        assert host.status == "connected", host.error
        assert "search_restaurants" in host.tool_names
        assert "get_restaurant_reviews" in host.tool_names
        found = host.call("search_restaurants", {"query": "kfc in old klang road", "name_contains": "kfc"})
        assert found.get("ok") is True
        assert found.get("eligible_restaurant_ids")
        empty = host.call("get_restaurant_reviews", {"restaurant_id": "not-a-real-id"})
        assert empty.get("ok") is True
        assert empty.get("reviews") == []
    finally:
        host.stop()
