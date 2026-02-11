from typing import List
from models import Tool, Message
import logging

logger = logging.getLogger(__name__)

class SkillPruner:
    """
    QWD Context Compressor (V3):
    Focuses EXCLUSIVELY on compressing conversation history to save tokens.
    Tool pruning is REMOVED to maximize Prefix Caching hit rates.
    """

    def __init__(self, qmd_path: str = None):
        self.qmd_path = qmd_path
        logger.info("Echo Retention (V3) initialized (Tool Pruning Disabled).")

    async def prune_messages(self, messages: List[Message], keep_last: int = 15) -> List[Message]:
        """
        Smart History Compression:
        - Keeps System Prompt intact (Cache Anchor).
        - Keeps last N messages intact (Short-term Memory).
        - Compresses old messages (Long-term Memory) using rule-based summaries.
        """
        if len(messages) <= keep_last:
            return messages

        # 1. Identify segments
        # Find the last system message index to keep prefix intact
        sys_end_idx = 0
        for i, m in enumerate(messages):
            if m.role == "system":
                sys_end_idx = i + 1
        
        # Safe slicing
        static_prefix = messages[:sys_end_idx]
        dynamic_history = messages[sys_end_idx:-keep_last]
        recent_context = messages[-keep_last:]
        
        if not dynamic_history:
            return messages

        compressed_history = []
        
        for msg in dynamic_history:
            new_content = msg.content
            
            # STRATEGY: Smart Summarization based on Role
            
            # A. Compress Tool Outputs (The biggest token hogs)
            if msg.role == "tool" and isinstance(new_content, str):
                if len(new_content) > 300:
                    # Smart Summary Logic
                    head = new_content[:150]
                    tail = new_content[-150:]
                    
                    summary_marker = f"\n... [System: Output compressed. Original: {len(msg.content)} chars. Showing Head/Tail] ...\n"
                    new_content = head + summary_marker + tail
            
            # B. Compress Assistant Code Blocks - REMOVED per user request
            # elif msg.role == "assistant" and isinstance(new_content, str):
            #     if len(new_content) > 1500:
            #         # Keep thought process, cut huge code dumps
            #         new_content = new_content[:500] + f"\n... [System: Historical response truncated for brevity] ..."

            # Reconstruct
            compressed_msg = Message(
                role=msg.role,
                content=new_content,
                tool_calls=msg.tool_calls,
                tool_call_id=msg.tool_call_id,
                name=msg.name
            )
            compressed_history.append(compressed_msg)

        final = static_prefix + compressed_history + recent_context
        
        logger.info(f"Context Compression: {len(messages)} msgs. Compressed {len(dynamic_history)} old items.")
        return final
