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
        
        # Payload Cleanup: Sanitize messages before sending to Gemini
        messages = []
        for m in request.messages:
            msg_dict = m.model_dump(exclude_none=True)
            
            # If it's a tool response, ensure content is a simple string or flattened JSON
            # This avoids #/components/schemas/ValidationError leaking back to Gemini
            if msg_dict.get("role") == "tool" or msg_dict.get("role") == "function":
                content = msg_dict.get("content")
                if not isinstance(content, str):
                    try:
                        # Convert complex content to string
                        content_str = json.dumps(content)
                        # Remove problematic keywords that trigger Gemini's strict schema checks
                        for forbidden in ["#/components/schemas/", "$ref", "ValidationError"]:
                            if forbidden in content_str:
                                content_str = content_str.replace(forbidden, f"CLEANED_{forbidden.replace('/', '_')}")
                        msg_dict["content"] = content_str
                    except:
                        msg_dict["content"] = str(content)
                elif isinstance(content, str):
                    # Even if it's already a string, check for problematic schemas
                    for forbidden in ["#/components/schemas/", "$ref", "ValidationError"]:
                        if forbidden in content:
                            msg_dict["content"] = content.replace(forbidden, f"CLEANED_{forbidden.replace('/', '_')}")
            
            messages.append(msg_dict)

        # Sanitize tools: ensure 'parameters' exists for Gemini compatibility
        tools = None
        if request.tools:
            tools = []
            for t in request.tools:
                t_dict = t.model_dump(exclude_none=True)
                # If function lacks parameters, inject empty object schema
                if "function" in t_dict and "parameters" not in t_dict["function"]:
                    t_dict["function"]["parameters"] = {"type": "object", "properties": {}}
                tools.append(t_dict)

        # Build kwargs dynamically
        # Use override if provided, else fall back to self.model_name
        target_model = model_override if model_override else self.model_name
        
        kwargs = {
            "model": target_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": request.tool_choice if tools else None,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": request.stream
        }
        
        # Explicitly pass API key if we have it
        effective_key = api_key or self.api_key
        if effective_key:
            if "bedrock" in target_model.lower():
                # Support AWS Keys in format: access_key:secret_key:region
                if ":" in effective_key:
                    parts = effective_key.split(":")
                    if len(parts) >= 3:
                        kwargs["aws_access_key_id"] = parts[0]
                        kwargs["aws_secret_access_key"] = parts[1]
                        kwargs["aws_region_name"] = parts[2]
                        print(f"DEBUG: Using AWS Bedrock credentials from key field (Region: {parts[2]})")
                    else:
                        kwargs["api_key"] = effective_key
                else:
                    kwargs["api_key"] = effective_key
            else:
                kwargs["api_key"] = effective_key
                # Also update environment variable to be safe, as litellm might fallback to it in some cases
                os.environ["GEMINI_API_KEY"] = effective_key
                print(f"DEBUG: Using API Key (first 5 chars): {effective_key[:5]}")
        else:
            print("DEBUG: No API Key provided to brain.chat!")

        # Explicitly handle Proxy from environment variables
        # This ensures LiteLLM respects the proxy even if underlying libraries don't auto-detect it
        proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
        if proxy_url:
            kwargs["proxy"] = proxy_url
            # For Gemini specifically, sometimes additional handling is needed, but "proxy" kwarg usually works
            print(f"DEBUG: Using Proxy: {proxy_url}")

        # Explicitly set safety settings for Gemini models to avoid empty responses (BLOCK_NONE)
        if "gemini" in target_model.lower():
            # LiteLLM format for safety settings
            kwargs["safety_settings"] = [
                {
                    "category": "HARM_CATEGORY_HARASSMENT",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_HATE_SPEECH",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_SEXUALLY_EXPLICIT",
                    "threshold": "BLOCK_NONE",
                },
                {
                    "category": "HARM_CATEGORY_DANGEROUS_CONTENT",
                    "threshold": "BLOCK_NONE",
                },
            ]

        if request.stream:
            return await litellm.acompletion(**kwargs)

        try:
            response = await litellm.acompletion(**kwargs)
            
            # Map LiteLLM response back to our simplified model if needed
            # LiteLLM already returns OpenAI-compatible objects mostly
            
            # Extract choice
            if not hasattr(response, "choices") or not response.choices:
                # Handle empty choices (e.g. content filtering or internal error)
                print(f"WARNING: Upstream model returned no choices. Response: {response}")
                raise ValueError("Upstream model returned empty choices (possibly due to safety filters or provider error).")

            choice_data = response.choices[0]
            message_data = choice_data.message

            # Safe extraction of content and tool calls
            # LiteLLM objects need to be converted to dicts/lists for Pydantic
            content = getattr(message_data, "content", None)
            if content is None:
                content = "" # Ensure it's a string, not None
                
            tool_calls = None
            if hasattr(message_data, "tool_calls") and message_data.tool_calls:
                # Force convert LiteLLM objects to plain dictionaries
                tool_calls = []
                for tc in message_data.tool_calls:
                    if hasattr(tc, "model_dump"):
                        tool_calls.append(tc.model_dump())
                    else:
                        # Fallback for older versions or dicts
                        tool_calls.append(dict(tc))

            # Construct our Message object
            msg = Message(
                role=message_data.role,
                content=content,
                tool_calls=tool_calls
            )

            choice = ChatCompletionResponseChoice(
                index=choice_data.index,
                message=msg,
                finish_reason=choice_data.finish_reason or "stop"
            )

            return ChatCompletionResponse(
                id=response.id,
                created=response.created,
                model=response.model,
                choices=[choice],
                usage=dict(response.usage) if response.usage else None
            )

        except Exception as e:
            # Handle API errors gracefully
            print(f"Error calling upstream model: {e}")
            raise e
