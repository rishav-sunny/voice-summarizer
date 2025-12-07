# Voice Summarizer — Interviewer Guide (FastAPI + React + Deepgram)

This project is a local-first voice transcription and summarization app. It uses:
- FastAPI backend (Python) with a WebSocket bridge to Deepgram Realtime.
- React (Vite) frontend that captures microphone audio and streams PCM16 frames.
- Simple local summarization endpoint (no external LLM), producing bullet points.

Note: The app was migrated from AssemblyAI to Deepgram. Ignore any old AssemblyAI mentions in older commits.

## Quick Start (Windows)
Prereqs: Python 3.10+, Node.js 18+, Chrome/Edge. Do NOT ship `node_modules` or `.venv` in zip.

1) Backend setup
```cmd
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```
Create `backend\.env`:
```
DEEPGRAM_API_KEY=YOUR_DEEPGRAM_KEY
```
Run (prefer python -m to avoid stale launchers):
```cmd
python -m uvicorn app:app --host 0.0.0.0 --port 8000
```

2) Frontend setup
```cmd
cd frontend
if (Test-Path .\package-lock.json) { npm ci } else { npm install }
npm ci
npm run dev
```
Open the shown URL (e.g., `http://localhost:5173`). Start Listening, speak, then End Session & Summarize.

Optional frontend config (`frontend\.env` if needed):
```
VITE_BACKEND_WS=ws://localhost:8000/ws/transcribe/
VITE_BACKEND_HTTP=http://localhost:8000
```

## File-by-File Explanation (Talking Points)

Top-level:
- `backend/`: FastAPI app. Handles WebSocket audio, talks to Deepgram, exposes HTTP endpoints.
- `frontend/`: React app (Vite). Captures mic, streams PCM16, displays interim/final transcripts and summary.
- `deploy/k8s.yaml`: Kubernetes manifests (Namespace, Secret, Deployments, Services). Not needed for local run.
- `README.md`: This guide.

Backend:
- `backend/app.py`: Main FastAPI app.
  - `GET /health`: Simple health check.
  - `WS /ws/transcribe/{session_id}`: Accepts raw PCM16 audio frames from the browser, forwards to Deepgram's realtime WS, relays transcripts back to the client, stores messages in-memory per `session_id`.
  - `POST /summarize`: Builds a local heuristic bullet list from the stored transcript lines for the given `session_id`.
  - Internals:
    - Connects to `wss://api.deepgram.com/v1/listen?encoding=linear16&sample_rate=16000` with `Authorization: Token <key>`.
    - Two async tasks: one reads Deepgram messages and emits interim/final transcripts; the other forwards client audio frames to Deepgram.
    - Simple in-memory session store for transcript lines (reset on process restart).
- `backend/requirements.txt`: Python dependencies (FastAPI, Uvicorn, websockets, python-dotenv, etc.).
- `backend/.env`: Contains `DEEPGRAM_API_KEY`. Not committed; user supplies.

Frontend:
- `frontend/src/App.jsx`: Main UI component.
  - Requests mic, creates an `AudioContext` (16kHz) and `ScriptProcessorNode`.
  - Converts Float32 buffers to little-endian PCM16 bytes and sends binary frames over WebSocket.
  - Displays interim vs final transcripts (final rendered with higher opacity), provides Start/Stop and End Session & Summarize controls.
- `frontend/package.json`: Scripts and dependencies. `npm run dev` starts Vite dev server.
- `frontend/vite.config.*`: Vite build config (default).
- `frontend/.env` (optional): Allows overriding backend URLs if not on localhost.

Kubernetes (optional):
- `deploy/k8s.yaml`: Includes `Namespace`, `Secret` (Deepgram key), `backend` & `frontend` `Deployment`s and `Service`s; `frontend` Service is `NodePort 30080`.
  - For local clusters (kind/k3d), build images (`voice-summarizer-backend:local`, `voice-summarizer-frontend:local`) and load them into the cluster, then `kubectl apply -f deploy/k8s.yaml`.
  - Not required for interviews; local run is sufficient.

## Architecture & Flow (Explain to Interviewer)
- Audio Capture: Browser captures microphone at 16 kHz, encodes to PCM16, sends frames over WebSocket to backend.
- Realtime Bridge: Backend opens a WS connection to Deepgram and forwards audio frames. Deepgram returns JSON messages with interim and final transcripts.
- UI Updates: Frontend receives transcript events over the same WS and updates the UI live.
- Summarization: After a session, the frontend calls `POST /summarize` with `session_id`. Backend compiles collected lines into concise bullets (no external LLM for reliability and cost control).
- Resilience: Backend auto-reconnects to Deepgram on transient errors; frontend includes start/stop controls to handle mic state.

## Demo Script (2–3 minutes)
1. Start backend: `python -m uvicorn app:app --port 8000` (key set in `.env`).
2. Start frontend: `npm run dev` and open the URL.
3. Click Start Listening, speak a few sentences.
4. Show interim vs final transcript lines updating.
5. Click End Session & Summarize; explain bullets generated.
6. Mention design choices: PCM16 binary streaming, local summarization (no external LLM), Deepgram free-tier friendly.

## Common Pitfalls & Fixes
- "Fatal error in launcher" for uvicorn: Use `python -m uvicorn ...` and recreate a fresh `.venv` on this machine.
- Env vars in Windows:
  - PowerShell: `$env:DEEPGRAM_API_KEY="YOUR_KEY"`
  - cmd.exe: `set DEEPGRAM_API_KEY=YOUR_KEY`
- No transcript: Check Deepgram key, internet connectivity, and that audio frames are binary PCM16 (not base64).
- Mic denied: Reopen page, allow mic; try Chrome.
- If zip included `node_modules` or `.venv`: delete them and reinstall (`npm ci`, new `python -m venv`).

## Security Notes
- Do not commit `.env` or API keys.
- If a key was ever exposed in a repo or sent widely, rotate it in Deepgram.

## Optional: Docker (no Kubernetes)
```cmd
cd backend
docker build -t voice-summarizer-backend:local .
cd ..\frontend
docker build -t voice-summarizer-frontend:local .
```
Run containers:
```cmd
docker run -p 8000:8000 -e DEEPGRAM_API_KEY=YOUR_KEY voice-summarizer-backend:local
docker run -p 3000:80 -e VITE_BACKEND_WS=ws://host.docker.internal:8000/ws/transcribe/ -e VITE_BACKEND_HTTP=http://host.docker.internal:8000 voice-summarizer-frontend:local
```
Open `http://localhost:3000`.

