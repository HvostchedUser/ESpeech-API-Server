# app/main.py
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import threading
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Response, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse

from config import (
    STATIC_DIR,
    VOICES_DIR,
    OUTPUT_DIR,
    API_BASE,
    OUTPUT_RETENTION_SECONDS,
    CLEANUP_INTERVAL_SECONDS,
)
from models import (
    JobStatus,
    ListVoicesResponse,
    SynthesisRequest,
    VoiceInfo,
)
from voices import discover_voices
from job_manager import JobManager
from tts import synthesize_raw, stream_audio_bytes

# ---------- Lifespan (replaces deprecated @app.on_event) ----------
_cleanup_stop = threading.Event()
jobs = JobManager()

def _cleanup_loop():
    time.sleep(2.0)  # let app warm up
    while not _cleanup_stop.is_set():
        try:
            jobs.cleanup_expired(OUTPUT_RETENTION_SECONDS)
        except Exception:
            pass
        _cleanup_stop.wait(timeout=CLEANUP_INTERVAL_SECONDS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    t = threading.Thread(target=_cleanup_loop, name="output-cleaner", daemon=True)
    t.start()
    try:
        yield
    finally:
        _cleanup_stop.set()


app = FastAPI(title="ESpeech TTS API", version="1.2.2", lifespan=lifespan)

# CORS (adjust as needed; permissive for local dev)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -------- API ROUTES --------
@app.get(f"{API_BASE}/voices", response_model=ListVoicesResponse)
def list_voices(refresh: bool = Query(False, description="Rescan the voices directory.")):
    voices = discover_voices() if refresh else list_voices._cache or discover_voices()  # type: ignore
    list_voices._cache = voices  # type: ignore
    payload = [
        VoiceInfo(
            id=v.id,
            name=v.name,
            ref_text_file=str(v.ref_text_path.relative_to(VOICES_DIR)),
            ref_audio_file=str(v.ref_audio_path.relative_to(VOICES_DIR)),
        )
        for v in voices.values()
    ]
    return ListVoicesResponse(voices=payload)

list_voices._cache = None  # type: ignore


@app.get(f"{API_BASE}/voices/{{voice_id}}/reference-audio")
def get_reference_audio(voice_id: str):
    voices = list_voices._cache or discover_voices()  # type: ignore
    if voice_id not in voices:
        raise HTTPException(404, f"Voice '{voice_id}' not found.")
    voice = voices[voice_id]
    path = voice.ref_audio_path
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "application/octet-stream"
    return Response(content=path.read_bytes(), media_type=mime, headers={
        "Content-Disposition": f'inline; filename="{path.name}"'
    })


@app.post(f"{API_BASE}/synthesize")
def create_synthesis_job(req: SynthesisRequest):
    voices = list_voices._cache or discover_voices()  # type: ignore
    voice = voices.get(req.voice_id)
    if not voice:
        raise HTTPException(404, f"Voice '{req.voice_id}' not found.")

    job_id = jobs.submit(
        voice=voice,
        text=req.text,
        speed=req.speed,
        nfe_step=req.nfe_step,
        seed=req.seed,
        fmt=req.format,
        callback_url=str(req.callback_url) if req.callback_url else None,
    )
    # Minimal JSON to avoid any forward-ref issues in some envs
    return {"job_id": job_id, "status": "queued"}


@app.get(f"{API_BASE}/jobs/{{job_id}}", response_model=JobStatus)
def get_job_status(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")

    # Touch on poll to extend TTL while the user keeps the page open
    jobs.touch(job_id)

    audio_url: Optional[str] = None
    if job.status == "done" and job.result_path and job.result_path.exists():
        audio_url = f"{API_BASE}/jobs/{job.id}/audio"

    return JobStatus(
        job_id=job.id,
        status=job.status,  # type: ignore
        error=job.error,
        audio_url=audio_url,
        filename=job.filename,
        mime_type=job.mime_type,
    )


@app.get(f"{API_BASE}/jobs/{{job_id}}/audio")
def download_job_audio(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if job.status != "done":
        raise HTTPException(409, "Job not completed yet.")

    # If file was cleaned up already, report as gone
    if not job.result_path or not job.result_path.exists():
        raise HTTPException(410, "The generated audio has expired.")

    # Extend TTL on access
    jobs.touch(job_id)

    path: Path = job.result_path
    mime = job.mime_type or "application/octet-stream"
    return Response(
        content=path.read_bytes(),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{path.name}"'},
    )


# Support HEAD requests used by the UI to probe for expiry without downloading
@app.head(f"{API_BASE}/jobs/{{job_id}}/audio")
def head_job_audio(job_id: str):
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(404, "Job not found.")
    if job.status != "done":
        raise HTTPException(409, "Job not completed yet.")
    if not job.result_path or not job.result_path.exists():
        raise HTTPException(410, "The generated audio has expired.")
    # Extend TTL on HEAD access too
    jobs.touch(job_id)
    path: Path = job.result_path
    mime = job.mime_type or "application/octet-stream"
    return Response(status_code=200, media_type=mime, headers={
        "Content-Disposition": f'attachment; filename="{path.name}"'
    })


# -------- Server-Sent Events for job status --------
@app.get(f"{API_BASE}/jobs/{{job_id}}/events")
async def sse_job_events(request: Request, job_id: str):
    """
    SSE stream for job status changes: emits events 'status' with JSON payload.
    Closes when job is done/error or client disconnects.
    """
    async def event_generator():
        last_status = None
        while True:
            if await request.is_disconnected():
                break
            job = jobs.get(job_id)
            if not job:
                payload = {"error": "not_found"}
                yield f"event: status\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                break

            status = job.status
            if status != last_status:
                payload = {
                    "job_id": job.id,
                    "status": status,
                    "filename": job.filename,
                    "mime_type": job.mime_type,
                }
                if status == "done" and job.result_path and job.result_path.exists():
                    payload["audio_url"] = f"{API_BASE}/jobs/{job.id}/audio"
                yield f"event: status\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                last_status = status
                if status in ("done", "error"):
                    break

            await asyncio.sleep(1.0)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# -------- Synchronous streaming synthesis endpoint --------
@app.post(f"{API_BASE}/synthesize/stream")
async def synthesize_stream(req: SynthesisRequest):
    """
    Runs synthesis synchronously and streams the audio bytes to the client.
    Note: true live streaming during inference is not supported by the underlying model.
    Streaming begins after synthesis completes.
    """
    voices = list_voices._cache or discover_voices()  # type: ignore
    voice = voices.get(req.voice_id)
    if not voice:
        raise HTTPException(404, f"Voice '{req.voice_id}' not found.")

    # Run synthesis (blocking)
    wave, sr = synthesize_raw(
        voice=voice,
        text=req.text,
        speed=req.speed,
        nfe_step=req.nfe_step,
        seed=req.seed,
    )

    from .tts import stream_audio_bytes
    mime = "audio/wav" if req.format == "wav" else "audio/mpeg"
    filename = f"{voice.id}_stream.{ 'wav' if req.format == 'wav' else 'mp3' }"

    generator = stream_audio_bytes(wave, sr, fmt=req.format, chunk_samples=48000)
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(generator, media_type=mime, headers=headers)


# -------- Mount static site LAST so API routes take precedence --------
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


# -------- Direct run (python main.py) --------
if __name__ == "__main__":
    import uvicorn
    # IMPORTANT: pass the ASGI object directly so running from /app works.
    uvicorn.run(app, host=os.environ.get("HOST", "0.0.0.0"), port=int(os.environ.get("PORT", 8000)), reload=False)
