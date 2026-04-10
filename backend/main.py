import json
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from chat_session import ChatSession

app = FastAPI()

# Serve frontend static files
FRONTEND_DIR = Path(__file__).parent.parent / "frontend"


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    session = ChatSession(ws)
    await session.start()

    try:
        while True:
            message = await ws.receive()

            if message["type"] != "websocket.receive":
                continue

            if "bytes" in message and message["bytes"]:
                # Binary: raw PCM audio during a voice call
                await session.handle_audio(message["bytes"])
                continue

            if "text" in message and message["text"]:
                data = json.loads(message["text"])
                msg_type = data.get("type")

                if msg_type == "start_call":
                    await session.start_call()
                elif msg_type == "stop_call":
                    await session.stop_call()
                elif msg_type == "interrupt":
                    await session.handle_interrupt()
                elif msg_type == "text_message":
                    await session.handle_text_message(data.get("text", ""))

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket Error] {e}")
    finally:
        await session.stop()


# Mount static files AFTER the WebSocket route so /ws isn't caught by static
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
