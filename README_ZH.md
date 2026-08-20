# Sen-Gateway

[English](README.md)

Sen-Gateway 是一个运行在本地、兼容 OpenAI 接口的多模型网关，适合 Agent、开发工具和应用统一接入不同的大模型服务。它将模型路由、厂商密钥管理、推理强度、请求追踪和可选的上下文压缩集中在一个轻量的 FastAPI 服务中。

## 主要能力

- **兼容 OpenAI 接口**：现有 SDK 和 Agent 客户端可通过 `/v1/chat/completions` 接入。
- **多厂商路由**：通过 LiteLLM 接入 OpenAI、Anthropic、Google Gemini、DeepSeek 和 AWS Bedrock。
- **支持 DeepSeek**：内置 DeepSeek V4 Pro、V4 Flash，也可以添加自定义模型 ID。
- **推理强度**：提供快速、深入、极致三档；调整推理强度不需要重新输入 API Key，请求显式参数始终优先。
- **按厂商保存密钥**：同一厂商的模型自动复用加密密钥，切回已经配置过的厂商也不需要重新填写。
- **Echo Retention V5**：可选择压缩较早的工具输出，同时保留近期对话上下文。
- **请求追踪**：查看原始请求、发送到上游的内容、模型返回、耗时、Token、缓存命中和上下文成本估算。
- **双语和主题**：支持 English、简体中文，以及跟随系统、浅色、深色主题。

## 界面

![Sen-Gateway 控制台](assets/dashboard.png)
![Sen-Gateway 上下文分析](assets/audit_view.png)

## 快速开始

### 环境要求

- Python 3.9+
- 可以访问所选模型厂商的网络
- 对应厂商的 API Key 或 AWS 凭据

### 安装并启动

```bash
git clone https://github.com/oneles/Sen-Gateway.git
cd Sen-Gateway

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python run.py
```

服务默认运行在 `http://127.0.0.1:8000`。

打开 `http://127.0.0.1:8000/dashboard`，登录后在“模型路由”中配置厂商、模型和 API Key。

本地控制台默认账号：

- 用户名：`admin`
- 密码：`88888888`

如果服务会被其他机器访问，请先修改默认密码：

```bash
python scripts/reset_password.py
```

## 调用网关

Sen-Gateway 接受标准 OpenAI Chat Completions 请求。使用 `default` 会自动路由到控制台中选择的模型。

### cURL

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "messages": [
      {"role": "user", "content": "你好"}
    ]
  }'
```

### Python

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://127.0.0.1:8000/v1",
    api_key="local-placeholder",
)

response = client.chat.completions.create(
    model="default",
    messages=[{"role": "user", "content": "你好"}],
)

print(response.choices[0].message.content)
```

客户端 API Key 只是为了兼容 SDK 的占位值，真实的模型厂商凭据由 Sen-Gateway 保存在本地。

## 推理强度

控制台提供三个默认档位：

| 档位 | DeepSeek V4 | 其他兼容推理模型 |
|---|---|---|
| 快速 | 关闭深度思考 | 低推理强度 |
| 深入 | 开启思考，`high` | 中等推理强度 |
| 极致 | 开启思考，`max` | 高推理强度 |

DeepSeek 会把 `low` 和 `medium` 都映射成 `high`，因此 Sen-Gateway 使用思考模式开关，让“快速”档真正减少隐藏推理。如果请求显式传入 `reasoning_effort` 或 `thinking`，请求参数会覆盖控制台默认值。

推理模型默认拥有更大的输出空间和上游超时时间，可以通过环境变量调整：

```env
REASONING_MIN_OUTPUT_TOKENS=4096
LITELLM_UPSTREAM_TIMEOUT_SECONDS=60
```

## 厂商密钥管理

- API Key 加密后保存在本地 SQLite 数据库中。
- 每个模型厂商拥有独立的密钥记录。
- 同一厂商切换模型时不需要重新输入密钥。
- API Key 输入框留空会继续使用已保存的密钥。
- 首次切换到尚未配置的厂商时，需要填写该厂商的密钥。
- AWS Bedrock 当前在控制台密钥字段中使用 `AccessKey:SecretKey:Region` 格式。

## Echo Retention V5

历史消息压缩是可选功能。启用后，Sen-Gateway 会针对浏览器结构、终端日志、搜索结果、JSON 和超长文本，以不同规则精简较早的工具输出；近期消息和系统提示词仍会发送给上游模型。

“上下文优化分析”会比较原始请求与实际上游内容。页面中的 Token 和成本属于诊断估算，适合相对比较；实际费用以模型厂商账单为准。

## 安全说明

- `.env`、`secret.key`、SQLite 数据库和运行日志均已排除在 Git 之外。
- `secret.key` 只在本地生成，不能提交或分享。
- 不要把真实厂商密钥写入源码、README 示例或会提交到 Git 的客户端配置。
- 控制台应只开放在可信网络中，并及时修改默认管理员密码。
- 如果本地加密密钥丢失，已经加密的厂商凭据无法恢复，需要重新填写。

## 项目结构

```text
Sen-Gateway/
├── app/                # FastAPI 路由、模型适配、控制台、上下文压缩
├── scripts/            # 维护和诊断工具
├── run.py              # 本地服务入口
├── requirements.txt    # 完整依赖锁定
└── README_ZH.md        # 中文文档
```

---

由森哥（Senge）开发 · Echo Retention V5
