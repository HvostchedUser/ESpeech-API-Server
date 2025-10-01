# app/tts.py
from __future__ import annotations

import gc
import uuid
import struct
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Iterable

import numpy as np
import soundfile as sf
import torch
from huggingface_hub import hf_hub_download, snapshot_download
from ruaccent import RUAccent

# ESpeech / F5-TTS imports
from f5_tts.infer.utils_infer import (
    infer_process,
    load_model,
    load_vocoder,
    preprocess_ref_audio_text,
)
from f5_tts.model import DiT
import lameenc

from config import (
    MODEL_CFG,
    MODEL_FILE,
    MODEL_REPO,
    VOCAB_FILE,
    OUTPUT_DIR,
    KEEP_MODEL_IN_MEMORY,
    VOCODER_REPO,
    VOCODER_PREFETCH,
    VOCODER_OFFLINE_AFTER_PREFETCH,
)
from voices import Voice


@dataclass
class _ModelBundle:
    model: any
    vocoder: any
    device: torch.device
    accentizer: RUAccent


_BUNDLE: Optional[_ModelBundle] = None


def _download_model_files() -> Tuple[Path, Path]:
    model_path = hf_hub_download(repo_id=MODEL_REPO, filename=MODEL_FILE)
    vocab_path = hf_hub_download(repo_id=MODEL_REPO, filename=VOCAB_FILE)
    return Path(model_path), Path(vocab_path)


def _prefetch_vocoder():
    """
    Ensure the Vocos repo is already present in the local HF cache so that
    the subsequent call to load_vocoder() doesn't hit the network (or at least
    finds the snapshot locally). Optionally switches HF to offline mode.
    """
    if VOCODER_PREFETCH:
        try:
            # This will noop if already cached.
            snapshot_download(repo_id=VOCODER_REPO, local_files_only=False)
        except Exception:
            # Don't crash startup just because prefetch failed; the loader will try normally.
            pass

        if VOCODER_OFFLINE_AFTER_PREFETCH:
            # Avoids further network checks if the snapshot is available.
            os.environ.setdefault("HF_HUB_OFFLINE", "1")


def _maybe_init_bundle() -> _ModelBundle:
    global _BUNDLE
    if _BUNDLE is not None:
        return _BUNDLE

    model_path, vocab_path = _download_model_files()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # Prefetch vocoder snapshot into HF cache (optional, but prevents repeated downloads/logs)
    _prefetch_vocoder()

    model = load_model(DiT, MODEL_CFG, str(model_path), vocab_file=str(vocab_path))
    vocoder = load_vocoder()

    accentizer = RUAccent()
    accentizer.load(omograph_model_size="turbo3.1", use_dictionary=True, tiny_mode=False)

    model.to(device)
    vocoder.to(device)

    _BUNDLE = _ModelBundle(model=model, vocoder=vocoder, device=device, accentizer=accentizer)
    return _BUNDLE


def _process_text_with_accent(text: str, accentizer: RUAccent) -> str:
    if not text or "+" in text:
        return text
    return accentizer.process_all(text)


def _encode_mp3_from_float32(wave: np.ndarray, sample_rate: int) -> bytes:
    if wave.ndim == 2 and wave.shape[1] == 1:
        wave = wave[:, 0]
    wav_i16 = np.clip(wave, -1.0, 1.0)
    wav_i16 = (wav_i16 * 32767.0).astype(np.int16)

    enc = lameenc.Encoder()
    enc.set_in_sample_rate(sample_rate)
    enc.set_channels(1)
    enc.set_bit_rate(192)
    enc.set_quality(2)
    mp3_bytes = enc.encode(wav_i16.tobytes())
    mp3_bytes += enc.flush()
    return mp3_bytes


def _mp3_stream_from_float32(wave: np.ndarray, sample_rate: int, chunk_samples: int = 48000) -> Iterable[bytes]:
    if wave.ndim == 2 and wave.shape[1] == 1:
        wave = wave[:, 0]
    wav_i16 = np.clip(wave, -1.0, 1.0)
    wav_i16 = (wav_i16 * 32767.0).astype(np.int16)

    enc = lameenc.Encoder()
    enc.set_in_sample_rate(sample_rate)
    enc.set_channels(1)
    enc.set_bit_rate(192)
    enc.set_quality(2)

    total = len(wav_i16)
    start = 0
    step = max(1152, chunk_samples)
    while start < total:
        end = min(start + step, total)
        chunk = wav_i16[start:end]
        yield enc.encode(chunk.tobytes())
        start = end
    yield enc.flush()


