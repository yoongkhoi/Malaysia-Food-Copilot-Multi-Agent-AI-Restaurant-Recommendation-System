"""Call the existing in-process MCP server. This does not open a browser connection."""

import asyncio
import json

from food_copilot.mcp.server import build_mcp_server


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structuredContent
    content = getattr(result, "content", None) or []
    if content and getattr(content[0], "text", None):
        return json.loads(content[0].text)
    raise RuntimeError("The MCP tool returned no content")


async def _call(server, name: str, arguments: dict) -> dict:
    from mcp.shared.memory import create_connected_server_and_client_session

    async with create_connected_server_and_client_session(server._mcp_server) as session:
        result = await session.call_tool(name, arguments)
        if result.isError:
            return {"ok": False, "error": "tool_failed"}
        return _payload(result)


def mcp_call(name: str, arguments: dict, server=None) -> dict:
    target = server or build_mcp_server()

    async def limited():
        return await asyncio.wait_for(_call(target, name, arguments), timeout=20)

    return asyncio.run(limited())
