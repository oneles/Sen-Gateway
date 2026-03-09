import os
import litellm

def _sanitize_json_schema(schema):
    if isinstance(schema, dict):
        schema.pop("patternProperties", None)
        schema.pop("additionalProperties", None)
        for k, v in schema.items():
            schema[k] = _sanitize_json_schema(v)
    elif isinstance(schema, list):
        for i in range(len(schema)):
            schema[i] = _sanitize_json_schema(schema[i])
    return schema

import json
import time
import boto3
import logging
from .models import (
    ChatCompletionRequest, ChatCompletionResponse,
    ChatCompletionResponseChoice, Message
)
from typing import List, Dict, Any, Union, AsyncGenerator

litellm.drop_params = True
logger = logging.getLogger(__name__)


def _convert_messages_for_messages_api(messages: list) -> tuple:
    """
    Convert OpenAI-format messages to Anthropic Messages API format.
    Returns (system_blocks, api_messages).
    """
    system_blocks = []
    api_messages = []

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content")
        tool_calls = msg.get("tool_calls")
        tool_call_id = msg.get("tool_call_id")

        if role == "system":
            if isinstance(content, str):
                system_blocks.append({"type": "text", "text": content})
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        system_blocks.append({"type": "text", "text": block["text"]})
            continue

        if role == "tool":
            result_content = content
            if isinstance(result_content, dict):
                result_content = json.dumps(result_content)
            elif not isinstance(result_content, str):
                result_content = str(result_content)

            api_messages.append({
                "role": "user",
                "content": [{
                    "type": "tool_result",
                    "tool_use_id": tool_call_id or "unknown",
                    "content": result_content
                }]
            })
            continue

        # Regular user/assistant message
        msg_content = []

        if isinstance(content, str) and content.strip():
            msg_content.append({"type": "text", "text": content})
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    if block.get("type") == "text" and block.get("text", "").strip():
                        msg_content.append({"type": "text", "text": block["text"]})

        # Tool calls from assistant
        if role == "assistant" and tool_calls:
            for tc in tool_calls:
                func = tc.get("function", {})
                args_str = func.get("arguments", "{}")
                try:
                    args_json = json.loads(args_str) if isinstance(args_str, str) else args_str
                except (json.JSONDecodeError, TypeError):
                    args_json = {"raw": str(args_str)}

                msg_content.append({
                    "type": "tool_use",
                    "id": tc.get("id", f"call_{int(time.time())}"),
                    "name": func.get("name", "unknown"),
                    "input": args_json
                })

        if not msg_content:
            msg_content.append({"type": "text", "text": "."})

        api_role = "assistant" if role == "assistant" else "user"
        api_messages.append({
            "role": api_role,
            "content": msg_content
        })

    # Merge consecutive same-role messages
    fixed = []
    for msg in api_messages:
        if fixed and fixed[-1]["role"] == msg["role"]:
            fixed[-1]["content"].extend(msg["content"])
        else:
            fixed.append(msg)

    # Ensure first message is from user
    if fixed and fixed[0]["role"] != "user":
        fixed.insert(0, {"role": "user", "content": [{"type": "text", "text": "."}]})

    return system_blocks, fixed


def _convert_tools_for_messages_api(tools: list) -> list:
    """Convert OpenAI-format tools to Anthropic Messages API format."""
    if not tools:
        return []

    api_tools = []
    for t in tools:
        if isinstance(t, dict):
            func = t.get("function", {})
        elif hasattr(t, "model_dump"):
            func = t.model_dump().get("function", {})
        else:
            continue

        name = func.get("name", "unknown")
        description = func.get("description", "")
        parameters = func.get("parameters", {"type": "object", "properties": {}})

        if "type" not in parameters:
            parameters["type"] = "object"
        if "properties" not in parameters:
            parameters["properties"] = {}

        api_tools.append({
            "name": name,
            "description": description or f"Tool: {name}",
            "input_schema": parameters
        })

    return api_tools


def _add_cache_control(system_blocks: list, messages: list, tools: list):
    """Add cache_control markers for prompt caching with 1 hour TTL."""
    cache_ctrl = {"type": "ephemeral", "ttl": "1h"}
    
    # Last system block
    if system_blocks:
        system_blocks[-1]["cache_control"] = cache_ctrl

    # Last tool definition
    if tools:
        tools[-1]["cache_control"] = cache_ctrl

    # Last content block before the final 2 messages
    if len(messages) > 2:
        target_msg = messages[-3]  # the message just before the last 2
        if target_msg.get("content"):
            target_msg["content"][-1]["cache_control"] = cache_ctrl


