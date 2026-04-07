import asyncio
import dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from config import DASHSCOPE_API_KEY, ASR_MODEL

dashscope.api_key = DASHSCOPE_API_KEY


class ASRService:
    """Wraps Paraformer streaming ASR. Accepts audio bytes, emits final transcripts."""

    def __init__(self):
        self.transcript_queue: asyncio.Queue[str] = asyncio.Queue()
        self._recognition: Recognition | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self):
        """Start a new ASR session. Call from the async event loop."""
        self._loop = asyncio.get_running_loop()
        callback = _Callback(self)
        self._recognition = Recognition(
            model=ASR_MODEL,
            callback=callback,
            format="pcm",
            sample_rate=16000,
        )
        self._recognition.start()

    def feed_audio(self, audio_bytes: bytes):
        """Feed raw PCM audio bytes into the ASR session."""
        if self._recognition:
            self._recognition.send_audio_frame(audio_bytes)

    def stop(self):
        """Stop the ASR session."""
        if self._recognition:
            try:
                self._recognition.stop()
            except Exception:
                pass
            self._recognition = None

    def _on_transcript(self, text: str):
        """Called from callback thread — schedule into async queue."""
        if self._loop and text.strip():
            self._loop.call_soon_threadsafe(self.transcript_queue.put_nowait, text)


class _Callback(RecognitionCallback):
    def __init__(self, service: ASRService):
        self._service = service

    def on_event(self, result: RecognitionResult):
        sentence = result.get_sentence()
        if RecognitionResult.is_sentence_end(sentence):
            self._service._on_transcript(sentence["text"])

    def on_complete(self):
        pass

    def on_error(self, result: RecognitionResult):
        print(f"[ASR Error] {result}")

    def on_close(self):
        pass
