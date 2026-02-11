# Sen-Gateway 🚀

**Sen-Gateway** 是一个高性能、轻量级的 AI 模型网关，专为提升大语言模型（尤其是 Google Gemini）的效率与经济性而设计。它实现了 OpenAI 兼容的 API 接口，并内置了创新的上下文压缩与审计机制。

## 🌟 核心特性

- **Echo Retention (回声保留) 算法**: 针对长文本对话设计的智能压缩策略。
  - **Cache Anchor**: 锁定 System Prompt 确保极致的 Prompt Caching 命中率（享受 0.1x 计费）。
  - **角色感知压缩**: 自动精简远期冗余的工具输出，保留核心助手回复与近期记忆。
- **可视化审计看板**: 基于真实 Gemini 计费规则的成本审计（Audit），实时展示 Token 节省率与缓存收益。
- **协议转换与分发**: 支持将 OpenAI, Anthropic 等模型统一映射为 OpenAI 兼容格式。
- **动态热配置**: 无需修改代码即可在 Web UI 切换模型、API Key 及代理设置。

## 🛠️ 安装与环境

### 1. 环境依赖
- Python 3.9+
- 推荐使用虚拟环境

```bash
cd Sen-Gateway
python3 -m venv venv
source venv/bin/activate  # Linux/macOS
pip install -r requirements.txt
```

### 2. 配置文件
创建 `.env` 文件并配置初始密钥：
```env
GEMINI_API_KEY=你的API_KEY
GEMINI_MODEL=gemini/gemini-1.5-flash
```

### 3. 启动服务
```bash
python main.py
```
默认运行在 `http://localhost:8000`。

## ⚙️ 在 OpenClaw 中配置

将 OpenClaw 的请求路由至 Sen-Gateway 即可享受加速与省钱：

1. **修改 OpenClaw Provider 配置**:
   在 OpenClaw 的模型配置文件中，将 `base_url` 指向网关地址：
   ```yaml
   base_url: "http://localhost:8000/v1"
   api_key: "any" # 实际 Key 由 Sen-Gateway 管理
   ```

2. **访问看板**:
   打开 `http://localhost:8000/dashboard` 即可查看流量审计（默认账号：`admin`，密码：`88888888`）。

## 📁 项目结构
- `main.py`: 网关入口与路由逻辑
- `pruner.py`: Echo Retention 压缩算法核心
- `dashboard.py`: 可视化看板后端 API
- `brain.py`: 模型交互层（适配 LiteLLM）
- `database.py`: 审计日志与配置存储 (SQLite)

---
*Developed by 森哥 (Senge) with 🕶️ vibe.*
