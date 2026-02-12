import os
import litellm
import json
from .models import ChatCompletionRequest, ChatCompletionResponse, ChatCompletionResponseChoice, Message
from typing import List, Dict, Any, Union, AsyncGenerator

# Ensure LiteLLM maps requests correctly for Gemini
litellm.drop_params = True

class Brain:
    """
    Interfaces with powerful upstream models (Google Gemini, OpenAI, etc.).
    """

    def __init__(self, model_name: str = "gemini/gemini-1.5-flash", api_key: str = None):
        self.model_name = model_name
        self.api_key = api_key
        # If API key is provided, set it for LiteLLM
        if self.api_key:
            os.environ["GEMINI_API_KEY"] = self.api_key

    async def chat(self, request: ChatCompletionRequest, api_key: str = None, model_override: str = None) -> Union[ChatCompletionResponse, AsyncGenerator[Any, None]]:
        """
        Forwards the request to the configured model with Echo Retention & Cache Anchor logic.
        """
        target_model = model_override if model_override else self.model_name
        is_bedrock = "bedrock" in target_model.lower()

        # 1. Payload Cleanup & Cache Anchor Injection
        messages = []
        cache_ctrl = {"type": "ephemeral"} # Bedrock/Anthropic Cache Control

        for i, m in enumerate(request.messages):
            msg_dict = m.model_dump(exclude_none=True)
            
            # Sanitization
            if msg_dict.get("role") in ["tool", "function"]:
                content = msg_dict.get("content")
                if not isinstance(content, str):
                    msg_dict["content"] = json.dumps(content)
            
            # [Cache Anchor Logic] - As per "Містер Цицькослав" advice
            # Cache the history before the last 2 messages to maximize hits
            if is_bedrock and i == len(request.messages) - 3:
                if isinstance(msg_dict["content"], str):
                    msg_dict["content"] = [{"type": "text", "text": msg_dict["content"], "cache_control": cache_ctrl}]
                elif isinstance(msg_dict["content"], list) and len(msg_dict["content"]) > 0:
                    msg_dict["content"][-1]["cache_control"] = cache_ctrl

            messages.append(msg_dict)

        # 2. Sanitize & Cache Tools
        tools = None
        if request.tools:
            tools = []
            for i, t in enumerate(request.tools):
                t_dict = t.model_dump(exclude_none=True)
                if "function" in t_dict:
                    if "parameters" not in t_dict["function"]:
                        t_dict["function"]["parameters"] = {"type": "object", "properties": {}}
                    if not t_dict["function"].get("description"):
                        t_dict["function"]["description"] = t_dict["function"]["name"]
                    
                    # [Cache Anchor Logic] - Cache the last tool definition
                    if is_bedrock and i == len(request.tools) - 1:
                        t_dict["cache_control"] = cache_ctrl
                tools.append(t_dict)

        # 3. Target Model Normalization
        if target_model.startswith("bedrock/global."):
            target_model = target_model.replace("bedrock/global.", "bedrock/anthropic.", 1)

        kwargs = {
            "model": target_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": request.tool_choice if tools else None,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": request.stream
        }
        
        # 4. Handle Auth
        effective_key = api_key or self.api_key
        if effective_key:
            if is_bedrock and ":" in effective_key:
                parts = effective_key.split(":")
                if len(parts) >= 3:
                    kwargs["aws_access_key_id"] = parts[0]
                    kwargs["aws_secret_access_key"] = parts[1]
                    kwargs["aws_region_name"] = parts[2]
            else:
                kwargs["api_key"] = effective_key
                os.environ["GEMINI_API_KEY"] = effective_key
        
        if os.environ.get("https_proxy") or os.environ.get("http_proxy"):
            kwargs["proxy"] = os.environ.get("https_proxy") or os.environ.get("http_proxy")

        # 5. Model Specific Tweaks
        if "gemini" in target_model.lower():
            kwargs["safety_settings"] = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ]

        if request.stream:
            kwargs["stream_options"] = {"include_usage": True}
            return await litellm.acompletion(**kwargs)

        try:
            response = await litellm.acompletion(**kwargs)
            
            if not hasattr(response, "choices") or not response.choices:
                raise ValueError("Upstream model returned empty choices.")

            choice_data = response.choices[0]
            message_data = choice_data.message

            content = getattr(message_data, "content", "") or ""
            tool_calls = None
            if hasattr(message_data, "tool_calls") and message_data.tool_calls:
                tool_calls = [tc.model_dump() if hasattr(tc, "model_dump") else dict(tc) for tc in message_data.tool_calls]

            msg = Message(role=message_data.role, content=content, tool_calls=tool_calls)
            choice = ChatCompletionResponseChoice(
                index=choice_data.index,
                message=msg,
                finish_reason=choice_data.finish_reason or "stop"
            )

            usage = dict(response.usage) if hasattr(response, "usage") and response.usage else None

            return ChatCompletionResponse(
                id=response.id,
                created=response.created,
                model=response.model,
                choices=[choice],
                usage=usage
            )
        except Exception as e:
            print(f"Error calling upstream model: {e}")
            raise e
