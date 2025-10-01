# app/voices.py
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Tuple

from config import VOICES_DIR, AUDIO_EXTS


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    folder: Path
    ref_text_path: Path
    ref_audio_path: Path

    @property
    def ref_text(self) -> str:
        return self.ref_text_path.read_text(encoding="utf-8").strip()


def _find_ref_files(folder: Path) -> Tuple[Optional[Path], Optional[Path]]:
    """Locate ref_text.txt (or *.txt) and an audio file in a voice folder."""
    ref_text_path = None
    # Prefer 'ref_text.txt', otherwise pick the first *.txt
    preferred = folder / "ref_text.txt"
    if preferred.exists():
        ref_text_path = preferred
    else:
        txts = sorted(folder.glob("*.txt"))
        if txts:
            ref_text_path = txts[0]

    audio_path = None
    for ext in AUDIO_EXTS:
        match = sorted(folder.glob(f"*{ext}"))
        if match:
            audio_path = match[0]
            break

    return ref_text_path, audio_path


def discover_voices() -> Dict[str, Voice]:
    """
    Scan VOICES_DIR and return a dict {voice_id: Voice}.
    A valid voice contains a .txt with reference text and an audio file.
    Optionally, a meta.json with {"name": "..."} can be provided for nicer display names.
    """
    voices: Dict[str, Voice] = {}
    if not VOICES_DIR.exists():
        return voices

    for item in sorted(VOICES_DIR.iterdir()):
        if not item.is_dir():
            continue
        ref_text_path, audio_path = _find_ref_files(item)
        if not ref_text_path or not audio_path:
            continue

        voice_id = item.name
        display_name = voice_id

        meta = item / "meta.json"
        if meta.exists():
            try:
                meta_data = json.loads(meta.read_text(encoding="utf-8"))
                display_name = meta_data.get("name", display_name)
            except Exception:
                pass

        voices[voice_id] = Voice(
            id=voice_id,
            name=display_name,
            folder=item,
            ref_text_path=ref_text_path,
            ref_audio_path=audio_path,
        )
    return voices

