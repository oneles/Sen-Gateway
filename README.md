# Sen-Gateway 🚀

[English](#english) | [中文](#中文)

---

<a name="english"></a>

## 🌟 Introduction

**Sen-Gateway** is a high-performance, lightweight AI model gateway designed to optimize efficiency and cost for Large Language Models (LLMs), especially **Google Gemini**. It implements an OpenAI-compatible API interface and features the innovative **Echo Retention** context compression and audit mechanism.

### 🧠 Core Features

- **Echo Retention (V3) Algorithm**: 
  - **Cache Anchor**: Locks the System Prompt to ensure maximum Prompt Caching hit rates (enjoy **0.1x** pricing).
  - **Role-Aware Compression**: Automatically trims redundant long-term tool outputs while preserving core assistant responses and recent memory, reducing Token consumption by **30%-80%** while maintaining intelligence.
- **Visual Audit Dashboard**: Real-time cost audit based on actual Gemini billing rules, displaying Token savings and cache benefits.
- **Unified Protocol Conversion**: Maps models from OpenAI, Anthropic, etc., to a unified OpenAI-compatible format for one-click distribution.
- **Dynamic Hot Configuration**: Switch models, configure API Keys, and proxy settings in real-time via Web UI without code changes.

### 🎨 Architecture Workflow

```mermaid
graph TD
    Client[Client (OpenWebUI/Cursor)] -->|OpenAI API Request| Gateway[Sen-Gateway Core]
    
    subgraph "Sen-Gateway (Python/FastAPI)"
        direction TB
        Gateway -->|1. Auth & Config| DB[(SQLite Config)]
        Gateway -->|2. Pruning Strategy| Pruner[Echo Retention (V3)]
        
        subgraph "Echo Retention Algorithm"
            Pruner -->|Lock| System[System Prompt (Cache Anchor)]
            Pruner -->|Keep| Recent[Recent History (15 msgs)]
            Pruner -->|Compress| Middle[Tool Outputs (Truncated)]
        end
        
        Pruner -->|Optimized Payload| Brain[Brain (LiteLLM Adapter)]
        Brain -->|3. Model API Call| LLM[Gemini / OpenAI / Claude]
        
        LLM -->|Response| Brain
        Brain -->|Stream/JSON| Gateway
        
        Gateway -->|4. Log & Audit| Audit[Audit System]
        Audit -->|Cost Analysis| Dashboard[Web Dashboard]
    end
    
    Gateway -->|Response| Client
```

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
GEMINI_MODEL=gemini/gemini-1.5-flash
```

---

## 🚀 Run & Integrate

### 1. Start Service
```bash
python run.py
```
Default runs on `http://localhost:8000`.

### 2. Client Configuration (OpenClaw/Cursor)
Point your client to Sen-Gateway:
- **Base URL**: `http://localhost:8000/v1`
- **API Key**: `any` (Gateway uses your configured key automatically)

### 3. Access Dashboard
Visit: `http://localhost:8000/dashboard`
- **Default User**: `admin`
- **Default Password**: `88888888`
- **Features**: View interaction logs, run cost audits, modify system config.

---

<a name="中文"></a>

## 🌟 简介

**Sen-Gateway** 是一个高性能、轻量级的 AI 模型网关，专为提升大语言模型（尤其是 **Google Gemini**）的效率与经济性而设计。它实现了 OpenAI 兼容的 API 接口，并内置了创新的 **Echo Retention (回声保留)** 上下文压缩与审计机制。

### 🧠 核心特性

- **Echo Retention (回声保留) V3 算法**: 
  - **Cache Anchor (缓存锚点)**: 锁定 System Prompt 确保极致的 Prompt Caching 命中率（享受 **0.1x** 计费）。
  - **角色感知压缩**: 自动精简远期冗余的工具输出，完整保留核心助手回复与近期记忆，在保持智商的前提下降低 **30%-80%** 的 Token 消耗。
- **可视化审计看板**: 基于真实 Gemini 计费规则的成本审计（Audit），实时展示 Token 节省率与缓存收益。
- **多协议统一转换**: 支持将 OpenAI, Anthropic 等模型统一映射为 OpenAI 兼容格式，一键分发。
- **动态热配置**: 运行中可通过 Web UI 实时切换模型、配置 API Key 及代理设置。

### 🎨 架构流程图

（见上方英文部分 Mermaid 图表，逻辑一致）

---

## 🛠️ 快速开始

### 1. 环境准备
- **Python**: 3.9+
- **网络**: 确保可以连接到大模型 API（或配置内置代理）

### 2. 安装与配置
```bash
# 克隆仓库
git clone https://github.com/oneles/Sen-Gateway.git
cd Sen-Gateway

# 创建并激活虚拟环境
python3 -m venv venv
source venv/bin/activate  # Linux/macOS

# 安装依赖
pip install -r requirements.txt
```

### 3. 设置 API Key
在根目录下创建 `.env` 文件：
```env
GEMINI_API_KEY=你的谷歌API密钥
GEMINI_MODEL=gemini/gemini-1.5-flash
```

---

## 🚀 运行与集成

### 1. 启动服务
```bash
python run.py
```
服务默认运行在 `http://localhost:8000`。

### 2. 在 OpenClaw/客户端中配置
将你的客户端（如 Cursor, OpenWebUI）指向 Sen-Gateway：
- **Base URL**: `http://localhost:8000/v1`
- **API Key**: `any` (网关会自动使用你在数据库/env中配置的真实 Key)

### 3. 访问看板 (Dashboard)
打开浏览器访问：`http://localhost:8000/dashboard`
- **默认账号**: `admin`
- **默认密码**: `88888888`
- **功能**: 查看交互详情、运行成本审计、修改系统配置。

---

## 📁 目录结构

```text
Sen-Gateway/
├── app/                # Core Logic (FastAPI, Pruner, Brain)
├── scripts/            # Tools (Reset Password, DB Check)
├── run.py              # Entry Point
├── requirements.txt    # Dependencies
└── README.md           # Documentation
```

---

## 🛡️ 安全提示
- 生产环境建议通过 `scripts/reset_password.py` 修改默认管理员密码。
- `secret.key` 用于加密存储 API Key，请妥善保管。

---
*Developed by 森哥 (Senge) | Tech Core: Echo Retention (V3)*