def _parse_messages_api_response(response: dict, model: str) -> ChatCompletionResponse:
    """Parse Anthropic Messages API response into OpenAI format."""
    content_blocks = response.get("content", [])
    stop_reason = response.get("stop_reason", "end_turn")
    usage_data = response.get("usage", {})

    text_parts = []
    tool_calls = []

    for block in content_blocks:
        if block.get("type") == "text":
            text_parts.append(block["text"])
        elif block.get("type") == "tool_use":
            tool_calls.append({
                "id": block.get("id", f"call_{int(time.time())}"),
                "type": "function",
                "function": {
                    "name": block.get("name", "unknown"),
                    "arguments": json.dumps(block.get("input", {}))
                }
            })

    finish_reason_map = {
        "end_turn": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
        "stop_sequence": "stop",
    }

    content = "\n".join(text_parts) if text_parts else ("" if tool_calls else " ")
    finish_reason = finish_reason_map.get(stop_reason, "stop")

    msg = Message(
        role="assistant",
        content=content,
        tool_calls=tool_calls if tool_calls else None
    )

    usage = None
    if usage_data:
        input_tokens = usage_data.get("input_tokens", 0)
        output_tokens = usage_data.get("output_tokens", 0)
        usage = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens
        }
        cache_creation = usage_data.get("cache_creation_input_tokens")
        cache_read = usage_data.get("cache_read_input_tokens")
        if cache_creation is not None:
            usage["cache_creation_input_tokens"] = cache_creation
        if cache_read is not None:
            usage["cache_read_input_tokens"] = cache_read

    return ChatCompletionResponse(
        id=response.get("id", f"bedrock-{int(time.time())}"),
        created=int(time.time()),
        model=model,
        choices=[ChatCompletionResponseChoice(
            index=0,
            message=msg,
            finish_reason=finish_reason
        )],
        usage=usage
    )


