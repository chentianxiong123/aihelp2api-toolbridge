"""上游请求模块：httpx 客户端、SSE 解析、对话请求。"""

import json
from typing import Any, AsyncIterator, Dict, Optional

import httpx
from fastapi import HTTPException

from account_manager import ensure_session, pick_account, refresh_account_session
from config import API_BASE, HEADERS, UPSTREAM_CONNECT_TIMEOUT, UPSTREAM_TIMEOUT

# 全局异步客户端 (连接池复用)
_http_client: Optional[httpx.AsyncClient] = None


def get_client() -> httpx.AsyncClient:
    """获取全局 httpx 客户端（连接池复用）。"""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            verify=False,
            timeout=httpx.Timeout(UPSTREAM_TIMEOUT, connect=UPSTREAM_CONNECT_TIMEOUT),
            headers=HEADERS,
            http2=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )
    return _http_client


async def close_client() -> None:
    """关闭全局 httpx 客户端。"""
    global _http_client
    if _http_client is not None and not _http_client.is_closed:
        await _http_client.aclose()


async def parse_sse_stream(response: httpx.Response) -> AsyncIterator[Dict[str, Any]]:
    """
    异步解析上游 SSE 流，逐条 yield JSON 消息 dict。
    使用 httpx 的 aiter_text() 真正异步读取，不阻塞事件循环,
    保证每个数据块实时转发给下游。
    """
    buffer = ""
    async for chunk in response.aiter_text():
        if not chunk:
            continue
        buffer += chunk
        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line:
                continue
            data = line[5:].lstrip() if line.startswith("data:") else line
            if not data:
                continue
            try:
                yield json.loads(data)
            except json.JSONDecodeError:
                continue
    # 处理缓冲区残留
    line = buffer.strip()
    if line.startswith("data:"):
        data = line[5:].lstrip()
        try:
            yield json.loads(data)
        except json.JSONDecodeError:
            pass


async def upstream_chat_stream(
    prompt: str, model: str, conversation_id: str
) -> httpx.Response:
    """
    向 oihelp 发起流式对话请求，返回已打开流的 Response。
    遇到 401 (session_invalid) 时自动重新登录刷新 token 并重试一次。
    调用方需自行管理 response 的上下文 (close)。
    """
    account = await ensure_session(pick_account())
    payload = {
        "username": account.get("username"),
        "sessionToken": account.get("sessionToken"),
        "conversationId": conversation_id,
        "message": prompt,
        "mode": "solve",
        "model": model,
    }
    client = get_client()

    # 第一次尝试
    req = client.build_request("POST", f"{API_BASE}/api/chat/agent", json=payload)
    resp = await client.send(req, stream=True)

    # 401 会话无效: 重新登录刷新 token 后重试一次
    if resp.status_code == 401:
        body = (await resp.aread()).decode("utf-8", errors="ignore")
        await resp.aclose()
        if "session_invalid" in body or "会话无效" in body:
            account = await refresh_account_session(account)
            payload["username"] = account.get("username")
            payload["sessionToken"] = account.get("sessionToken")
            req = client.build_request(
                "POST", f"{API_BASE}/api/chat/agent", json=payload
            )
            resp = await client.send(req, stream=True)

    if resp.status_code != 200:
        await resp.aclose()
        raise HTTPException(
            status_code=502, detail=f"上游服务暂时不可用（HTTP {resp.status_code}）"
        )
    return resp
