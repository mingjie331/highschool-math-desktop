import threading
import unittest
from backend.compile_queue import CompileScheduler, CompileCancelled


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.scheduler = CompileScheduler()
        self.release = threading.Event()
        self.addCleanup(self.scheduler.stop)
        self.addCleanup(self.release.set)

    def blocked(self, priority=0, session=None, revision=0):
        started = threading.Event()
        def run(cancelled):
            started.set()
            self.release.wait(3)
            return b'blocker'
        job = self.scheduler.submit(run, priority=priority, session=session, revision=revision)
        self.assertTrue(started.wait(1))
        return job

    def test_pending_preview_keeps_only_latest(self):
        blocker = self.blocked()
        ran = []
        jobs = [self.scheduler.submit(lambda cancel, n=n: ran.append(n) or b'pdf',
                                     priority=1, session='editor', revision=n) for n in range(1, 11)]
        self.release.set()
        blocker.future.result(2)
        self.assertEqual(jobs[-1].future.result(2), b'pdf')
        self.assertEqual(ran, [10])
        for job in jobs[:-1]:
            self.assertIsInstance(job.future.exception(), CompileCancelled)

    def test_cancel_active_preview_does_not_cancel_save(self):
        started = threading.Event()
        ended = threading.Event()
        def preview(cancelled):
            started.set()
            cancelled.wait(3)
            ended.set()
            return b'old'
        old = self.scheduler.submit(preview, priority=1, session='editor', revision=1)
        self.assertTrue(started.wait(1))
        save = self.scheduler.submit(lambda cancel: b'saved', priority=0)
        latest = self.scheduler.submit(lambda cancel: b'latest', priority=1, session='editor', revision=2)
        self.assertTrue(ended.wait(1))
        self.assertIsInstance(old.future.exception(), CompileCancelled)
        self.assertEqual(save.future.result(2), b'saved')
        self.assertEqual(latest.future.result(2), b'latest')

    def test_late_request_and_old_cancel_cannot_replace_latest(self):
        self.blocked()
        latest = self.scheduler.submit(lambda cancel: b'latest', priority=1, session='e', revision=2)
        old = self.scheduler.submit(lambda cancel: b'old', priority=1, session='e', revision=1)
        self.scheduler.cancel('e', 1)
        self.release.set()
        self.assertEqual(latest.future.result(2), b'latest')
        self.assertIsInstance(old.future.exception(), CompileCancelled)

    def test_save_precedes_queued_preview(self):
        self.blocked()
        ran = []
        preview = self.scheduler.submit(lambda cancel: ran.append('preview') or b'', priority=1)
        save = self.scheduler.submit(lambda cancel: ran.append('save') or b'', priority=0)
        self.release.set()
        save.future.result(2); preview.future.result(2)
        self.assertEqual(ran, ['save', 'preview'])

    def test_export_is_not_starved_by_interactive_work(self):
        self.blocked()
        ran = []
        export = self.scheduler.submit(lambda cancel: ran.append('export') or b'', priority=2)
        jobs = [self.scheduler.submit(lambda cancel, n=n: ran.append(n) or b'', priority=0) for n in range(12)]
        self.release.set()
        for job in jobs: job.future.result(2)
        export.future.result(2)
        self.assertLessEqual(ran.index('export'), 5)

    def test_shutdown_unblocks_waiters_and_restart_works(self):
        started = threading.Event()
        job = self.scheduler.submit(lambda cancel: started.set() or cancel.wait(3) or b'')
        self.assertTrue(started.wait(1))
        queued = self.scheduler.submit(lambda cancel: b'queued')
        self.scheduler.stop()
        self.assertIsInstance(job.future.exception(), CompileCancelled)
        self.assertIsInstance(queued.future.exception(), CompileCancelled)
        self.scheduler.start()
        self.assertEqual(self.scheduler.submit(lambda cancel: b'new').future.result(2), b'new')
