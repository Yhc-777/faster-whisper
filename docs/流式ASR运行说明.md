# 流式 ASR 运行说明

本文说明如何运行本仓库新增的 streaming ASR MVP。架构设计见 [流式ASR架构设计.md](./流式ASR架构设计.md)。

## 1. 后端

进入仓库并激活你的 conda 环境：

```bash
cd /media/u/bak1/6t/haochen/faster-whisper
conda activate /media/u/bak1/6t/haochen/envs/faster-whisper/
```

安装后端依赖：

```bash
pip install -r backend/requirements.txt
pip install -e .
```

如需使用默认模型路径，无需额外配置：

```text
/media/u/bak1/6t/haochen/faster-whisper/models/faster-whisper-large-v3
```

如需使用微调后的 CT2 模型：

```bash
export ASR_MODEL_PATH=/media/u/bak1/6t/haochen/Whisper-Finetune/models/0404_keke_medium_transcribe/ct2/0404_keke_medium_transcribe-ct2
```

启动后端：

```bash
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/health
```

WebSocket 地址：

```text
ws://127.0.0.1:8000/api/v1/asr/stream
```

## 2. 前端

进入前端目录并安装依赖：

```bash
cd /media/u/bak1/6t/haochen/faster-whisper/frontend
npm install
```

开发模式：

```bash
npm run dev
```

默认访问 Vite 输出的地址，例如：

```text
http://127.0.0.1:5173
```

生产构建：

```bash
npm run build
```

构建完成后，后端会自动尝试从以下目录提供静态页面：

```text
/media/u/bak1/6t/haochen/faster-whisper/frontend/dist
```

此时可访问：

```text
http://127.0.0.1:8000/
```

## 3. 常用配置

后端配置通过环境变量控制：

```bash
export ASR_MODEL_PATH=/path/to/ct2-model
export ASR_DEVICE=cuda
export ASR_COMPUTE_TYPE=float16
export ASR_LANGUAGE=zh
export ASR_WINDOW_SEC=3.0
export ASR_HOP_SEC=1.0
export ASR_QUEUE_SIZE=32
export ASR_MAX_SESSIONS=8
```

低显存时可尝试：

```bash
export ASR_COMPUTE_TYPE=int8_float16
```

## 4. 协议摘要

客户端先发送 JSON start 消息：

```json
{
  "type": "start",
  "session_id": "demo",
  "sample_rate": 16000,
  "channels": 1,
  "encoding": "pcm_s16le",
  "language": "zh",
  "task": "transcribe",
  "window_sec": 3.0,
  "hop_sec": 1.0
}
```

随后用 binary frame 发送 little-endian `pcm_s16le` 音频。停止时发送：

```json
{
  "type": "stop"
}
```

服务端会返回 `partial` 和 `final` 消息。

## 5. 当前实现边界

- 这是可运行的 MVP，已实现固定滑窗、推理队列、partial/final、overlap 文本拼接和前端麦克风采集。
- VAD 当前是轻量能量 VAD，用于会话状态扩展；final 主要由客户端 stop 触发。
- 多说话人分离、说话人识别、复杂热词 bias、Prometheus 原生格式还未实现。
- 前端需要浏览器允许麦克风权限；生产环境使用 HTTPS 时，WebSocket 地址应使用 `wss://`。

