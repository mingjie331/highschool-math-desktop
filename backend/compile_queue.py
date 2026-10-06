"""One compiler, bounded preview work and cancellation scoped to an editor."""
from concurrent.futures import Future
from dataclasses import dataclass, field
import threading
from typing import Callable


class CompileCancelled(RuntimeError):
    pass


@dataclass
class CompileJob:
    run: Callable[[threading.Event], bytes]
    priority: int
    order: int
    session: str | None = None
    revision: int = 0
    cancelled: threading.Event = field(default_factory=threading.Event)
    future: Future = field(default_factory=Future)


class CompileScheduler:
    def __init__(self):
        self._condition = threading.Condition()
        self._queue: list[CompileJob] = []
        self._sessions: dict[str, CompileJob] = {}
        self._active: CompileJob | None = None
        self._thread: threading.Thread | None = None
        self._stopped = False
        self._order = 0
        self._interactive_burst = 0

    def start(self):
        with self._condition:
            if self._thread and self._thread.is_alive() and self._stopped:
                raise RuntimeError('上一次编译尚未停止')
            self._stopped = False

    @staticmethod
    def _cancel(job, message='预览已过期或取消'):
        job.cancelled.set()
        if not job.future.done():
            job.future.set_exception(CompileCancelled(message))

    def submit(self, run, *, priority=0, session=None, revision=0) -> CompileJob:
        with self._condition:
            if self._stopped:
                raise RuntimeError('应用正在退出，编译已停止。')
            previous = self._sessions.get(session) if session else None
            if previous and revision == previous.revision:
                return previous
            self._order += 1
            job = CompileJob(run, priority, self._order, session, revision)
            if previous and revision < previous.revision:
                self._cancel(job)
                return job
            if previous:
                self._cancel(previous)
            if session:
                self._sessions[session] = job
            self._queue = [item for item in self._queue if not item.future.done()]
            self._queue.append(job)
            # Only completed sessions may be evicted; active sessions stay bounded.
            if len(self._sessions) > 256:
                for key, item in list(self._sessions.items()):
                    if item.future.done() and item is not job:
                        self._sessions.pop(key)
                        if len(self._sessions) <= 256:
                            break
            if not self._thread or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._worker, name='latex-compiler', daemon=True)
                self._thread.start()
            self._condition.notify_all()
            return job

    def cancel(self, session, revision):
        with self._condition:
            job = self._sessions.get(session)
            if job and job.revision == revision:
                self._cancel(job)
                self._condition.notify_all()

    def cancel_job(self, job):
        with self._condition:
            self._cancel(job)
            self._condition.notify_all()

    def stop(self):
        with self._condition:
            self._stopped = True
            for job in self._queue + ([self._active] if self._active else []):
                self._cancel(job, '应用正在退出，编译已停止。')
            self._queue.clear()
            self._condition.notify_all()
            thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=5)
        with self._condition:
            self._sessions.clear()

    def _worker(self):
        while True:
            with self._condition:
                self._queue = [job for job in self._queue if not job.future.done()]
                while not self._queue and not self._stopped:
                    self._condition.wait()
                    self._queue = [job for job in self._queue if not job.future.done()]
                if self._stopped:
                    return
                exports = [job for job in self._queue if job.priority == 2]
                if exports and self._interactive_burst >= 5:
                    job = min(exports, key=lambda item: item.order)
                else:
                    job = min(self._queue, key=lambda item: (item.priority, item.order))
                self._queue.remove(job)
                self._active = job
                self._interactive_burst = 0 if job.priority == 2 else self._interactive_burst + 1
            try:
                if not job.cancelled.is_set():
                    result = job.run(job.cancelled)
                    with self._condition:
                        if not job.future.done():
                            job.future.set_result(result)
            except Exception as exc:
                with self._condition:
                    if not job.future.done():
                        job.future.set_exception(exc)
            finally:
                with self._condition:
                    self._active = None

