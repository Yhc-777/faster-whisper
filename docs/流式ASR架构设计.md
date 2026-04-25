# 基于 faster-whisper 的流式 ASR 架构设计

本文设计一套面向 `faster-whisper` 的 streaming ASR 架构，目标是在保持较高识别质量的前提下，提供可落地、可扩展、可观测的低延迟语音转写服务。参考资料包括 SayToWords 的 [Whisper 分类文章](https://www.saytowords.com/blogs/categories/Whisper/) 与 [Real-Time Streaming with Whisper](https://www.saytowords.com/blogs/Real-Time-Streaming-with-Whisper/)；其中关于 Whisper 非原生流式、需要通过滑动窗口和重叠缓冲实现低延迟识别的思路，是本设计的核心基础。

## 1. 设计目标

### 1.1 功能目标

- 支持浏览器麦克风、文件伪流式、后端音频流三类输入。
- 支持实时返回 partial result，并在语音稳定后返回 final result。
- 支持中文 `transcribe` 主路径，并保留多语言和 `translate` 扩展能力。
- 支持 VAD、滑动窗口、重叠去重、时间戳修正、热词提示、文本清洗。
- 支持单机 GPU 服务优先落地，并预留多实例水平扩展能力。

### 1.2 性能目标

| 指标 | 建议目标 |
| --- | --- |
| 首字延迟 | 1.0-3.0 秒，取决于 chunk/window 配置 |
| partial 更新间隔 | 500ms-1500ms |
| final 延迟 | 语音结束后 500ms-2000ms |
| 音频采样率 | 16kHz mono PCM |
| 单连接窗口长度 | 2-5 秒 |
| 窗口重叠 | 0.5-1.0 秒 |

### 1.3 工程目标

- 后端负责音频接入、缓冲、切窗、推理、结果拼接和监控。
- 前端负责音频采集、重采样、编码、WebSocket 传输和实时字幕展示。
- 推理模型常驻进程，避免每次请求重复加载模型。
- 对 GPU 推理资源进行队列化和限流，避免并发连接直接打爆显存。

## 2. 推荐目录结构

后续开发时建议在仓库根目录新增 `backend` 与 `frontend` 两个目录，文档继续放在 `docs` 下：

```text
faster-whisper/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── config.py
│   │   ├── api/
│   │   │   └── websocket.py
│   │   ├── audio/
│   │   │   ├── resampler.py
│   │   │   ├── ring_buffer.py
│   │   │   └── vad.py
│   │   ├── asr/
│   │   │   ├── engine.py
│   │   │   ├── session.py
│   │   │   ├── stitcher.py
│   │   │   └── postprocess.py
│   │   ├── schemas/
│   │   │   └── messages.py
│   │   └── observability/
│   │       └── metrics.py
│   ├── tests/
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── audio/
│   │   │   ├── capture.ts
│   │   │   ├── resample.ts
│   │   │   └── pcm.ts
│   │   ├── asr/
│   │   │   ├── client.ts
│   │   │   └── protocol.ts
│   │   └── components/
│   │       └── LiveTranscript.tsx
│   └── package.json
└── docs/
    └── 流式ASR架构设计.md
```

该结构把接入层、音频处理、ASR 推理、拼接后处理分开，避免后续把流式状态、模型调用和 WebSocket 处理写在同一个文件里。

## 3. 总体架构

### 3.1 数据流

```text
Browser Microphone
  -> Web Audio / AudioWorklet
  -> 16kHz mono PCM chunk
  -> WebSocket
  -> Backend Session
  -> Ring Buffer
  -> VAD / Segmenter
  -> Sliding Window Builder
  -> faster-whisper Inference Queue
  -> Dedup / Timestamp Stitcher
  -> Partial / Final Result
  -> Browser Subtitle UI
```

### 3.2 后端核心组件

| 组件 | 职责 |
| --- | --- |
| `WebSocket Gateway` | 管理连接、鉴权、协议消息、心跳、断开清理 |
| `StreamingSession` | 每个连接一个会话，保存音频缓冲、语言、窗口参数、已提交文本 |
| `RingBuffer` | 保存最近 N 秒 PCM，支持按时间截取滑动窗口 |
| `Segmenter` | 按固定窗口或 VAD 触发生成待识别音频片段 |
| `InferenceQueue` | 将多个 session 的请求串行或小批量送入 GPU |
| `FasterWhisperEngine` | 常驻加载 `WhisperModel`，封装 `transcribe` 参数 |
| `Stitcher` | 处理重叠文本去重、时间戳平移、partial 到 final 的状态转换 |
| `PostProcessor` | 清洗异常字符、空白、音乐符号、重复尾巴等 |
| `Metrics` | 记录延迟、RTF、队列长度、GPU 使用、错误率 |

### 3.3 为什么不是“真正逐帧解码”

Whisper / faster-whisper 的接口以一段音频为输入，并不是像传统流式 RNN-T/CTC 那样逐帧输出 token。因此实际工程中通常使用“短窗口 + 重叠 + 增量拼接”的准流式方案。SayToWords 的实时 Whisper 文章也强调了这一点：Whisper 不是原生 streaming 模型，需要依靠 sliding windows、overlap 和 buffering 取得实时体验。

## 4. 流式切窗策略

### 4.1 推荐默认参数

```text
sample_rate = 16000
channels = 1
chunk_ms = 100
window_sec = 3.0
hop_sec = 1.0
overlap_sec = 1.0
min_speech_sec = 0.3
max_buffer_sec = 30.0
```

含义：

- 前端每 `100ms` 发送一包 PCM，降低 WebSocket 包数量和端到端等待。
- 后端每累计到 `window_sec` 音频后开始第一次推理。
- 后续每隔 `hop_sec` 生成一次新窗口。
- 每个窗口保留 `overlap_sec` 与上一窗口重叠，降低边界掉字概率。
- session 的 ring buffer 最多保留 `max_buffer_sec`，避免长连接内存无限增长。

### 4.2 固定滑窗模式

适合实时字幕、会议记录等连续语音场景：

```text
窗口 1: 0.0s - 3.0s
窗口 2: 1.0s - 4.0s
窗口 3: 2.0s - 5.0s
窗口 4: 3.0s - 6.0s
```

优点是输出稳定、逻辑简单；缺点是无声段也可能触发推理，增加 GPU 消耗，并且尾部静音可能导致幻觉文本。

### 4.3 VAD 辅助模式

适合对成本和稳定性要求更高的场景：

- 使用前端能量检测或后端 Silero VAD 判断 speech / silence。
- speech 开始后进入 active 状态，持续滑窗识别。
- 检测到连续静音 `500ms-1000ms` 后，触发当前 utterance 的 final。
- final 后清理部分上下文，只保留很短的 overlap。

`faster-whisper` 自身支持 `vad_filter=True`，但该参数主要用于一次性音频的静音过滤。流式服务中建议把“是否触发推理、何时提交 final”的 VAD 放在业务层，`vad_filter=True` 作为模型内部的辅助过滤手段谨慎开启。

### 4.4 长语音上下文策略

Whisper 对上下文较敏感，`condition_on_previous_text=True` 可能提升连贯性，但在流式场景中也可能把上一个窗口的错误继续传播，甚至在静音或噪声中产生重复文本。建议：

- 默认 `condition_on_previous_text=False`，优先保证 partial 稳定。
- 对会议、访谈等长上下文可尝试维护 `initial_prompt`，但只注入最近确定的 final 文本摘要或术语。
- 不要把所有历史文本无限拼入 prompt，容易增加幻觉和延迟。

## 5. faster-whisper 推理设计

### 5.1 模型加载

当前环境路径：

```bash
conda activate /media/u/bak1/6t/haochen/envs/faster-whisper/
```

后端启动时加载模型一次：

```python
from faster_whisper import WhisperModel

model = WhisperModel(
    "/media/u/bak1/6t/haochen/faster-whisper/models/faster-whisper-large-v3",
    device="cuda",
    compute_type="float16",
)
```

如果使用你已有的微调 CT2 模型，可替换为类似路径：

```text
/media/u/bak1/6t/haochen/Whisper-Finetune/models/0404_keke_medium_transcribe/ct2/0404_keke_medium_transcribe-ct2
```

模型加载必须放在进程级单例中，不应放进 WebSocket handler 内部。

### 5.2 推荐转写参数

中文实时转写建议从以下参数开始：

```python
segments, info = model.transcribe(
    audio_array,
    task="transcribe",
    language="zh",
    beam_size=1,
    best_of=1,
    temperature=0.0,
    vad_filter=False,
    condition_on_previous_text=False,
    word_timestamps=True,
)
```

说明：

- `beam_size=1`：流式 partial 优先低延迟，先用 greedy 解码；final 可选 `beam_size=3` 或 `5` 二次确认。
- `language="zh"`：明确语言，避免短窗口语言检测不稳定。
- `condition_on_previous_text=False`：降低错误传播。
- `word_timestamps=True`：便于对 overlap 区域做更稳的时间戳拼接。
- `vad_filter=False`：流式触发交给业务层；若尾部幻觉明显，可在 final 阶段再试 `vad_filter=True`。

### 5.3 partial 与 final 双通道

建议同一段语音采用两级推理：

| 阶段 | 触发 | 参数 | 用途 |
| --- | --- | --- | --- |
| partial | 每个 hop | `beam_size=1`、短窗口 | 快速刷新字幕 |
| final | VAD 判断语音结束或用户停止 | `beam_size=3/5`、完整 utterance | 生成稳定结果 |

这样可以兼顾实时体验和最终文本质量。partial 允许被覆盖，final 一旦提交后只在明确需要纠错时更新。

### 5.4 推理队列

GPU 推理不建议每个 WebSocket session 直接并发调用模型。推荐后端维护一个全局 `asyncio.Queue`：

```text
StreamingSession -> InferenceRequest -> asyncio.Queue -> Worker -> FasterWhisperEngine
```

队列请求字段：

```text
request_id
session_id
audio
start_time
end_time
is_final
language
task
decode_options
created_at
```

单 GPU 初期使用 1 个 worker 最稳；如果模型和显存允许，再增加 worker 或改为 micro-batch。`BatchedInferencePipeline` 更适合离线批处理，流式场景要谨慎使用，因为 batching 会增加等待时间。

## 6. 拼接与去重

### 6.1 需要解决的问题

滑窗 overlap 会带来重复文本：

```text
窗口 1: 今天下午我们讨论项目进度
窗口 2: 我们讨论项目进度和上线计划
```

期望输出：

```text
今天下午我们讨论项目进度和上线计划
```

### 6.2 文本级去重

初期可以使用文本后缀/前缀最大重叠匹配：

```text
committed_text_suffix 与 new_text_prefix 比较
找到最长公共部分后只追加新增部分
```

建议规则：

- 对中文按字符比较，对英文按 token/word 比较。
- 最小重叠长度建议中文 `4-8` 字，英文 `2-4` 词。
- 对标点、空格、全半角先做归一化。
- 若匹配置信度不足，不提交为 final，只作为 partial 展示。

### 6.3 时间戳级拼接

如果启用 `word_timestamps=True`，应优先使用时间戳做拼接：

- 将每个窗口内 segment / word 时间加上窗口的全局 `start_time`。
- 丢弃早于 `last_committed_time - tolerance` 的词。
- 对 `overlap_sec` 内的词做文本相似度去重。
- final 阶段按全局时间重新排序。

时间戳级拼接比纯文本拼接更适合长语音和多说话人场景。

### 6.4 partial 稳定策略

不要把每次窗口结果都立即永久提交。建议分三层状态：

| 状态 | 含义 |
| --- | --- |
| `committed` | 已 final，不再改变 |
| `stable_partial` | 连续两次以上窗口都出现，可展示为较稳定文本 |
| `volatile_partial` | 最新窗口尾部文本，允许频繁变化 |

前端展示时可把 `committed` 正常显示，`partial` 用浅色或光标样式显示。

## 7. WebSocket 协议设计

### 7.1 连接地址

```text
ws://host:port/api/v1/asr/stream
```

### 7.2 客户端到服务端消息

开始消息：

```json
{
  "type": "start",
  "session_id": "client-generated-id",
  "sample_rate": 16000,
  "channels": 1,
  "encoding": "pcm_s16le",
  "language": "zh",
  "task": "transcribe",
  "window_sec": 3.0,
  "hop_sec": 1.0
}
```

音频消息建议使用 binary frame 发送原始 PCM；如果必须 JSON，可以 base64，但会增加体积和 CPU 成本。

结束消息：

```json
{
  "type": "stop"
}
```

心跳消息：

```json
{
  "type": "ping",
  "timestamp": 1710000000.123
}
```

### 7.3 服务端到客户端消息

partial：

```json
{
  "type": "partial",
  "session_id": "xxx",
  "text": "今天下午我们讨论",
  "start": 0.0,
  "end": 3.0,
  "revision": 12,
  "latency_ms": 860
}
```

final：

```json
{
  "type": "final",
  "session_id": "xxx",
  "text": "今天下午我们讨论项目进度和上线计划。",
  "start": 0.0,
  "end": 6.8,
  "revision": 15,
  "latency_ms": 1280
}
```

错误：

```json
{
  "type": "error",
  "code": "AUDIO_FORMAT_UNSUPPORTED",
  "message": "Only 16kHz mono pcm_s16le is supported."
}
```

## 8. 前端设计

### 8.1 音频采集

浏览器端建议使用 `AudioWorklet`，不要再使用已过时的 `ScriptProcessorNode`。流程：

```text
navigator.mediaDevices.getUserMedia
  -> AudioContext
  -> AudioWorkletProcessor
  -> Float32 PCM
  -> 16kHz resample
  -> Int16 PCM
  -> WebSocket binary frame
```

### 8.2 前端职责边界

前端只做轻量处理：

- 采集麦克风并请求权限。
- 重采样到 16kHz mono。
- 按 `chunk_ms` 切包发送。
- 展示 partial / final。
- 处理断线重连、停止录音、错误提示。

前端不负责最终 VAD 和拼接逻辑，避免不同浏览器行为导致结果不一致。可以做简单能量检测用于 UI 麦克风音量条，但不要作为后端 final 的唯一依据。

### 8.3 UI 展示

建议分为：

- 已确认文本区：展示 final。
- 实时浮动文本区：展示 partial。
- 状态栏：展示连接状态、延迟、识别语言、是否正在讲话。

## 9. 后端设计

### 9.1 技术选型

推荐：

- Web 框架：`FastAPI`
- WebSocket：FastAPI / Starlette 原生 WebSocket
- 音频数组：`numpy`
- 重采样：优先前端完成；后端兜底可用 `scipy` 或 `soxr`
- ASR：当前仓库本地 `faster_whisper`
- 监控：Prometheus metrics + 日志

### 9.2 Session 生命周期

```text
CONNECT
  -> receive start
  -> create StreamingSession
  -> receive audio chunks
  -> append RingBuffer
  -> maybe enqueue partial inference
  -> maybe enqueue final inference
  -> send partial/final
  -> receive stop or disconnect
  -> flush final
  -> release session
```

### 9.3 并发与限流

必须设置：

- 最大并发连接数。
- 每连接最大缓冲秒数。
- 推理队列最大长度。
- 单用户最大连接数。
- 请求超时和心跳超时。

队列满时可以：

- 丢弃旧 partial，只保留最新 partial。
- final 请求优先级高于 partial。
- 对低优先级 session 降低 partial 频率。

### 9.4 错误处理

常见错误：

| 错误 | 处理 |
| --- | --- |
| 非 16kHz 音频 | 拒绝或后端重采样 |
| WebSocket 断开 | flush 已有音频，清理 session |
| GPU OOM | 返回错误，降低并发或切换 int8 |
| 推理超时 | 丢弃 partial，保留 final |
| 空音频/静音 | 不返回文本或返回空 partial |

## 10. 模型与参数选型

### 10.1 模型大小

实时服务的模型选择需要平衡速度和准确率：

| 模型 | 优点 | 缺点 | 建议场景 |
| --- | --- | --- | --- |
| `base/small` | 延迟低 | 准确率较弱 | 实时字幕、弱 GPU |
| `medium` | 质量和速度折中 | 显存需求更高 | 中文实时转写主力 |
| `large-v3` | 准确率高 | 延迟和显存压力大 | final 二次确认、离线增强 |
| 微调 CT2 模型 | 领域适配好 | 泛化需验证 | 固定业务语料 |

如果 GPU 资源足够，可以使用“两模型策略”：

- partial 使用 `small/medium`。
- final 使用 `large-v3` 或领域微调模型。

### 10.2 compute_type

| compute_type | 说明 |
| --- | --- |
| `float16` | GPU 上质量和速度较均衡 |
| `int8_float16` | 降低显存，速度通常较好，质量需测试 |
| `int8` | CPU 或显存紧张时可用 |

建议先以 `float16` 建立质量基线，再测试 `int8_float16`。

## 11. 质量优化

### 11.1 音频前处理

- 输入统一为 16kHz mono。
- 控制音量，避免削波。
- 对强噪声场景可在前端或后端加入轻量降噪，但要验证是否损伤语音。
- 对电话音频可保留 8kHz 到 16kHz 的重采样，但准确率会低于高质量麦克风。

### 11.2 文本后处理

可复用当前脚本中的思路：

- `unicodedata.normalize("NFKC", text)`
- 去掉 `\ufffd`
- 去掉音乐符号 `♩♪♫♬♭♮♯`
- 合并多余空白
- 对中文标点做最终规范化

### 11.3 幻觉控制

流式 Whisper 常见问题是尾部静音、噪声或短窗口导致幻觉。建议：

- VAD 判断静音后停止继续对静音推理。
- `condition_on_previous_text=False` 作为默认。
- 对很短音频片段不触发推理。
- final 阶段用完整 utterance 重跑，而不是直接信任最后一个 partial。
- 检测重复 n-gram，超过阈值时降级或丢弃尾部。

## 12. 可观测性

建议采集以下指标：

| 指标 | 含义 |
| --- | --- |
| `asr_active_sessions` | 当前连接数 |
| `asr_audio_buffer_seconds` | 每个 session 缓冲长度 |
| `asr_inference_queue_size` | 推理队列长度 |
| `asr_partial_latency_ms` | partial 端到端延迟 |
| `asr_final_latency_ms` | final 端到端延迟 |
| `asr_realtime_factor` | 推理耗时 / 音频时长 |
| `asr_gpu_memory_bytes` | GPU 显存 |
| `asr_error_total` | 错误计数 |

日志中至少包含：

```text
session_id
request_id
audio_start
audio_end
is_final
inference_ms
queue_wait_ms
text_length
error_code
```

## 13. 测试方案

### 13.1 单元测试

- `RingBuffer`：追加、截取、过期清理。
- `Segmenter`：窗口触发、hop 计算、静音 final。
- `Stitcher`：中文重叠去重、英文重叠去重、时间戳平移。
- `PostProcessor`：异常字符清洗、空白归一化。
- `Protocol`：start/stop/error 消息校验。

### 13.2 集成测试

- 使用本地 wav 文件模拟 100ms chunk 发送。
- 检查服务端是否按预期返回 partial 和 final。
- 检查断开连接后 session 是否清理。
- 检查长音频下内存是否稳定。

### 13.3 性能测试

至少覆盖：

- 单连接 10 分钟连续语音。
- 5/10/20 并发连接。
- 不同 `window_sec` 与 `hop_sec` 参数组合。
- `beam_size=1` 与 `beam_size=5` 的延迟和准确率对比。
- `float16` 与 `int8_float16` 的显存和质量对比。

建议记录：

```text
RTF
P50/P95/P99 partial latency
P50/P95/P99 final latency
GPU utilization
GPU memory
WER/CER
```

## 14. 部署建议

### 14.1 单机开发部署

```bash
cd /media/u/bak1/6t/haochen/faster-whisper
conda activate /media/u/bak1/6t/haochen/envs/faster-whisper/

# 后续 backend 建好后
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000
```

### 14.2 生产部署

推荐一张 GPU 对应一个或少量 ASR worker 进程：

```text
Nginx / Gateway
  -> backend instance 1 -> GPU 0
  -> backend instance 2 -> GPU 1
  -> backend instance 3 -> GPU 2
```

WebSocket 是有状态长连接，负载均衡需要 sticky session。扩容时按 GPU worker 数量扩，不建议多个进程无控制地抢同一张 GPU。

### 14.3 配置项

建议所有关键参数走环境变量或配置文件：

```text
ASR_MODEL_PATH
ASR_DEVICE
ASR_COMPUTE_TYPE
ASR_LANGUAGE
ASR_TASK
ASR_WINDOW_SEC
ASR_HOP_SEC
ASR_OVERLAP_SEC
ASR_MAX_SESSIONS
ASR_QUEUE_SIZE
ASR_ENABLE_WORD_TIMESTAMPS
```

## 15. 迭代路线

### 阶段 1：最小可用版本

- FastAPI WebSocket 接入。
- 前端发送 16kHz mono PCM。
- 后端固定 3 秒窗口、1 秒 hop。
- `beam_size=1` 返回 partial。
- stop 时整段 final。

### 阶段 2：稳定性增强

- 加入 VAD 状态机。
- 加入 overlap 文本去重。
- 加入异常文本清洗。
- 加入队列、限流和超时。
- 加入基础 metrics。

### 阶段 3：质量增强

- word timestamp 拼接。
- partial/final 双参数推理。
- final 二次确认。
- 热词 prompt / 领域词表。
- CER/WER 自动评估集。

### 阶段 4：生产化

- 多 GPU 多实例部署。
- sticky session 负载均衡。
- Prometheus/Grafana 监控。
- 压测和容量模型。
- 鉴权、审计和数据脱敏。

## 16. 关键实现原则

- 模型进程常驻，不在请求内加载。
- partial 优先低延迟，final 优先准确率。
- 业务层负责流式状态，`faster-whisper` 只作为窗口级推理引擎。
- VAD 用于减少无效推理和尾部幻觉，但不要过早切断语音。
- overlap 是必须的，拼接去重也是必须的。
- GPU 调用必须有队列和限流。
- 所有窗口结果都带全局时间，方便调试、拼接和前端展示。
- 长期运行必须关注内存、队列长度、GPU 显存和断连清理。

