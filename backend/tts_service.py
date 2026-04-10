import asyncio
import re
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, ResultCallback, AudioFormat
from config import DASHSCOPE_API_KEY, VOICE_ID, TTS_MODEL

dashscope.api_key = DASHSCOPE_API_KEY

# Sentence boundary pattern: Chinese/English punctuation
SENTENCE_END = re.compile(r"[。！？；，\n.!?;,]")
# Max chars to buffer before forcing a flush (lower = faster first audio)
MAX_BUFFER = 15


class TTSService:
    """Wraps CosyVoice streaming TTS with voice cloning. Feeds LLM text deltas, emits PCM audio."""

    def __init__(self):
        self.audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._tts: SpeechSynthesizer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._text_buffer = ""
        self._cancelled = False

    def start(self, speed: float = 0.95):
        """Initialize a new TTS streaming session with optional speed."""
        self._loop = asyncio.get_running_loop()
        self._cancelled = False
        self._text_buffer = ""
        callback = _Callback(self)
        self._tts = SpeechSynthesizer(
            model=TTS_MODEL,
            voice=VOICE_ID,
            format=AudioFormat.PCM_24000HZ_MONO_16BIT,
            speech_rate=speed,
            callback=callback,
        )

    def feed_text(self, text: str):
        """Feed LLM text delta directly to TTS. Server decides when to commit."""
        if self._cancelled or not self._tts:
            return
        if text:
            self._tts.streaming_call(text)

    def flush(self):
        """Signal end of text and complete TTS stream."""
        if self._tts:
            self._tts.streaming_complete()

    def cancel(self):
        """Cancel current TTS generation."""
        self._cancelled = True
        self._text_buffer = ""
        if self._tts:
            try:
                self._tts.streaming_cancel()
            except Exception:
                pass
            self._tts = None

    def stop(self):
        """Stop and clean up."""
        self.cancel()

    def _on_audio(self, data: bytes):
        """Called from callback thread — schedule into async queue."""
        if self._loop and not self._cancelled:
            self._loop.call_soon_threadsafe(self.audio_queue.put_nowait, data)

    def _on_complete(self):
        """Signal end of audio stream."""
        if self._loop:
            self._loop.call_soon_threadsafe(self.audio_queue.put_nowait, None)


class _Callback(ResultCallback):
    def __init__(self, service: TTSService):
        self._service = service

    def on_open(self):
        pass

    def on_data(self, data: bytes) -> None:
        self._service._on_audio(data)

    def on_complete(self):
        self._service._on_complete()

    def on_error(self, message):
        self._service._on_complete()

    def on_close(self):
        pass
