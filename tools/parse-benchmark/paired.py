"""2 つのハーネスを同じ論理 CPU で短く交互に動かし、組ごとの時間の比を集計する。

Windows 専用。他の処理と同居するデスクトップでは、反復ごとの所要時間が数十 % 揺れ、
長い反復を順に比べても小さな差を判別できない。候補と対照の `serve` を同じ論理 CPU と
高い優先度に固定し、入力の部分集合を 1 反復ずつ「候補 → 対照」「対照 → 候補」の順で
交互に測る。隣り合う 2 回の比 (候補 ÷ 対照、1 未満が候補の高速) の中央値と、
固定した seed のブートストラップによる中央値の 95% 区間を保存する。

    python paired.py --candidate <exe> --control <exe> --manifest <subset.jsonl>
        --source-root <dir> --pairs 30 --cpu 6 --output <paired.json>
"""

import argparse
import ctypes
import json
import random
import statistics
import subprocess
import time

HIGH_PRIORITY_CLASS = 0x80
PROCESS_SET_INFORMATION = 0x200
PROCESS_QUERY_INFORMATION = 0x400
WARMUP_ROUNDS = 2
BOOTSTRAP_SAMPLES = 5000
BOOTSTRAP_SEED = 20261030


def _start(binary, manifest, root, cpu):
    """`serve` を起動し、指定した論理 CPU と高い優先度に固定する。

    Returns:
        起動したプロセス。

    Raises:
        OSError: プロセスの優先度か論理 CPU を設定できなかったとき。

    """
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel32.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    process = subprocess.Popen(
        [binary, "serve", manifest, root, "ts"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
    )
    handle = kernel32.OpenProcess(
        PROCESS_SET_INFORMATION | PROCESS_QUERY_INFORMATION, False, process.pid
    )
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenProcess failed")
    try:
        if not kernel32.SetPriorityClass(handle, HIGH_PRIORITY_CLASS):
            raise OSError(ctypes.get_last_error(), "SetPriorityClass failed")
        if not kernel32.SetProcessAffinityMask(handle, 1 << cpu):
            raise OSError(ctypes.get_last_error(), "SetProcessAffinityMask failed")
    finally:
        kernel32.CloseHandle(handle)
    return process


def _run_round(process, round_number):
    """1 反復を測り、全コーパスの実時間と CPU 時間の合計を求める。

    Returns:
        (実時間 ns, CPU 時間 ns, コーパス別の実時間 ns) の組。

    Raises:
        RuntimeError: 測定が終わる前にハーネスが終了したとき。

    """
    process.stdin.write(f"{round_number}\n")
    process.stdin.flush()
    wall = cpu = 0
    corpora = {}
    while True:
        line = process.stdout.readline()
        if not line:
            raise RuntimeError("Benchmark exited")
        if line.strip() == "DONE":
            return wall, cpu, corpora
        row = json.loads(line)
        wall += row["wall_ns"]
        cpu += row["cpu_ns"]
        corpora[row["corpus"]] = row["wall_ns"]


def _summarize(samples):
    """組ごとの比から中央値・範囲・ブートストラップ区間を求める。

    Returns:
        集計値の辞書。

    """
    ratios = [s["candidate_wall_ns"] / s["control_wall_ns"] for s in samples]
    rng = random.Random(BOOTSTRAP_SEED)
    boot = sorted(
        statistics.median(rng.choices(ratios, k=len(ratios)))
        for _ in range(BOOTSTRAP_SAMPLES)
    )
    return {
        "pairs": len(samples),
        "ratio_median": statistics.median(ratios),
        "ratio_mean": statistics.mean(ratios),
        "ratio_min": min(ratios),
        "ratio_max": max(ratios),
        "ratio_median_ci95": [
            boot[int(0.025 * BOOTSTRAP_SAMPLES)],
            boot[int(0.975 * BOOTSTRAP_SAMPLES) - 1],
        ],
        "candidate_faster_pairs": sum(r < 1 for r in ratios),
        "candidate_median_ms": statistics.median(
            s["candidate_wall_ns"] for s in samples
        )
        / 1e6,
        "control_median_ms": statistics.median(s["control_wall_ns"] for s in samples)
        / 1e6,
    }


def main():
    """候補と対照を交互に測り、組ごとの生データと集計を保存する。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate", required=True)
    parser.add_argument("--control", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--pairs", type=int, default=30)
    parser.add_argument("--cpu", type=int, default=6)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    processes = {
        name: _start(binary, args.manifest, args.source_root, args.cpu)
        for name, binary in (("candidate", args.candidate), ("control", args.control))
    }
    samples = []
    try:
        for round_number in range(WARMUP_ROUNDS):
            for process in processes.values():
                _run_round(process, round_number)
        started = time.perf_counter()
        for pair in range(args.pairs):
            order = (
                ("candidate", "control") if pair % 2 == 0 else ("control", "candidate")
            )
            result = {
                name: _run_round(processes[name], WARMUP_ROUNDS + pair)
                for name in order
            }
            samples.append(
                {
                    "pair": pair,
                    "order": list(order),
                    "candidate_wall_ns": result["candidate"][0],
                    "control_wall_ns": result["control"][0],
                    "candidate_cpu_ns": result["candidate"][1],
                    "control_cpu_ns": result["control"][1],
                    "candidate_corpora": result["candidate"][2],
                    "control_corpora": result["control"][2],
                }
            )
        elapsed = time.perf_counter() - started
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.stdin.close()
                try:
                    process.wait(timeout=60)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()

    summary = _summarize(samples)
    summary.update({"cpu": args.cpu, "elapsed_s": elapsed})
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(
            {"summary": summary, "samples": samples},
            stream,
            ensure_ascii=False,
            indent=1,
        )
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
