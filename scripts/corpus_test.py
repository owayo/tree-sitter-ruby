#!/usr/bin/env python3
"""tree-sitter parse ベースの低メモリなコーパステストランナー。

大規模な parser テーブル（parser.c 約15MB）では `tree-sitter test` が
過剰なメモリ（RSS 8GB+, VSIZE 400GB+）を消費するため、
本スクリプトは各コーパステストを `tree-sitter parse` で実行する。

事前準備:
    mkdir -p /tmp/ts-lib
    cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
CORPUS_DIR = PROJECT_DIR / "test" / "corpus"


def is_separator(line):
    """区切り線を判定する。"""
    s = line.strip()
    if len(s) < 3:
        return None
    if all(c == "=" for c in s):
        return "="
    if all(c == "-" for c in s):
        return "-"
    return None


def extract_tests(filepath):
    """コーパスファイルからテストケースを抽出する。"""
    with open(filepath, encoding="utf-8") as f:
        lines = f.readlines()

    tests = []
    i = 0
    while i < len(lines):
        if is_separator(lines[i]) == "=":
            i += 1
            name_lines = []
            while i < len(lines):
                if is_separator(lines[i]) == "=":
                    break
                name_lines.append(lines[i].strip())
                i += 1
            if i >= len(lines):
                break
            name = " ".join(part for part in name_lines if part)
            i += 1

            code_lines = []
            while i < len(lines):
                if is_separator(lines[i]) == "-":
                    break
                if is_separator(lines[i]) == "=":
                    break
                code_lines.append(lines[i].rstrip("\n"))
                i += 1

            ast_lines = []
            if i < len(lines) and is_separator(lines[i]) == "-":
                i += 1
                while i < len(lines):
                    if is_separator(lines[i]) == "=":
                        break
                    ast_lines.append(lines[i].rstrip("\n"))
                    i += 1

            while code_lines and not code_lines[0].strip():
                code_lines.pop(0)
            while code_lines and not code_lines[-1].strip():
                code_lines.pop()

            code = "\n".join(code_lines)
            expected_ast = "\n".join(ast_lines)
            expects_error = "(ERROR" in expected_ast or "(MISSING" in expected_ast
            if code.strip():
                tests.append((name, code, expects_error))
        else:
            i += 1

    return tests


def format_failure_detail(detail):
    """失敗理由を表示用文字列に整形する。"""
    if isinstance(detail, int):
        return f"{detail} errors"
    return str(detail)


def main():
    """全コーパステストを実行して結果を返す。"""
    total = 0
    passed = 0
    failed = 0
    failures = []

    env = {**os.environ, "TREE_SITTER_LIBDIR": "/tmp/ts-lib"}

    for fname in sorted(os.listdir(CORPUS_DIR)):
        if not fname.endswith(".txt"):
            continue
        filepath = os.path.join(CORPUS_DIR, fname)
        tests = extract_tests(filepath)

        for name, code, expects_error in tests:
            total += 1
            with tempfile.NamedTemporaryFile(
                mode="w",
                suffix=".rb",
                delete=False,
                encoding="utf-8",
            ) as f:
                f.write(code + "\n")
                tmpfile = f.name

            try:
                result = subprocess.run(
                    ["tree-sitter", "parse", tmpfile],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=10,
                    env=env,
                )
                output = result.stdout + result.stderr
                has_error = "(ERROR" in output or "(MISSING" in output
                if expects_error:
                    if has_error:
                        passed += 1
                    else:
                        failed += 1
                        failures.append((fname, name, "expected ERROR but parsed OK"))
                elif not has_error and result.returncode == 0:
                    passed += 1
                else:
                    failed += 1
                    errs = output.count("(ERROR") + output.count("(MISSING")
                    failures.append((fname, name, errs))
            except subprocess.TimeoutExpired:
                failed += 1
                failures.append((fname, name, "TIMEOUT"))
            finally:
                os.unlink(tmpfile)

    if failures:
        print("\n--- Failures ---")
        for fname, name, err in failures:
            print(f"  FAIL: {fname} :: {name} ({format_failure_detail(err)})")

    print("\n=== Results ===")
    print(f"Total: {total} | Pass: {passed} | Fail: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
