# 使用本地 CTranslate2 模型与各任务（transcribe / translate）

本文结合仓库根目录 [README.md](../README.md) 的说明，说明如何把 **本机已转换好的 CTranslate2（ct2）模型目录** 传给 `faster-whisper`，以及如何通过参数区分**转写**与**翻译**两类任务。

## 1. 本地模型路径

你当前的 ct2 模型目录为：

```text
/media/u/bak1/6t/haochen/Whisper-Finetune/models/0404_keke_medium_transcribe/ct2/0404_keke_medium_transcribe-ct2
```

在代码里，把 `WhisperModel` 的第一个参数设为**该目录的字符串路径**即可（与 README「Load a converted model」中 `WhisperModel("whisper-large-v3-ct2")` 的用法相同，只是换成绝对路径）：

- 该目录中应包含 CTranslate2 导出的模型文件，以及通常随模型一并放置的 `tokenizer.json`、`preprocessor_config.json` 等（与 README「Model conversion」章节一致）。

## 2. 环境（与本仓库文档一致）

安装与 GPU 运行库配置参见同目录下的 [环境搭建.md](./环境搭建.md)。README 亦说明：`faster-whisper` 不依赖系统安装 FFmpeg，音频由 PyAV 处理。

在已激活的 conda 环境中，确保能 `import faster_whisper`（例如 `pip install -e .` 安装本仓库）。

## 3. 两类任务分别是什么

`WhisperModel.transcribe(...)` 的第二个核心参数是 `task`（见源码 `faster_whisper/transcribe.py` 文档）：

| `task` 取值 | 含义（与 OpenAI Whisper 一致） |
| --- | --- |
| `transcribe`（默认） | 把语音**转写**成**与输入语言一致**的文本。需指定 `language=语言代码`，或让模型在音频前 30 秒**自动检测**语言。 |
| `translate` | 把**非英语**语音**翻译成英语**文本（输出为英语）。 |

支持的语言代码为 Whisper 的 ISO 639-1 等集合（如中文为 `zh`），与 `faster_whisper` 内置的 `Tokenizer` 校验一致。

**与微调检查点名称的关系**：你目录名含 `transcribe`，一般表示该 checkpoint 按**转写**目标训练/微调；**主路径应使用 `task="transcribe"`**，并设好 `language`（例如中文转写用 `language="zh"`）。若未做「语音译成英语」的翻译任务微调，使用 `task="translate"` 往往**不可靠**，仅作协议层说明，不保证与官方 large 模型同质量。

## 4. 示例：加载本地模型并做转写（transcribe）

```python
from faster_whisper import WhisperModel

MODEL = "/media/u/bak1/6t/haochen/Whisper-Finetune/models/0404_keke_medium_transcribe/ct2/0404_keke_medium_transcribe-ct2"

# GPU + FP16（与 README 示例一致，可按需改为 int8 等）
model = WhisperModel(MODEL, device="cuda", compute_type="float16")

# 中文语音 → 中文文本；明确指定语言可避免检测误差
segments, info = model.transcribe(
    "audio.mp3",
    task="transcribe",
    language="zh",
    beam_size=5,
)

# README 重要提示：segments 是生成器，需迭代或 list() 才会真正跑完推理
for segment in segments:
    print("[%.2fs -> %.2fs] %s" % (segment.start, segment.end, segment.text))
```

不指定 `language` 时，库会在**前 30 秒**音频上检测语言，再整段转写（行为见 `transcribe` 文档字符串）。

## 5. 示例：翻译任务（translate，输出英语）

在**多语言** Whisper 类模型上，`translate` 表示「非英 → 英」：

```python
segments, info = model.transcribe(
    "non_english.mp3",
    task="translate",
    language="zh",  # 源语言是中文
    beam_size=5,
)

for segment in segments:
    print("[%.2fs -> %.2fs] %s" % (segment.start, segment.end, segment.text))
```

**注意**：`language` 填的是**源语音语言**，不是目标语；目标语在 `translate` 下固定为英语。

## 6. 批处理与可选功能（与 README 一致）

- **批处理加速**：`BatchedInferencePipeline` 的 `transcribe` 可视为 `WhisperModel.transcribe` 的批处理替代品，**同样使用上面加载的本地 `WhisperModel` 路径**即可。
- **词级时间戳**：`word_timestamps=True`。
- **VAD**：`vad_filter=True`，可配合 `vad_parameters` 调参（README 有示例）。

## 7. 与 README 其它章节的对应关系

- **从 Hugging Face 名称下载**：`WhisperModel("large-v3")`；**本机目录**：`WhisperModel(本地ct2目录)`。见 README「Load a converted model」。
- **自己转换 PyTorch/Transformers 模型为 ct2**：`ct2-transformers-converter` 或转换 API，见 README「Model conversion」；转换得到的 `output_dir` 即可作为上述 `MODEL` 路径使用。

若某路径加载报错，先确认该路径为**目录**且含 CTranslate2 的 `model.bin`（或分片）及 `config.json` 等，并尽量保留转换时 `--copy_files` 所复制的 tokenizer 与预处理器文件。
