#!/usr/bin/env python3
# ruff: noqa: DOC201, DOC501
"""tree-sitter parse ベースの低メモリなコーパステストランナー。

大規模な parser テーブル（parser.c 約15MB）では `tree-sitter test` が
過剰なメモリ（RSS 8GB+, VSIZE 400GB+）を消費するため、
本スクリプトは各コーパステストを `tree-sitter parse` で実行する。

子プロセスはプロセスグループ単位で起動し、5 秒ごとに RSS 合計を観測する。
閾値 (TS_MEMORY_LIMIT_MB、既定 1024MB) を超過したら即座に SIGKILL して
PC のハングを防ぐ。tree-sitter 側にも `--timeout` (µs) を渡し、
内部 wallclock タイマーで暴走パースを未然に止める。

事前準備:
    mkdir -p /tmp/ts-lib
    cc -shared -fPIC -O0 -o /tmp/ts-lib/ruby.dylib -I src src/parser.c src/scanner.c

共有ライブラリの置き場所は `TREE_SITTER_LIBDIR` で上書きできる。未設定なら
POSIX では `/tmp/ts-lib`、Windows では TEMP ディレクトリ配下の `ts-lib` を使う
（後者は Git Bash の `/tmp` と同じ実体を指す）。
"""

import csv
import math
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
CORPUS_DIR = PROJECT_DIR / "test" / "corpus"

DEFAULT_MEMORY_LIMIT_MB = 1024.0
PARSE_TIMEOUT_SECONDS = 10
POLL_INTERVAL_SECONDS = 5.0
POSIX_LIB_DIR = "/tmp/ts-lib"
LIB_DIR_NAME = "ts-lib"


def configure_stdio_encoding(streams=None):
    """非 ASCII を含む出力が既定コードページで落ちないようにする。

    Windows の Python は stdout の既定エンコーディングが cp1252/cp932 に
    なるため、日本語を含むコーパスのテスト名を print した時点で
    UnicodeEncodeError が送出され、ランナーごと異常終了してしまう。
    """
    if streams is None:
        streams = (sys.stdout, sys.stderr)
    for stream in streams:
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            pass


def resolve_lib_dir(env=None):
    """tree-sitter が parser 共有ライブラリを探すディレクトリを解決する。

    POSIX パスをそのまま Windows のネイティブ CLI に渡すと、ドライブレターの
    無い root 相対パスとしてカレントドライブ基準（例 `D:/tmp/ts-lib`）に解決され、
    Git Bash の `/tmp`（= TEMP ディレクトリ）に置いた共有ライブラリを見失う。
    """
    if env is None:
        env = os.environ
    override = env.get("TREE_SITTER_LIBDIR", "").strip()
    if override:
        return override
    if os.name == "nt":
        return str(Path(tempfile.gettempdir()) / LIB_DIR_NAME)
    return POSIX_LIB_DIR


def tree_sitter_command(env=None):
    """実行する tree-sitter CLI のパスを返す。"""
    if env is None:
        env = os.environ
    override = env.get("TREE_SITTER_CLI")
    if override:
        return override

    native_executable = "tree-sitter.exe" if os.name == "nt" else "tree-sitter"
    native_cli = PROJECT_DIR / "node_modules" / "tree-sitter-cli" / native_executable
    if native_cli.is_file():
        return str(native_cli)

    shim_executable = "tree-sitter.cmd" if os.name == "nt" else "tree-sitter"
    local_cli = PROJECT_DIR / "node_modules" / ".bin" / shim_executable
    if local_cli.is_file():
        return str(local_cli)

    return "tree-sitter"


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


def strip_line_ending(text):
    """末尾の 1 行分の改行だけを取り除く。"""
    if text.endswith("\r\n"):
        return text[:-2]
    if text.endswith("\n") or text.endswith("\r"):
        return text[:-1]
    return text


