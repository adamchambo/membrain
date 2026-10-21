"""Service ownership, PID verification and client lifecycle checks."""
import importlib.util
import json
from pathlib import Path
import subprocess
import socket
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

    def test_port_with_recent_connections_can_be_rebound(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(('127.0.0.1', 0))
            listener.listen()
            port = listener.getsockname()[1]
            self.assertFalse(launcher.available(port))
            with socket.create_connection(('127.0.0.1', port)) as client:
                connection, _ = listener.accept()
                connection.close()
                self.assertEqual(client.recv(1), b'')
        self.assertTrue(launcher.available(port))

    def test_cli_exit_leaves_services_to_the_supervisor(self):
        with patch.object(launcher, 'ensure_services') as ensure, patch.object(launcher.subprocess, 'call', return_value=0) as client, patch.object(launcher, 'stop') as stop:
            self.assertEqual(launcher.supervise('menu', 8123, True), 0)
            ensure.assert_called_once_with(8123)
            self.assertIn('--no-setup', client.call_args.args[0])
            stop.assert_not_called()

    def test_healthy_existing_stack_does_not_spawn_duplicate_services(self):
        with TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)), patch.object(launcher, 'available', return_value=False), patch.object(launcher, 'wait_api'), patch.object(launcher, 'fetch', return_value={'worker': {'ready': True}}), patch.object(launcher.subprocess, 'Popen') as spawn:
            launcher.ensure_services(8000)
            spawn.assert_not_called()

    def test_startup_failure_cleans_up_only_owned_api(self):
        api = self.process()
        with TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)), patch.object(launcher, 'postgres'), patch.object(launcher, 'available', return_value=True), patch.object(launcher, 'wait_api', side_effect=launcher.StartupError('not ready')), patch.object(launcher.subprocess, 'run', return_value=MagicMock(returncode=0)), patch.object(launcher.subprocess, 'Popen', return_value=api):
            with self.assertRaises(launcher.StartupError): launcher.serve(8000, 'test')
            api.terminate.assert_called_once()

    def test_stop_ignores_stale_or_unrelated_process(self):
        with TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)), patch.object(launcher.subprocess, 'run', return_value=MagicMock(stdout='/usr/bin/unrelated')) as inspect, patch.object(launcher.os, 'kill') as kill:
            path=launcher.registry_path(8000);path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'pid':123,'token':'safe-token'}))
            self.assertEqual(launcher.stop_services(8000),0)
            kill.assert_not_called()

    def test_registry_requires_the_exact_supervisor_token(self):
        with TemporaryDirectory() as directory, patch.object(launcher, 'ROOT', Path(directory)):
            path=launcher.registry_path(8000);path.parent.mkdir(parents=True)
            path.write_text(json.dumps({'pid':123,'token':'safe-token'}))
            command=f'{directory}/.venv/bin/python {directory}/tools/start_local.py serve --port 8000 --service-token safe-token'
            with patch.object(launcher.subprocess,'run',return_value=MagicMock(stdout=command)):
                self.assertEqual(launcher.managed_service(8000)['pid'],123)
            with patch.object(launcher.subprocess,'run',return_value=MagicMock(stdout=command.replace('safe-token','wrong-token'))):
                self.assertIsNone(launcher.managed_service(8000))

    def test_graceful_stop_escalates_only_for_owned_process(self):
        process = self.process()
        process.wait.side_effect = [subprocess.TimeoutExpired('worker', 10), 0]
        launcher.stop(process)
        process.terminate.assert_called_once()
        process.kill.assert_called_once()

    def test_wait_does_not_accept_an_unrelated_http_service(self):
        with patch.object(launcher, 'fetch', side_effect=[{'status': 'ok'}, {'info': {'title': 'Other API'}}]):
            with self.assertRaises(launcher.StartupError): launcher.wait_api('http://127.0.0.1:8000',None)

    def test_already_running_database_is_left_unchanged(self):
        with TemporaryDirectory() as directory:
            root = Path(directory);(root/'.local/postgres').mkdir(parents=True)
            (root/'.local/postgres/PG_VERSION').write_text('18')
            with patch.object(launcher,'ROOT',root),patch('app.database.database_url') as url,patch.object(launcher.shutil,'which',return_value='/fake/pg_ctl'),patch.object(launcher.subprocess,'run',return_value=MagicMock(returncode=0)) as run:
                url.return_value.host='127.0.0.1';launcher.postgres();self.assertEqual(run.call_count,1)
