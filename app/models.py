# app/models.py
from __future__ import annotations

from typing import Optional, Literal, List
from pydantic import BaseModel, Field, AnyUrl


class VoiceInfo(BaseModel):
    id: str
    name: str
    ref_text_file: str
    ref_audio_file: str


class ListVoicesResponse(BaseModel):
    voices: List[VoiceInfo]


class SynthesisRequest(BaseModel):
    voice_id: str = Field(..., description="Folder name in voices/ for the chosen voice.")
    text: str = Field(..., description="Text to synthesize (Russian text; stress marks optional).")
    speed: float = Field(1.0, ge=0.5, le=2.0)
    nfe_step: int = Field(71, ge=8, le=128)
    seed: int = Field(-1, description="-1 for random")
    format: Literal["wav", "mp3"] = Field("mp3")
    callback_url: Optional[AnyUrl] = Field(
        None,
        description="Optional webhook URL. If provided, the server will POST the final status JSON when the job finishes or fails.",
    )


class JobStatus(BaseModel):
    job_id: str
    status: Literal["queued", "running", "done", "error"]
    error: Optional[str] = None
    audio_url: Optional[str] = None  # populated when done
    filename: Optional[str] = None   # basename of the audio file
    mime_type: Optional[str] = None
