"""同じ入力集合の検証と、別プロセスでの交互測定を実行する。Python 3.7 以降。"""

import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
import queue
import statistics
import subprocess
import sys
import threading
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[2]
GUARD_SPEC = importlib.util.spec_from_file_location(
    "ruby_benchmark_corpus_guard", PROJECT / "scripts" / "corpus_test.py"
)
corpus_test = importlib.util.module_from_spec(GUARD_SPEC)
GUARD_SPEC.loader.exec_module(corpus_test)

CORPORA = [
    "ruby_ruby",
    "rubocop_rubocop",
    "Homebrew_brew",
    "rails_rails",
    "mastodon_mastodon",
]


def write_json(path, value):
    """集計値をUTF-8で保存する。"""
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def git(root, *args):
    """検証用ソースのGit状態を読み取る。"""
    result = subprocess.run(
        ["git", "-C", str(root)] + list(args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def manifest(root, output):
    """全入力の相対パス・サイズ・ハッシュと取得元の版を固定する。"""
    snapshots = {}
    with (output / "manifest.jsonl").open(
        "w", encoding="utf-8", newline="\n"
    ) as stream:
        for corpus in CORPORA:
            directory = root / corpus
            if not directory.is_dir():
                raise RuntimeError("Missing corpus: " + corpus)
            source_sha = directory / ".source_sha"
            files = sorted(
                p
                for p in directory.rglob("*.rb")
                if ".git" not in p.relative_to(directory).parts and p.is_file()
            )
            if not files:
                raise RuntimeError("Empty corpus: " + corpus)
            snapshots[corpus] = {
                "head": git(directory, "rev-parse", "HEAD"),
                "source_sha": source_sha.read_text(encoding="utf-8").strip()
                if source_sha.exists()
                else None,
                "status": git(directory, "status", "--porcelain"),
                "files": len(files),
            }
            for path in files:
                source = path.read_bytes()
                stream.write(
                    json.dumps(
                        {
                            "corpus": corpus,
                            "path": path.relative_to(directory).as_posix(),
                            "bytes": len(source),
                            "sha256": hashlib.sha256(source).hexdigest(),
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    write_json(output / "snapshots.json", snapshots)


def validate(binary, root, output, label):
    """両者の受理と木のハッシュを保存し、共通集合の退行を拒否する。"""
    result = corpus_test.run_with_memory_guard(
        [str(binary), "validate", str(output / "manifest.jsonl"), str(root)],
        timeout=600,
        memory_limit_mb=6144,
        env=os.environ.copy(),
    )
    (output / (label + "-validation.jsonl")).write_text(result.stdout, encoding="utf-8")
    if result.returncode or result.kill_reason:
        raise RuntimeError(str(result.kill_reason) + " " + result.stderr)
    rows = [json.loads(line) for line in result.stdout.splitlines()]
    manifest_rows = [
        json.loads(line)
        for line in (output / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    if [(r["corpus"], r["path"]) for r in rows] != [
        (r["corpus"], r["path"]) for r in manifest_rows
    ]:
        raise RuntimeError("Validation input mismatch")
    common = {
        (r["corpus"], r["path"])
        for r in rows
        if not r["ts_errors"] and not r["ts_missing"] and not r["prism_errors"]
    }
    common_path = output / "common.jsonl"
    if common_path.exists():
        fixed = {
            (r["corpus"], r["path"])
            for r in map(
                json.loads, common_path.read_text(encoding="utf-8").splitlines()
            )
        }
        if not fixed or not fixed.issubset(common):
            raise RuntimeError("Regression in fixed common input set")
    if not common_path.exists():
        common_path.write_text(
            "".join(
                json.dumps(r, ensure_ascii=False) + "\n"
                for r in manifest_rows
                if (r["corpus"], r["path"]) in common
            ),
            encoding="utf-8",
        )
    summary = {}
    for corpus in CORPORA:
        selected = [r for r in rows if r["corpus"] == corpus]
        summary[corpus] = {
            "files": len(selected),
            "bytes": sum(r["bytes"] for r in selected),
            "ts_failures": sum(
                bool(r["ts_errors"] or r["ts_missing"]) for r in selected
            ),
            "prism_failures": sum(bool(r["prism_errors"]) for r in selected),
            "common": sum((r["corpus"], r["path"]) in common for r in selected),
        }
    write_json(output / (label + "-validation-summary.json"), summary)
    print(json.dumps(summary, indent=2))


def reader(process, messages):
    """子プロセスの出力を期限付きで受け取れるキューへ転送する。"""
    try:
        for line in process.stdout:
            messages.put(line)
    finally:
        messages.put(None)


def memory_guard(process, stop):
    """応答待ちの間も上限を監視し、過剰なメモリ使用で測定を続けない。"""
    if sys.platform != "win32":
        return

    # PROCESS_MEMORY_COUNTERS の DWORD 2 個と SIZE_T 8 個。
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [
            (name, ctypes.c_size_t)
            for name in (
                "peak_rss",
                "rss",
                "peak_paged",
                "paged",
                "peak_nonpaged",
                "nonpaged",
                "commit",
                "peak_commit",
            )
        ]

    query = ctypes.WinDLL("psapi").GetProcessMemoryInfo
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(Counters), ctypes.c_ulong]
    query.restype = ctypes.c_int
    while not stop.wait(0.5):
        counters = Counters()
        counters.cb = ctypes.sizeof(counters)
        if (
            query(int(process._handle), ctypes.byref(counters), counters.cb)
            and max(counters.rss, counters.commit) > 6 * 1024**3
        ):
            process.kill()
            return


def bench(binary, root, output, label, reverse, control_binary=None):
    """独立したプロセスを交互に動かし、反復ごとの全体時間から集計する。"""
    processes = {}
    queues = {}
    rows = []
    stop = threading.Event()
    engines = ["ts", "prism"] + (["control"] if control_binary else [])
    try:
        for engine in engines:
            executable = control_binary if engine == "control" else binary
            implementation = "ts" if engine == "control" else engine
            process = subprocess.Popen(
                [
                    str(executable),
                    "serve",
                    str(output / "common.jsonl"),
                    str(root),
                    implementation,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            processes[engine] = process
            queues[engine] = queue.Queue()
            threading.Thread(
                target=memory_guard, args=(process, stop), daemon=True
            ).start()
            threading.Thread(
                target=reader, args=(process, queues[engine]), daemon=True
            ).start()
        for iteration in range(9):
            order = (
                engines if (iteration + reverse) % 2 == 0 else list(reversed(engines))
            )
            for engine in order:
                process = processes[engine]
                process.stdin.write(str(iteration) + "\n")
                process.stdin.flush()
                count = 0
                while True:
                    # 最初の応答待ちには全入力の読み込みも含む。計測前の準備を待つ。
                    line = queues[engine].get(timeout=600 if iteration == 0 else 60)
                    if line is None:
                        raise RuntimeError("Benchmark exited: " + engine)
                    if line.strip() == "DONE":
                        break
                    row = json.loads(line)
                    row["engine"] = engine
                    memory = row["memory"]
                    if memory and max(memory.values()) > 6 * 1024**3:
                        raise RuntimeError("Memory limit exceeded: " + engine)
                    row["warmup"] = iteration < 2
                    rows.append(row)
                    count += 1
                if count != len(CORPORA):
                    raise RuntimeError("Missing benchmark corpus")
            print("round", iteration, "done", flush=True)
    finally:
        stop.set()
        for process in processes.values():
            if process.poll() is None:
                process.stdin.close()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        (output / (label + "-timings.jsonl")).write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8"
        )
    summary = {}
    for corpus in (
        ["rails_rails"] + [c for c in CORPORA if c != "rails_rails"] + ["total"]
    ):
        summary[corpus] = {}
        for engine in engines:
            samples = []
            cpus = []
            for iteration in range(2, 9):
                selected = [
                    r
                    for r in rows
                    if r["round"] == iteration
                    and r["engine"] == engine
                    and (corpus == "total" or r["corpus"] == corpus)
                ]
                samples.append(sum(r["wall_ns"] for r in selected) / 1e6)
                cpus.append(sum(r["cpu_ns"] for r in selected) / 1e6)
            summary[corpus][engine] = {
                "median_ms": statistics.median(samples),
                "min_ms": min(samples),
                "max_ms": max(samples),
                "cpu_median_ms": statistics.median(cpus),
            }
        summary[corpus]["prism_over_ts"] = (
            summary[corpus]["prism"]["median_ms"] / summary[corpus]["ts"]["median_ms"]
        )
    write_json(output / (label + "-summary.json"), summary)
    print(json.dumps(summary, indent=2))


def main():
    """マニフェスト作成・検証・測定の指定された処理を実行する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["manifest", "validate", "bench"])
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--binary", type=Path)
    parser.add_argument("--label", default="baseline")
    parser.add_argument("--reverse", type=int, default=0)
    parser.add_argument("--control-binary", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    if args.mode == "manifest":
        manifest(args.source_root, args.output)
    elif args.mode == "validate":
        validate(args.binary, args.source_root, args.output, args.label)
    else:
        bench(
            args.binary,
            args.source_root,
            args.output,
            args.label,
            args.reverse,
            args.control_binary,
        )


if __name__ == "__main__":
    main()
