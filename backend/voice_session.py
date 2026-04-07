import asyncio
import json
from fastapi import WebSocket

from asr_service import ASRService
from llm_service import LLMService
from tts_service import TTSService


class VoiceSession:
    """Orchestrates one voice conversation session over a WebSocket."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.asr = ASRService()
        self.llm = LLMService()
        self.tts = TTSService()
        self._running = False
        self._responding = False

    async def start(self):
        """Start the voice session — launch ASR and background tasks."""
        self._running = True
        self.asr.start()
        # Launch background tasks
        asyncio.create_task(self._transcript_loop())
        asyncio.create_task(self._audio_playback_loop())
        await self._send_status("listening")

    async def stop(self):
        """Stop the voice session and clean up."""
        self._running = False
        self.asr.stop()
        self.tts.stop()
        self.llm.cancel()

    async def handle_audio(self, audio_bytes: bytes):
        """Handle incoming audio from the browser."""
        self.asr.feed_audio(audio_bytes)

    async def handle_interrupt(self):
        """User started speaking while AI is responding — cancel current response."""
        if self._responding:
            self.llm.cancel()
            self.tts.cancel()
            self._responding = False
            # Drain stale audio chunks from the queue
            while not self.tts.audio_queue.empty():
                try:
                    self.tts.audio_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
            # Tell browser to reset its playback schedule
            await self._send_json({"type": "interrupt_ack"})
            await self._send_status("listening")

    async def _transcript_loop(self):
        """Watch ASR transcripts and trigger LLM + TTS pipeline."""
        while self._running:
            try:
                text = await asyncio.wait_for(
                    self.asr.transcript_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            if not self._running:
                break

            # Send user transcript to browser
            await self._send_json({
                "type": "transcript",
                "role": "user",
                "text": text,
            })

            # Generate AI response
            self._responding = True
            await self._send_status("thinking")

            self.tts.start()
            full_response = ""

            async for delta in self.llm.chat(text):
                if not self._running or not self._responding:
                    break
                self.tts.feed_text(delta)
                full_response += delta

                # Switch to speaking status on first delta
                if full_response == delta:
                    await self._send_status("speaking")

            if self._responding:
                self.tts.flush()
                # Send full assistant transcript
                await self._send_json({
                    "type": "transcript",
                    "role": "assistant",
                    "text": full_response,
                })

            self._responding = False
            await self._send_status("listening")

    async def _audio_playback_loop(self):
        """Forward TTS audio chunks to browser."""
        while self._running:
            try:
                data = await asyncio.wait_for(
                    self.tts.audio_queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            if data is None:
                # End of current TTS stream
                continue

            if self._running:
                try:
                    await self.ws.send_bytes(data)
                except Exception:
                    break

    async def _send_json(self, data: dict):
        try:
            await self.ws.send_text(json.dumps(data, ensure_ascii=False))
        except Exception:
            pass

    async def _send_status(self, state: str):
        await self._send_json({"type": "status", "state": state})
