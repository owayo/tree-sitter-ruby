#!/usr/bin/env python3
"""scripts/corpus_test.py のユニットテスト。"""

import io
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import corpus_test


class CorpusTestScriptTests(unittest.TestCase):
    """コーパス補助関数の振る舞いを検証する。"""

    def _write_corpus(self, body):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(body)
            return f.name

    def test_is_separator(self):
        self.assertEqual(corpus_test.is_separator("=====\n"), "=")
        self.assertEqual(corpus_test.is_separator("---\n"), "-")
        self.assertIsNone(corpus_test.is_separator("--=\n"))

    def test_extract_tests(self):
        corpus = textwrap.dedent(
            """\
            =========
            normal case
            =========
            puts "ok"
            ---
            (program
              (call))
            =========
            error case
            =========
            p(
            ---
            (program
              (ERROR))
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(tests), 2)
        self.assertEqual(tests[0], ("normal case", 'puts "ok"', False))
        self.assertEqual(tests[1], ("error case", "p(", True))

    def test_extract_tests_works_under_ascii_locale(self):
        corpus = textwrap.dedent(
            """\
            =========
            utf8 case
            =========
            puts "äö"
            ---
            (program
              (call))
            """
        )
        path = self._write_corpus(corpus)
        try:
            env = {
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parent),
                "PYTHONUTF8": "0",
                "PYTHONCOERCECLOCALE": "0",
                "LC_ALL": "C",
                "CORPUS_FILE": path,
            }
            cmd = [
                sys.executable,
                "-c",
                (
                    "import os; from corpus_test import extract_tests; "
                    "print(len(extract_tests(os.environ['CORPUS_FILE'])))"
                ),
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                env=env,
                timeout=10,
            )
        finally:
            os.unlink(path)

        self.assertEqual(result.returncode, 0, msg=result.stderr)
        self.assertEqual(result.stdout.strip(), "1")

    def test_format_failure_detail(self):
        self.assertEqual(corpus_test.format_failure_detail(2), "2 errors")
        self.assertEqual(
            corpus_test.format_failure_detail("TIMEOUT"),
            "TIMEOUT",
        )

    def test_summarize_command_failure_prefers_error_line(self):
        output = textwrap.dedent(
            """\
            node:events:486
            Error: spawn /tmp/tree-sitter ENOENT
                at ChildProcess._handle.onexit (node:internal/child_process:286:19)
            Node.js v24.12.0
            """
        )

        self.assertEqual(
            corpus_test.summarize_command_failure(1, output),
            "exit 1: Error: spawn /tmp/tree-sitter ENOENT",
        )

    @patch("corpus_test.subprocess.run", side_effect=FileNotFoundError)
    def test_check_tree_sitter_cli_reports_missing_command(self, mock_run):
        message = corpus_test.check_tree_sitter_cli({})

        self.assertEqual(
            message,
            "tree-sitter コマンドが見つかりません。tree-sitter-cli をインストールしてください。",
        )
        mock_run.assert_called_once()

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.subprocess.run")
    def test_main_reports_tree_sitter_setup_error(self, mock_run, mock_listdir):
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=1,
            stdout="",
            stderr=textwrap.dedent(
                """\
                node:events:486
                Error: spawn /tmp/tree-sitter ENOENT
                Emitted 'error' event on ChildProcess instance
                """
            ),
        )

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = corpus_test.main()

        self.assertEqual(exit_code, 2)
        mock_listdir.assert_not_called()
        self.assertIn("--- Setup Error ---", stdout.getvalue())
        self.assertIn("tree-sitter CLI を起動できません。", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch(
        "corpus_test.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["tree-sitter", "--version"], timeout=10),
    )
    def test_main_reports_tree_sitter_setup_timeout(self, mock_run, mock_listdir):
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = corpus_test.main()

        self.assertEqual(exit_code, 2)
        mock_run.assert_called_once()
        mock_listdir.assert_not_called()
        self.assertIn("--- Setup Error ---", stdout.getvalue())
        self.assertIn("10 秒でタイムアウト", stdout.getvalue())

    # --- is_separator 境界値テスト ---

    def test_is_separator_empty_string(self):
        """空文字列は区切り線ではない。"""
        self.assertIsNone(corpus_test.is_separator(""))
        self.assertIsNone(corpus_test.is_separator("\n"))

    def test_is_separator_short_strings(self):
        """3文字未満は区切り線と認識しない。"""
        self.assertIsNone(corpus_test.is_separator("=="))
        self.assertIsNone(corpus_test.is_separator("--"))
        self.assertIsNone(corpus_test.is_separator("="))

    def test_is_separator_exact_boundary(self):
        """ちょうど3文字は区切り線として認識する。"""
        self.assertEqual(corpus_test.is_separator("==="), "=")
        self.assertEqual(corpus_test.is_separator("---"), "-")

    def test_is_separator_mixed_chars(self):
        """異なる文字の混在は区切り線ではない。"""
        self.assertIsNone(corpus_test.is_separator("=-="))
        self.assertIsNone(corpus_test.is_separator("-=-=-"))

    # --- extract_tests エッジケーステスト ---

    def test_extract_tests_empty_file(self):
        """空のコーパスファイルからはテストが抽出されない。"""
        path = self._write_corpus("")
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)
        self.assertEqual(tests, [])

    def test_extract_tests_multiline_name(self):
        """複数行のテスト名が結合される。"""
        corpus = textwrap.dedent(
            """\
            =========
            first line
            second line
            =========
            x = 1
            ---
            (program
              (assignment))
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0][0], "first line second line")

    def test_extract_tests_strips_blank_lines_around_code(self):
        """コード前後の空行が除去される。"""
        corpus = textwrap.dedent(
            """\
            =========
            blank padded
            =========

            x = 1

            ---
            (program
              (assignment))
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(tests[0][1], "x = 1")

    def test_extract_tests_missing_in_ast(self):
        """期待 AST に MISSING が含まれる場合 expects_error が True になる。"""
        corpus = textwrap.dedent(
            """\
            =========
            missing case
            =========
            def foo
            ---
            (program
              (method (MISSING)))
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(tests), 1)
        self.assertTrue(tests[0][2])

    def test_extract_tests_no_separator_line(self):
        """区切り線なしのテキストからはテストが抽出されない。"""
        path = self._write_corpus("just some text\nwithout separators\n")
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)
        self.assertEqual(tests, [])

    # --- summarize_command_failure エッジケーステスト ---

    def test_summarize_command_failure_empty_output(self):
        """出力が空の場合、終了コードのみ返す。"""
        self.assertEqual(
            corpus_test.summarize_command_failure(1, ""),
            "exit 1",
        )

    def test_summarize_command_failure_only_noise(self):
        """ノイズ行のみの場合、終了コードのみ返す。"""
        output = textwrap.dedent(
            """\
                at ChildProcess._handle.onexit (node:internal/child_process:286:19)
            Emitted 'error' event on ChildProcess instance
            Node.js v24.12.0
            """
        )
        self.assertEqual(
            corpus_test.summarize_command_failure(1, output),
            "exit 1",
        )

    def test_summarize_command_failure_no_error_prefix(self):
        """Error: プレフィックスがない場合、最初の有意な行を使用する。"""
        output = "Something went wrong\n"
        self.assertEqual(
            corpus_test.summarize_command_failure(2, output),
            "exit 2: Something went wrong",
        )

    # --- check_tree_sitter_cli 追加テスト ---

    @patch("corpus_test.subprocess.run")
    def test_check_tree_sitter_cli_success(self, mock_run):
        """CLI が正常に起動できる場合 None を返す。"""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        self.assertIsNone(corpus_test.check_tree_sitter_cli({}))

    @patch("corpus_test.subprocess.run")
    def test_check_tree_sitter_cli_enoent_message(self, mock_run):
        """ENOENT エラー時に install.js の実行を案内する。"""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=1,
            stdout="",
            stderr=(
                "node:events:486\n"
                "Error: spawn tree-sitter-cli/tree-sitter ENOENT\n"
                "Node.js v24.12.0\n"
            ),
        )
        message = corpus_test.check_tree_sitter_cli({})
        self.assertIn("tree-sitter CLI の実体を起動できません", message)
        self.assertIn("install.js", message)

    # --- main 関数の追加テスト ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.subprocess.run")
    def test_main_all_tests_pass(self, mock_run, mock_listdir):
        """全テスト通過時に exit 0 を返す。"""
        corpus = textwrap.dedent(
            """\
            =========
            simple
            =========
            x = 1
            ---
            (program
              (assignment))
            """
        )
        corpus_path = self._write_corpus(corpus)
        corpus_fname = os.path.basename(corpus_path)
        corpus_dir = os.path.dirname(corpus_path)

        # tree-sitter --version の呼び出し
        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        # tree-sitter parse の呼び出し（エラーなし）
        parse_result = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (assignment))\n",
            stderr="",
        )
        mock_run.side_effect = [version_result, parse_result]
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with (
                redirect_stdout(stdout),
                patch.object(corpus_test, "CORPUS_DIR", corpus_dir),
            ):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("Pass: 1", stdout.getvalue())
        self.assertIn("Fail: 0", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.subprocess.run")
    def test_main_with_failure(self, mock_run, mock_listdir):
        """パースエラー時に exit 1 と失敗詳細を出力する。"""
        corpus = textwrap.dedent(
            """\
            =========
            broken
            =========
            def (
            ---
            (program
              (method))
            """
        )
        corpus_path = self._write_corpus(corpus)
        corpus_fname = os.path.basename(corpus_path)
        corpus_dir = os.path.dirname(corpus_path)

        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        parse_result = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (ERROR))\n",
            stderr="",
        )
        mock_run.side_effect = [version_result, parse_result]
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with (
                redirect_stdout(stdout),
                patch.object(corpus_test, "CORPUS_DIR", corpus_dir),
            ):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("FAIL:", stdout.getvalue())
        self.assertIn("Fail: 1", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.subprocess.run")
    def test_main_parse_timeout(self, mock_run, mock_listdir):
        """パース時のタイムアウトが TIMEOUT として記録される。"""
        corpus = textwrap.dedent(
            """\
            =========
            slow parse
            =========
            x = 1
            ---
            (program
              (assignment))
            """
        )
        corpus_path = self._write_corpus(corpus)
        corpus_fname = os.path.basename(corpus_path)
        corpus_dir = os.path.dirname(corpus_path)

        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        mock_run.side_effect = [
            version_result,
            subprocess.TimeoutExpired(["tree-sitter", "parse"], timeout=10),
        ]
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with (
                redirect_stdout(stdout),
                patch.object(corpus_test, "CORPUS_DIR", corpus_dir),
            ):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("TIMEOUT", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
