# aihelp2api-toolbridge

> 两个独立项目，统一归档在一个仓库中。

## 目录结构

```
.
├── aihelp2api/          # OIHelp → OpenAI 兼容 API 网关（Python FastAPI）
│   ├── app.py           # 启动入口
│   ├── routes.py        # API 路由 /v1/models, /v1/chat/completions
│   ├── upstream.py      # 上游 httpx 客户端 + SSE 解析
│   ├── account_manager.py  # 账号管理（随机选号、session 刷新、自动补号）
│   ├── tool_calling.py  # 工具调用：提示注入、解析、流式过滤
│   ├── register.py      # OIHelp 批量注册脚本
│   ├── config.py        # 配置（.env + 环境变量）
│   ├── requirements.txt
│   └── README.md
│
├── tool-bridge/         # Tool Bridge：OpenAI ↔ Anthropic 格式转换代理（Python）
│   ├── toolbridge/      # 主模块
│   │   ├── server.py    # HTTP 服务器
│   │   ├── proxy.py     # 代理核心
│   │   ├── router.py    # 路由分发
│   │   ├── format_openai.py
│   │   ├── format_anthropic.py
│   │   ├── sse.py       # SSE 流式
│   │   ├── model_map.py # 模型映射
│   │   ├── virtual_tools.py
│   │   ├── config.py
│   │   └── desktop.py
│   ├── tests/           # 单元测试
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── requirements.txt
│   └── README.md
│
└── README.md            # 本文件
```

## 两个项目的区别

| | aihelp2api | tool-bridge |
|--|------------|-------------|
| 用途 | OIHelp 私有 API → 标准 OpenAI API | OpenAI/Anthropic 格式互转代理 |
| 框架 | FastAPI + uvicorn | 标准库 http.server |
| 认证 | API Key + 账号池 | Upstream Auth Header |
| 工具调用 | 自研 <tool_call> 格式注入 | 原生函数调用格式 |
| Docker | 否 | 是 |

## 启动

### aihelp2api
```bash
cd aihelp2api
cp .env.example .env   # 编辑配置
pip install -r requirements.txt
python app.py
```

### tool-bridge
```bash
cd tool-bridge
cp .env.example .env   # 编辑配置
pip install -r requirements.txt
python -m toolbridge
# 或 Docker:
docker compose up -d
```

## 安全

- `accounts.json`（真实账号凭据）**不在**本仓库中
- 各项目的 `.env` 和 `.env.example` 不含敏感值