def normalize_tree(tree):
    """AST 比較用に空白・フィールド名・parse 統計行を正規化する。"""
    ast_lines = []
    for line in tree.splitlines():
        if "\tParse:" in line:
            continue
        ast_lines.append(line)
    ast = "\n".join(ast_lines)
    ast = re.sub(r"\b[A-Za-z_][A-Za-z0-9_]*:\s*", "", ast)
    return re.sub(r"\s+", "", ast)


def extract_tests(filepath, include_expected_ast=False):
    """コーパスファイルからテストケースを抽出する。"""
    with open(filepath, encoding="utf-8", newline="") as f:
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
                code_lines.append(lines[i])
                i += 1

            ast_lines = []
            if i < len(lines) and is_separator(lines[i]) == "-":
                i += 1
                while i < len(lines):
                    if is_separator(lines[i]) == "=":
                        break
                    ast_lines.append(strip_line_ending(lines[i]))
                    i += 1

            while code_lines and not code_lines[0].strip():
                code_lines.pop(0)
            while code_lines and not code_lines[-1].strip():
                code_lines.pop()

            code = strip_line_ending("".join(code_lines))
            expected_ast = "\n".join(ast_lines)
            expects_error = "(ERROR" in expected_ast or "(MISSING" in expected_ast
            if code.strip():
                if include_expected_ast:
                    tests.append((name, code, expected_ast, expects_error))
                else:
                    tests.append((name, code, expects_error))
        else:
            i += 1

    return tests


def format_failure_detail(detail):
    """失敗理由を表示用文字列に整形する。"""
    if isinstance(detail, int):
        return f"{detail} errors"
    return str(detail)


def first_cause_line(output):
    """`Caused by:` チェーン先頭の 1 行を返す。無ければ None。

    tree-sitter CLI は真の失敗理由を `Caused by:` 以下に出すため、
    先頭の `Error:` 行だけでは原因が分からない。
    """
    lines = output.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "Caused by:":
            continue
        for cause in lines[index + 1 :]:
            stripped = cause.strip()
            if stripped:
                return re.sub(r"^\d+:\s*", "", stripped)
    return None


def summarize_command_failure(returncode, output):
    """コマンド失敗時の要約を 1 行に整形する。"""
    cause = first_cause_line(output)
    suffix = f" (caused by: {cause})" if cause else ""
    for line in output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Error:"):
            return f"exit {returncode}: {stripped}{suffix}"

    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("at "):
            continue
        if stripped.startswith("Emitted 'error' event"):
            continue
        if stripped.startswith("Node.js v"):
            continue
        return f"exit {returncode}: {stripped}"

    return f"exit {returncode}"


class _GuardedResult:
    """run_with_memory_guard の戻り値。

    subprocess.CompletedProcess 互換 (returncode/stdout/stderr) に
    kill_reason 属性を追加した薄いオブジェクト。kill_reason が文字列のときに
    タイムアウト/メモリ超過などの強制終了を表す。
    """

    __slots__ = ("kill_reason", "returncode", "stderr", "stdout")

    def __init__(self, returncode, stdout, stderr, kill_reason=None):
        """戻り値オブジェクトを構築する。"""
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        self.kill_reason = kill_reason


def _resolve_memory_limit_mb(env=None):
    """環境変数 TS_MEMORY_LIMIT_MB から RSS 上限値 (MB) を解決する。"""
    src = env if env is not None else os.environ
    raw = src.get("TS_MEMORY_LIMIT_MB", "").strip()
    if not raw:
        return DEFAULT_MEMORY_LIMIT_MB
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MEMORY_LIMIT_MB
    if not math.isfinite(value) or value <= 0:
        return DEFAULT_MEMORY_LIMIT_MB
    return value


