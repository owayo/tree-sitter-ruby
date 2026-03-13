#!/usr/bin/env python3
"""scripts/corpus_test.py のユニットテスト。"""

import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
