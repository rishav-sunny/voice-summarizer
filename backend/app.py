"""FastAPI backend for Deepgram realtime transcription + local summarization.

Replaces previous AssemblyAI integration with Deepgram's realtime API.
Features:
 - WebSocket endpoint /ws/transcribe/{session_id}
 - Forwards raw PCM16 (16kHz mono) audio frames from frontend to Deepgram
 - Receives interim + final transcripts and pushes them to the browser
 - Stores transcript events per session for later summarization
 - Local summarization endpoint /summarize (heuristic bullet list)
 - Graceful error handling & auto-reconnect to Deepgram
"""

import asyncio
import base64
import json
import os
from typing import Dict, List, Tuple

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import websockets

load_dotenv()
DEEPGRAM_API_KEY = os.getenv("DEEPGRAM_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", os.getenv("GOOGLE_API_KEY", ""))
SUMMARIZER_MODEL = os.getenv("SUMMARIZER_MODEL", "gemini-pro")
DEEPGRAM_URL = "wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate=16000&channels=1"

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class SessionSummaryRequest(BaseModel):
    session_id: str

class SessionSummaryResponse(BaseModel):
    session_id: str
    summary: str
    source: str = "local"  # "gemini" or "local"

# In-memory session store: SESSIONS[session_id] = {"messages": [ {...} ]}
SESSIONS: Dict[str, Dict[str, List[Dict]]] = {}

@app.get("/health")
async def health():
    return {"status": "ok"}

async def _local_summarize(transcript: str) -> str:
    lines = [l.strip() for l in transcript.split("\n") if l.strip()]
    bullets = []
    for l in lines:
        if len(l) <= 200:
            bullets.append(l)
        if len(bullets) >= 12:
            break
    if not bullets:
        return "No transcript available to summarize."
    return "\n".join(f"• {b}" for b in bullets)

async def _gemini_summarize(transcript: str) -> Tuple[str, str]:
    """Summarize transcript using Google Gemini (Generative Language API).
    Uses gemini-1.5-flash via REST. Falls back to local if API fails.
    """
    if not GEMINI_API_KEY:
        return (await _local_summarize(transcript), "local")
    if not transcript.strip():
        return ("No transcript available to summarize.", "local")
    import aiohttp
    model = SUMMARIZER_MODEL or "gemini-pro"
    base_urls = [
        "https://generativelanguage.googleapis.com/v1/models",
        "https://generativelanguage.googleapis.com/v1beta/models",
    ]
    prompt = (
        "You are a concise meeting summarizer. Summarize the following transcript into 6-10 clear bullet points, "
        "group related ideas, and highlight decisions and action items. Keep bullets short. Transcript:\n\n"
        + transcript
    )
    payload = {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": prompt}],
            }
        ]
    }
    try:
        async with aiohttp.ClientSession() as session:
            last_error = None
            for base in base_urls:
                url = f"{base}/{model}:generateContent?key={GEMINI_API_KEY}"
                try:
                    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                        if resp.status != 200:
                            try:
                                err_txt = await resp.text()
                            except Exception:
                                err_txt = "<no body>"
                            print(f"[GEMINI] HTTP {resp.status} at {base}: {err_txt[:500]}")
                            last_error = (resp.status, err_txt)
                            continue
                        data = await resp.json()
                        candidates = data.get("candidates") or []
                        if not candidates:
                            print("[GEMINI] No candidates in response")
                            last_error = (200, "no candidates")
                            continue
                        parts = candidates[0].get("content", {}).get("parts", [])
                        texts = [p.get("text", "") for p in parts if isinstance(p, dict)]
                        text = "\n".join(t for t in texts if t).strip()
                        if not text:
                            print("[GEMINI] Empty text in parts")
                            last_error = (200, "empty parts")
                            continue
                        return (text, "gemini")
                except Exception as e:
                    print(f"[GEMINI] Exception at {base}: {type(e)._name_}: {e}")
                    last_error = ("exception", str(e))
                    continue
            # Fallback after trying both v1 and v1beta
            print(f"[GEMINI] Fallback to local summarizer due to error: {last_error}")
            return (await _local_summarize(transcript), "local")
    except Exception as e:
        print(f"[GEMINI] Exception: {type(e)._name_}: {e}")
        return (await _local_summarize(transcript), "local")

