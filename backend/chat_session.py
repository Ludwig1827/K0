import asyncio
import json
import random
import re
from fastapi import WebSocket

from asr_service import ASRService
from llm_service import LLMService
from tts_service import TTSService

# Filler phrases spoken while LLM is thinking — feels natural and masks latency
THINKING_FILLERS = [
    "嗯，",
]

# Only use fillers when LLM takes too long (seconds)
FILLER_DELAY = 1.5

# Detect user emotion from their text to adjust TTS parameters
_USER_EMOTION_PATTERNS = {
    "sad":      re.compile(r"难过|伤心|哭|不开心|累|烦|郁闷|心烦|崩溃|失眠|焦虑|压力|孤独|寂寞|想哭|受不了|好难|痛苦|分手|失恋|不想活"),
    "happy":    re.compile(r"开心|高兴|快乐|太好了|哈哈|嘿嘿|好棒|成功|通过|录取|好消息|恋爱|表白"),
    "shocked":  re.compile(r"什么|不会吧|天哪|我靠|卧槽|真假|离谱|震惊|吓死"),
    "romantic": re.compile(r"喜欢你|爱你|好可爱|最喜欢|想你|抱抱|亲亲|老婆|宝贝"),
}


def detect_user_emotion(text: str) -> str:
    """Detect the dominant emotion from user text."""
    for emotion, pattern in _USER_EMOTION_PATTERNS.items():
        if pattern.search(text):
            return emotion
    return "neutral"


# TTS speed per emotional context: slower for sad/tender, faster for excited
EMOTION_TTS_SPEED = {
    "sad": 0.85,
    "happy": 1.05,
    "shocked": 1.1,
    "romantic": 0.88,
    "neutral": 0.95,
}


class ChatSession:
    """Orchestrates one chat session (text + voice) over a WebSocket. Owns LLM state across the whole session; ASR/TTS only active during voice calls."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.asr = ASRService()
        self.llm = LLMService()
        self.tts = TTSService()
        self._running = False
        self._responding = False

    async def start(self):
        """Session-level start: launch background loops. Called on WS accept. No mic/TTS yet."""
        self._running = True
        asyncio.create_task(self._transcript_loop())
        asyncio.create_task(self._audio_playback_loop())
        await self._send_status("idle")

    async def start_call(self):
        """Start a voice call: activate ASR + TTS. Session must already be started."""
        self.asr.start()
        self.tts.start()
        await self._send_status("listening")

    async def stop_call(self):
        """Stop ASR + TTS for a voice call. Session (and LLM history) stays alive."""
        self.asr.stop()
        self.tts.stop()
        if self._responding:
            self.llm.cancel()
            self._responding = False
        await self._send_status("idle")

    async def stop(self):
        """Terminate the entire session. Called on WebSocket disconnect."""
        self._running = False
        await self.stop_call()

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
            # Pre-build TTS connection for next turn
            self.tts.start()
            await self._send_status("listening")

    async def handle_text_message(self, text: str):
        """Process a text-mode message: run LLM, stream deltas back as JSON. No ASR/TTS."""
        if not text.strip():
            return
        if self._responding:
            await self._send_json({"type": "text_error", "reason": "busy"})
            return
        # Also refuse if a voice call is active (ASR is running)
        if self.asr._recognition is not None:
            await self._send_json({"type": "text_error", "reason": "in_call"})
            return

        self._responding = True

        # Echo user message (triggers client user-emotion animation)
        await self._send_json({
            "type": "transcript",
            "role": "user",
            "text": text,
        })
        await self._send_status("thinking")

        full_response = ""
        try:
            async for delta in self.llm.chat(text):
                if not self._responding:
                    break
                full_response += delta
                await self._send_json({
                    "type": "text_delta",
                    "text": delta,
                })
        finally:
            await self._send_json({
                "type": "text_done",
                "text": full_response,
            })
            self._responding = False
            await self._send_status("idle")

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

            # Detect user emotion and adjust TTS accordingly
            user_emotion = detect_user_emotion(text)
            tts_speed = EMOTION_TTS_SPEED.get(user_emotion, 0.95)

            # Restart TTS with emotion-appropriate speed
            self.tts.cancel()
            self.tts.start(speed=tts_speed)

            # Send emotion info to frontend
            await self._send_json({
                "type": "user_emotion",
                "emotion": user_emotion,
            })

            # Generate AI response
            self._responding = True
            await self._send_status("thinking")

            full_response = ""
            first_delta = True
            filler_sent = False

            # Start LLM generation — only send filler if first token is slow
            gen = self.llm.chat(text).__aiter__()
            filler_task = None

            async def _maybe_send_filler():
                """Send a filler phrase if LLM hasn't responded yet."""
                nonlocal filler_sent
                await asyncio.sleep(FILLER_DELAY)
                if first_delta and self._responding and not filler_sent:
                    filler_sent = True
                    filler = random.choice(THINKING_FILLERS)
                    self.tts.feed_text(filler)
                    await self._send_status("speaking")

            filler_task = asyncio.create_task(_maybe_send_filler())

            async for delta in gen:
                if not self._running or not self._responding:
                    break
                if first_delta:
                    first_delta = False
                    filler_task.cancel()
                    if not filler_sent:
                        await self._send_status("speaking")
                self.tts.feed_text(delta)
                full_response += delta

            if self._responding:
                self.tts.flush()
                # Send full assistant transcript
                await self._send_json({
                    "type": "transcript",
                    "role": "assistant",
                    "text": full_response,
                })

            self._responding = False
            # Pre-build TTS connection for next turn (saves ~1s on next response)
            self.tts.start()
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
