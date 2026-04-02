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

    def test_format_failure_detail_zero(self):
        """エラー数 0 でも正しく整形される。"""
        self.assertEqual(corpus_test.format_failure_detail(0), "0 errors")

    def test_format_failure_detail_large_number(self):
        """大きなエラー数も正しく整形される。"""
        self.assertEqual(corpus_test.format_failure_detail(999), "999 errors")

    def test_format_failure_detail_non_string(self):
        """整数以外の型はそのまま文字列化される。"""
        self.assertEqual(corpus_test.format_failure_detail(None), "None")

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

    def test_extract_tests_ignores_unterminated_name_section(self):
        """閉じ区切りのないテスト名セクションは無視される。"""
        corpus = textwrap.dedent(
            """\
            =========
            unterminated
            still name
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(tests, [])

    def test_extract_tests_stops_code_on_next_header(self):
        """AST 区切りがなくても次のヘッダーで前ケースを閉じる。"""
        corpus = textwrap.dedent(
            """\
            =========
            first
            =========
            puts :ok
            =========
            second
            =========
            puts :next
            ---
            (program
              (call))
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(
            tests,
            [
                ("first", "puts :ok", False),
                ("second", "puts :next", False),
            ],
        )

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

    def test_summarize_command_failure_skips_blank_lines(self):
        """先頭の空行は無視して最初の有意な行を使用する。"""
        output = "\n\nSomething went wrong\n"
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

    @patch("corpus_test.subprocess.run")
    def test_check_tree_sitter_cli_reports_generic_failure(self, mock_run):
        """一般的な起動失敗では要約付きメッセージを返す。"""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=2,
            stdout="",
            stderr="permission denied\n",
        )
        self.assertEqual(
            corpus_test.check_tree_sitter_cli({}),
            "tree-sitter CLI を起動できません。exit 2: permission denied",
        )

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
    def test_main_skips_non_txt_and_accepts_expected_error(
        self, mock_run, mock_listdir
    ):
        """非 txt を無視し、期待どおりの ERROR は成功として扱う。"""
        corpus = textwrap.dedent(
            """\
            =========
            expected error
            =========
            def (
            ---
            (program
              (ERROR))
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
            returncode=1,
            stdout="(program (ERROR))\n",
            stderr="",
        )
        mock_run.side_effect = [version_result, parse_result]
        mock_listdir.return_value = ["README.md", corpus_fname]

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
        self.assertEqual(mock_run.call_count, 2)

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.subprocess.run")
    def test_main_reports_expected_error_when_parse_succeeds(
        self, mock_run, mock_listdir
    ):
        """ERROR 期待ケースが正常終了した場合は失敗として報告する。"""
        corpus = textwrap.dedent(
            """\
            =========
            expected error
            =========
            def (
            ---
            (program
              (ERROR))
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
            stdout="(program (method))\n",
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
        self.assertIn("expected ERROR but parsed OK", stdout.getvalue())

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
    def test_main_reports_command_failure_detail_without_error_nodes(
        self, mock_run, mock_listdir
    ):
        """非 0 終了かつ ERROR ノードなしならコマンド失敗詳細を表示する。"""
        corpus = textwrap.dedent(
            """\
            =========
            command failure
            =========
            puts :ok
            ---
            (program
              (call))
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
            returncode=2,
            stdout="",
            stderr="\npermission denied\n",
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
        self.assertIn("exit 2: permission denied", stdout.getvalue())

    def test_extract_tests_skips_whitespace_only_code(self):
        """コードが空白のみの場合テストとして抽出されない。"""
        corpus = textwrap.dedent(
            """\
            =========
            blank code
            =========

            ---
            (program)
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)
        self.assertEqual(tests, [])

    def test_extract_tests_error_tag_in_name(self):
        """:error タグ付きテスト名で expects_error が True になる。"""
        corpus = textwrap.dedent(
            """\
            =========
            broken syntax
            :error
            =========
            def (
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

        self.assertEqual(len(tests), 1)
        self.assertTrue(tests[0][2])

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.subprocess.run")
    def test_main_mixed_pass_and_fail(self, mock_run, mock_listdir):
        """複数テストで一部パス・一部失敗の集計が正確であること。"""
        corpus = textwrap.dedent(
            """\
            =========
            pass case
            =========
            x = 1
            ---
            (program
              (assignment))
            =========
            fail case
            =========
            y = 2
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
        pass_result = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (assignment))\n",
            stderr="",
        )
        fail_result = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (ERROR))\n",
            stderr="",
        )
        mock_run.side_effect = [version_result, pass_result, fail_result]
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
        self.assertIn("Pass: 1", stdout.getvalue())
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

    # --- is_separator 追加境界値テスト ---

    def test_is_separator_with_trailing_whitespace(self):
        """末尾空白付きの区切り線を正しく認識する。"""
        self.assertEqual(corpus_test.is_separator("=====   "), "=")
        self.assertEqual(corpus_test.is_separator("-----\t"), "-")

    def test_is_separator_with_leading_whitespace(self):
        """先頭空白付きの区切り線を正しく認識する。"""
        self.assertEqual(corpus_test.is_separator("  ====="), "=")
        self.assertEqual(corpus_test.is_separator("\t-----"), "-")

    # --- extract_tests 追加エッジケーステスト ---

    def test_extract_tests_empty_expected_ast(self):
        """期待 AST が空でもテストとして抽出される。"""
        corpus = textwrap.dedent(
            """\
            =========
            empty ast
            =========
            x = 1
            ---
            =========
            next case
            =========
            y = 2
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

        self.assertEqual(len(tests), 2)
        self.assertEqual(tests[0][0], "empty ast")
        self.assertFalse(tests[0][2])
        self.assertEqual(tests[1][0], "next case")

    def test_extract_tests_consecutive_tests_without_ast(self):
        """AST なしの連続テストが正しく抽出される。"""
        corpus = textwrap.dedent(
            """\
            =========
            first
            =========
            a = 1
            =========
            second
            =========
            b = 2
            =========
            third
            =========
            c = 3
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

        self.assertEqual(len(tests), 3)
        self.assertEqual(tests[0][1], "a = 1")
        self.assertEqual(tests[1][1], "b = 2")
        self.assertEqual(tests[2][1], "c = 3")

    # --- summarize_command_failure 追加テスト ---

    def test_summarize_command_failure_multiple_error_lines(self):
        """複数の Error: 行がある場合、最初のものを使用する。"""
        output = textwrap.dedent(
            """\
            Error: first error
            Error: second error
            """
        )
        self.assertEqual(
            corpus_test.summarize_command_failure(1, output),
            "exit 1: Error: first error",
        )

    def test_summarize_command_failure_whitespace_only_output(self):
        """出力が空白のみの場合、終了コードのみ返す。"""
        self.assertEqual(
            corpus_test.summarize_command_failure(1, "   \n  \n"),
            "exit 1",
        )

    # --- main 関数の追加テスト ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.subprocess.run")
    def test_main_empty_corpus_directory(self, mock_run, mock_listdir):
        """corpus ディレクトリに .txt ファイルがない場合、0 件で成功する。"""
        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_listdir.return_value = ["README.md", ".gitkeep"]

        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = corpus_test.main()

        self.assertEqual(exit_code, 0)
        self.assertIn("Total: 0", stdout.getvalue())
        self.assertIn("Pass: 0", stdout.getvalue())
        self.assertIn("Fail: 0", stdout.getvalue())

    # --- is_separator 追加テスト ---

    def test_is_separator_other_repeated_chars(self):
        """= と - 以外の同一文字繰り返しは区切り線ではない。"""
        self.assertIsNone(corpus_test.is_separator("***"))
        self.assertIsNone(corpus_test.is_separator("###"))
        self.assertIsNone(corpus_test.is_separator("~~~"))

    def test_is_separator_tab_only(self):
        """タブ文字のみの行は区切り線ではない。"""
        self.assertIsNone(corpus_test.is_separator("\t\t\t"))

    # --- extract_tests 追加テスト ---

    def test_extract_tests_empty_name_section(self):
        """名前セクションが空行のみの場合、空文字列のテスト名になる。"""
        corpus = textwrap.dedent(
            """\
            =========

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
        self.assertEqual(tests[0][0], "")

    def test_extract_tests_file_ends_after_dash_separator(self):
        """--- の直後にファイルが終了する場合、AST 空でテスト抽出される。"""
        corpus = textwrap.dedent(
            """\
            =========
            trailing dash
            =========
            x = 1
            ---
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0][0], "trailing dash")
        self.assertFalse(tests[0][2])

    def test_extract_tests_no_trailing_newline(self):
        """ファイル末尾に改行がないケースでも正常に抽出される。"""
        corpus = (
            "=========\nno newline\n=========\nx = 1\n---\n(program\n  (assignment))"
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0][0], "no newline")

    def test_extract_tests_both_error_and_missing(self):
        """AST に ERROR と MISSING が両方含まれる場合 expects_error が True になる。"""
        corpus = textwrap.dedent(
            """\
            =========
            both markers
            =========
            def foo(
            ---
            (program
              (ERROR)
              (MISSING))
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(tests), 1)
        self.assertTrue(tests[0][2])

    # --- format_failure_detail 追加テスト ---

    def test_format_failure_detail_bool_is_int_subclass(self):
        """bool は int のサブクラスなので整数分岐に入り f-string で文字列化される。"""
        self.assertEqual(corpus_test.format_failure_detail(True), "True errors")
        self.assertEqual(corpus_test.format_failure_detail(False), "False errors")

    def test_format_failure_detail_float_uses_str(self):
        """float は int ではないので str() で変換される。"""
        self.assertEqual(corpus_test.format_failure_detail(1.5), "1.5")

    def test_format_failure_detail_empty_string(self):
        """空文字列はそのまま空文字列として返される。"""
        self.assertEqual(corpus_test.format_failure_detail(""), "")

    # --- summarize_command_failure 追加テスト ---

    def test_summarize_command_failure_error_only_label(self):
        """'Error:' のみの行（メッセージなし）もそのまま返される。"""
        self.assertEqual(
            corpus_test.summarize_command_failure(1, "Error:\n"),
            "exit 1: Error:",
        )

    def test_summarize_command_failure_noise_then_meaningful(self):
        """ノイズ行の後に有意な行がある場合、有意な行が返される。"""
        output = textwrap.dedent(
            """\
                at ChildProcess._handle.onexit (node:internal/child_process:286:19)
            actual error message
            """
        )
        self.assertEqual(
            corpus_test.summarize_command_failure(1, output),
            "exit 1: actual error message",
        )

    def test_summarize_command_failure_error_mid_line_not_matched(self):
        """Error: が行頭でない場合は Error: 優先マッチしない。"""
        output = "Some context Error: detail\n"
        self.assertEqual(
            corpus_test.summarize_command_failure(1, output),
            "exit 1: Some context Error: detail",
        )

    # --- check_tree_sitter_cli 追加テスト ---

    @patch(
        "corpus_test.subprocess.run", side_effect=PermissionError("permission denied")
    )
    def test_check_tree_sitter_cli_permission_error_propagates(self, mock_run):
        """PermissionError は FileNotFoundError ではないため未キャッチで伝播する。"""
        with self.assertRaises(PermissionError):
            corpus_test.check_tree_sitter_cli({})

    @patch("corpus_test.subprocess.run")
    def test_check_tree_sitter_cli_partial_enoent_match(self, mock_run):
        """tree-sitter-cli/tree-sitter は含むが ENOENT を含まない場合は一般エラー。"""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=1,
            stdout="",
            stderr="Error: spawn tree-sitter-cli/tree-sitter SIGABRT\n",
        )
        message = corpus_test.check_tree_sitter_cli({})
        self.assertIn("tree-sitter CLI を起動できません", message)
        self.assertNotIn("install.js", message)

    # --- main 関数の追加テスト ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.subprocess.run")
    def test_main_multiple_corpus_files(self, mock_run, mock_listdir):
        """複数の corpus ファイルにまたがるテスト集計が正確であること。"""
        corpus1 = textwrap.dedent(
            """\
            =========
            file1 test
            =========
            x = 1
            ---
            (program
              (assignment))
            """
        )
        corpus2 = textwrap.dedent(
            """\
            =========
            file2 test
            =========
            y = 2
            ---
            (program
              (assignment))
            """
        )
        path1 = self._write_corpus(corpus1)
        path2 = self._write_corpus(corpus2)
        corpus_dir = os.path.dirname(path1)

        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        parse_ok = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (assignment))\n",
            stderr="",
        )
        mock_run.side_effect = [version_result, parse_ok, parse_ok]
        mock_listdir.return_value = sorted(
            [os.path.basename(path1), os.path.basename(path2)]
        )

        try:
            stdout = io.StringIO()
            with (
                redirect_stdout(stdout),
                patch.object(corpus_test, "CORPUS_DIR", corpus_dir),
            ):
                exit_code = corpus_test.main()
        finally:
            os.unlink(path1)
            os.unlink(path2)

        self.assertEqual(exit_code, 0)
        self.assertIn("Total: 2", stdout.getvalue())
        self.assertIn("Pass: 2", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.subprocess.run")
    def test_main_missing_only_in_output(self, mock_run, mock_listdir):
        """パース出力に MISSING のみ含まれる場合も失敗として報告する。"""
        corpus = textwrap.dedent(
            """\
            =========
            missing node
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
        parse_result = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (MISSING) (assignment))\n",
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
        self.assertIn("Fail: 1", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.subprocess.run")
    def test_main_txt_file_without_test_cases(self, mock_run, mock_listdir):
        """.txt ファイルはあるがテストケースが0件の場合、0 件で成功する。"""
        corpus_path = self._write_corpus("just text without separators\n")
        corpus_fname = os.path.basename(corpus_path)
        corpus_dir = os.path.dirname(corpus_path)

        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        mock_run.return_value = version_result
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
        self.assertIn("Total: 0", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
