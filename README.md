# Sen-Gateway 🚀

**Sen-Gateway** 是一个高性能、轻量级的 AI 模型网关，专为提升大语言模型（尤其是 Google Gemini）的效率与经济性而设计。它实现了 OpenAI 兼容的 API 接口，并内置了创新的 **Echo Retention (回声保留)** 上下文压缩与审计机制。

---

## 🌟 核心特性

- **Echo Retention (回声保留) V3 算法**: 
  - **Cache Anchor**: 锁定 System Prompt 确保极致的 Prompt Caching 命中率（享受 **0.1x** 计费）。
  - **角色感知压缩**: 自动精简远期冗余的工具输出，完整保留核心助手回复与近期记忆，在保持智商的前提下降低 **30%-80%** 的 Token 消耗。
- **可视化审计看板**: 基于真实 Gemini 计费规则的成本审计（Audit），实时展示 Token 节省率与缓存收益。
- **多协议统一转换**: 支持将 OpenAI, Anthropic 等模型统一映射为 OpenAI 兼容格式，一键分发。
- **动态热配置**: 运行中可通过 Web UI 实时切换模型、配置 API Key 及代理设置。

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

## 📁 目录结构说明

```text
Sen-Gateway/
├── app/                # 核心业务逻辑 (FastAPI, 剪枝算法, 模型适配)
├── scripts/            # 工具脚本 (密码重置、数据库检查、压力测试)
├── run.py              # 服务启动入口
├── requirements.txt    # 项目依赖清单
└── README.md           # 使用说明
```

---

## 🛡️ 安全提示
- 生产环境建议通过 `scripts/reset_password.py` 修改默认管理员密码。
- `secret.key` 用于加密存储 API Key，请妥善保管。

---
*Developed by 森哥 (Senge) | 技术核心：Echo Retention (V3)*
