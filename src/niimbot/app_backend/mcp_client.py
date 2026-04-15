"""Thin MCP client for talking to the local niimbot server over stdio."""

from __future__ import annotations

import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


class NiimbotMCPClient:
    def __init__(self) -> None:
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def connect(self) -> None:
        if self._session is not None:
            return

        stack = AsyncExitStack()
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "niimbot.mcp.server"],
            env=os.environ.copy(),
        )
        read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await session.initialize()

        self._stack = stack
        self._session = session

    async def close(self) -> None:
        if self._stack is not None:
            await self._stack.aclose()
        self._stack = None
        self._session = None

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        await self.connect()
        assert self._session is not None
        result = await self._session.call_tool(name, arguments=arguments)
        if result.isError:
            text_chunks = []
            for item in result.content:
                text = getattr(item, "text", None)
                if text:
                    text_chunks.append(text)
            raise RuntimeError("\n".join(text_chunks) or f"MCP tool {name} failed")
        if result.structuredContent is not None:
            return result.structuredContent
        if len(result.content) == 1 and getattr(result.content[0], "text", None):
            raise RuntimeError(result.content[0].text)
        return {}
