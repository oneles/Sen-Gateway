# Sen-Gateway

[简体中文](README_ZH.md)

Sen-Gateway is a local, OpenAI-compatible model gateway for routing agent and application traffic across multiple LLM providers. It combines runtime model switching, provider-scoped credential storage, reasoning controls, request inspection, and optional context compression in one lightweight FastAPI service.

## Highlights

- **OpenAI-compatible endpoint** — use `/v1/chat/completions` with existing SDKs and agent clients.
- **Multi-provider routing** — configure OpenAI, Anthropic, Google Gemini, DeepSeek, and AWS Bedrock models through LiteLLM.
- **DeepSeek support** — built-in DeepSeek V4 Pro and V4 Flash routes, plus custom model IDs.
- **Reasoning strength** — choose Fast, Deep, or Maximum without re-entering an API key. Explicit request parameters always take priority.
- **Provider-scoped credentials** — models from the same provider reuse its encrypted key; switching back to a configured provider does not require entering the key again.
- **Echo Retention V5** — optionally compress older tool output while preserving recent conversation context.
- **Request observability** — inspect the original request, final upstream payload, model response, latency, usage, cache hits, and estimated context cost.
- **Bilingual dashboard** — English and Simplified Chinese, with system, light, and dark themes.

## Interface

![Sen-Gateway Dashboard](assets/dashboard.png)
![Sen-Gateway Audit View](assets/audit_view.png)

## Quick start

### Requirements

- Python 3.9+
- Network access to the selected model provider
- A provider API key or AWS credentials

### Install and run

```bash
git clone https://github.com/oneles/Sen-Gateway.git
cd Sen-Gateway

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python run.py
```

The gateway starts at `http://127.0.0.1:8000`.

Open `http://127.0.0.1:8000/dashboard`, sign in, and configure the provider, model, and API key under **Routing**.

Default local dashboard credentials:

- Username: `admin`
- Password: `88888888`

Change the default password before exposing the service to other machines:

```bash
python scripts/reset_password.py
```

## Call the gateway

Sen-Gateway accepts standard OpenAI chat-completion requests. Use `default` to route through the model selected in the dashboard.

### cURL

```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "default",
    "messages": [
      {"role": "user", "content": "Hello"}
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
    messages=[{"role": "user", "content": "Hello"}],
)

print(response.choices[0].message.content)
```

The client-side key is only a placeholder for SDK compatibility. Provider credentials are managed locally by Sen-Gateway.

## Reasoning controls

The dashboard provides three gateway defaults:

| Mode | DeepSeek V4 | Other compatible reasoning models |
|---|---|---|
| Fast | Thinking disabled | Low effort |
| Deep | Thinking enabled, `high` | Medium effort |
| Maximum | Thinking enabled, `max` | High effort |

DeepSeek maps `low` and `medium` reasoning effort to `high`, so Sen-Gateway uses the thinking toggle to make Fast mode meaningfully different. If a request explicitly supplies `reasoning_effort` or `thinking`, the request value overrides the dashboard default.

Reasoning models receive a larger output allowance and upstream timeout by default. These values can be overridden with environment variables:

```env
REASONING_MIN_OUTPUT_TOKENS=4096
LITELLM_UPSTREAM_TIMEOUT_SECONDS=60
```

## Provider credentials

- Keys are encrypted before they are stored in the local SQLite database.
- Each provider has its own saved credential.
- Switching models within the same provider does not require entering the key again.
- Leaving the API-key field blank preserves the saved key.
- Switching to a provider that has never been configured requires that provider's key.
- AWS Bedrock currently accepts `AccessKey:SecretKey:Region` in the dashboard key field.

## Echo Retention V5

History compression is optional. When enabled, Sen-Gateway reduces older tool output using content-aware rules for browser trees, terminal logs, search results, structured JSON, and long fallback text. Recent messages and the system prompt remain available to the upstream model.

The audit view compares the captured request with the payload sent upstream. Its token and cost figures are estimates for diagnosis and relative comparison; provider billing remains authoritative.

## Security

- `.env`, `secret.key`, the SQLite database, and runtime logs are excluded from Git.
- `secret.key` is generated locally and must not be committed or shared.
- Never place a real provider key in source code, README examples, or client configuration committed to Git.
- Keep the dashboard bound to a trusted network and change the default administrator password.
- If a local encryption key is lost, existing encrypted provider credentials cannot be recovered and must be entered again.

## Project structure

```text
Sen-Gateway/
├── app/                # FastAPI routes, model adapter, dashboard, pruning
├── scripts/            # Maintenance and diagnostic utilities
├── run.py              # Local service entry point
├── requirements.txt    # Full dependency lock
└── README.md           # English documentation
```

---

Developed by 森哥 (Senge) · Echo Retention V5
