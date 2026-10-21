"""Verify ownership and cleanup without starting services or touching bank data."""
import importlib.util
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('membrain_start_local', ROOT / 'tools/start_local.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


class LauncherTests(unittest.TestCase):
    def process(self, code=None):
        process = MagicMock()
        process.poll.return_value = code
        process.wait.return_value = code or 0
        process.returncode = code or 0
        return process

    def test_owned_services_stop_when_cli_exits(self):
        api, worker, cli = self.process(), self.process(), self.process(0)
        with TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)), \
             patch.object(launcher, 'postgres') as postgres, patch.object(launcher, 'available', return_value=True), \
             patch.object(launcher, 'wait_api'), patch.object(launcher.time, 'sleep'), \
             patch.object(launcher.subprocess, 'run', return_value=MagicMock(returncode=0)), \
             patch.object(launcher.subprocess, 'Popen', side_effect=[api, worker, cli]) as spawn:
            self.assertEqual(launcher.supervise('menu', 8123, True), 0)
            postgres.assert_called_once()
            api.terminate.assert_called_once()
            worker.terminate.assert_called_once()
            self.assertIn('--no-setup', spawn.call_args_list[-1].args[0])
            self.assertIn('http://127.0.0.1:8123', spawn.call_args_list[-1].args[0])

    def test_reused_api_is_not_migrated_or_stopped(self):
        worker, cli = self.process(), self.process(0)
        with TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)), \
             patch.object(launcher, 'postgres'), patch.object(launcher, 'available', return_value=False), \
             patch.object(launcher, 'wait_api'), patch.object(launcher.time, 'sleep'), \
             patch.object(launcher.subprocess, 'run') as migrate, \
             patch.object(launcher.subprocess, 'Popen', side_effect=[worker, cli]):
            self.assertEqual(launcher.supervise(), 0)
            migrate.assert_not_called()
            worker.terminate.assert_called_once()

    def test_startup_failure_cleans_up_owned_api(self):
        api = self.process()
        with TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)), \
             patch.object(launcher, 'postgres'), patch.object(launcher, 'available', return_value=True), \
             patch.object(launcher, 'wait_api', side_effect=launcher.StartupError('not ready')), \
             patch.object(launcher.subprocess, 'run', return_value=MagicMock(returncode=0)), \
             patch.object(launcher.subprocess, 'Popen', return_value=api):
            with self.assertRaises(launcher.StartupError):
                launcher.supervise()
            api.terminate.assert_called_once()

    def test_graceful_stop_escalates_only_for_owned_process(self):
        process = self.process()
        process.wait.side_effect = [subprocess.TimeoutExpired('worker', 10), 0]
        launcher.stop(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()

    def test_wait_does_not_accept_an_unrelated_http_service(self):
        with patch.object(launcher, 'fetch', side_effect=[{'status': 'ok'}, {'info': {'title': 'Other API'}}]):
            with self.assertRaises(launcher.StartupError):
                launcher.wait_api('http://127.0.0.1:8000', None)

    def test_already_running_database_is_left_unchanged(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / '.local/postgres').mkdir(parents=True)
            (root / '.local/postgres/PG_VERSION').write_text('18')
            with patch.object(launcher, 'ROOT', root), patch('app.database.database_url') as url, \
                 patch.object(launcher.shutil, 'which', return_value='/fake/pg_ctl'), \
                 patch.object(launcher.subprocess, 'run', return_value=MagicMock(returncode=0)) as run:
                url.return_value.host = '127.0.0.1'
                launcher.postgres()
                self.assertEqual(run.call_count, 1)
                self.assertEqual(run.call_args.args[0][-1], 'status')
