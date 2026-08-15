# OIHelp2API

将 OIHelp 转换为 OpenAI 兼容的 API 服务，支持流式响应、思考过程、工具调用和自动账号管理。

## 功能特性

- ✅ OpenAI 兼容接口（`/v1/models`, `/v1/chat/completions`）
- ✅ 流式响应 + 思考过程（`reasoning_content`）
- ✅ 工具调用（Function Calling）
- ✅ 自动账号管理（低于阈值自动补号）
- ✅ 会话失效自动重登

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

依赖包说明（`requirements.txt`）：
- `fastapi` - Web 框架
- `uvicorn` - ASGI 服务器
- `httpx` - 异步 HTTP 客户端
- `python-dotenv` - 环境变量加载
- `requests` - 同步 HTTP 客户端（注册模块使用）

### 2. 配置环境

复制 `.env.example` 为 `.env`，按需修改：

```env
API_KEY=sk-oihelp               # API 鉴权密钥
PORT=8000                       # 服务端口
DEFAULT_MODEL=gpt-5.5-low       # 默认模型
ACCOUNT_MIN_THRESHOLD=3         # 账号数量低于此值触发自动补号
AUTO_REGISTER_COUNT=5           # 每次补号数量
```

### 3. 配置账号

复制 `accounts.json.example` 为 `accounts.json`，填入真实账号信息：

```json
[
  {
    "username": "your_real_username",
    "password": "your_real_password",
    "sessionToken": "",
    "balance": 200000
  }
]
```

或使用自动注册功能（服务启动时自动检测并补充账号）。

### 4. 启动服务

```bash
python app.py
```

访问：
- API: `http://localhost:8000`
- 文档: `http://localhost:8000/docs`

## 使用示例

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer sk-oihelp" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "gpt-5.5-low",
    "messages": [{"role": "user", "content": "你好"}],
    "stream": true
  }'
```

## 项目结构

| 文件 | 说明 |
|------|------|
| `app.py` | 启动入口 |
| `config.py` | 配置管理 + 模型映射 |
| `routes.py` | API 路由实现 |
| `upstream.py` | 上游请求处理 |
| `account_manager.py` | 账号管理 + 自动补号 |
| `tool_calling.py` | 工具调用逻辑 |
| `register.py` | 账号注册与登录 |

## 自动补号机制

服务启动时检查 `accounts.json` 账号数量，低于 `ACCOUNT_MIN_THRESHOLD` 时自动注册新账号。

手动触发：
```python
from account_manager import check_and_auto_register
check_and_auto_register()
```

## 核心配置

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `API_KEY` | `sk-oihelp` | API 鉴权密钥 |
| `PORT` | `8000` | 服务端口 |
| `DEFAULT_MODEL` | `gpt-5.5-low` | 默认模型 |
| `ACCOUNT_MIN_THRESHOLD` | `3` | 最小账号数阈值 |
| `AUTO_REGISTER_COUNT` | `5` | 每次补号数量 |

## 模型配置

在 `config.py` 的 `MODELS` 字典中添加或修改：

```python
MODELS = {
    "gemini-3.1-pro": "gemini-3.1-pro-preview-thinking-24576",
    "gpt-5.4": "gpt-5.4",
    # 更多模型...
}
```

## License

MIT
