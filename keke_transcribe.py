import re
import unicodedata

from faster_whisper import WhisperModel

MODEL = "/media/u/bak1/6t/haochen/Whisper-Finetune/models/0404_keke_medium_transcribe/ct2/0404_keke_medium_transcribe-ct2"


def clean_asr_text(s: str) -> str:
    """去掉解码/束搜索中偶发的 U+FFFD、音符符号等（库默认会抑制一部分，但未必全覆盖）。"""
    t = unicodedata.normalize("NFKC", s)
    t = t.replace("\ufffd", "")
    t = re.sub(r"[♩♪♫♬♭♮♯]+", "", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

# GPU + FP16（与 README 示例一致，可按需改为 int8 等）
model = WhisperModel(MODEL, device="cuda")

# 中文语音 → 中文文本；明确指定语言可避免检测误差
# 若句尾出现 channel / 英文碎片等，多为尾部静音或低能段触发的“幻觉”。
# vad：减轻尾部长静音段导致的胡编；不要同时开 repetition_penalty + no_repeat_ngram，
# 易在中文子词上扭曲打分、冒出怪符号。若句尾仍重复英文，可再试 initial_prompt 或
# condition_on_previous_text=False。
segments, info = model.transcribe(
    "/media/u/bak1/6t/haochen/whisper_deploy/assets/K279_014.wav",
    task="transcribe",
    language="zh",
    beam_size=5,
    vad_filter=True,
    vad_parameters=dict(min_silence_duration_ms=500),
    condition_on_previous_text=False,
)

# README 重要提示：segments 是生成器，需迭代或 list() 才会真正跑完推理
for segment in segments:
    text = clean_asr_text(segment.text)
    print("[%.2fs -> %.2fs] %s" % (segment.start, segment.end, text))