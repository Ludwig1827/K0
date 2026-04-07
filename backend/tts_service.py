import asyncio
import re
import dashscope
from dashscope.audio.tts_v2 import SpeechSynthesizer, ResultCallback, AudioFormat
from config import DASHSCOPE_API_KEY, VOICE_ID, TTS_MODEL

dashscope.api_key = DASHSCOPE_API_KEY

# Sentence boundary pattern: Chinese/English punctuation
SENTENCE_END = re.compile(r"[。！？；\n.!?;]")
# Max chars to buffer before forcing a flush
MAX_BUFFER = 40


class TTSService:
    """Wraps CosyVoice streaming TTS. Buffers text to sentence boundaries, emits PCM audio."""

    def __init__(self):
        self.audio_queue: asyncio.Queue[bytes | None] = asyncio.Queue()
        self._synthesizer: SpeechSynthesizer | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._text_buffer = ""
        self._cancelled = False

    def start(self):
        """Initialize a new TTS streaming session."""
        self._loop = asyncio.get_running_loop()
        self._cancelled = False
        self._text_buffer = ""
        callback = _Callback(self)
        self._synthesizer = SpeechSynthesizer(
            model=TTS_MODEL,
            voice=VOICE_ID,
            format=AudioFormat.PCM_16000HZ_MONO_16BIT,
            callback=callback,
        )

    def feed_text(self, text: str):
        """Feed LLM text delta. Buffers until sentence boundary, then flushes to TTS."""
        if self._cancelled or not self._synthesizer:
            return
        self._text_buffer += text
        # Check for sentence boundary or buffer overflow
        while self._text_buffer:
            match = SENTENCE_END.search(self._text_buffer)
            if match:
                # Flush up to and including the punctuation
                end = match.end()
                sentence = self._text_buffer[:end]
                self._text_buffer = self._text_buffer[end:]
                self._synthesizer.streaming_call(sentence)
            elif len(self._text_buffer) >= MAX_BUFFER:
                # Force flush on long buffer without punctuation
                self._synthesizer.streaming_call(self._text_buffer)
                self._text_buffer = ""
            else:
                break

    def flush(self):
        """Flush remaining buffer and complete TTS stream."""
        if self._synthesizer:
            if self._text_buffer:
                self._synthesizer.streaming_call(self._text_buffer)
                self._text_buffer = ""
            self._synthesizer.streaming_complete()

    def cancel(self):
        """Cancel current TTS generation."""
        self._cancelled = True
        self._text_buffer = ""
        if self._synthesizer:
            try:
                self._synthesizer.streaming_cancel()
            except Exception:
                pass

    def stop(self):
        """Stop and clean up."""
        self.cancel()
        self._synthesizer = None

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

    def on_data(self, data: bytes):
        self._service._on_audio(data)

    def on_complete(self):
        self._service._on_complete()

    def on_error(self, message):
        print(f"[TTS Error] {message}")

    def on_close(self):
        pass

    def on_open(self):
        pass

    def on_event(self, message):
        pass
