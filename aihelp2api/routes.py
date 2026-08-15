"""API 路由模块：/v1/models 和 /v1/chat/completions。"""
import json
import time
import uuid
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from config import API_KEY, DEFAULT_MODEL, MODELS, SYSTEM_OVERRIDE
from tool_calling import (
    ToolCallFilter,
    allowed_tool_names_from_tools,
    inject_tools_into_messages,
    normalize_tool_messages,
    parse_tool_calls,
)
from upstream import parse_sse_stream, upstream_chat_stream


# ======== 辅助函数 ========
def check_auth(authorization: Optional[str]):
    """校验 API Key。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid Authorization header"
        )
    token = authorization.split(" ", 1)[1].strip()
    if token != API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API key")


def build_prompt(messages: List[Dict[str, Any]]) -> str:
    """
    把 OpenAI 的 messages 数组拼成单条 prompt，保留角色信息。
    首条强制注入系统覆盖提示词以压制上游内置提示词。
    工具注入已在调用前通过 inject_tools_into_messages 完成，此处不再处理。
    """
    parts = [f"[系统指令]\n{SYSTEM_OVERRIDE}"]  # 首条强制注入

    for m in messages:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "system":
            parts.append(f"[系统指令]\n{content}")
        elif role == "user":
            parts.append(f"[用户]\n{content}")
        elif role == "assistant":
            parts.append(f"[助手]\n{content}")
        else:
            parts.append(f"[{role}]\n{content}")
    return "\n\n".join(parts)


def now_timestamp() -> int:
    return int(time.time())


def make_chunk(
    completion_id: str,
    model: str,
    content: str = "",
    reasoning: str = "",
    finish_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """构造流式 chunk。content/reasoning 二选一或都可为空。"""
    delta: Dict[str, Any] = {}
    if reasoning:
        delta["reasoning_content"] = reasoning
    if content:
        delta["content"] = content
    return {
        "id": completion_id,
        "object": "chat.completion.chunk",
        "created": now_timestamp(),
        "model": model,
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}],
    }


def make_completion(
    completion_id: str,
    model: str,
    content: str,
    reasoning: str = "",
    usage: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    message: Dict[str, Any] = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    return {
        "id": completion_id,
        "object": "chat.completion",
        "created": now_timestamp(),
        "model": model,
        "choices": [{"index": 0, "message": message, "finish_reason": "stop"}],
        "usage": usage or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }


def sse_encode(obj: Dict[str, Any]) -> bytes:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n".encode("utf-8")


# ======== 路由 ========
async def list_models(authorization: Optional[str] = Header(None)):
    check_auth(authorization)
    data = [
        {"id": name, "object": "model", "created": 1700000000, "owned_by": "oihelp"}
        for name in MODELS
    ]
    return {"object": "list", "data": data}


async def chat_completions(request: Request, authorization: Optional[str] = Header(None)):
    check_auth(authorization)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    messages = body.get("messages")
    if not messages or not isinstance(messages, list):
        raise HTTPException(status_code=400, detail="messages is required")

    model = body.get("model") or DEFAULT_MODEL
    if model not in MODELS:
        raise HTTPException(
            status_code=400,
            detail=f"Model '{model}' not supported. Available: {list(MODELS)}",
        )
    upstream_model = MODELS[model]
    stream = bool(body.get("stream", False))

    # 工具处理
    tools = body.get("tools") or []
    tool_choice = body.get("tool_choice")
    allowed_names = allowed_tool_names_from_tools(tools) if tools else set()

    # 标准化 tool 消息 + 注入工具提示
    messages = normalize_tool_messages(messages)
    messages = inject_tools_into_messages(messages, tools, tool_choice)

    prompt = build_prompt(messages)
    conversation_id = body.get("conversation_id") or str(uuid.uuid4().int)[:13]
    completion_id = f"chatcmpl-{uuid.uuid4().hex[:24]}"

    # ====== 流式 ======
    if stream:

        async def event_stream() -> AsyncIterator[bytes]:
            # 首个 chunk: role
            first = {
                "id": completion_id,
                "object": "chat.completion.chunk",
                "created": now_timestamp(),
                "model": model,
                "choices": [{"index": 0, "delta": {"role": "assistant"}, "finish_reason": None}],
            }
            yield sse_encode(first)

            resp: Optional[httpx.Response] = None
            tool_filter = ToolCallFilter()
            raw_parts: List[str] = []

            try:
                resp = await upstream_chat_stream(prompt, upstream_model, conversation_id)
                # 实时逐条转发，同时过滤 <tool_call> 块
                async for msg in parse_sse_stream(resp):
                    msg_type = msg.get("type")
                    if msg_type == "reasoning":
                        piece = msg.get("content", "")
                        raw_parts.append(piece)
                        visible = tool_filter.feed(piece)
                        if visible:
                            yield sse_encode(make_chunk(completion_id, model, reasoning=visible))
                    elif msg_type == "content":
                        piece = msg.get("content", "")
                        raw_parts.append(piece)
                        visible = tool_filter.feed(piece)
                        if visible:
                            yield sse_encode(make_chunk(completion_id, model, content=visible))
                    elif msg.get("done") is True:
                        break
            except HTTPException as e:
                err = {"error": {"message": e.detail, "type": "upstream_error"}}
                yield sse_encode(err)
                return
            except httpx.HTTPError as e:
                err = {"error": {"message": str(e), "type": "connection_error"}}
                yield sse_encode(err)
                return
            finally:
                if resp is not None:
                    await resp.aclose()

            # flush 过滤器，解析完整文本
            remaining = tool_filter.flush()
            if remaining:
                yield sse_encode(make_chunk(completion_id, model, content=remaining))

            full_text = "".join(raw_parts)
            _, tool_calls = parse_tool_calls(full_text, allowed_names)

            # 如果有工具调用，发送 tool_calls 增量
            if tool_calls:
                for call in tool_calls:
                    # 第一个增量: id + type + name
                    yield sse_encode(
                        {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": now_timestamp(),
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "id": call["id"],
                                                "type": call["type"],
                                                "function": {
                                                    "name": call["function"]["name"],
                                                    "arguments": "",
                                                },
                                            }
                                        ]
                                    },
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )
                    # 第二个增量: arguments
                    yield sse_encode(
                        {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": now_timestamp(),
                            "model": model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {
                                        "tool_calls": [
                                            {
                                                "index": 0,
                                                "function": {
                                                    "arguments": call["function"]["arguments"]
                                                },
                                            }
                                        ]
                                    },
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )
                # 结束: tool_calls
                yield sse_encode(make_chunk(completion_id, model, finish_reason="tool_calls"))
            else:
                # 结束: stop
                yield sse_encode(make_chunk(completion_id, model, finish_reason="stop"))

            yield b"data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # ====== 非流式 ======
    resp: Optional[httpx.Response] = None
    try:
        resp = await upstream_chat_stream(prompt, upstream_model, conversation_id)
    except HTTPException as e:
        raise e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"上游连接失败: {e}")

    full_content = ""
    full_reasoning = ""
    raw_parts: List[str] = []
    usage = None

    try:
        async for msg in parse_sse_stream(resp):
            msg_type = msg.get("type")
            if msg_type == "reasoning":
                piece = msg.get("content", "")
                raw_parts.append(piece)
                full_reasoning += piece
            elif msg_type == "content":
                piece = msg.get("content", "")
                raw_parts.append(piece)
                full_content += piece
            elif msg.get("done") is True:
                tu = msg.get("tokenUsage") or {}
                usage = {
                    "prompt_tokens": tu.get("input", 0),
                    "completion_tokens": tu.get("output", 0),
                    "total_tokens": tu.get("total", 0),
                }
    finally:
        await resp.aclose()

    # 解析工具调用
    full_text = "".join(raw_parts)
    clean_text, tool_calls = parse_tool_calls(full_text, allowed_names)

    if tool_calls:
        # 有工具调用: 返回 tool_calls, finish_reason=tool_calls
        return JSONResponse(
            {
                "id": completion_id,
                "object": "chat.completion",
                "created": now_timestamp(),
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {
                            "role": "assistant",
                            "content": clean_text or None,
                            "tool_calls": tool_calls,
                        },
                        "finish_reason": "tool_calls",
                    }
                ],
                "usage": usage
                or {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        )

    # 无工具调用: 正常返回
    return JSONResponse(make_completion(completion_id, model, full_content, full_reasoning, usage))


async def root():
    return {"status": "ok", "service": "oihelp-openai-api"}
