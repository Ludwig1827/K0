import asyncio
from typing import AsyncGenerator
import dashscope
from dashscope import Generation
from config import DASHSCOPE_API_KEY, LLM_MODEL, SYSTEM_PROMPT

dashscope.api_key = DASHSCOPE_API_KEY

MAX_HISTORY_TURNS = 20


class LLMService:
    """Wraps Qwen streaming LLM. Maintains conversation history."""

    def __init__(self):
        self.history: list[dict] = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self._cancelled = False

    def cancel(self):
        """Cancel the current generation."""
        self._cancelled = True

    def reset(self):
        """Reset conversation history."""
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    async def chat(self, user_text: str) -> AsyncGenerator[str, None]:
        """Send user text, yield LLM response deltas."""
        self._cancelled = False
        self.history.append({"role": "user", "content": user_text})

        # Trim history: keep system prompt + last N turns
        if len(self.history) > MAX_HISTORY_TURNS * 2 + 1:
            self.history = [self.history[0]] + self.history[-(MAX_HISTORY_TURNS * 2):]

        full_response = ""
        loop = asyncio.get_running_loop()
        delta_queue: asyncio.Queue[str | None] = asyncio.Queue()

        # Run the blocking streaming iteration in a thread so it doesn't block the event loop
        def _stream_in_thread():
            try:
                responses = Generation.call(
                    model=LLM_MODEL,
                    messages=list(self.history),
                    stream=True,
                    incremental_output=True,
                    result_format="message",
                )
                for chunk in responses:
                    if self._cancelled:
                        break
                    if chunk.status_code == 200:
                        delta = chunk.output.choices[0]["message"]["content"]
                        if delta:
                            loop.call_soon_threadsafe(delta_queue.put_nowait, delta)
            finally:
                loop.call_soon_threadsafe(delta_queue.put_nowait, None)

        loop.run_in_executor(None, _stream_in_thread)

        while True:
            delta = await delta_queue.get()
            if delta is None or self._cancelled:
                break
            full_response += delta
            yield delta

        if full_response and not self._cancelled:
            self.history.append({"role": "assistant", "content": full_response})
