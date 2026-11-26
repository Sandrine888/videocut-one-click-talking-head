"""Single-worker job boundary owned by B. UI never parses console output."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json
from pathlib import Path
import threading
import time
import uuid

from .pipeline import GenerateOptions, GenerationError, generate, write_json


class BusyError(RuntimeError):
    pass


class JobManager:
    def __init__(self, workspace, adapters=None, runner=generate):
        self.root = Path(workspace).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.adapters, self.runner = adapters, runner
        self._lock = threading.RLock()
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="videocut")
        self._jobs, self._active, self._closing = {}, None, False
        directory = self.root / "jobs"
        directory.mkdir(exist_ok=True)
        for path in directory.glob("*.json"):
            try:
                job = json.loads(path.read_text(encoding="utf-8"))
                if job["status"] in {"queued", "running"}:
                    job.update(status="failed", message="服务已重启，此前任务已中断，请重新生成。")
                    write_json(path, job)
                self._jobs[job["task_id"]] = job
            except (OSError, ValueError, KeyError, TypeError):
                continue

    def _save(self, job):
        write_json(self.root / "jobs" / (job["task_id"] + ".json"), job)

    def snapshot(self, task_id):
        with self._lock:
            if task_id not in self._jobs:
                raise KeyError("找不到该任务。")
            # Return a detached snapshot; workers must not mutate HTTP responses.
            return json.loads(json.dumps(self._jobs[task_id], ensure_ascii=False))

    def start(self, options, *, request_key=None):
        with self._lock:
            if self._closing:
                raise BusyError("工具正在退出，请重新启动后生成。")
            if self._active:
                active = self._jobs[self._active]
                if request_key and active.get("request_key") == request_key:
                    return self.snapshot(self._active)
                raise BusyError("已有视频正在处理，请等当前任务完成。")
            task_id = uuid.uuid4().hex
            job = dict(task_id=task_id, status="queued", stage="等待",
                       message="已开始准备生成。", request_key=request_key,
                       created_at=time.time(), options=asdict(options), events=[])
            self._jobs[task_id], self._active = job, task_id
            self._save(job)
            self._pool.submit(self._run, task_id, options)
            return self.snapshot(task_id)

    def _run(self, task_id, options):
        def progress(event):
            with self._lock:
                job = self._jobs[task_id]
                job.update(status="running", stage=event["stage"], message=event["message"])
                job["events"].append(event)
                self._save(job)
        try:
            result = self.runner(options, adapters=self.adapters, on_event=progress, task_id=task_id)
            with self._lock:
                job = self._jobs[task_id]
                job.update(status="completed", result=result, message="生成已结束，请预览并查看检查状态。")
        except Exception as exc:
            with self._lock:
                job = self._jobs[task_id]
                job.update(status="failed", message=str(exc),
                           stage=getattr(exc, "stage", job["stage"]),
                           task_dir=getattr(exc, "task_dir", None))
        finally:
            with self._lock:
                self._save(self._jobs[task_id])
                self._active = None

    def close(self):
        self._pool.shutdown(wait=True)

    def begin_shutdown(self):
        with self._lock:
            if self._active:
                raise BusyError("视频正在处理，完成后再退出工具。")
            self._closing = True
