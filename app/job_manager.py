# app/job_manager.py
from __future__ import annotations

import os
import time
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor, Future
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Callable, Tuple, Iterable

import requests

from config import MAX_WORKERS, OUTPUT_DIR
from voices import Voice
from tts import synthesize_to_file


@dataclass
class Job:
    id: str
    status: str = "queued"  # queued | running | done | error
    error: Optional[str] = None
    result_path: Optional[Path] = None
    mime_type: Optional[str] = None
    filename: Optional[str] = None
    last_access_ts: float = 0.0  # updated on completion and when accessed
    callback_url: Optional[str] = None  # optional webhook


class JobManager:
    def __init__(self, max_workers: int = MAX_WORKERS):
        self._executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="tts")
        self._jobs: Dict[str, Job] = {}
        self._futures: Dict[str, Future] = {}
        self._lock = threading.Lock()

    def submit(
        self,
        voice: Voice,
        text: str,
        *,
        speed: float,
        nfe_step: int,
        seed: int,
        fmt: str,
        callback_url: Optional[str] = None,
    ) -> str:
        job_id = uuid.uuid4().hex
        job = Job(id=job_id, callback_url=callback_url)
        with self._lock:
            self._jobs[job_id] = job

        def task() -> Tuple[Path, str]:
            return synthesize_to_file(
                voice=voice,
                text=text,
                speed=speed,
                nfe_step=nfe_step,
                seed=seed,
                fmt=fmt,
            )

        def done_callback(fut: Future):
            try:
                out_path, mime = fut.result()
                now = time.time()
                with self._lock:
                    j = self._jobs[job_id]
                    j.status = "done"
                    j.result_path = out_path
                    j.mime_type = mime
                    j.filename = out_path.name
                    j.last_access_ts = now
                # Fire webhook (non-blocking)
                self._post_webhook_safe(job_id)
            except Exception as e:
                with self._lock:
                    j = self._jobs[job_id]
                    j.status = "error"
                    j.error = f"{e}\n{traceback.format_exc()}"
                # Fire webhook (non-blocking)
                self._post_webhook_safe(job_id)

        with self._lock:
            self._jobs[job_id].status = "queued"

        fut = self._executor.submit(self._run_with_status, job_id, task)
        fut.add_done_callback(done_callback)
        with self._lock:
            self._futures[job_id] = fut
        return job_id

    def _post_webhook_safe(self, job_id: str) -> None:
        """POST final job state to callback_url, if provided."""
        def _worker():
            job = self.get(job_id)
            if not job or not job.callback_url:
                return
            payload = {
                "job_id": job.id,
                "status": job.status,
                "error": job.error,
                "filename": job.filename,
                "mime_type": job.mime_type,
            }
            try:
                # Short timeouts; webhook should be quick.
                requests.post(job.callback_url, json=payload, timeout=5)
            except Exception:
                # Silence webhook errors; do not crash the service
                pass

        t = threading.Thread(target=_worker, name=f"webhook-{job_id[:6]}", daemon=True)
        t.start()

    def _run_with_status(self, job_id: str, fn: Callable[[], Tuple[Path, str]]):
        with self._lock:
            self._jobs[job_id].status = "running"
        return fn()

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def exists(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._jobs

    # ---- Access & cleanup helpers ----

    def touch(self, job_id: str) -> None:
        """Mark job as accessed (used to extend TTL)."""
        now = time.time()
        with self._lock:
            j = self._jobs.get(job_id)
            if j:
                j.last_access_ts = now
                if j.result_path and j.result_path.exists():
                    try:
                        os.utime(j.result_path, times=(now, now))
                    except Exception:
                        pass

    def iter_jobs(self) -> Iterable[Job]:
        with self._lock:
            return list(self._jobs.values())

    def cleanup_expired(self, retention_seconds: int) -> int:
        """
        Delete output files that haven't been accessed for `retention_seconds`.
        Returns the number of files deleted.
        """
        now = time.time()
        deleted = 0
        with self._lock:
            for j in self._jobs.values():
                if j.status == "done" and j.result_path and j.result_path.exists():
                    last = j.last_access_ts or (j.result_path.stat().st_mtime)
                    if now - last >= retention_seconds:
                        try:
                            j.result_path.unlink(missing_ok=True)
                            deleted += 1
                        except Exception:
                            pass
                        finally:
                            j.result_path = None
                            j.filename = None
                            j.mime_type = None
        # Defensive: purge orphan files in OUTPUT_DIR
        for p in OUTPUT_DIR.glob("*"):
            try:
                if not p.is_file():
                    continue
                age = now - p.stat().st_mtime
                if age >= retention_seconds and not self._is_tracked_file(p):
                    p.unlink(missing_ok=True)
                    deleted += 1
            except Exception:
                pass
        return deleted

    def _is_tracked_file(self, path: Path) -> bool:
        with self._lock:
            for j in self._jobs.values():
                if j.result_path and j.result_path == path:
                    return True
        return False
