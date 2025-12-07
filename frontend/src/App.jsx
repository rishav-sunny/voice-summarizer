import React, { useRef, useState } from 'react'

// React frontend adapted for Deepgram realtime via backend bridge.
// Differences from previous version:
//  - Sends raw binary PCM16 frames (not base64  JSON) over WS.
//  - Accepts interim + final transcripts; displays both in order received.
//  - UI & session behavior unchanged.

export default function App() {
  const [sessionId] = useState(() => Math.random().toString(36).slice(2))
  const [listening, setListening] = useState(false)
  const [transcript, setTranscript] = useState([])
  const [summary, setSummary] = useState(null)
  const wsRef = useRef(null)
  const mediaStreamRef = useRef(null)
  const audioCtxRef = useRef(null)
  const processorRef = useRef(null)

  const BACKEND_WS = import.meta.env.VITE_BACKEND_WS || `ws://${location.hostname}:8000/ws/transcribe/`
  const BACKEND_HTTP = import.meta.env.VITE_BACKEND_HTTP || `http://${location.hostname}:8000`

  async function startListening() {
    if (listening) return
    setTranscript([])
    setSummary(null)

    const ws = new WebSocket(`${BACKEND_WS}${sessionId}`)
    ws.binaryType = 'arraybuffer'
    ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        if (data.transcript || data.text) {
          setTranscript((t) => [...t, data])
        }
        if (data.error) {
          console.error('Backend error:', data.error)
        }
      } catch (e) {
        // ignore non-JSON
      }
    }
    ws.onopen = () => console.log('WS connected')
    ws.onclose = () => console.log('WS closed')
    wsRef.current = ws

    // Capture mic audio & stream PCM16 little-endian @16kHz
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    mediaStreamRef.current = stream
    const audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 })
    audioCtxRef.current = audioCtx
    const source = audioCtx.createMediaStreamSource(stream)
    const processor = audioCtx.createScriptProcessor(4096, 1, 1)
    processorRef.current = processor

    processor.onaudioprocess = (e) => {
      if (!wsRef.current || wsRef.current.readyState !== 1) return
      const input = e.inputBuffer.getChannelData(0)
      const buffer = new ArrayBuffer(input.length * 2)
      const view = new DataView(buffer)
      let offset = 0
      for (let i = 0; i < input.length; i++) {
        let s = Math.max(-1, Math.min(1, input[i]))
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
        offset += 2
      }
      wsRef.current.send(buffer)
    }

    source.connect(processor)
    processor.connect(audioCtx.destination)
    setListening(true)
  }

  async function stopListening() {
    setListening(false)
    try { processorRef.current && processorRef.current.disconnect() } catch {}
    try { audioCtxRef.current && audioCtxRef.current.state !== 'closed' && audioCtxRef.current.close() } catch {}
    try { mediaStreamRef.current && mediaStreamRef.current.getTracks().forEach(t => t.stop()) } catch {}
    try { wsRef.current && wsRef.current.readyState === 1 && wsRef.current.close() } catch {}
    processorRef.current = null
    audioCtxRef.current = null
    mediaStreamRef.current = null
    wsRef.current = null
  }

  async function endSessionAndSummarize() {
    await stopListening()
    try {
      const res = await fetch(`${BACKEND_HTTP}/summarize`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: sessionId })
      })
      const data = await res.json()
      setSummary(data.summary || 'No summary')
    } catch (e) {
      setSummary('Failed to summarize')
    }
  }

  return (
    <div style={{ maxWidth: 800, margin: '40px auto', fontFamily: 'system-ui' }}>
      <h1>Voice Summarizer</h1>
      <p>Session: <code>{sessionId}</code></p>
      <div style={{ display: 'flex', gap: 12 }}>
        <button onClick={startListening} disabled={listening}>Start Listening</button>
        <button onClick={stopListening} disabled={!listening}>Stop Listening</button>
        <button onClick={endSessionAndSummarize}>End Session & Summarize</button>
      </div>
      <h2>Live Transcript</h2>
      <div style={{ border: '1px solid #ddd', padding: 12, minHeight: 160 }}>
        {transcript.map((t, i) => (
          <div key={i} style={{ opacity: t.is_final ? 1 : 0.6 }}>
            {t.transcript}
          </div>
        ))}
      </div>
      <h2>Summary</h2>
      <div style={{ whiteSpace: 'pre-wrap', border: '1px solid #ddd', padding: 12, minHeight: 120 }}>
        {summary || '—'}
      </div>
    </div>
  )
}
