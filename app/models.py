from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional, Union

# OpenAI-compatible Request Models

class Message(BaseModel):
    role: str
    content: Optional[Union[str, List[Dict[str, Any]]]] = None  # Text or Multimodal content
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None

class Tool(BaseModel):
    type: str = "function"
    function: Dict[str, Any]

class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Message]
    tools: Optional[List[Tool]] = None
    tool_choice: Optional[Union[str, Dict[str, Any]]] = None
    max_tokens: Optional[int] = None
    temperature: Optional[float] = 1.0
    stream: Optional[bool] = False
    n: Optional[int] = 1

# OpenAI-compatible Response Models (Simplified)

class ChatCompletionResponseChoice(BaseModel):
    index: int
    message: Message
    finish_reason: str

class ChatCompletionResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[ChatCompletionResponseChoice]
    usage: Optional[Dict[str, Any]] = None  # Relaxed type to allow extra fields from LiteLLM
