"""Poll off the input thread; deliver results only between terminal prompts."""
from __future__ import annotations
from dataclasses import replace
from queue import Queue, Empty
from threading import Event, Lock, Thread
from .types import Backend, ClientError, Context, Job, Result


class Monitor:
    def __init__(self, backend: Backend, interval: float = 1.0):
        """Poll backend every interval seconds; callers drain queued notifications."""
        self.backend, self.interval = backend, interval
        self.pending: dict = {}
        self.completed: dict = {}
        self.lock = Lock()
        self.stop_event = Event()
        self.messages = Queue()
        self.thread = Thread(target=self._run, daemon=True)

    def start(self):
        self.thread.start()

    def watch(self, job: Job, context: Context):
        if job.status in ('succeeded', 'failed', 'cancelled'):
            return
        with self.lock:
            self.pending[job.id] = (job, context)
            self.completed.pop(job.id, None)

    def tick(self):
        with self.lock:
            jobs = list(self.pending.values())
        for job, context in jobs:
            if self.stop_event.is_set():
                return
            try:
                status, result = self.backend.poll(job, context)
            except ClientError:
                # Keep tracking through temporary disconnections; report once per job.
                with self.lock:
                    notified = self.completed.get(('offline', job.id))
                    self.completed[('offline', job.id)] = True
                if not notified:
                    self.messages.put((job, Result('API unavailable while checking work; polling will resume.', context)))
                continue
            with self.lock:
                self.completed.pop(('offline', job.id), None)
            if status in ('succeeded', 'failed', 'cancelled'):
                with self.lock:
                    self.pending.pop(job.id, None)
                    self.completed[job.id] = result
                self.messages.put((replace(job, status=status), result))

    def _run(self):
        while not self.stop_event.wait(self.interval):
            self.tick()

    def drain(self) -> list[tuple[Job, Result]]:
        results = []
        while True:
            try:
                results.append(self.messages.get_nowait())
            except Empty:
                return results

    def stop(self):
        self.stop_event.set()
        if self.thread.is_alive():
            self.thread.join(timeout=12)
