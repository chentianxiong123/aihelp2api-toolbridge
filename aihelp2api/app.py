"""
OIHelp → OpenAI 兼容 API 服务 (支持工具调用)

启动入口：加载配置、注册路由、启动服务。

依赖:
    pip install fastapi uvicorn httpx python-dotenv

运行:
    python app.py
    # 或: uvicorn app:app --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from account_manager import auto_register_background
from config import HOST, PORT
from routes import chat_completions, list_models, root
from upstream import close_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理：启动时检查账号并自动补号，关闭时清理连接池。"""
    # 启动: 检查账号数量，低于阈值自动补号
    await auto_register_background()
    yield
    # 关闭: 清理 httpx 连接池
    await close_client()


# 创建 FastAPI 应用
app = FastAPI(title="OIHelp OpenAI API", version="1.0", lifespan=lifespan)

# 注册路由
app.get("/")(root)
app.get("/v1/models")(list_models)
app.post("/v1/chat/completions")(chat_completions)


if __name__ == "__main__":
    import uvicorn

    print(f"🌐 服务地址: http://{HOST}:{PORT}")
    print(f"📖 API 文档: http://{HOST}:{PORT}/docs")
    uvicorn.run(app, host=HOST, port=PORT)
