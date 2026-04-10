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
    session: ChatSession | None = None

    try:
        while True:
            message = await ws.receive()

            if message["type"] == "websocket.receive":
                if "bytes" in message and message["bytes"]:
                    # Binary: audio data
                    if session:
                        await session.handle_audio(message["bytes"])

                elif "text" in message and message["text"]:
                    # JSON: control message
                    data = json.loads(message["text"])
                    msg_type = data.get("type")

                    if msg_type == "start":
                        if session:
                            await session.stop()
                        session = ChatSession(ws)
                        await session.start()

                    elif msg_type == "stop":
                        if session:
                            await session.stop()
                            session = None

                    elif msg_type == "interrupt":
                        if session:
                            await session.handle_interrupt()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[WebSocket Error] {e}")
    finally:
        if session:
            await session.stop()


# Mount static files AFTER the WebSocket route so /ws isn't caught by static
app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
