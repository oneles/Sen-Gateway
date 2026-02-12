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
        Forwards the request to the configured model.
        Supports streaming if request.stream is True.
        """
        
        # Payload Cleanup: Sanitize messages
        messages = []
        for m in request.messages:
            msg_dict = m.model_dump(exclude_none=True)
            
            # Sanitization for Gemini and Bedrock
            if msg_dict.get("role") in ["tool", "function"]:
                content = msg_dict.get("content")
                if not isinstance(content, str):
                    try:
                        content_str = json.dumps(content)
                        # Remove problematic keywords
                        for forbidden in ["#/components/schemas/", "$ref", "ValidationError"]:
                            if forbidden in content_str:
                                content_str = content_str.replace(forbidden, f"CLEANED_{forbidden.replace('/', '_')}")
                        msg_dict["content"] = content_str
                    except:
                        msg_dict["content"] = str(content)
            
            messages.append(msg_dict)

        # Sanitize tools
        tools = None
        if request.tools:
            tools = []
            for t in request.tools:
                t_dict = t.model_dump(exclude_none=True)
                # Ensure 'parameters' exists
                if "function" in t_dict and "parameters" not in t_dict["function"]:
                    t_dict["function"]["parameters"] = {"type": "object", "properties": {}}
                
                # Bedrock specific: Descriptions cannot be empty strings for some models
                if "function" in t_dict and not t_dict["function"].get("description"):
                    t_dict["function"]["description"] = t_dict["function"]["name"]
                
                tools.append(t_dict)

        target_model = model_override if model_override else self.model_name
        
        # Clean up target_model: some users might send 'bedrock/global.anthropic...' 
        # which LiteLLM provider parsing might choke on if it sees 'global' as the provider.
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
        
        # Handle API key / Bedrock credentials
        effective_key = api_key or self.api_key
        if effective_key:
            if "bedrock" in target_model.lower():
                if ":" in effective_key:
                    parts = effective_key.split(":")
                    if len(parts) >= 3:
                        kwargs["aws_access_key_id"] = parts[0]
                        kwargs["aws_secret_access_key"] = parts[1]
                        kwargs["aws_region_name"] = parts[2]
                        print(f"DEBUG: Bedrock Credentials detected for region: {parts[2]}")
                # If no credentials found in key, litellm will use env vars
            else:
                kwargs["api_key"] = effective_key
                os.environ["GEMINI_API_KEY"] = effective_key
        
        # Handle Proxy
        proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
        if proxy_url:
            kwargs["proxy"] = proxy_url

        # Gemini Safety
        if "gemini" in target_model.lower():
            kwargs["safety_settings"] = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"}
            ]

        if request.stream:
            # For streaming, we also want usage
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

            # Ensure usage data is captured
            usage = None
            if hasattr(response, "usage") and response.usage:
                usage = dict(response.usage)

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
