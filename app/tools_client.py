import asyncio
import json
import os
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@asynccontextmanager
async def hospital_tools(emit):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "app.mcp_server"], env=dict(os.environ)
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            async def call(name, args):
                emit(
                    "mcp.call",
                    name,
                    {
                        "arguments": {k: v for k, v in args.items() if k != "session_id"},
                        "transport": "stdio",
                    },
                )
                async with asyncio.timeout(15):
                    result = await session.call_tool(name, args)
                if result.isError:
                    emit("mcp.error", name, {"error": "도구 실행 실패"})
                    raise RuntimeError("MCP 도구 실행 실패")
                data = result.structuredContent
                if data is None:
                    data = json.loads(next(c.text for c in result.content if c.type == "text"))
                emit("mcp.result", name, {"result": data})
                return data

            yield call