def _wav_header(num_samples: int, sample_rate: int, num_channels: int = 1, sample_width: int = 2) -> bytes:
    byte_rate = sample_rate * num_channels * sample_width
    block_align = num_channels * sample_width
    data_size = num_samples * sample_width * num_channels
    riff_size = 36 + data_size
    return (
        b"RIFF" +
        struct.pack("<I", riff_size) +
        b"WAVEfmt " +
        struct.pack("<I", 16) +
        struct.pack("<H", 1) +
        struct.pack("<H", num_channels) +
        struct.pack("<I", sample_rate) +
        struct.pack("<I", byte_rate) +
        struct.pack("<H", block_align) +
        struct.pack("<H", sample_width * 8) +
        b"data" +
        struct.pack("<I", data_size)
    )


def _wav_stream_from_float32(wave: np.ndarray, sample_rate: int, chunk_samples: int = 65536) -> Iterable[bytes]:
    if wave.ndim == 2 and wave.shape[1] == 1:
        wave = wave[:, 0]
    wav_i16 = np.clip(wave, -1.0, 1.0)
    wav_i16 = (wav_i16 * 32767.0).astype(np.int16)

    yield _wav_header(num_samples=len(wav_i16), sample_rate=sample_rate, num_channels=1, sample_width=2)

    total = len(wav_i16)
    start = 0
    while start < total:
        end = min(start + chunk_samples, total)
        chunk = wav_i16[start:end]
        yield chunk.tobytes()
        start = end


def synthesize_raw(
    voice: Voice,
    text: str,
    *,
    speed: float = 1.0,
    nfe_step: int = 64,
    seed: int = -1,
) -> Tuple[np.ndarray, int]:
    bundle = _maybe_init_bundle()
    device = bundle.device

    ref_text = _process_text_with_accent(voice.ref_text, bundle.accentizer)
    gen_text = _process_text_with_accent(text, bundle.accentizer)

    ref_audio_proc, ref_text_final = preprocess_ref_audio_text(str(voice.ref_audio_path), ref_text)

    if seed < 0 or seed > 2**31 - 1:
        seed = int(np.random.randint(0, 2**31 - 1))
    torch.manual_seed(seed)

    try:
        final_wave, final_sample_rate, _ = infer_process(
            ref_audio_proc,
            ref_text_final,
            gen_text,
            bundle.model,
            bundle.vocoder,
            nfe_step=nfe_step,
            speed=speed,
        )
    finally:
        if device.type == "cuda" and not KEEP_MODEL_IN_MEMORY:
            try:
                bundle.model.to("cpu")
                bundle.vocoder.to("cpu")
                torch.cuda.empty_cache()
                gc.collect()
            except Exception:
                pass

    return final_wave, final_sample_rate


def synthesize_to_file(
    voice: Voice,
    text: str,
    *,
    speed: float = 1.0,
    nfe_step: int = 64,
    seed: int = -1,
    fmt: str = "mp3",
) -> Tuple[Path, str]:
    final_wave, final_sample_rate = synthesize_raw(
        voice=voice, text=text, speed=speed, nfe_step=nfe_step, seed=seed
    )

    uid = uuid.uuid4().hex[:10]
    base_name = f"{voice.id}_{uid}"
    if fmt == "wav":
        out_path = OUTPUT_DIR / f"{base_name}.wav"
        sf.write(str(out_path), final_wave, final_sample_rate)
        mime = "audio/wav"
        return out_path, mime

    mp3_bytes = _encode_mp3_from_float32(final_wave, final_sample_rate)
    out_path = OUTPUT_DIR / f"{base_name}.mp3"
    out_path.write_bytes(mp3_bytes)
    mime = "audio/mpeg"
    return out_path, mime


def stream_audio_bytes(
    wave: np.ndarray,
    sample_rate: int,
    fmt: str = "mp3",
    chunk_samples: int = 48000,
) -> Iterable[bytes]:
    if fmt == "wav":
        yield from _wav_stream_from_float32(wave, sample_rate, chunk_samples=max(4096, chunk_samples))
    else:
        yield from _mp3_stream_from_float32(wave, sample_rate, chunk_samples=chunk_samples)
