# 可霖の咖啡店

<p align="center">
  <img src="frontend/kelin.png" alt="可霖" height="400">
</p>

一个实时语音对话的 AI 虚拟角色应用。可霖是一位来自魔法世界的治愈系少女，在她的咖啡店里倾听你的烦恼。

## 功能

- **实时语音对话** — 基于 WebSocket 的全双工语音通信，支持打断
- **流式 ASR + LLM + TTS** — 语音识别、大模型生成、语音合成全链路流式处理，低延迟
- **情感系统** — 根据用户情绪动态调整语速和角色动画（开心、难过、惊讶、害羞等）
- **角色立绘动画** — 待机呼吸、聆听、思考、说话、打招呼、开心蹦跳、害羞、点头、惊讶
- **白天/夜间模式** — 一键切换，自动记忆
- **对话记录** — 自动保存到浏览器 localStorage，刷新不丢失

## 技术栈

| 模块 | 技术 |
|------|------|
| 前端 | 原生 HTML/CSS/JS，AudioWorklet |
| 后端 | Python，FastAPI，WebSocket |
| 语音识别 | 阿里云 Paraformer 实时 ASR |
| 大模型 | 通义千问 Qwen-Turbo |
| 语音合成 | Qwen3 TTS 实时语音克隆 |
| 部署 | Docker，Cloudflare Tunnel |

## 快速开始

### 环境要求

- Python 3.11+
- 阿里云 DashScope API Key

### 本地运行

```bash
# 克隆项目
git clone https://github.com/Ludwig1827/K0.git
cd K0

# 配置 API Key
echo "DASHSCOPE_API_KEY=你的key" > backend/.env

# 安装依赖
pip install -r backend/requirements.txt

# 启动服务
cd backend
python main.py
```

访问 http://localhost:8080

### Docker 部署

```bash
# 配置 API Key
echo "DASHSCOPE_API_KEY=你的key" > backend/.env

# 构建并运行
docker build -t kelin-cafe .
docker run -d --name kelin-cafe --restart always -p 8080:8080 kelin-cafe
```

### 云服务器部署（HTTPS）

浏览器麦克风权限要求 HTTPS。推荐使用 Cloudflare Tunnel（免费）：

```bash
# 安装 cloudflared
wget https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
dpkg -i cloudflared-linux-amd64.deb

# 启动隧道
cloudflared tunnel --url http://localhost:8080
```

会输出一个 `https://xxx.trycloudflare.com` 地址，分享给朋友即可使用。

## 项目结构

```
K0/
├── backend/
│   ├── main.py              # FastAPI 服务入口
│   ├── config.py            # 配置与角色设定
│   ├── voice_session.py     # 语音会话编排
│   ├── asr_service.py       # 语音识别服务
│   ├── llm_service.py       # 大模型服务
│   ├── tts_service.py       # 语音合成服务
│   └── requirements.txt     # Python 依赖
├── frontend/
│   ├── index.html           # 前端页面
│   ├── audio-processor.js   # AudioWorklet 音频采集
│   └── kelin.png            # 角色立绘
└── Dockerfile               # Docker 构建文件
```

## 许可

MIT
