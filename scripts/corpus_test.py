#!/usr/bin/env python3
"""Alternative corpus test runner using tree-sitter parse.

tree-sitter test consumes excessive memory (RSS 8GB+, VSIZE 400GB+) with large
parser tables (parser.c ~15MB). This script runs each corpus test case via
tree-sitter parse instead, using minimal memory (~10MB RSS).

Prerequisites:
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
    """Return '=' for header lines, '-' for divider lines, None otherwise.

    Returns:
        '=', '-', or None.

    """
    s = line.strip()
    if len(s) < 3:
        return None
    if all(c == "=" for c in s):
        return "="
    if all(c == "-" for c in s):
        return "-"
    return None


def extract_tests(filepath):
    """Extract test cases from a corpus file.

    Returns:
        List of (name, code, expects_error) tuples.

    """
    with open(filepath) as f:
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


def main():
    """Run all corpus tests and report results.

    Returns:
        0 if all tests pass, 1 otherwise.

    """
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
            with tempfile.NamedTemporaryFile(mode="w", suffix=".rb", delete=False) as f:
                f.write(code + "\n")
                tmpfile = f.name

            try:
                result = subprocess.run(
                    ["tree-sitter", "parse", tmpfile],
                    capture_output=True,
                    text=True,
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
            print(f"  FAIL: {fname} :: {name} ({err} errors)")

    print("\n=== Results ===")
    print(f"Total: {total} | Pass: {passed} | Fail: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
