import json
import re
from typing import List, Union, Dict, Any
from .models import Tool, Message
import logging

logger = logging.getLogger(__name__)

class BrowserPruner:
    @staticmethod
    def prune(content: str, lang: str = "en") -> str:
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "nodes" in data:
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
                    reason = "non_interactive_nodes" if lang == "en" else "非交互节点已隐藏"
                    preserved_nodes.append({
                        "_sys_hidden": True,
                        "reason": reason,
                        "omitted_count": omitted_count
                    })
                data["nodes"] = preserved_nodes
                return json.dumps(data, ensure_ascii=False)
            return content
        except Exception:
            return content

class ExecPruner:
    @staticmethod
    def prune(content: str, lang: str = "en") -> str:
        lines = content.splitlines()
        if len(lines) <= 30:
            return content
            
        head = lines[:10]
        tail = lines[-20:]
        middle = lines[10:-20]
        
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
            msg = f"--- [System Hidden: {omitted_count} lines of normal logs omitted. Context preserved.] ---" if lang == "en" else f"--- [系统已隐藏: 忽略了 {omitted_count} 行常规日志。保留关键上下文。] ---"
            pruned_middle.append(msg)
            
        return "\n".join(head + pruned_middle + tail)

class SearchPruner:
    @staticmethod
    def prune(content: str, lang: str = "en") -> str:
        try:
            data = json.loads(content)
            if isinstance(data, dict) and "items" in data:
                items = data.get("items", [])
                if len(items) > 5:
                    omitted = len(items) - 5
                    new_items = items[:5]
                    reason = "search_results_truncation" if lang == "en" else "搜索结果截断"
                    new_items.append({
                        "_sys_hidden": True,
                        "reason": reason,
                        "omitted_count": omitted
                    })
                    data["items"] = new_items
                return json.dumps(data, ensure_ascii=False)
        except Exception:
            pass
        return content

class JsonPruner:
    @staticmethod
    def prune(content: str, lang: str = "en") -> str:
        try:
            data = json.loads(content)
            data = JsonPruner._prune_obj(data, lang)
            return json.dumps(data, ensure_ascii=False, indent=2)
        except Exception:
            return content

    @staticmethod
    def _prune_obj(obj: Any, lang: str = "en") -> Any:
        if isinstance(obj, list):
            if len(obj) > 3:
                new_list = [JsonPruner._prune_obj(item, lang) for item in obj[:2]]
                reason = "array_truncation" if lang == "en" else "列表截断"
                hint = "Ask user to use pagination or specific filters if these items are needed." if lang == "en" else "如需更多项请要求翻页或使用特定过滤器。"
                new_list.append({
                    "_sys_hidden": True,
                    "reason": reason,
                    "omitted_count": len(obj) - 3,
                    "hint": hint
                })
                new_list.append(JsonPruner._prune_obj(obj[-1], lang))
                return new_list
            return [JsonPruner._prune_obj(item, lang) for item in obj]
        elif isinstance(obj, dict):
            new_dict = {}
            for k, v in obj.items():
                if isinstance(v, str) and len(v) > 500:
                    msg = "...[System Hidden: string truncated]" if lang == "en" else "...[系统已隐藏: 字符串过长已截断]"
                    new_dict[k] = v[:200] + msg
                else:
                    new_dict[k] = JsonPruner._prune_obj(v, lang)
            return new_dict
        return obj

class TextFallbackPruner:
    @staticmethod
    def prune(content: str, lang: str = "en") -> str:
        max_chars = 1500
        if not content or len(content) <= max_chars:
            return content
        head = content[:500]
        tail = content[-500:]
        omitted = len(content) - 1000
        msg = f"TextFallback, {omitted} chars omitted. Context preserved." if lang == "en" else f"文本回退，已隐藏 {omitted} 字符。保留上下文。"
        return f"{head}\n\n--- [System Hidden: {msg}] ---\n\n{tail}"


class SkillPruner:
    """
    Echo Retention (V5): Tool-Aware Pruning with Multi-Language Support
    """
    def __init__(self, lang: str = "en"):
        self.lang = lang
        logger.info(f"Echo Retention (V5) initialized: Tool-Aware Pruning Enabled (Language: {lang}).")

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
            new_content = BrowserPruner.prune(content, self.lang)
        elif tool_name in ["exec", "process"]:
            new_content = ExecPruner.prune(content, self.lang)
        elif tool_name in ["web_search", "web_fetch"]:
            new_content = SearchPruner.prune(content, self.lang)
        elif self._is_json(content):
            new_content = JsonPruner.prune(content, self.lang)
        else:
            new_content = TextFallbackPruner.prune(content, self.lang)

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