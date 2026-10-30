"""CPU プロファイラーの応答待ちと、失敗時の資源回収を検証する。"""

import collections
import importlib.util
import io
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

PROFILE_PATH = (
    Path(__file__).resolve().parents[1]
    / "tools"
    / "parse-benchmark"
    / "sample_profile.py"
)
SPEC = importlib.util.spec_from_file_location("benchmark_profile", PROFILE_PATH)
profile = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(profile)


class BenchmarkProfileTests(unittest.TestCase):
    """応答の欠落と例外でもプロファイラーが終了することを確認する。"""

    def process(self, output=""):
        """応答文字列と終了状態を制御できるプロセスを作る。

        Returns:
            インメモリのパイプを持つプロセスのモック。

        """
        process = mock.Mock()
        process.stdin = io.StringIO()
        process.stdout = io.StringIO(output)
        process.poll.return_value = 7
        return process

    def test_wait_done_skips_data_and_accepts_complete_response(self):
        """データ行を読み飛ばし、完了応答の次の行は残す。"""
        process = self.process('data\n{"wall_ns": 1}\nDONE\nremaining\n')
        profile._wait_done(process)
        self.assertEqual(process.stdout.readline(), "remaining\n")

    def test_startup_eof_exits_with_an_error_within_the_deadline(self):
        """起動直後の子プロセス終了を、期限内にエラーとして報告する。"""
        script = """
import importlib.util
import sys
spec = importlib.util.spec_from_file_location('profile', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module._win32 = lambda: (None, None, None)
module.ctypes.WinDLL = lambda *args, **kwargs: None
sys.argv = ['profile', '--binary', sys.executable, '--manifest', 'missing.jsonl',
            '--source-root', '.', '--output', 'profile.json']
module.main()
"""
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "-c", script, str(PROFILE_PATH)],
                cwd=directory,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("before DONE", result.stderr)
            self.assertFalse((Path(directory) / "profile.json").exists())

    def test_drive_propagates_eof_and_always_sets_completion(self):
        """計測途中の EOF を通知し、採取側の待機を終える。"""
        process = self.process("data\n")
        done = threading.Event()
        errors = []
        profile._drive(process, 1, done, errors)
        self.assertTrue(done.is_set())
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], RuntimeError)
        self.assertEqual(process.stdin.getvalue(), "1\n")

    def test_drive_preserves_write_error_and_sets_completion(self):
        """指示を書けなくても元の例外と完了通知を失わない。"""
        process = self.process()
        error = BrokenPipeError("child closed stdin")
        process.stdin = mock.Mock()
        process.stdin.write.side_effect = error
        done = threading.Event()
        errors = []
        profile._drive(process, 2, done, errors)
        self.assertTrue(done.is_set())
        self.assertEqual(errors, [error])

    def test_sampling_error_resumes_thread_and_reaps_real_child(self):
        """採取の例外でスレッドを再開し、タイマーと実子プロセスを回収する。"""
        process = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "import sys,time; sys.stdin.readline(); time.sleep(60)",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self.addCleanup(profile._stop_process, process)
        kernel = mock.Mock()
        kernel.SuspendThread.return_value = 0
        error = LookupError("context failed")
        kernel.GetThreadContext.side_effect = error
        winmm = mock.Mock()
        winmm.timeBeginPeriod.return_value = 0
        with self.assertRaises(LookupError) as raised:
            profile._sample(process, 123, 1, kernel, winmm)
        self.assertIs(raised.exception, error)
        kernel.ResumeThread.assert_called_once_with(123)
        winmm.timeEndPeriod.assert_called_once_with(1)
        self.assertIsNotNone(process.poll())
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    def test_stop_process_kills_a_child_that_ignores_termination(self):
        """終了要求に応じない子プロセスは強制終了して回収する。"""
        process = self.process()
        process.poll.return_value = None
        process.wait.side_effect = [subprocess.TimeoutExpired("child", 5), 0]
        profile._stop_process(process)
        process.terminate.assert_called_once_with()
        process.kill.assert_called_once_with()
        self.assertEqual(process.wait.call_count, 2)
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)

    def test_symbol_lookup_failure_closes_symbols_and_process_handle(self):
        """名前の解決に失敗してもシンボル情報とハンドルを解放する。"""
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 55
        dbghelp = mock.Mock()
        dbghelp.SymInitializeW.return_value = True
        error = LookupError("symbol failed")
        dbghelp.SymFromAddrW.side_effect = error
        with mock.patch.object(profile, "_modules", return_value=[(4096, 4096, "exe")]):
            with self.assertRaises(LookupError) as raised:
                profile._resolve_counts(
                    collections.Counter({4096: 1}),
                    self.process(),
                    "benchmark.exe",
                    kernel,
                    mock.Mock(),
                    dbghelp,
                )
        self.assertIs(raised.exception, error)
        dbghelp.SymCleanup.assert_called_once_with(55)
        kernel.CloseHandle.assert_called_once_with(55)

    def test_failed_symbol_initialization_closes_only_process_handle(self):
        """初期化できなかったシンボル情報は解放処理の対象にしない。"""
        kernel = mock.Mock()
        kernel.OpenProcess.return_value = 55
        dbghelp = mock.Mock()
        dbghelp.SymInitializeW.return_value = False
        with mock.patch.object(profile, "_modules", return_value=[]):
            with self.assertRaises(OSError):
                profile._resolve_counts(
                    {}, self.process(), "benchmark.exe", kernel, mock.Mock(), dbghelp
                )
        dbghelp.SymCleanup.assert_not_called()
        kernel.CloseHandle.assert_called_once_with(55)

    def test_thread_enumeration_failure_releases_both_handles(self):
        """列挙中の例外でもスレッドとスナップショットのハンドルを閉じる。"""
        kernel = mock.Mock()
        kernel.CreateToolhelp32Snapshot.return_value = 55
        kernel.OpenThread.return_value = 66

        def first(snapshot, entry):
            """対象プロセスに所属するスレッドを1件返す。

            Returns:
                スレッドが見つかったことを示す True。

            """
            entry._obj.process_id = 42
            entry._obj.thread_id = 7
            return True

        kernel.Thread32First.side_effect = first
        kernel.GetThreadTimes.side_effect = LookupError("times failed")
        with self.assertRaises(LookupError):
            profile._busiest_thread(kernel, 42)
        self.assertEqual(
            kernel.CloseHandle.call_args_list, [mock.call(66), mock.call(55)]
        )

    def test_main_sampling_failure_closes_thread_handle_and_pipes(self):
        """採取処理から例外が伝わっても呼出側の資源を残さない。"""
        process = self.process("DONE\n")
        process.poll.return_value = None
        kernel = mock.Mock()
        kernel.OpenThread.return_value = 44
        error = RuntimeError("sampling failed")
        argv = [
            "profile",
            "--binary",
            "benchmark.exe",
            "--manifest",
            "manifest.jsonl",
            "--source-root",
            ".",
            "--output",
            "profile.json",
        ]
        with ExitStack() as patches:
            patches.enter_context(mock.patch.object(sys, "argv", argv))
            patches.enter_context(
                mock.patch.object(profile, "_win32", return_value=(kernel, None, None))
            )
            patches.enter_context(
                mock.patch.object(profile.ctypes, "WinDLL", create=True)
            )
            patches.enter_context(
                mock.patch.object(profile.subprocess, "Popen", return_value=process)
            )
            patches.enter_context(
                mock.patch.object(profile, "_busiest_thread", return_value=7)
            )
            patches.enter_context(
                mock.patch.object(profile, "_sample", side_effect=error)
            )
            with self.assertRaises(RuntimeError) as raised:
                profile.main()
        self.assertIs(raised.exception, error)
        kernel.CloseHandle.assert_called_once_with(44)
        process.terminate.assert_called_once_with()
        self.assertTrue(process.stdin.closed)
        self.assertTrue(process.stdout.closed)


if __name__ == "__main__":
    unittest.main()
