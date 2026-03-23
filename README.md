# Sen-Gateway 🚀 (Echo Retention V5)

[中文版](README_ZH.md)

---

## 🌟 Introduction

**Sen-Gateway** is a high-performance, lightweight AI model gateway designed to optimize efficiency and cost for Large Language Models (LLMs), especially **Google Gemini**. It implements an OpenAI-compatible API interface and features the innovative **Echo Retention** context compression and multi-language audit mechanism.

### 📸 Preview

![Sen-Gateway Dashboard](assets/dashboard.png)
![Sen-Gateway Audit View](assets/audit_view.png)

### 🧠 Core Features

- **Echo Retention (V5) Algorithm**: 
  - **Tool-Aware Pruning**: Automatically detects and prunes outputs from Browser, Terminal Logs, Search, and JSON data with semantic precision.
  - **Multi-Language Support**: Aligns pruning markers with the user's language (EN/ZH) to minimize model context-switching overhead.
  - **Cache Anchor**: Locks the System Prompt to ensure maximum Prompt Caching hit rates (enjoy **0.1x** pricing).
  - **Role-Aware Compression**: Automatically trims redundant long-term tool outputs while preserving core assistant responses and recent memory, reducing Token consumption by **20%-40%**.
- **Visual Audit Dashboard**: Real-time cost audit based on actual Gemini billing rules, displaying Token savings and cache benefits.
- **Unified Protocol Conversion**: Maps models from OpenAI, Anthropic, AWS Bedrock, etc., to a unified OpenAI-compatible format.
- **Dynamic Hot Configuration**: Switch models, configure API Keys, proxy settings, and **pruning language** in real-time via Web UI.

---

## 💡 Developer Recommendation: Prompt Injection

To help the LLM better understand the **Echo Retention (V5)** pruning logic and reduce reasoning hallucinations, we strongly recommend injecting the following strategy into your **System Prompt** at the application layer (e.g., OpenClaw, Cursor, or custom apps).

Choose the version that matches the **Language** setting in your Sen-Gateway Dashboard:

### 🇺🇸 Recommended English Prompt
> **[System: Sen-Gateway V5 Semantic Pruning Awareness]**
> Context optimization is active. Tool outputs have been pruned using **Echo Retention (V5)** strategies to reduce latency:
> - **Browser**: Only interactive nodes (with `ref` or functional roles) are preserved. Static nodes are omitted.
> - **Exec Logs**: Middle segments are hidden; only HEAD/TAIL and lines containing `error|warning|failed|exception` are kept.
> - **Structured Data (JSON)**: Large arrays are sampled (First 2 + Last 1); strings longer than 500 chars are truncated.
> - **Search**: Only the top 5 results are shown.
> - **Long Text (Fallback)**: For text over 1500 chars, only the first and last 500 chars are preserved.
> 
> **Note**: If critical details are missing, explicitly request a "full-context" retry or specific filters.

### 🇨🇳 Recommended Chinese Prompt
> **[系统：Sen-Gateway V5 语义剪枝感知]**
> 当前会话已启用语义压缩。为了提升响应速度并降低延迟，系统已根据以下 **V5 剪枝策略** 对工具输出进行了精简：
> - **浏览器 (Browser)**: 仅保留具备 `ref` 句柄或交互角色（如按钮、输入框）的 UI 节点，剔除静态展示内容。
> - **终端日志 (Exec/Process)**: 仅保留首尾各 10/20 行，以及中间部分包含 `error|warning|failed|exception` 的关键行。
> - **结构化数据 (JSON)**: 对列表进行采样（保留前2项与最后1项），长字符串（>500 字符）会被截断展示。
> - **网页搜索 (Search)**: 仅保留相关度最高的前 5 条结果。
> - **长文本 (Fallback)**: 超过 1500 字符的文本仅保留首尾各 500 字符。
> 
> **提示**：如需获取被隐藏的完整细节，请明确要求“禁用剪枝重试”或“获取完整数据”。

---

## 🛠️ Quick Start

### 1. Prerequisites
- **Python**: 3.9+
- **Network**: Ensure access to LLM APIs (or configure built-in proxy).

### 2. Installation
```bash
# Clone repository
git clone https://github.com/oneles/Sen-Gateway.git
cd Sen-Gateway

# Create & Activate Virtual Environment
python3 -m venv venv
source venv/bin/activate  # Linux/macOS

# Install Dependencies
pip install -r requirements.txt
```

### 3. Setup API Key
Create a `.env` file in the root directory:
```env
GEMINI_API_KEY=your_google_api_key
GEMINI_MODEL=gemini/gemini-2.5-flash
```

---

## 🚀 Run & Integrate

### 1. Start Service
```bash
python run.py
```
Default runs on `http://localhost:8000`.

### 2. Client Configuration (OpenClaw/Cursor)

Point your client to Sen-Gateway. For **AWS Bedrock**, use the format `AccessKey:SecretKey:Region` in the API Key field.

### 3. Access Dashboard
Visit: `http://localhost:8000/dashboard`
- **Default User**: `admin`
- **Default Password**: `88888888`
- **Features**: View interaction logs, run cost audits, modify system config (including **Language Switch**).

---

## ⚡ Advanced Usage

### 🕵️ Agent Payload Handling (Auto-Compression)
Sen-Gateway is optimized for **Agentic Workflows** (e.g., Tool Use). 
- When an Agent generates massive tool outputs (e.g., file reading, web search), the **Echo Retention** algorithm automatically truncates middle content (retaining only head/tail) for older messages.
- This ensures the Agent's "Chain of Thought" remains intact while preventing context window explosion.

### 💰 Cost Auditing (The Audit System)
The Dashboard isn't just for logs; it's a **Token Actuary**:
1. Select multi-turn logs in the sidebar.
2. Click **🚀 Audit**.
3. The system calculates cost based on:
   - **Token Count**: 1 Chinese char ≈ 2 tokens, 4 English chars ≈ 1 token.
   - **Implicit Caching**: Automatically detects common prefixes between turns and applies **0.1x - 0.25x (Prompt Caching)** discount rates.
   - **Efficiency**: Displays real-time savings gained through Echo Retention vs. raw full-history requests.

---

```text
Sen-Gateway/
├── app/                # Core Logic (FastAPI, Pruner, Brain)
├── scripts/            # Tools (Reset Password, DB Check)
├── run.py              # Entry Point
├── requirements.txt    # Dependencies
└── README.md           # Documentation
```

---

## 🛡️ Security
- Recommended: change default admin password via `scripts/reset_password.py`.
- `secret.key` is used for encrypting API Keys. Keep it safe.

---
*Developed by 森哥 (Senge) | Tech Core: Echo Retention (V5)*
