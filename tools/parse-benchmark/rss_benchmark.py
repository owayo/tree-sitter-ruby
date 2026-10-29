"""Windows の RSS 監視だけを、同じ停止中の子プロセスで交互に測定する。"""

import argparse
import ctypes
import hashlib
import importlib.util
import json
import platform
import statistics
import subprocess
import sys
import time
from pathlib import Path


def load(path, name):
    """指定した版のランナーを独立したモジュールとして読み込む。

    Returns:
        読み込んだランナーのモジュール。

    """
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def handle_count():
    """測定側のハンドル数を取得し、繰り返しによるリークを確認する。

    Returns:
        現在のプロセスが保持するハンドル数。

    Raises:
        OSError: Windows API による取得が失敗した場合。

    """
    api = ctypes.WinDLL("kernel32")
    current = api.GetCurrentProcess
    current.restype = ctypes.c_void_p
    query = api.GetProcessHandleCount
    query.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
    query.restype = ctypes.c_int
    count = ctypes.c_uint32()
    if not query(current(), ctypes.byref(count)):
        raise OSError("GetProcessHandleCount failed")
    return count.value


def main():
    """ウォームアップ後に順番を反転して、時間・CPU・RSS の生値を保存する。

    Raises:
        RuntimeError: 測定対象の準備や RSS の取得に失敗した場合。

    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("Windows の API と tasklist を比較するため Windows が必要")
    candidate = Path(__file__).resolve().parents[2] / "scripts/corpus_test.py"
    modules = {
        "baseline": load(args.baseline, "rss_baseline"),
        "candidate": load(candidate, "rss_candidate"),
    }
    rows = []
    with subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-c",
            (
                "import time; data=bytearray(64*1024*1024); "
                "print('ready'); time.sleep(300)"
            ),
        ],
        stdout=subprocess.PIPE,
        text=True,
    ) as process:
        try:
            if process.stdout.readline().strip() != "ready":
                raise RuntimeError("測定対象を準備できない")
            for name, module in modules.items():
                if module._get_rss_mb(process.pid) is None and name == "candidate":
                    raise RuntimeError("RSS を取得できない")
            handles_before = handle_count()
            for iteration in range(11):
                order = list(modules)
                if iteration % 2:
                    order.reverse()
                for name in order:
                    start_cpu = time.process_time_ns()
                    start = time.perf_counter_ns()
                    rss = modules[name]._get_rss_mb(process.pid)
                    elapsed = time.perf_counter_ns() - start
                    cpu = time.process_time_ns() - start_cpu
                    if rss is None and name == "candidate":
                        raise RuntimeError("測定中に RSS を取得できなくなった")
                    rows.append(
                        {
                            "round": iteration,
                            "engine": name,
                            "wall_ms": elapsed / 1e6,
                            "cpu_ms": cpu / 1e6,
                            "rss_mb": rss,
                        }
                    )
            for _ in range(200):
                modules["candidate"]._get_rss_mb(process.pid)
            handles_after = handle_count()
        finally:
            process.kill()
            process.wait(timeout=5)
    result = {
        "python": sys.version,
        "platform": platform.platform(),
        "baseline_sha256": hashlib.sha256(args.baseline.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "warmup": "one RSS query per implementation",
        "unavailable": (
            "null RSS includes baseline command timeout; kept in wall samples"
        ),
        "target": "one idle Python process holding a 64 MiB bytearray",
        "handles_before": handles_before,
        "handles_after_200_extra_candidate_queries": handles_after,
        "samples": rows,
        "summary": {},
    }
    for name in modules:
        samples = [row["wall_ms"] for row in rows if row["engine"] == name]
        result["summary"][name] = {
            "median_ms": statistics.median(samples),
            "min_ms": min(samples),
            "max_ms": max(samples),
            "cpu_median_ms": statistics.median(
                row["cpu_ms"] for row in rows if row["engine"] == name
            ),
            "successful_queries": sum(
                row["rss_mb"] is not None for row in rows if row["engine"] == name
            ),
        }
    result["reduction_percent"] = 100 * (
        1
        - result["summary"]["candidate"]["median_ms"]
        / result["summary"]["baseline"]["median_ms"]
    )
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
