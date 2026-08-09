#!/usr/bin/env python3
"""scripts/corpus_test.py のユニットテスト。"""

import io
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import contextmanager, redirect_stdout
from pathlib import Path
from unittest.mock import Mock, patch

import corpus_test


class CorpusTestScriptTests(unittest.TestCase):
    """コーパス補助関数の振る舞いを検証する。"""

    def setUp(self):
        """Patch resolve_library_path so main() checks stay environment agnostic."""
        patcher = patch.object(
            corpus_test, "resolve_library_path", return_value=__file__
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def _write_corpus(self, body):
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".txt",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(body)
            return f.name

    @contextmanager
    def _with_corpus_dir(self, corpus_dir):
        with patch.object(corpus_test, "CORPUS_DIR", corpus_dir):
            yield

    @contextmanager
    def _capture_stdout_with_corpus_dir(self, corpus_dir, stdout):
        with self._with_corpus_dir(corpus_dir):
            with redirect_stdout(stdout):
                yield

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

    def test_extract_tests_can_include_expected_ast(self):
        """main() 用に期待 AST を含めて抽出できる。"""
        corpus = textwrap.dedent(
            """\
            =========
            normal case
            =========
            puts "ok"
            ---
            (program
              (call))
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path, include_expected_ast=True)
        finally:
            os.unlink(path)

        self.assertEqual(
            tests[0],
            ("normal case", 'puts "ok"', "(program\n  (call))", False),
        )

    def test_extract_tests_preserves_single_cr_in_code(self):
        """コード内の単独 CR を LF に正規化せず保持する。"""
        with tempfile.NamedTemporaryFile(
            mode="wb",
            suffix=".txt",
            delete=False,
        ) as f:
            f.write(b'=========\ncr case\n=========\nputs\r\r"hi"\n---\n(program)\n')
            path = f.name

        try:
            tests = corpus_test.extract_tests(path, include_expected_ast=True)
        finally:
            os.unlink(path)

        self.assertEqual(tests[0][1], 'puts\r\r"hi"')

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
                check=False,
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

    def test_tree_sitter_command_uses_env_override(self):
        """TREE_SITTER_CLI が指定されていれば最優先で使う。"""
        self.assertEqual(
            corpus_test.tree_sitter_command({"TREE_SITTER_CLI": "/custom/tree-sitter"}),
            "/custom/tree-sitter",
        )

    def test_tree_sitter_command_prefers_project_local_cli(self):
        """node_modules/.bin のローカル CLI を PATH より優先する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            bin_dir = project_dir / "node_modules" / ".bin"
            bin_dir.mkdir(parents=True)
            executable = "tree-sitter.cmd" if os.name == "nt" else "tree-sitter"
            cli = bin_dir / executable
            cli.write_text("#!/bin/sh\n", encoding="utf-8")

            with patch.object(corpus_test, "PROJECT_DIR", project_dir):
                self.assertEqual(corpus_test.tree_sitter_command({}), str(cli))

    def test_tree_sitter_command_prefers_native_package_binary(self):
        """tree-sitter-cli パッケージ内のネイティブバイナリを shim より優先する。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = Path(tmpdir)
            package_dir = project_dir / "node_modules" / "tree-sitter-cli"
            package_dir.mkdir(parents=True)
            native_executable = "tree-sitter.exe" if os.name == "nt" else "tree-sitter"
            native_cli = package_dir / native_executable
            native_cli.write_text("#!/bin/sh\n", encoding="utf-8")

            bin_dir = project_dir / "node_modules" / ".bin"
            bin_dir.mkdir(parents=True)
            shim_executable = "tree-sitter.cmd" if os.name == "nt" else "tree-sitter"
            shim_cli = bin_dir / shim_executable
            shim_cli.write_text("#!/bin/sh\n", encoding="utf-8")

            with patch.object(corpus_test, "PROJECT_DIR", project_dir):
                self.assertEqual(corpus_test.tree_sitter_command({}), str(native_cli))

    def test_tree_sitter_command_falls_back_to_path(self):
        """ローカル CLI がなければ PATH 上の tree-sitter にフォールバックする。"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(corpus_test, "PROJECT_DIR", Path(tmpdir)):
                self.assertEqual(corpus_test.tree_sitter_command({}), "tree-sitter")

    def test_strip_line_ending_removes_one_line_ending(self):
        """末尾の改行だけを除去し、本文中の CR は残す。"""
        self.assertEqual(corpus_test.strip_line_ending("x\n"), "x")
        self.assertEqual(corpus_test.strip_line_ending("x\r\n"), "x")
        self.assertEqual(corpus_test.strip_line_ending("x\r"), "x")
        self.assertEqual(corpus_test.strip_line_ending("x\r\r"), "x\r")

    def test_normalize_tree_ignores_fields_whitespace_and_parse_stats(self):
        """AST 比較ではフィールド名・空白・parse 統計行を無視する。"""
        actual = textwrap.dedent(
            """\
            (program
              (call
                method: (identifier)
                arguments: (argument_list
                  (string))))
            /tmp/example.rb\tParse: 0.01 ms\t(ERROR [0, 0] - [0, 1])
            """
        )
        expected = "(program (call (identifier) (argument_list (string))))"

        self.assertEqual(
            corpus_test.normalize_tree(actual),
            corpus_test.normalize_tree(expected),
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

    def test_summarize_command_failure_empty_output_uses_returncode(self):
        """空の output では returncode のみを返す。"""
        self.assertEqual(
            corpus_test.summarize_command_failure(3, ""),
            "exit 3",
        )

    def test_summarize_command_failure_only_filtered_lines(self):
        """すべての行がフィルター対象の場合は returncode のみを返す。"""
        output = textwrap.dedent(
            """\
                at ChildProcess._handle.onexit (node:internal/child_process:286:19)
            Emitted 'error' event on ChildProcess instance
            Node.js v24.12.0
            """
        )
        self.assertEqual(
            corpus_test.summarize_command_failure(42, output),
            "exit 42",
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
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_reports_tree_sitter_setup_error(
        self, mock_run, mock_guard, mock_listdir
    ):
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
        self.assertIn("cd node_modules/tree-sitter-cli", message)

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
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_all_tests_pass(self, mock_run, mock_guard, mock_listdir):
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
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        # tree-sitter parse の呼び出し（エラーなし）
        mock_guard.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (assignment))\n",
            stderr="",
        )
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("Pass: 1", stdout.getvalue())
        self.assertIn("Fail: 0", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_skips_non_txt_and_accepts_expected_error(
        self, mock_run, mock_guard, mock_listdir
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

        mock_run.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        mock_guard.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=1,
            stdout="(program (ERROR))\n",
            stderr="",
        )
        mock_listdir.return_value = ["README.md", corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("Pass: 1", stdout.getvalue())
        self.assertIn("Fail: 0", stdout.getvalue())
        self.assertEqual(mock_run.call_count, 1)
        self.assertEqual(mock_guard.call_count, 1)

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_reports_expected_error_when_parse_succeeds(
        self, mock_run, mock_guard, mock_listdir
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

        mock_run.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        mock_guard.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (method))\n",
            stderr="",
        )
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("expected ERROR but parsed OK", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_with_failure(self, mock_run, mock_guard, mock_listdir):
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
        mock_run.return_value = version_result
        mock_guard.return_value = parse_result
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("FAIL:", stdout.getvalue())
        self.assertIn("Fail: 1", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_reports_command_failure_detail_without_error_nodes(
        self, mock_run, mock_guard, mock_listdir
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
        mock_run.return_value = version_result
        mock_guard.return_value = parse_result
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("exit 2: permission denied", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_reports_ast_mismatch(self, mock_run, mock_guard, mock_listdir):
        """構文エラーがなくても期待 AST と違えば失敗として報告する。"""
        corpus = textwrap.dedent(
            """\
            =========
            wrong ast
            =========
            x = 1
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
            stdout="tree-sitter 0.26.8\n",
            stderr="",
        )
        parse_result = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (assignment))\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_guard.return_value = parse_result
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("AST mismatch", stdout.getvalue())

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

    def test_extract_tests_error_tag_in_name_with_error_in_ast(self):
        """AST に ERROR が含まれる場合 expects_error が True になる（:error タグではなく AST で判定）。"""
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
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_mixed_pass_and_fail(self, mock_run, mock_guard, mock_listdir):
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
        mock_run.return_value = version_result
        mock_guard.side_effect = [pass_result, fail_result]
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("Pass: 1", stdout.getvalue())
        self.assertIn("Fail: 1", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_parse_timeout(self, mock_run, mock_guard, mock_listdir):
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
        mock_run.return_value = version_result
        mock_guard.return_value = corpus_test._GuardedResult(
            None, "", "", "TIMEOUT (10s)"
        )
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
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
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_empty_corpus_directory(self, mock_run, mock_guard, mock_listdir):
        """corpus ディレクトリに .txt ファイルがない場合、0 件で成功する。"""
        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_listdir.return_value = ["README.md", ".gitkeep"]

        corpus_dir = tempfile.mkdtemp()
        stdout = io.StringIO()
        try:
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.rmdir(corpus_dir)

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
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_multiple_corpus_files(self, mock_run, mock_guard, mock_listdir):
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
        mock_run.return_value = version_result
        mock_guard.side_effect = [parse_ok, parse_ok]
        mock_listdir.return_value = sorted(
            [os.path.basename(path1), os.path.basename(path2)]
        )

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(path1)
            os.unlink(path2)

        self.assertEqual(exit_code, 0)
        self.assertIn("Total: 2", stdout.getvalue())
        self.assertIn("Pass: 2", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_missing_only_in_output(self, mock_run, mock_guard, mock_listdir):
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
        mock_run.return_value = version_result
        mock_guard.return_value = parse_result
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("Fail: 1", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_txt_file_without_test_cases(self, mock_run, mock_guard, mock_listdir):
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
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("Total: 0", stdout.getvalue())

    # --- extract_tests: :error タグの動作テスト ---

    def test_extract_tests_error_tag_without_error_in_ast(self):
        """:error タグがテスト名にあるが AST に ERROR がない場合、expects_error は False になる。

        現在の実装は :error タグを解釈しないため、AST のみで判定する。
        """
        corpus = textwrap.dedent(
            """\
            =========
            broken syntax
            :error
            =========
            def (
            ---
            (program
              (method))
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(tests), 1)
        # :error タグは未実装のため expects_error は False
        self.assertFalse(tests[0][2])

    # --- extract_tests: コード内に区切り線に似た行がある場合 ---

    def test_extract_tests_code_with_separator_like_line(self):
        """コード内に区切り線として認識される行があると、そこでコードが区切られる。"""
        corpus = textwrap.dedent(
            """\
            =========
            separator in code
            =========
            x = 1
            =========
            next test
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

        # "=====" がコード区切りとして扱われ、2つのテストに分割される
        self.assertEqual(len(tests), 2)
        self.assertEqual(tests[0][1], "x = 1")
        self.assertEqual(tests[1][1], "y = 2")

    # --- main: 複数 ERROR/MISSING ノードのカウント ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_counts_multiple_error_nodes(self, mock_run, mock_guard, mock_listdir):
        """パース出力に複数の ERROR/MISSING がある場合、合計数が報告される。"""
        corpus = textwrap.dedent(
            """\
            =========
            multi error
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
            stdout="(program (ERROR) (assignment (MISSING)) (ERROR))\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_guard.return_value = parse_result
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        # ERROR 2件 + MISSING 1件 = 3件
        self.assertIn("3 errors", stdout.getvalue())

    # --- main: パース中の PermissionError ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_permission_error_during_parse_propagates(
        self, mock_run, mock_guard, mock_listdir
    ):
        """パース実行中の PermissionError は未キャッチで伝播する。"""
        corpus = textwrap.dedent(
            """\
            =========
            perm error
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
        mock_run.return_value = version_result
        mock_guard.side_effect = PermissionError("permission denied")
        mock_listdir.return_value = [corpus_fname]

        try:
            with self._with_corpus_dir(corpus_dir), self.assertRaises(PermissionError):
                corpus_test.main()
        finally:
            os.unlink(corpus_path)

    # --- __main__ ガードのテスト ---

    @patch("corpus_test.main", return_value=0)
    def test_main_guard_calls_sys_exit(self, mock_main):
        """CLI エントリーポイントが sys.exit(main()) を呼ぶことを検証する。"""
        with self.assertRaises(SystemExit) as cm:
            corpus_test.run()
        self.assertEqual(cm.exception.code, 0)
        mock_main.assert_called_once_with()

    # --- main: expected ERROR だがパース成功の場合 ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_expected_error_but_parsed_ok(
        self, mock_run, mock_guard, mock_listdir
    ):
        """期待 AST に ERROR があるがパースが成功した場合、失敗として報告する。"""
        corpus = textwrap.dedent(
            """\
            =========
            should error
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
        # パース結果にエラーなし = 期待と不一致
        parse_ok = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (method))\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_guard.return_value = parse_ok
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("expected ERROR but parsed OK", stdout.getvalue())

    # --- main: 非ゼロ終了コードでエラーノードなし ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_nonzero_exit_without_error_nodes(
        self, mock_run, mock_guard, mock_listdir
    ):
        """tree-sitter parse が非ゼロで終了しエラーノードもない場合、コマンド失敗として報告する。"""
        corpus = textwrap.dedent(
            """\
            =========
            cmd fail
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
        parse_fail = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=1,
            stdout="",
            stderr="Error: some internal error\n",
        )
        mock_run.return_value = version_result
        mock_guard.return_value = parse_fail
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("exit 1:", stdout.getvalue())

    # --- extract_tests: コード内に --- が含まれる場合 ---

    def test_extract_tests_dash_separator_in_code_splits_ast(self):
        """コード内に --- があると AST 区切りとして認識される。"""
        corpus = textwrap.dedent(
            """\
            =========
            yaml heredoc
            =========
            x = <<~YAML
            ---
            key: value
            YAML
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

        # 最初の --- でコード/AST が分割される
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0][1], "x = <<~YAML")

    # --- extract_tests: 末尾が === で終わる場合 ---

    def test_extract_tests_file_ends_with_header_separator(self):
        """ファイルが === で終わる場合、前のテストが正しく抽出される。"""
        corpus = "=========\nfirst\n=========\nx = 1\n========="
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        # 最初のテストは === でコードが区切られ、2番目は名前未完了で無視
        self.assertEqual(len(tests), 1)
        self.assertEqual(tests[0][0], "first")
        self.assertEqual(tests[0][1], "x = 1")

    # --- summarize_command_failure: 特殊な出力パターン ---

    def test_summarize_command_failure_error_prefix_with_indentation(self):
        """インデントされた Error: 行が正しく検出される。"""
        output = "    Error: indented error message\n"
        self.assertEqual(
            corpus_test.summarize_command_failure(1, output),
            "exit 1: Error: indented error message",
        )

    def test_summarize_command_failure_only_blank_and_node_version(self):
        """空行と Node.js バージョンのみの場合、終了コードのみ返す。"""
        output = "\n\nNode.js v22.0.0\n"
        self.assertEqual(
            corpus_test.summarize_command_failure(1, output),
            "exit 1",
        )

    # --- main: stderr のみにエラー出力がある場合 ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_error_in_stderr_only(self, mock_run, mock_guard, mock_listdir):
        """stdout は空で stderr に ERROR がある場合、失敗として検出される。"""
        corpus = textwrap.dedent(
            """\
            =========
            stderr error
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
            returncode=1,
            stdout="",
            stderr="(program (ERROR))\n",
        )
        mock_run.return_value = version_result
        mock_guard.return_value = parse_result
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 1)
        self.assertIn("Fail: 1", stdout.getvalue())

    # --- is_separator: 長い区切り線 ---

    def test_is_separator_very_long_line(self):
        """非常に長い区切り線も正しく認識する。"""
        self.assertEqual(corpus_test.is_separator("=" * 1000), "=")
        self.assertEqual(corpus_test.is_separator("-" * 500), "-")

    # --- extract_tests: 複数の :error タグ付きテスト ---

    def test_extract_tests_multiple_tests_with_error_tags(self):
        """複数のテストケースでそれぞれ正しく expects_error が設定される。"""
        corpus = textwrap.dedent(
            """\
            =========
            normal
            =========
            x = 1
            ---
            (program
              (assignment))
            =========
            error1
            =========
            def (
            ---
            (program
              (ERROR))
            =========
            error2
            =========
            class (
            ---
            (program
              (MISSING))
            """
        )
        path = self._write_corpus(corpus)
        try:
            tests = corpus_test.extract_tests(path)
        finally:
            os.unlink(path)

        self.assertEqual(len(tests), 3)
        self.assertFalse(tests[0][2])  # normal
        self.assertTrue(tests[1][2])  # ERROR
        self.assertTrue(tests[2][2])  # MISSING

    # --- main: 期待 ERROR で MISSING のみ検出される場合 ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_expected_error_matched_by_missing(
        self, mock_run, mock_guard, mock_listdir
    ):
        """期待 AST に ERROR があり、パース結果に MISSING がある場合は成功。"""
        corpus = textwrap.dedent(
            """\
            =========
            error via missing
            =========
            def foo(
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
            stdout="(program (MISSING))\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_guard.return_value = parse_result
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        # MISSING も ERROR 系として扱うので成功
        self.assertEqual(exit_code, 0)
        self.assertIn("Pass: 1", stdout.getvalue())

    # --- check_tree_sitter_cli: タイムアウトの直接テスト ---

    @patch(
        "corpus_test.subprocess.run",
        side_effect=subprocess.TimeoutExpired(["tree-sitter", "--version"], timeout=10),
    )
    def test_check_tree_sitter_cli_timeout(self, mock_run):
        """CLI 起動確認がタイムアウトした場合にタイムアウトメッセージを返す。"""
        message = corpus_test.check_tree_sitter_cli({})
        self.assertIn("10 秒でタイムアウト", message)
        mock_run.assert_called_once()

    # --- extract_tests: 複数の空行名前セクション ---

    def test_extract_tests_name_with_only_blank_lines(self):
        """名前セクションが複数の空行のみの場合でも空名前でテストが抽出される。"""
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
        self.assertEqual(tests[0][1], "x = 1")

    # --- main: KeyboardInterrupt がパース中に発生した場合 ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_keyboard_interrupt_during_parse_propagates(
        self, mock_run, mock_guard, mock_listdir
    ):
        """パース実行中の KeyboardInterrupt は未キャッチで伝播する。"""
        corpus = textwrap.dedent(
            """\
            =========
            interrupt
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
        mock_run.return_value = version_result
        mock_guard.side_effect = KeyboardInterrupt()
        mock_listdir.return_value = [corpus_fname]

        try:
            with self._with_corpus_dir(corpus_dir), self.assertRaises(
                KeyboardInterrupt
            ):
                corpus_test.main()
        finally:
            os.unlink(corpus_path)

    # --- summarize_command_failure: Emitted 'error' event のみ ---

    def test_summarize_command_failure_only_emitted_error(self):
        """Emitted 'error' event のみの場合、終了コードのみ返す。"""
        output = "Emitted 'error' event on ChildProcess instance\n"
        self.assertEqual(
            corpus_test.summarize_command_failure(1, output),
            "exit 1",
        )

    # --- extract_tests: コード末尾の空白がトリムされる ---

    def test_extract_tests_code_trailing_whitespace_lines_trimmed(self):
        """コード末尾に空白のみの行があっても除去される。"""
        corpus = textwrap.dedent(
            """\
            =========
            trailing ws
            =========
            x = 1
               \t
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

    # --- main: 空コードのテストがスキップされる ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_empty_code_tests_not_counted(
        self, mock_run, mock_guard, mock_listdir
    ):
        """コードが空のテストケースは extract_tests でスキップされ集計に含まれない。"""
        corpus = textwrap.dedent(
            """\
            =========
            empty code
            =========

            ---
            (program)
            =========
            valid code
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
        parse_ok = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=0,
            stdout="(program (assignment))\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_guard.return_value = parse_ok
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        # 空コードはスキップされるので Total: 1
        self.assertEqual(exit_code, 0)
        self.assertIn("Total: 1", stdout.getvalue())

    # --- main: CORPUS_DIR が存在しない場合 ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_missing_corpus_dir(self, mock_run, mock_guard, mock_listdir):
        """corpus ディレクトリが存在しない場合、setup error で終了する。"""
        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        mock_run.return_value = version_result

        stdout = io.StringIO()
        with self._capture_stdout_with_corpus_dir("/nonexistent/path", stdout):
            exit_code = corpus_test.main()

        self.assertEqual(exit_code, 2)
        mock_listdir.assert_not_called()
        self.assertIn("--- Setup Error ---", stdout.getvalue())
        self.assertIn("corpus ディレクトリが見つかりません", stdout.getvalue())

    # --- main: NamedTemporaryFile 失敗時に UnboundLocalError にならない ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_tempfile_creation_failure_propagates(
        self, mock_run, mock_guard, mock_listdir
    ):
        """一時ファイル作成失敗時に UnboundLocalError ではなく OSError が伝播する。"""
        corpus = textwrap.dedent(
            """\
            =========
            tempfail
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
        mock_run.return_value = version_result
        mock_listdir.return_value = [corpus_fname]

        try:
            with self._with_corpus_dir(corpus_dir):
                with patch(
                    "corpus_test.tempfile.NamedTemporaryFile",
                    side_effect=OSError("disk full"),
                ), self.assertRaises(OSError, msg="disk full"):
                    corpus_test.main()
        finally:
            os.unlink(corpus_path)

    # --- check_tree_sitter_cli の追加テスト ---

    @patch("corpus_test.subprocess.run")
    def test_check_tree_sitter_cli_enoent_without_cli_path(self, mock_run):
        """ENOENT を含むが tree-sitter-cli/tree-sitter を含まない場合は一般エラー。"""
        mock_run.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=1,
            stdout="",
            stderr="Error: ENOENT some other path\n",
        )
        message = corpus_test.check_tree_sitter_cli({})
        self.assertIn("tree-sitter CLI を起動できません", message)
        self.assertNotIn("install.js", message)

    # --- main: 環境変数が正しく渡されることの検証 ---

    @patch.dict(os.environ, {"TREE_SITTER_LIBDIR": "/tmp/ts-lib"})
    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_passes_tree_sitter_libdir_env(
        self, mock_run, mock_guard, mock_listdir
    ):
        """main() が TREE_SITTER_LIBDIR=/tmp/ts-lib を env に含めて subprocess を呼ぶ。"""
        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_listdir.return_value = []

        corpus_dir = tempfile.mkdtemp()
        stdout = io.StringIO()
        try:
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                corpus_test.main()
        finally:
            os.rmdir(corpus_dir)

        # 最初の subprocess.run 呼び出し (check_tree_sitter_cli) の env を検証
        _, call_kwargs = mock_run.call_args_list[0]
        env = call_kwargs["env"]
        self.assertEqual(env.get("TREE_SITTER_LIBDIR"), "/tmp/ts-lib")

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_uses_resolved_tree_sitter_command(
        self, mock_run, mock_guard, mock_listdir
    ):
        """main() の起動確認と parse が同じ CLI パスを使う。"""
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

        version_result = subprocess.CompletedProcess(
            args=["/custom/tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.8\n",
            stderr="",
        )
        parse_result = subprocess.CompletedProcess(
            args=["/custom/tree-sitter", "parse"],
            returncode=0,
            stdout="(program (assignment))\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_guard.return_value = parse_result
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                with patch(
                    "corpus_test.tree_sitter_command",
                    return_value="/custom/tree-sitter",
                ):
                    exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        self.assertEqual(exit_code, 0)
        first_cmd = mock_run.call_args_list[0][0][0]
        second_cmd = mock_guard.call_args_list[0][0][0]
        self.assertEqual(first_cmd[:2], ["/custom/tree-sitter", "--version"])
        self.assertEqual(second_cmd[:2], ["/custom/tree-sitter", "parse"])
        self.assertIn("--no-ranges", second_cmd)
        self.assertEqual(
            second_cmd[2:6], ["--lib-path", __file__, "--lang-name", "ruby"]
        )

    # --- extract_tests: .DS_Store 等の非 .txt ファイルが混在するケース ---

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_ignores_hidden_and_non_txt_files(
        self, mock_run, mock_guard, mock_listdir
    ):
        """隠しファイルや非 .txt ファイルはスキップされる。"""
        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_listdir.return_value = [".DS_Store", "notes.md", "README"]

        corpus_dir = tempfile.mkdtemp()
        stdout = io.StringIO()
        try:
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()
        finally:
            os.rmdir(corpus_dir)

        self.assertEqual(exit_code, 0)
        self.assertIn("Total: 0", stdout.getvalue())

    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_skips_hidden_txt_and_txt_directory(self, mock_run, mock_guard):
        """隠し .txt ファイルや .txt ディレクトリは実行対象にしない。"""
        version_result = subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.7\n",
            stderr="",
        )
        mock_run.return_value = version_result

        with tempfile.TemporaryDirectory() as corpus_dir:
            os.mkdir(os.path.join(corpus_dir, "dir.txt"))
            with open(
                os.path.join(corpus_dir, ".hidden.txt"),
                "w",
                encoding="utf-8",
            ) as f:
                f.write(
                    "=========\nhidden\n=========\nx = 1\n---\n(program (assignment))\n"
                )

            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                exit_code = corpus_test.main()

        self.assertEqual(exit_code, 0)
        self.assertIn("Total: 0", stdout.getvalue())
        mock_guard.assert_not_called()

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_unlink_oserror_does_not_crash(
        self, mock_run, mock_guard, mock_listdir
    ):
        """一時ファイル削除時の OSError がテスト全体をクラッシュさせないことを検証する。"""
        corpus = textwrap.dedent(
            """\
            =========
            unlink fail
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
            stdout="(program (assignment))\n",
            stderr="",
        )
        mock_run.return_value = version_result
        mock_guard.return_value = parse_result
        mock_listdir.return_value = [corpus_fname]

        try:
            stdout = io.StringIO()
            with self._capture_stdout_with_corpus_dir(corpus_dir, stdout):
                with patch(
                    "corpus_test.os.unlink", side_effect=OSError("permission denied")
                ):
                    exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        # OSError が握りつぶされてテストは正常終了する
        self.assertEqual(exit_code, 0)
        self.assertIn("Pass: 1", stdout.getvalue())


class ResolveMemoryLimitTests(unittest.TestCase):
    """`_resolve_memory_limit_mb` の環境変数解析を検証する。"""

    def test_returns_default_when_unset(self):
        """環境変数が未設定なら既定値を返す。"""
        self.assertEqual(
            corpus_test._resolve_memory_limit_mb({}),
            corpus_test.DEFAULT_MEMORY_LIMIT_MB,
        )

    def test_returns_default_when_blank(self):
        """空文字列も既定値にフォールバックする。"""
        self.assertEqual(
            corpus_test._resolve_memory_limit_mb({"TS_MEMORY_LIMIT_MB": "   "}),
            corpus_test.DEFAULT_MEMORY_LIMIT_MB,
        )

    def test_returns_default_when_not_a_number(self):
        """数値以外なら既定値にフォールバックする。"""
        self.assertEqual(
            corpus_test._resolve_memory_limit_mb({"TS_MEMORY_LIMIT_MB": "abc"}),
            corpus_test.DEFAULT_MEMORY_LIMIT_MB,
        )

    def test_returns_default_when_zero_or_negative(self):
        """0 以下の値は安全側の既定値に丸める。"""
        for value in ("0", "-1", "-512.5"):
            with self.subTest(value=value):
                self.assertEqual(
                    corpus_test._resolve_memory_limit_mb({"TS_MEMORY_LIMIT_MB": value}),
                    corpus_test.DEFAULT_MEMORY_LIMIT_MB,
                )

    def test_returns_default_when_not_finite(self):
        """NaN と無限大はメモリ監視を無効化するため既定値に戻す。"""
        for value in ("nan", "inf", "-inf"):
            with self.subTest(value=value):
                self.assertEqual(
                    corpus_test._resolve_memory_limit_mb({"TS_MEMORY_LIMIT_MB": value}),
                    corpus_test.DEFAULT_MEMORY_LIMIT_MB,
                )

    def test_returns_parsed_value_for_valid_number(self):
        """有効な値はそのまま採用される。"""
        self.assertAlmostEqual(
            corpus_test._resolve_memory_limit_mb({"TS_MEMORY_LIMIT_MB": "2048.5"}),
            2048.5,
        )

    def test_falls_back_to_environ_when_env_arg_omitted(self):
        """env 引数を省略した場合は os.environ から解決する。"""
        with patch.dict(os.environ, {"TS_MEMORY_LIMIT_MB": "1500"}, clear=False):
            self.assertEqual(corpus_test._resolve_memory_limit_mb(), 1500.0)


class GetRssMbTests(unittest.TestCase):
    """OS ごとの RSS 取得と単位変換を検証する。"""

    def test_windows_tasklist_csv_preserves_thousands_separator(self):
        """引用符内の桁区切りカンマを列区切りとして扱わない。"""
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout='"tree-sitter.exe","4242","Console","1","12,344 K"\n',
            stderr="",
        )
        with patch.object(corpus_test.sys, "platform", "win32"):
            with patch("corpus_test.subprocess.run", return_value=result):
                self.assertAlmostEqual(corpus_test._get_rss_mb(4242), 12344 / 1024)

    def test_posix_ps_converts_kilobytes_to_megabytes(self):
        """ps の KiB 出力を MiB に変換する。"""
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="2048\n",
            stderr="",
        )
        with patch.object(corpus_test.sys, "platform", "darwin"):
            with patch("corpus_test.subprocess.run", return_value=result):
                self.assertEqual(corpus_test._get_rss_mb(4242), 2.0)

    def test_process_group_rss_sums_only_matching_group(self):
        """同じプロセスグループの RSS だけを合算する。"""
        result = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="99 1024\n99 2048\n100 4096\ninvalid\n",
            stderr="",
        )
        with patch.object(corpus_test.sys, "platform", "darwin"):
            with patch("corpus_test.os.getpgid", return_value=99):
                with patch("corpus_test.subprocess.run", return_value=result):
                    self.assertEqual(
                        corpus_test._get_process_group_rss_mb(4242),
                        3.0,
                    )


class KillProcessTreeTests(unittest.TestCase):
    """プロセスツリー強制終了の OS 別フォールバックを検証する。"""

    def test_windows_taskkill_failure_falls_back_to_process_kill(self):
        """taskkill の起動に失敗しても対象プロセスを直接終了する。"""
        proc = Mock(pid=4242)
        with patch.object(corpus_test.sys, "platform", "win32"):
            with patch(
                "corpus_test.subprocess.run", side_effect=OSError("taskkill failed")
            ) as mock_run:
                corpus_test._kill_process_tree(proc)

        mock_run.assert_called_once_with(
            ["taskkill", "/PID", "4242", "/T", "/F"],
            capture_output=True,
            check=False,
            timeout=5,
        )
        proc.kill.assert_called_once_with()

    def test_posix_group_kill_failure_falls_back_to_process_kill(self):
        """プロセスグループ終了に失敗しても対象プロセスを直接終了する。"""
        proc = Mock(pid=4242)
        with patch.object(corpus_test.sys, "platform", "darwin"):
            with patch("corpus_test.os.getpgid", return_value=99) as mock_getpgid:
                with patch(
                    "corpus_test.os.killpg", side_effect=OSError("killpg failed")
                ) as mock_killpg:
                    corpus_test._kill_process_tree(proc)

        mock_getpgid.assert_called_once_with(4242)
        mock_killpg.assert_called_once_with(99, corpus_test.signal.SIGKILL)
        proc.kill.assert_called_once_with()


class RunWithMemoryGuardTests(unittest.TestCase):
    """`run_with_memory_guard` の制御フローを検証する。"""

    def test_returns_completed_command_output(self):
        """正常終了したコマンドの stdout / returncode を返す。"""
        result = corpus_test.run_with_memory_guard(
            [sys.executable, "-c", "print('ok')"],
            timeout=5,
            memory_limit_mb=corpus_test.DEFAULT_MEMORY_LIMIT_MB,
            env=os.environ,
        )
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout.strip(), "ok")
        self.assertIsNone(result.kill_reason)

    def test_kills_process_after_timeout(self):
        """timeout 秒経過したらプロセスを強制終了し kill_reason を設定する。"""
        result = corpus_test.run_with_memory_guard(
            [sys.executable, "-c", "import time; time.sleep(10)"],
            timeout=1,
            memory_limit_mb=corpus_test.DEFAULT_MEMORY_LIMIT_MB,
            env=os.environ,
            poll_interval=0.2,
        )
        self.assertIsInstance(result.kill_reason, str)
        self.assertIn("TIMEOUT", result.kill_reason)

    def test_large_output_does_not_block_until_timeout(self):
        """pipe バッファを超える出力でも drain しながら正常終了を待てる。"""
        result = corpus_test.run_with_memory_guard(
            [
                sys.executable,
                "-c",
                (
                    "import sys; "
                    "sys.stdout.write('x' * (1024 * 1024)); "
                    "sys.stderr.write('e' * (128 * 1024))"
                ),
            ],
            timeout=5,
            memory_limit_mb=corpus_test.DEFAULT_MEMORY_LIMIT_MB,
            env=os.environ,
            poll_interval=0.1,
        )
        self.assertEqual(result.returncode, 0)
        self.assertIsNone(result.kill_reason)
        self.assertEqual(len(result.stdout), 1024 * 1024)
        self.assertEqual(len(result.stderr), 128 * 1024)

    @unittest.skipIf(
        sys.platform == "win32",
        "POSIX のプロセスグループ RSS 合算を検証するテスト",
    )
    def test_kills_when_child_process_exceeds_memory_limit(self):
        """子プロセスだけが RSS 上限を超えてもプロセスグループごと kill する。"""
        child_code = (
            "import time\n"
            "chunks = [bytearray(1024 * 1024) for _ in range(80)]\n"
            "time.sleep(10)\n"
        )
        parent_code = (
            "import subprocess, sys, time\n"
            f"subprocess.Popen([sys.executable, '-c', {child_code!r}])\n"
            "time.sleep(10)\n"
        )
        result = corpus_test.run_with_memory_guard(
            [sys.executable, "-c", parent_code],
            timeout=5,
            memory_limit_mb=30,
            env=os.environ,
            poll_interval=0.2,
        )
        self.assertIsInstance(result.kill_reason, str)
        self.assertIn("MEMORY_KILL", result.kill_reason)


class ResolveLibDirTests(unittest.TestCase):
    """共有ライブラリディレクトリの解決を検証する。"""

    def test_env_override_wins(self):
        """TREE_SITTER_LIBDIR が指定されていればそのまま使う。"""
        self.assertEqual(
            corpus_test.resolve_lib_dir({"TREE_SITTER_LIBDIR": "D:/custom/ts-lib"}),
            "D:/custom/ts-lib",
        )

    def test_env_override_is_trimmed(self):
        """前後の空白は取り除いて解釈する。"""
        self.assertEqual(
            corpus_test.resolve_lib_dir({"TREE_SITTER_LIBDIR": "  /opt/ts-lib \n"}),
            "/opt/ts-lib",
        )

    def test_blank_override_falls_back_to_default(self):
        """空白のみの指定は未設定として扱う。"""
        with patch.object(corpus_test.os, "name", "posix"):
            self.assertEqual(
                corpus_test.resolve_lib_dir({"TREE_SITTER_LIBDIR": "   "}),
                corpus_test.POSIX_LIB_DIR,
            )

    def test_posix_default(self):
        """POSIX では /tmp/ts-lib を既定にする。"""
        with patch.object(corpus_test.os, "name", "posix"):
            self.assertEqual(corpus_test.resolve_lib_dir({}), "/tmp/ts-lib")

    def test_windows_default_uses_native_temp_dir(self):
        """Windows では POSIX パスではなくネイティブの TEMP 配下を使う。"""
        with patch.object(corpus_test.os, "name", "nt"):
            with patch.object(
                corpus_test.tempfile, "gettempdir", return_value="C:/Temp"
            ):
                resolved = corpus_test.resolve_lib_dir({})

        self.assertEqual(resolved, os.path.join("C:/Temp", "ts-lib"))
        self.assertFalse(resolved.startswith("/tmp"))

    def test_falls_back_to_os_environ(self):
        """env 未指定なら os.environ を参照する。"""
        with patch.dict(os.environ, {"TREE_SITTER_LIBDIR": "/env/ts-lib"}):
            self.assertEqual(corpus_test.resolve_lib_dir(), "/env/ts-lib")


class ConfigureStdioEncodingTests(unittest.TestCase):
    """出力ストリームの UTF-8 化を検証する。"""

    def test_reconfigures_streams_to_utf8(self):
        """reconfigure を持つストリームは UTF-8 + replace に切り替える。"""

        class _Stream:
            def __init__(self):
                self.calls = []

            def reconfigure(self, **kwargs):
                self.calls.append(kwargs)

        stream = _Stream()
        corpus_test.configure_stdio_encoding([stream])

        self.assertEqual(
            stream.calls, [{"encoding": "utf-8", "errors": "backslashreplace"}]
        )

    def test_skips_streams_without_reconfigure(self):
        """reconfigure を持たないストリーム (StringIO 等) では何もしない。"""
        corpus_test.configure_stdio_encoding([io.StringIO()])

    def test_swallows_reconfigure_errors(self):
        """reconfigure が失敗してもランナーを落とさない。"""

        class _Stream:
            def reconfigure(self, **kwargs):
                raise ValueError("detached")

        corpus_test.configure_stdio_encoding([_Stream()])

    def test_defaults_to_std_streams(self):
        """引数なしなら sys.stdout / sys.stderr を対象にする。"""
        calls = []

        class _Stream:
            def reconfigure(self, **kwargs):
                calls.append(kwargs)

        with patch.object(corpus_test.sys, "stdout", _Stream()):
            with patch.object(corpus_test.sys, "stderr", _Stream()):
                corpus_test.configure_stdio_encoding()

        self.assertEqual(len(calls), 2)


class RootCauseLineTests(unittest.TestCase):
    """tree-sitter の Caused by チェーン抽出を検証する。"""

    def test_returns_none_without_cause_section(self):
        """Caused by が無ければ None を返す。"""
        self.assertIsNone(corpus_test.root_cause_line("Error: boom\n"))

    def test_extracts_single_cause(self):
        """単一原因はそのまま返す。"""
        output = textwrap.dedent(
            """\
            Error: Failed to load language for path "x.rb"

            Caused by:
                Error opening dynamic library /tmp/ts-lib/ruby.dll -- dlopen failed
            """
        )
        self.assertEqual(
            corpus_test.root_cause_line(output),
            "Error opening dynamic library /tmp/ts-lib/ruby.dll -- dlopen failed",
        )

    def test_returns_deepest_cause_without_numbering(self):
        """複数原因では最深部を、番号付けを外して返す。"""
        output = textwrap.dedent(
            """\
            Error: Failed to load language for path "x.rb"

            Caused by:
                0: failed to load language for current directory
                1: The specified module could not be found. (os error 126)
            """
        )
        self.assertEqual(
            corpus_test.root_cause_line(output),
            "The specified module could not be found. (os error 126)",
        )

    def test_returns_none_when_cause_section_is_empty(self):
        """Caused by の後に内容が無ければ None を返す。"""
        self.assertIsNone(corpus_test.root_cause_line("Caused by:\n\n"))

    def test_strips_ansi_before_matching(self):
        """ANSI エスケープ付きでも Caused by を認識する。"""
        output = "\x1b[31mError:\x1b[0m boom\n\nCaused by:\n    os error 126\n"
        self.assertEqual(corpus_test.root_cause_line(output), "os error 126")

    def test_summarize_command_failure_appends_root_cause(self):
        """失敗要約に最深部の原因を添える。"""
        output = textwrap.dedent(
            """\
            Error: Failed to load language for path "x.rb"

            Caused by:
                No language found
            """
        )
        self.assertEqual(
            corpus_test.summarize_command_failure(1, output),
            'exit 1: Error: Failed to load language for path "x.rb"'
            " (root cause: No language found)",
        )

    def test_summarize_command_failure_strips_ansi_error_line(self):
        """着色された Error: 行でも要約が取りこぼさない。"""
        output = '\x1b[31mError:\x1b[0m Failed to load language for path "x.rb"\n'
        self.assertEqual(
            corpus_test.summarize_command_failure(1, output),
            'exit 1: Error: Failed to load language for path "x.rb"',
        )


class ResolveLibraryPathTests(unittest.TestCase):
    """共有ライブラリのファイルパス解決を検証する。"""

    def test_explicit_lib_path_wins(self):
        """TREE_SITTER_LIB_PATH は libdir より優先される。"""
        env = {
            "TREE_SITTER_LIB_PATH": "C:/Temp/ts-lib/ruby.dll",
            "TREE_SITTER_LIBDIR": "/ignored",
        }
        self.assertEqual(
            corpus_test.resolve_library_path(env), "C:/Temp/ts-lib/ruby.dll"
        )

    def test_derives_from_libdir_with_platform_suffix(self):
        """libdir とプラットフォーム既定の拡張子から組み立てる。"""
        env = {"TREE_SITTER_LIBDIR": "/opt/ts-lib"}
        self.assertEqual(
            corpus_test.resolve_library_path(env),
            os.path.join("/opt/ts-lib", "ruby" + corpus_test.library_suffix()),
        )

    def test_library_suffix_per_platform(self):
        """プラットフォームごとの拡張子を返す。"""
        for platform, expected in (
            ("win32", ".dll"),
            ("darwin", ".dylib"),
            ("linux", ".so"),
        ):
            with patch.object(corpus_test.sys, "platform", platform):
                self.assertEqual(corpus_test.library_suffix(), expected)


class MainEnvironmentTests(unittest.TestCase):
    """main() の環境変数受け渡しとセットアップ検証を確認する。"""

    @staticmethod
    def _version_ok():
        return subprocess.CompletedProcess(
            args=["tree-sitter", "--version"],
            returncode=0,
            stdout="tree-sitter 0.26.11\n",
            stderr="",
        )

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_passes_resolved_libdir_and_no_color(
        self, mock_run, mock_guard, mock_listdir
    ):
        """解決済み libdir と NO_COLOR=1 を env に含める。"""
        mock_run.return_value = self._version_ok()
        mock_listdir.return_value = []

        corpus_dir = tempfile.mkdtemp()
        stdout = io.StringIO()
        try:
            with patch.object(corpus_test, "CORPUS_DIR", corpus_dir):
                with patch.object(
                    corpus_test, "resolve_lib_dir", return_value="C:/Temp/ts-lib"
                ):
                    with patch.object(
                        corpus_test, "resolve_library_path", return_value=__file__
                    ):
                        with redirect_stdout(stdout):
                            corpus_test.main()
        finally:
            os.rmdir(corpus_dir)

        _, call_kwargs = mock_run.call_args_list[0]
        env = call_kwargs["env"]
        self.assertEqual(env.get("TREE_SITTER_LIBDIR"), "C:/Temp/ts-lib")
        self.assertEqual(env.get("NO_COLOR"), "1")

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_main_reports_missing_library_as_setup_error(
        self, mock_run, mock_guard, mock_listdir
    ):
        """共有ライブラリが無ければ 1 件もパースせず setup error で終わる。"""
        mock_run.return_value = self._version_ok()

        stdout = io.StringIO()
        with patch.object(
            corpus_test,
            "resolve_library_path",
            return_value=os.path.join(tempfile.gettempdir(), "definitely-missing.dll"),
        ):
            with redirect_stdout(stdout):
                exit_code = corpus_test.main()

        self.assertEqual(exit_code, 2)
        mock_listdir.assert_not_called()
        mock_guard.assert_not_called()
        self.assertIn("--- Setup Error ---", stdout.getvalue())
        self.assertIn("parser 共有ライブラリが見つかりません", stdout.getvalue())

    @patch("corpus_test.os.listdir")
    @patch("corpus_test.run_with_memory_guard")
    @patch("corpus_test.subprocess.run")
    def test_expected_error_case_reports_cli_failure(
        self, mock_run, mock_guard, mock_listdir
    ):
        """ツリーが出ない CLI 失敗は期待 ERROR ケースでも成功にしない。"""
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
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write(corpus)
            corpus_path = f.name

        mock_run.return_value = self._version_ok()
        mock_guard.return_value = subprocess.CompletedProcess(
            args=["tree-sitter", "parse"],
            returncode=1,
            stdout="",
            stderr=(
                '\x1b[31mError:\x1b[0m Failed to load language for path "x.rb"\n'
                "\nCaused by:\n"
                "    The specified module could not be found. (os error 126)\n"
            ),
        )
        mock_listdir.return_value = [os.path.basename(corpus_path)]

        stdout = io.StringIO()
        try:
            with patch.object(corpus_test, "CORPUS_DIR", os.path.dirname(corpus_path)):
                with patch.object(
                    corpus_test, "resolve_library_path", return_value=__file__
                ):
                    with redirect_stdout(stdout):
                        exit_code = corpus_test.main()
        finally:
            os.unlink(corpus_path)

        output = stdout.getvalue()
        self.assertEqual(exit_code, 1)
        self.assertNotIn("expected ERROR but parsed OK", output)
        self.assertIn("Failed to load language", output)
        self.assertIn("root cause: The specified module could not be found.", output)


if __name__ == "__main__":
    unittest.main()