@app.post("/summarize", response_model=SessionSummaryResponse)
async def summarize(req: SessionSummaryRequest):
    msgs = SESSIONS.get(req.session_id, {}).get("messages", [])
    transcript_texts: List[str] = []
    for m in msgs:
        # Expect stored keys: transcript, is_final, speaker (optional)
        text = m.get("transcript") or m.get("text")
        if not text:
            continue
        spk = m.get("speaker") or m.get("speaker_label")
        if spk:
            transcript_texts.append(f"[{spk}] {text}")
        else:
            transcript_texts.append(text)
    transcript = "\n".join(transcript_texts)
    # Prefer Gemini if key present; otherwise local summarizer
    summary, source = await _gemini_summarize(transcript)
    return SessionSummaryResponse(session_id=req.session_id, summary=summary, source=source)


async def connect_deepgram():
    """Establish a Deepgram realtime websocket connection."""
    if not DEEPGRAM_API_KEY:
        raise RuntimeError("Missing DEEPGRAM_API_KEY")
    return await websockets.connect(
        DEEPGRAM_URL,
        extra_headers={
            "Authorization": f"Token {DEEPGRAM_API_KEY}",
            "Accept": "application/json", 
        },
        ping_interval=20,
        ping_timeout=20,
        max_size=10_000_000,
    )

@app.websocket("/ws/transcribe/{session_id}")
async def websocket_transcribe(websocket: WebSocket, session_id: str):
    """Accepts a WebSocket from the frontend. Forwards audio to Deepgram and relays transcripts back."""
    await websocket.accept()
    if not DEEPGRAM_API_KEY:
        await websocket.send_json({"error": "Missing DEEPGRAM_API_KEY"})
        await websocket.close()
        return
    """Initialize session present inside message."""
    SESSIONS.setdefault(session_id, {"messages": []})
    await websocket.send_json({"status": "connecting_deepgram"})

    dg_ws = None
    stop_flag = False

    async def deepgram_receiver():
        nonlocal dg_ws, stop_flag
        while not stop_flag:
            try:
                if dg_ws is None or dg_ws.closed:
                    dg_ws = await connect_deepgram()
                    await websocket.send_json({"status": "deepgram_connected"})
                async for raw_msg in dg_ws:
                    try:
                        data = json.loads(raw_msg)
                    except Exception:
                        continue
                    # Deepgram sends messages with "is_final" and transcript at channel.alternatives[0].transcript
                    alt = (
                        data.get("channel", {})
                        .get("alternatives", [{}])[0]
                    )
                    transcript = alt.get("transcript", "")
                    is_final = alt.get("words") is not None and data.get("is_final", False)
                    if transcript:
                        msg_obj = {
                            "transcript": transcript,
                            "is_final": is_final,
                        }
                        SESSIONS[session_id]["messages"].append(msg_obj)
                        await websocket.send_json(msg_obj)
            except WebSocketDisconnect:
                stop_flag = True
            except Exception as e:
                err_msg = f"{type(e)._name_}: {e!s}"
                await websocket.send_json({"error": "deepgram_recv_error", "detail": err_msg})
                # Backoff before reconnect
                await asyncio.sleep(2)
                continue
            finally:
                if dg_ws and dg_ws.closed:
                    await asyncio.sleep(1)

    async def client_audio_sender():
        nonlocal dg_ws, stop_flag
        while not stop_flag:
            try:
                msg = await websocket.receive()
            except WebSocketDisconnect:
                stop_flag = True
                break
            except Exception:
                stop_flag = True
                break
            message_type = msg.get("type")
            if message_type == "websocket.disconnect":
                stop_flag = True
                break
            if message_type == "websocket.receive":
                data_bytes = msg.get("bytes")
                text_data = msg.get("text")
                # We prefer binary PCM frames; if text (legacy base64 JSON), attempt decode
                if data_bytes:
                    if dg_ws and not dg_ws.closed:
                        try:
                            await dg_ws.send(data_bytes)
                        except Exception as e:
                            await websocket.send_json({"error": f"deepgram_send_error: {e}"})
                    continue
                if text_data:
                    try:
                        payload = json.loads(text_data)
                        b64_audio = payload.get("audio")
                        if b64_audio and dg_ws and not dg_ws.closed:
                            import base64
                            pcm = base64.b64decode(b64_audio)
                            await dg_ws.send(pcm)
                    except Exception:
                        pass

    recv_task = asyncio.create_task(deepgram_receiver())
    send_task = asyncio.create_task(client_audio_sender())
    done, pending = await asyncio.wait({recv_task, send_task}, return_when=asyncio.FIRST_COMPLETED)
    for p in pending:
        p.cancel()

    # Cleanup
    stop_flag = True
    if dg_ws and not dg_ws.closed:
        try:
            await dg_ws.close()
        except Exception:
            pass
    try:
        await websocket.close()
    except Exception:
        pass