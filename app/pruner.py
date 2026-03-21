import json
import re
from typing import List, Union, Dict, Any
from .models import Tool, Message
import logging

logger = logging.getLogger(__name__)

class BrowserPruner:
    @staticmethod
    def prune(content: str) -> str:
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "nodes" in data:
                # Assuming it's a UI tree structure
                interactive_roles = {"button", "link", "input", "textbox", "checkbox", "radio"}
                preserved_nodes = []
                omitted_count = 0
                for node in data.get("nodes", []):
                    role = node.get("role", "")
                    has_ref = "ref" in node
                    if has_ref or role in interactive_roles:
                        preserved_nodes.append(node)
                    else:
                        omitted_count += 1
                
                if omitted_count > 0:
                    preserved_nodes.append({
                        "_sys_hidden": True,
                        "reason": "non_interactive_nodes",
                        "omitted_count": omitted_count
                    })
                data["nodes"] = preserved_nodes
                return json.dumps(data, ensure_ascii=False)
            return content
        except Exception:
            return content

class ExecPruner:
    @staticmethod
    def prune(content: str) -> str:
        lines = content.splitlines()
        if len(lines) <= 30:
            return content
            
        head = lines[:10]
        tail = lines[-20:]
        middle = lines[10:-20]
        
        # Extract keyword lines from middle
        keywords = ["error", "warning", "exception", "failed"]
        key_lines = []
        omitted_count = 0
        
        for line in middle:
            if any(k in line.lower() for k in keywords):
                key_lines.append(line)
            else:
                omitted_count += 1
                
        pruned_middle = key_lines
        if omitted_count > 0:
            pruned_middle.append(f"--- [System Hidden: {omitted_count} lines of normal logs omitted. Context preserved.] ---")
            
        return "\n".join(head + pruned_middle + tail)

class SearchPruner:
    @staticmethod
    def prune(content: str) -> str:
        # Assuming web_search might be JSON or structured text
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "items" in data:
                items = data.get("items", [])
                if len(items) > 5:
                    omitted = len(items) - 5
                    new_items = items[:5]
                    new_items.append({
                        "_sys_hidden": True,
                        "reason": "search_results_truncation",
                        "omitted_count": omitted
                    })
                    data["items"] = new_items
                return json.dumps(data, ensure_ascii=False)
        except Exception:
            pass
        return content

class JsonPruner:
    @staticmethod
    def prune(content: str) -> str:
        try:
            data = json.loads(content)
            data = JsonPruner._prune_obj(data)
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            return content

    @staticmethod
    def _prune_obj(obj: Any) -> Any:
        if isinstance(obj, list):
            if len(obj) > 3:
                new_list = [JsonPruner._prune_obj(item) for item in obj[:2]]
                new_list.append({
                    "_sys_hidden": True,
                    "reason": "array_truncation",
                    "omitted_count": len(obj) - 3,
                    "hint": "Ask user to use pagination or specific filters if these items are needed."
                })
                new_list.append(JsonPruner._prune_obj(obj[-1]))
                return new_list
            return [JsonPruner._prune_obj(item) for item in obj]
        elif isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                if isinstance(v, str) and len(v) > 500:
                    new_dict[k] = v[:200] + "...[System Hidden: string truncated]"
                else:
                    new_dict[k] = JsonPruner._prune_obj(v)
            return new_dict
        return obj

class TextFallbackPruner:
    @staticmethod
    def prune(content: str) -> str:
        max_chars = 1500
        if not content or len(content) <= max_chars:
            return content
        head = content[:500]
        tail = content[-500:]
        omitted = len(content) - 1000
        return f"{head}\n\n--- [System Hidden: TextFallback, {omitted} chars omitted. Context preserved.] ---\n\n{tail}"


class SkillPruner:
    """
    Echo Retention (V5): Tool-Aware Pruning
    """
    def __init__(self, qmd_path: str = None):
        self.qmd_path = qmd_path
        logger.info("Echo Retention (V5) initialized: Tool-Aware Pruning Enabled.")

    def _is_json(self, content: str) -> bool:
        if not content: return False
        content = content.strip()
        if (content.startswith("{") and content.endswith("}")) or (content.startswith("[") and content.endswith("]")):
            try:
                json.loads(content)
                return True
            except:
                return False
        return False

    def compress_tool_message(self, message: Message) -> Message:
        if message.role != "tool":
            return message
            
        tool_name = message.name
        content = message.content
        if not isinstance(content, str):
            return message

        if tool_name in ["browser.snapshot", "browser.act", "browser"]:
            new_content = BrowserPruner.prune(content)
        elif tool_name in ["exec", "process"]:
            new_content = ExecPruner.prune(content)
        elif tool_name in ["web_search", "web_fetch"]:
            new_content = SearchPruner.prune(content)
        elif self._is_json(content):
            new_content = JsonPruner.prune(content)
        else:
            new_content = TextFallbackPruner.prune(content)

        return Message(
            role=message.role,
            content=new_content,
            tool_calls=message.tool_calls,
            tool_call_id=message.tool_call_id,
            name=message.name
        )

    async def prune_messages(self, messages: List[Message], keep_last: int = 15) -> List[Message]:
        if len(messages) <= keep_last:
            return messages

        sys_end_idx = 0
        for i, m in enumerate(messages):
            if m.role == "system":
                sys_end_idx = i + 1
        
        static_prefix = messages[:sys_end_idx]
        dynamic_history = messages[sys_end_idx:-keep_last]
        recent_context = messages[-keep_last:]
        
        compressed_history = []
        for msg in dynamic_history:
            if msg.role == "tool" and isinstance(msg.content, str) and len(msg.content) > 300:
                compressed_msg = self.compress_tool_message(msg)
            else:
                compressed_msg = Message(
                    role=msg.role,
                    content=msg.content,
                    tool_calls=msg.tool_calls,
                    tool_call_id=msg.tool_call_id,
                    name=msg.name
                )
            compressed_history.append(compressed_msg)

        final = static_prefix + compressed_history + recent_context
        logger.info(f"V5 Compression: {len(messages)} -> {len(final)} msgs. Tool-aware pruning applied.")
        return final