class Brain:
    def __init__(self, model_name: str = "gemini/gemini-1.5-flash", api_key: str = None):
        self.model_name = model_name
        self.api_key = api_key
        if self.api_key:
            os.environ["GEMINI_API_KEY"] = self.api_key

    async def chat(
        self,
        request: ChatCompletionRequest,
        api_key: str = None,
        model_override: str = None
    ) -> Union[ChatCompletionResponse, AsyncGenerator[Any, None]]:

        target_model = model_override or self.model_name
        effective_key = api_key or self.api_key

        # Route Bedrock models through native Messages API
        if "bedrock" in target_model.lower():
            return await self._bedrock_converse(request, target_model, effective_key)

        # Everything else goes through LiteLLM
        return await self._litellm_call(request, target_model, effective_key)

    async def _bedrock_converse(
        self,
        request: ChatCompletionRequest,
        target_model: str,
        api_key: str = None
    ):
        """Native Bedrock via Anthropic Messages API (invoke_model) with prompt caching."""

        # Resolve model ID
        model_id = target_model.replace("bedrock/", "")

        # Figure out region from model prefix or env
        region = os.environ.get("AWS_REGION_NAME", "us-east-1")

        # Handle cross-region inference profiles
        if "global." in model_id:
            if region.startswith("eu"):
                model_id = model_id.replace("global.", "eu.")
            else:
                model_id = model_id.replace("global.", "us.")

        logger.info(f"Bedrock Messages API: model={model_id}, region={region}")

        # Build client
        client_kwargs = {"service_name": "bedrock-runtime", "region_name": region}

        # Support AWS keys from api_key field (format: access:secret:region)
        if api_key and ":" in api_key:
            parts = api_key.split(":")
            if len(parts) >= 3:
                client_kwargs["aws_access_key_id"] = parts[0]
                client_kwargs["aws_secret_access_key"] = parts[1]
                client_kwargs["region_name"] = parts[2]
                region = parts[2]
                logger.info(f"Using AWS credentials from key field, region={region}")

        client = boto3.client(**client_kwargs)

        # Convert messages
        messages_raw = [m.model_dump(exclude_none=True) for m in request.messages]
        system_blocks, api_messages = _convert_messages_for_messages_api(messages_raw)

        # Convert tools
        tools_list = []
        if request.tools:
            tools_raw = [t.model_dump(exclude_none=True) for t in request.tools]
            tools_list = _convert_tools_for_messages_api(tools_raw)

        # Add cache control markers
        _add_cache_control(system_blocks, api_messages, tools_list)

        # Build Messages API request body
        body = {
            "anthropic_version": "bedrock-2023-05-31",
            "messages": api_messages,
        }

        if system_blocks:
            body["system"] = system_blocks

        if tools_list:
            body["tools"] = tools_list

        if request.max_tokens:
            body["max_tokens"] = request.max_tokens
        else:
            body["max_tokens"] = 8192  # Messages API requires max_tokens

        if request.temperature is not None:
            body["temperature"] = request.temperature

        if request.stream:
            return await self._bedrock_stream(client, model_id, body, target_model)
        else:
            return self._bedrock_sync(client, model_id, body, target_model)

    def _bedrock_sync(self, client, model_id: str, body: dict, model: str) -> ChatCompletionResponse:
        """Synchronous Bedrock invoke_model call."""
        try:
            response = client.invoke_model(
                modelId=model_id,
                body=json.dumps(body),
                contentType="application/json"
            )
            response_body = json.loads(response["body"].read())
            logger.info(f"Bedrock usage: {response_body.get('usage', {})}")
            return _parse_messages_api_response(response_body, model)
        except Exception as e:
            logger.error(f"Bedrock invoke_model error: {e}")
            raise

    async def _bedrock_stream(self, client, model_id: str, body: dict, model: str):
        """Streaming Bedrock invoke_model_with_response_stream → OpenAI SSE chunks."""

        async def generate():
            try:
                response = client.invoke_model_with_response_stream(
                    modelId=model_id,
                    body=json.dumps(body),
                    contentType="application/json"
                )
                event_stream = response.get("body", [])
                resp_id = f"bedrock-{int(time.time())}"

                tool_index = -1
                current_tool_id = None
                current_tool_name = None
                
                # Track usage across stream
                total_usage = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0
                }
                cache_usage = {}

                for event in event_stream:
                    chunk_bytes = event.get("chunk", {}).get("bytes")
                    if not chunk_bytes:
                        continue

                    data = json.loads(chunk_bytes.decode("utf-8"))
                    event_type = data.get("type")

                    if event_type == "message_start":
                        # Contains usage info for input
                        msg = data.get("message", {})
                        usage = msg.get("usage", {})
                        if usage:
                            total_usage["prompt_tokens"] = usage.get("input_tokens", 0)
                            total_usage["completion_tokens"] = usage.get("output_tokens", 0)
                            total_usage["total_tokens"] = total_usage["prompt_tokens"] + total_usage["completion_tokens"]
                            
                            cache_creation = usage.get("cache_creation_input_tokens")
                            cache_read = usage.get("cache_read_input_tokens")
                            if cache_creation is not None:
                                cache_usage["cache_creation_input_tokens"] = cache_creation
                            if cache_read is not None:
                                cache_usage["cache_read_input_tokens"] = cache_read
                            
                            logger.info(f"Bedrock stream usage (start): {total_usage | cache_usage}")

                    elif event_type == "content_block_start":
                        block = data.get("content_block", {})
                        if block.get("type") == "tool_use":
                            tool_index += 1
                            current_tool_id = block.get("id", f"call_{int(time.time())}")
                            current_tool_name = block.get("name", "unknown")
                            yield {
                                "id": resp_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [{
                                            "index": tool_index,
                                            "id": current_tool_id,
                                            "type": "function",
                                            "function": {
                                                "name": current_tool_name,
                                                "arguments": ""
                                            }
                                        }]
                                    },
                                    "finish_reason": None
                                }]
                            }

                    elif event_type == "content_block_delta":
                        delta = data.get("delta", {})
                        delta_type = delta.get("type")

                        if delta_type == "text_delta":
                            yield {
                                "id": resp_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {"content": delta.get("text", "")},
                                    "finish_reason": None
                                }]
                            }

                        elif delta_type == "input_json_delta":
                            yield {
                                "id": resp_id,
                                "object": "chat.completion.chunk",
                                "created": int(time.time()),
                                "model": model,
                                "choices": [{
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [{
                                            "index": tool_index,
                                            "function": {
                                                "arguments": delta.get("partial_json", "")
                                            }
                                        }]
                                    },
                                    "finish_reason": None
                                }]
                            }

                    elif event_type == "content_block_stop":
                        pass  # No action needed

                    elif event_type == "message_delta":
                        stop_reason = data.get("delta", {}).get("stop_reason", "end_turn")
                        finish_map = {
                            "end_turn": "stop",
                            "max_tokens": "length",
                            "tool_use": "tool_calls",
                            "stop_sequence": "stop",
                        }
                        # Update final usage
                        final_usage = data.get("usage", {})
                        if final_usage:
                            output_tokens = final_usage.get("output_tokens", 0)
                            total_usage["completion_tokens"] = output_tokens
                            total_usage["total_tokens"] = total_usage["prompt_tokens"] + output_tokens
                            logger.info(f"Bedrock stream usage (delta): output_tokens={output_tokens}")

                        yield {
                            "id": resp_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [{
                                "index": 0,
                                "delta": {},
                                "finish_reason": finish_map.get(stop_reason, "stop")
                            }]
                        }

                    elif event_type == "message_stop":
                        # Build usage chunk in pure OpenAI format
                        cache_read = cache_usage.get("cache_read_input_tokens", 0) if cache_usage else 0
                        cache_write = cache_usage.get("cache_creation_input_tokens", 0) if cache_usage else 0
                        
                        # OpenAI format: prompt_tokens INCLUDES cached tokens
                        non_cached_prompt = total_usage["prompt_tokens"]
                        total_prompt = non_cached_prompt + cache_read
                        
                        usage_chunk = {
                            "prompt_tokens": total_prompt,  # includes cached
                            "completion_tokens": total_usage["completion_tokens"],
                            "total_tokens": total_prompt + total_usage["completion_tokens"],
                            "prompt_tokens_details": {
                                "cached_tokens": cache_read,  # how many were cached
                                "audio_tokens": 0
                            },
                            "completion_tokens_details": {
                                "reasoning_tokens": 0,
                                "audio_tokens": 0,
                                "cache_creation_tokens": cache_write
                            }
                        }
                        
                        final_chunk = {
                            "id": resp_id,
                            "object": "chat.completion.chunk",
                            "created": int(time.time()),
                            "model": model,
                            "choices": [],
                            "usage": usage_chunk
                        }
                        logger.info(f"Bedrock stream usage (final): {usage_chunk}")
                        logger.info(f"Sending final usage chunk: {final_chunk}")
                        yield final_chunk

            except Exception as e:
                logger.error(f"Bedrock stream error: {e}")
                yield {
                    "id": f"bedrock-err-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "choices": [{
                        "index": 0,
                        "delta": {"content": f"\n\n[Gateway Error: {str(e)}]"},
                        "finish_reason": "stop"
                    }]
                }

        return generate()

    async def _litellm_call(
        self,
        request: ChatCompletionRequest,
        target_model: str,
        effective_key: str = None
    ):
        """LiteLLM path for non-Bedrock models (Gemini, OpenAI, etc.)."""

        messages = []
        for m in request.messages:
            msg_dict = m.model_dump(exclude_none=True)
            if msg_dict.get("role") in ("tool", "function"):
                content = msg_dict.get("content")
                if not isinstance(content, str):
                    try:
                        msg_dict["content"] = json.dumps(content)
                    except:
                        msg_dict["content"] = str(content)
            messages.append(msg_dict)

        tools = None
        if request.tools:
            tools = []
            for t in request.tools:
                t_dict = t.model_dump(exclude_none=True)
                if "function" in t_dict:
                    if "parameters" not in t_dict["function"]:
                        t_dict["function"]["parameters"] = {"type": "object", "properties": {}}
                    else:
                        t_dict["function"]["parameters"] = _sanitize_json_schema(t_dict["function"]["parameters"])
                tools.append(t_dict)

        kwargs = {
            "model": target_model,
            "messages": messages,
            "tools": tools,
            "tool_choice": request.tool_choice if tools else None,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "stream": request.stream,
            "timeout": 15
        }

        if effective_key:
            kwargs["api_key"] = effective_key
            os.environ["GEMINI_API_KEY"] = effective_key

        proxy_url = os.environ.get("https_proxy") or os.environ.get("http_proxy")
        if proxy_url:
            kwargs["proxy"] = proxy_url

        if "gemini" in target_model.lower():
            kwargs["safety_settings"] = [
                {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_SEXUALLY_EXPLICIT", "threshold": "BLOCK_NONE"},
                {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_NONE"},
            ]

        if request.stream:
            return await litellm.acompletion(**kwargs)

        try:
            response = await litellm.acompletion(**kwargs)
            if not hasattr(response, "choices") or not response.choices:
                raise ValueError("Upstream model returned empty choices.")

            choice_data = response.choices[0]
            message_data = choice_data.message
            content = getattr(message_data, "content", None) or ""

            tool_calls = None
            if hasattr(message_data, "tool_calls") and message_data.tool_calls:
                tool_calls = []
                for tc in message_data.tool_calls:
                    if hasattr(tc, "model_dump"):
                        tool_calls.append(tc.model_dump())
                    else:
                        tool_calls.append(dict(tc))

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
            logger.error(f"LiteLLM error: {e}")
            raise
