"""Lightweight in-process async job queue.

Jobs are kept in memory only. For multi-replica or persistent
deployments, swap this for Redis/RQ or Celery.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    status: str = "queued"  # queued | running | done | error
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    progress: Optional[float] = None  # 0..1
    progress_seconds: Optional[float] = None
    duration_seconds: Optional[float] = None
    result: Optional[Any] = None
    error: Optional[str] = None
    metadata: Optional[Any] = None

    def to_dict(self) -> dict:
        return asdict(self)


class JobQueue:
    def __init__(self, workers: int = 1, max_jobs_kept: int = 200) -> None:
        self._jobs: Dict[str, Job] = {}
        self._order: List[str] = []
        self._lock = threading.Lock()
        self._queue: "queue.Queue" = queue.Queue()
        self._workers: List[threading.Thread] = []
        self._max_jobs_kept = max_jobs_kept
        for i in range(max(1, workers)):
            t = threading.Thread(
                target=self._worker_loop, name=f"whisper-worker-{i}", daemon=True
            )
            t.start()
            self._workers.append(t)
        logger.info("JobQueue started with %d worker(s).", workers)

    def submit(
        self, fn: Callable[[Job], Any], metadata: Any = None
    ) -> Job:
        job = Job(id=uuid.uuid4().hex, metadata=metadata)
        with self._lock:
            self._jobs[job.id] = job
            self._order.append(job.id)
            self._evict_locked()
        self._queue.put((job, fn))
        return job

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list_jobs(self) -> List[Job]:
        with self._lock:
            return [self._jobs[i] for i in self._order if i in self._jobs]

    def _evict_locked(self) -> None:
        # Drop oldest finished jobs once we're over the cap.
        if len(self._order) <= self._max_jobs_kept:
            return
        keep: List[str] = []
        removable: List[str] = []
        for jid in self._order:
            j = self._jobs.get(jid)
            if j and j.status in ("done", "error"):
                removable.append(jid)
            else:
                keep.append(jid)
        excess = len(self._order) - self._max_jobs_kept
        for jid in removable[:excess]:
            self._jobs.pop(jid, None)
        self._order = [j for j in self._order if j in self._jobs]

    def _worker_loop(self) -> None:
        while True:
            job, fn = self._queue.get()
            job.status = "running"
            job.started_at = time.time()
            try:
                result = fn(job)
                job.result = result
                job.status = "done"
                job.progress = 1.0
            except Exception as e:
                logger.exception("Job %s failed", job.id)
                job.error = str(e)
                job.status = "error"
            finally:
                job.finished_at = time.time()
                self._queue.task_done()
