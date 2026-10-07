#!/usr/bin/env python3
"""Offline contract tests for external-command evidence."""
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('subprocess_contract', ROOT / 'scripts/repo_seo_baseline.py')
repo = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repo)


class SubprocessContract(unittest.TestCase):
    def test_missing_executable_remains_skipped(self):
        with mock.patch.object(repo.shutil, 'which', return_value=None), mock.patch.object(repo.subprocess, 'run') as run:
            self.assertEqual(repo.run_cmd(['missing']), {'status': 'skipped', 'reason': 'missing not found'})
        run.assert_not_called()

    def test_disappearing_executable_is_structured_error(self):
        with mock.patch.object(repo.shutil, 'which', return_value='/synthetic/tool'), mock.patch.object(repo.subprocess, 'run', side_effect=FileNotFoundError(2, 'gone')):
            self.assertEqual(repo.run_cmd(['tool']), {'status': 'error', 'reason': 'execution_error', 'command': ['tool']})

    def test_permission_error_is_structured_error(self):
        with mock.patch.object(repo.shutil, 'which', return_value='/synthetic/tool'), mock.patch.object(repo.subprocess, 'run', side_effect=PermissionError(13, 'denied')):
            self.assertEqual(repo.run_cmd(['tool']), {'status': 'error', 'reason': 'execution_error', 'command': ['tool']})

    def test_other_os_error_is_structured_error(self):
        with mock.patch.object(repo.shutil, 'which', return_value='/synthetic/tool'), mock.patch.object(repo.subprocess, 'run', side_effect=OSError(8, 'bad executable format')):
            self.assertEqual(repo.run_cmd(['tool']), {'status': 'error', 'reason': 'execution_error', 'command': ['tool']})

    def test_encoding_is_explicit_and_strict(self):
        result = subprocess.CompletedProcess(['tool'], 0, ' value\n', ' note\n')
        with mock.patch.object(repo.shutil, 'which', return_value='/synthetic/tool'), mock.patch.object(repo.subprocess, 'run', return_value=result) as run:
            self.assertEqual(repo.run_cmd(['tool'], cwd=Path('/synthetic'), timeout=7), {
                'status': 'ok', 'returncode': 0, 'stdout': 'value', 'stderr': 'note', 'command': ['tool'],
            })
        run.assert_called_once_with(['tool'], cwd='/synthetic', text=True, encoding='utf-8', errors='strict', capture_output=True, timeout=7, check=False)

    def test_invalid_utf8_in_either_stream_has_no_rejected_output(self):
        for fd in (1, 2):
            with self.subTest(fd=fd):
                args = [sys.executable, '-c', f'import os; os.write({fd}, bytes([255, 254]))']
                result = repo.run_cmd(args)
                self.assertEqual(result, {'status': 'error', 'reason': 'decode_error', 'command': args})
                self.assertEqual(json.loads(json.dumps(result)), result)

    def test_valid_unicode_survives(self):
        args = [sys.executable, '-c', 'import os; os.write(1, "中文 café 😀\\n".encode("utf-8")); os.write(2, "警告\\n".encode("utf-8"))']
        self.assertEqual(repo.run_cmd(args), {
            'status': 'ok', 'returncode': 0, 'stdout': '中文 café 😀', 'stderr': '警告', 'command': args,
        })

    def test_nonzero_exit_preserves_both_streams(self):
        args = [sys.executable, '-c', 'import sys; print("evidence"); print("diagnostic", file=sys.stderr); sys.exit(7)']
        self.assertEqual(repo.run_cmd(args), {
            'status': 'error', 'returncode': 7, 'stdout': 'evidence', 'stderr': 'diagnostic', 'command': args,
        })

    def test_timeout_contract_and_partial_output_remain_unchanged(self):
        args = ['tool']
        timeout = subprocess.TimeoutExpired(args, 1, output=b'partial\xff', stderr=b'diagnostic\xfe')
        with mock.patch.object(repo.shutil, 'which', return_value='/synthetic/tool'), mock.patch.object(repo.subprocess, 'run', side_effect=timeout):
            self.assertEqual(repo.run_cmd(args, timeout=1), {'status': 'error', 'reason': 'timeout', 'command': args})

    def test_cli_json_survives_command_boundary_failures(self):
        failures = (UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid start byte'), FileNotFoundError(2, 'gone'), PermissionError(13, 'denied'))
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), tempfile.TemporaryDirectory() as tmp:
                stream = io.StringIO()
                with mock.patch.object(sys, 'argv', ['repo', '--root', tmp, '--json']), mock.patch.object(repo.shutil, 'which', return_value='/synthetic/tool'), mock.patch.object(repo.subprocess, 'run', side_effect=failure), redirect_stdout(stream):
                    repo.main()
                payload = json.loads(stream.getvalue())
                for result in payload['git'].values():
                    self.assertEqual(result['status'], 'error')
                    self.assertEqual(result['reason'], 'decode_error' if isinstance(failure, UnicodeDecodeError) else 'execution_error')
                    self.assertNotIn('stdout', result)
                    self.assertNotIn('stderr', result)
                # Aggregate status is a separate existing contract; only command
                # evidence and continued JSON emission are asserted here.


if __name__ == '__main__':
    unittest.main()
