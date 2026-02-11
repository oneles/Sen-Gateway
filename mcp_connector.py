import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from typing import List, Dict, Any
import logging

logger = logging.getLogger(__name__)

class MCPConnector:
    """
    Connects to various MCP Servers and handles tool discovery and execution.
    """
    def __init__(self):
        self.tools_cache = [] # List of all discovered tools
        self.server_sessions = {} # server_name -> session

    async def connect_to_server(self, name: str, command: str, args: List[str]):
        """Connect to a local MCP server via stdio"""
        server_params = StdioServerParameters(
            command=command,
            args=args,
            env=None
        )
        
        # This is a bit complex as mcp-python uses async context managers
        # In a real app, we'd need a background task to keep these alive
        logger.info(f"Connecting to MCP server: {name} via {command}")
        
        # For prototype, we'll implement a way to list tools once
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools_response = await session.list_tools()
                
                # Tag tools with their origin server
                for tool in tools_response.tools:
                    tool_data = {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": tool.inputSchema,
                        "origin_server": name
                    }
                    self.tools_cache.append(tool_data)
                
                logger.info(f"Discovered {len(tools_response.tools)} tools from {name}")

    def get_openai_tools(self, filtered_names: List[str] = None) -> List[Dict[str, Any]]:
        """
        Converts cached MCP tools to OpenAI format, optionally filtering by name.
        """
        openai_tools = []
        for tool in self.tools_cache:
            if filtered_names and tool["name"] not in filtered_names:
                continue
                
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool["name"],
                    "description": tool["description"],
                    "parameters": tool["input_schema"]
                }
            })
        return openai_tools
