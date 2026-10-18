"""One MCP session for the process. Tools are discovered, then called over the MCP protocol."""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

from food_copilot.config.settings import ROOT

logger = logging.getLogger("food_copilot.mcp")


def _payload(result) -> dict:
    import json

    if getattr(result, "structuredContent", None):
        content = result.structuredContent
        return content if isinstance(content, dict) else {"ok": True, "value": content}
    blocks = getattr(result, "content", None) or []
    if blocks and getattr(blocks[0], "text", None):
        parsed = json.loads(blocks[0].text)
        return parsed if isinstance(parsed, dict) else {"ok": True, "value": parsed}
    raise RuntimeError("The MCP tool returned no content")


class MemoryMcp:
    """In-memory MCP client and server. Calls still go through a client session."""

    def __init__(self, server):
        self.server = server
        self.status = "connected"
        self.error = ""
        self.tool_names = self._list()

    def _list(self) -> list[str]:
        async def run():
            from mcp.shared.memory import create_connected_server_and_client_session

            async with create_connected_server_and_client_session(self.server._mcp_server) as session:
                listed = await session.list_tools()
                return [tool.name for tool in listed.tools]

        return asyncio.run(run())

    def call(self, name: str, arguments: dict) -> dict:
        from food_copilot.agents.mcp_client import mcp_call

        if name not in self.tool_names:
            return {"ok": False, "error": "tool_not_discovered", "tool": name}
        return mcp_call(name, arguments, server=self.server)


class McpHost:
    """Stdio subprocess. start() is idempotent. stop() closes the session and the process."""

    def __init__(self):
        self.status = "disconnected"
        self.error = ""
        self.tool_names: list[str] = []
        self._loop = None
        self._thread = None
        self._session = None
        self._stopped = None
        self._ready = threading.Event()
        self._lock = threading.Lock()

    def start(self, timeout: float = 40) -> None:
        with self._lock:
            if self.status == "connected":
                return
            if self._thread and self._thread.is_alive():
                return
            self._ready.clear()
            self.error = ""
            self._thread = threading.Thread(target=self._thread_main, name="mcp-host", daemon=True)
            self._thread.start()
        if not self._ready.wait(timeout):
            self.status = "disconnected"
            self.error = self.error or "startup_timeout"
            logger.error("mcp startup did not finish: %s", self.error)
            return
        if self.status != "connected":
            logger.error("mcp disconnected: %s", self.error or "unknown")

    def _thread_main(self) -> None:
        try:
            asyncio.run(self._serve())
        except Exception as exc:
            self.status = "disconnected"
            self.error = exc.__class__.__name__
            logger.exception("mcp host stopped")
            self._ready.set()

    async def _serve(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        self._loop = asyncio.get_running_loop()
        self._stopped = asyncio.Event()
        script = Path(ROOT) / "scripts" / "mcp_server.py"
        params = StdioServerParameters(
            command=sys.executable,
            args=[str(script)],
            cwd=str(ROOT),
            env=os.environ.copy(),
        )
        try:
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    self._session = session
                    self.tool_names = [tool.name for tool in listed.tools]
                    self.status = "connected"
                    self.error = ""
                    logger.info("mcp connected tools=%s", ",".join(self.tool_names))
                    self._ready.set()
                    await self._stopped.wait()
        except Exception as exc:
            self.status = "disconnected"
            self.error = exc.__class__.__name__
            logger.exception("mcp session failed")
        finally:
            self._session = None
            if self.status == "connected":
                self.status = "disconnected"
            self._ready.set()

    def call(self, name: str, arguments: dict) -> dict:
        if self.status != "connected" or self._session is None or self._loop is None:
            return {"ok": False, "error": "mcp_disconnected", "detail": self.error or "not connected", "tool": name}
        if name not in self.tool_names:
            return {"ok": False, "error": "tool_not_discovered", "tool": name, "discovered": self.tool_names}

        async def _call():
            result = await self._session.call_tool(name, arguments or {})
            if result.isError:
                return {"ok": False, "error": "tool_failed", "tool": name}
            return _payload(result)

        future = asyncio.run_coroutine_threadsafe(_call(), self._loop)
        try:
            return future.result(timeout=25)
        except Exception as exc:
            logger.exception("mcp tool %s failed", name)
            return {"ok": False, "error": exc.__class__.__name__, "tool": name}

    def stop(self) -> None:
        loop = self._loop
        stopped = self._stopped
        if loop is not None and stopped is not None and loop.is_running():
            loop.call_soon_threadsafe(stopped.set)
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=5)
        self.status = "disconnected"
        self._session = None


_HOST = McpHost()


def current_host() -> McpHost:
    return _HOST