def _get_rss_mb(pid):
    """指定 PID の RSS を MB 単位で返す。取得不可なら None。"""
    if sys.platform == "win32":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=2,
            )
        except (OSError, subprocess.SubprocessError):
            return None
        if result.returncode != 0:
            return None
        for parts in csv.reader(result.stdout.splitlines()):
            if len(parts) >= 5 and parts[1] == str(pid):
                mem = parts[4].replace(",", "").replace(" K", "").strip()
                try:
                    return int(mem) / 1024.0
                except ValueError:
                    return None
        return None

    try:
        result = subprocess.run(
            ["ps", "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    text = result.stdout.strip()
    if not text:
        return None
    try:
        return int(text) / 1024.0
    except ValueError:
        return None


def _get_process_group_rss_mb(pid):
    """指定 PID と同じプロセスグループの RSS 合計を MB 単位で返す。"""
    if sys.platform == "win32":
        return _get_rss_mb(pid)

    try:
        pgid = os.getpgid(pid)
    except OSError:
        return None

    try:
        result = subprocess.run(
            ["ps", "-ax", "-o", "pgid=", "-o", "rss="],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None

    total_kb = 0
    found = False
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            process_pgid = int(parts[0])
            rss_kb = int(parts[1])
        except ValueError:
            continue
        if process_pgid == pgid:
            total_kb += rss_kb
            found = True

    if not found:
        return None
    return total_kb / 1024.0


def _kill_process_tree(proc):
    """プロセス（およびプロセスグループ）を強制終了する。"""
    if sys.platform == "win32":
        try:
            proc.kill()
        except OSError:
            pass
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    except (OSError, ProcessLookupError):
        try:
            proc.kill()
        except OSError:
            pass


def run_with_memory_guard(
    cmd,
    *,
    timeout,
    memory_limit_mb,
    env,
    poll_interval=POLL_INTERVAL_SECONDS,
):
    """tree-sitter コマンドをメモリ監視付きで実行する。

    poll_interval 秒ごとに RSS を確認し、memory_limit_mb (MB) を超過したら
    プロセスグループごと SIGKILL する。timeout 秒を超えても強制終了する。
    """
    popen_kwargs = {
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "text": True,
        "encoding": "utf-8",
        "errors": "replace",
        "env": env,
    }
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, **popen_kwargs)

    start = time.monotonic()
    kill_reason = None
    stdout = ""
    stderr = ""

    while True:
        elapsed = time.monotonic() - start
        remaining = timeout - elapsed
        if remaining <= 0:
            kill_reason = f"TIMEOUT ({timeout:.0f}s)"
            break

        wait = min(poll_interval, remaining)
        try:
            stdout, stderr = proc.communicate(timeout=wait)
            break
        except subprocess.TimeoutExpired:
            pass

        rss_mb = _get_process_group_rss_mb(proc.pid)
        if rss_mb is not None and rss_mb > memory_limit_mb:
            kill_reason = f"MEMORY_KILL: {rss_mb:.0f}MB > {memory_limit_mb:.0f}MB"
            break

    if kill_reason is not None:
        _kill_process_tree(proc)
        try:
            stdout, stderr = proc.communicate(timeout=10)
        except subprocess.TimeoutExpired:
            _kill_process_tree(proc)
            try:
                stdout, stderr = proc.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                stdout, stderr = "", ""

    return _GuardedResult(proc.returncode, stdout or "", stderr or "", kill_reason)


def _parse_timeout_micros():
    """tree-sitter parse に渡す内部 wallclock タイムアウト (µs) を返す。"""
    return int(PARSE_TIMEOUT_SECONDS * 1_000_000 * 0.8)


def check_tree_sitter_cli(env, command=None):
    """tree-sitter CLI が実行可能か事前に検証する。"""
    if command is None:
        command = tree_sitter_command(env)
    try:
        result = subprocess.run(
            [command, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            env=env,
        )
    except FileNotFoundError:
        return "tree-sitter コマンドが見つかりません。tree-sitter-cli をインストールしてください。"  # noqa: E501
    except subprocess.TimeoutExpired:
        return (
            "tree-sitter CLI の起動確認が 10 秒でタイムアウトしました。"
            " CLI の実体が正常に起動できるか確認してください。"
        )

    if result.returncode == 0:
        return None

    output = result.stdout + result.stderr
    detail = summarize_command_failure(result.returncode, output)
    if "tree-sitter-cli/tree-sitter" in output and "ENOENT" in output:
        return (
            "tree-sitter CLI の実体を起動できません。"
            f" {detail}。"
            "`(cd node_modules/tree-sitter-cli && node install.js)` を実行するか、"
            "build script を承認して再インストールしてください。"
        )
    return f"tree-sitter CLI を起動できません。{detail}"


def main():
    """全コーパステストを実行して結果を返す。"""
    total = 0
    passed = 0
    failed = 0
    failures = []

    configure_stdio_encoding()

    env = {
        **os.environ,
        "TREE_SITTER_LIBDIR": resolve_lib_dir(),
        # 失敗要約が ANSI エスケープ入りの `Error:` 行を取りこぼさないようにする。
        "NO_COLOR": "1",
    }
    command = tree_sitter_command(env)
    setup_error = check_tree_sitter_cli(env, command)
    if setup_error:
        print("\n--- Setup Error ---")
        print(f"  {setup_error}")
        return 2

    if not os.path.isdir(CORPUS_DIR):
        print("\n--- Setup Error ---")
        print(f"  corpus ディレクトリが見つかりません: {CORPUS_DIR}")
        return 2

    memory_limit_mb = _resolve_memory_limit_mb(env)
    parse_timeout_arg = f"--timeout={_parse_timeout_micros()}"

    for fname in sorted(os.listdir(CORPUS_DIR)):
        if fname.startswith(".") or not fname.endswith(".txt"):
            continue
        filepath = os.path.join(CORPUS_DIR, fname)
        if not os.path.isfile(filepath):
            continue
        tests = extract_tests(filepath, include_expected_ast=True)

        for name, code, expected_ast, expects_error in tests:
            total += 1
            tmpfile = None
            try:
                with tempfile.NamedTemporaryFile(
                    mode="w",
                    suffix=".rb",
                    delete=False,
                    encoding="utf-8",
                    # Windows で LF が CRLF に翻訳されると、単独 CR や
                    # バックスラッシュ行継続の回帰ケースが崩れる。
                    newline="",
                ) as f:
                    f.write(code + "\n")
                    tmpfile = f.name

                result = run_with_memory_guard(
                    [command, "parse", "--no-ranges", parse_timeout_arg, tmpfile],
                    timeout=PARSE_TIMEOUT_SECONDS,
                    memory_limit_mb=memory_limit_mb,
                    env=env,
                )

                kill_reason = getattr(result, "kill_reason", None)
                if isinstance(kill_reason, str):
                    failed += 1
                    failures.append((fname, name, kill_reason))
                    continue

                stdout = result.stdout or ""
                stderr = result.stderr or ""
                output = stdout + stderr
                has_error = "(ERROR" in output or "(MISSING" in output
                expected_norm = normalize_tree(expected_ast)
                actual_norm = normalize_tree(output)
                ast_matches = not expected_ast.strip() or actual_norm == expected_norm
                if expects_error:
                    if has_error:
                        passed += 1
                    else:
                        failed += 1
                        failures.append((fname, name, "expected ERROR but parsed OK"))
                elif not has_error and result.returncode == 0 and ast_matches:
                    passed += 1
                else:
                    failed += 1
                    errs = output.count("(ERROR") + output.count("(MISSING")
                    if errs == 0 and result.returncode != 0:
                        detail = summarize_command_failure(result.returncode, output)
                    elif errs == 0 and not ast_matches:
                        detail = "AST mismatch"
                    else:
                        detail = errs
                    failures.append((fname, name, detail))
            finally:
                if tmpfile is not None:
                    try:
                        os.unlink(tmpfile)
                    except OSError:
                        pass

    if failures:
        print("\n--- Failures ---")
        for fname, name, err in failures:
            print(f"  FAIL: {fname} :: {name} ({format_failure_detail(err)})")

    print("\n=== Results ===")
    print(f"Total: {total} | Pass: {passed} | Fail: {failed}")
    return 0 if failed == 0 else 1


def run():
    """CLI エントリーポイントとして main() の終了コードで終了する。"""
    sys.exit(main())


if __name__ == "__main__":
    run()
