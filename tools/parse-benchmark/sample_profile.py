"""計測ハーネスの主スレッドの命令位置を採取し、関数別の CPU 割合を集計する。

Windows 専用。管理者権限の要る ETW (WPR) を使わず、同じユーザーのプロセスに対して
SuspendThread / GetThreadContext / ResumeThread で RIP を読み、dbghelp で PDB から
関数名を引く。数えるのは採取した時点の最内の関数だけで、呼び出し先を含む時間ではない。
入力の読み込みと最初の 1 反復は採取しない。
PDB のない DLL の関数名は、最寄りのエクスポート名になる。

    python sample_profile.py --binary <exe> --manifest <common.jsonl>
        --source-root <dir> --rounds 2 --output <profile.json>
"""

import argparse
import collections
import ctypes
import json
import os
import subprocess
import threading
import time
from ctypes import wintypes

TH32CS_SNAPTHREAD = 0x4
THREAD_SUSPEND_RESUME = 0x2
THREAD_GET_CONTEXT = 0x8
THREAD_QUERY_INFORMATION = 0x40
PROCESS_QUERY_INFORMATION = 0x400
PROCESS_VM_READ = 0x10
# x64 の CONTEXT 構造体: 16 バイト境界・全体 1232 バイト、ContextFlags と Rip の位置。
CONTEXT_CONTROL = 0x00100001
CONTEXT_SIZE = 1232
CONTEXT_FLAGS_OFFSET = 0x30
CONTEXT_RIP_OFFSET = 0xF8
# C の sizeof(SYMBOL_INFOW)。末尾の Name[1] までを含む。
SYMBOL_INFO_SIZE = 88
SYMOPT_UNDNAME = 0x2
SYMOPT_DEFERRED_LOADS = 0x4
SAMPLE_INTERVAL_SECONDS = 0.001


class _ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.DWORD),
        ("usage", wintypes.DWORD),
        ("thread_id", wintypes.DWORD),
        ("process_id", wintypes.DWORD),
        ("base_priority", ctypes.c_long),
        ("delta_priority", ctypes.c_long),
        ("flags", wintypes.DWORD),
    ]


class _SymbolInfo(ctypes.Structure):
    _fields_ = [
        ("size", wintypes.ULONG),
        ("type_index", wintypes.ULONG),
        ("reserved", ctypes.c_uint64 * 2),
        ("index", wintypes.ULONG),
        ("symbol_size", wintypes.ULONG),
        ("module_base", ctypes.c_uint64),
        ("flags", wintypes.ULONG),
        ("value", ctypes.c_uint64),
        ("address", ctypes.c_uint64),
        ("register", wintypes.ULONG),
        ("scope", wintypes.ULONG),
        ("tag", wintypes.ULONG),
        ("name_length", wintypes.ULONG),
        ("max_name_length", wintypes.ULONG),
        ("name", wintypes.WCHAR * 512),
    ]


class _ModuleInfo(ctypes.Structure):
    _fields_ = [
        ("base", ctypes.c_void_p),
        ("size", wintypes.DWORD),
        ("entry_point", ctypes.c_void_p),
    ]


def _win32():
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    kernel32.OpenThread.restype = wintypes.HANDLE
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.SuspendThread.argtypes = [wintypes.HANDLE]
    kernel32.ResumeThread.argtypes = [wintypes.HANDLE]
    kernel32.GetThreadContext.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    kernel32.GetThreadTimes.argtypes = [wintypes.HANDLE] + [
        ctypes.POINTER(ctypes.c_uint64)
    ] * 4
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    psapi.EnumProcessModulesEx.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.HMODULE),
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.DWORD,
    ]
    psapi.GetModuleBaseNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.HMODULE,
        wintypes.LPWSTR,
        wintypes.DWORD,
    ]
    psapi.GetModuleInformation.argtypes = [
        wintypes.HANDLE,
        wintypes.HMODULE,
        ctypes.POINTER(_ModuleInfo),
        wintypes.DWORD,
    ]
    dbghelp = ctypes.WinDLL("dbghelp", use_last_error=True)
    dbghelp.SymSetOptions.argtypes = [wintypes.DWORD]
    dbghelp.SymInitializeW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.BOOL]
    dbghelp.SymFromAddrW.argtypes = [
        wintypes.HANDLE,
        ctypes.c_uint64,
        ctypes.POINTER(ctypes.c_uint64),
        ctypes.POINTER(_SymbolInfo),
    ]
    dbghelp.SymCleanup.argtypes = [wintypes.HANDLE]
    return kernel32, psapi, dbghelp


def _busiest_thread(kernel32, pid):
    """CPU 時間が最も長いスレッド (パースする主スレッド) を探す。

    Returns:
        スレッド ID。対象のプロセスにスレッドがなければ None。

    Raises:
        OSError: スレッドのスナップショットが得られない場合。

    """
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPTHREAD, 0)
    if not snapshot or snapshot == ctypes.c_void_p(-1).value:
        raise OSError("Cannot enumerate benchmark threads")
    entry = _ThreadEntry()
    entry.size = ctypes.sizeof(entry)
    best_id, best_time = None, -1
    try:
        found = kernel32.Thread32First(snapshot, ctypes.byref(entry))
        while found:
            if entry.process_id == pid:
                handle = kernel32.OpenThread(
                    THREAD_QUERY_INFORMATION, False, entry.thread_id
                )
                if handle:
                    try:
                        times = [ctypes.c_uint64() for _ in range(4)]
                        if kernel32.GetThreadTimes(
                            handle, *(ctypes.byref(t) for t in times)
                        ):
                            used = times[2].value + times[3].value
                            if used > best_time:
                                best_id, best_time = entry.thread_id, used
                    finally:
                        kernel32.CloseHandle(handle)
            found = kernel32.Thread32Next(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return best_id


def _modules(psapi, process):
    """読み込まれたモジュールを列挙する。

    Returns:
        モジュールごとの (先頭アドレス, 大きさ, 名前) のリスト。

    """
    handles = (wintypes.HMODULE * 1024)()
    needed = wintypes.DWORD()
    psapi.EnumProcessModulesEx(
        process, handles, ctypes.sizeof(handles), ctypes.byref(needed), 3
    )
    result = []
    for handle in handles[: needed.value // ctypes.sizeof(wintypes.HMODULE)]:
        name = ctypes.create_unicode_buffer(260)
        psapi.GetModuleBaseNameW(process, handle, name, 260)
        info = _ModuleInfo()
        psapi.GetModuleInformation(
            process, handle, ctypes.byref(info), ctypes.sizeof(info)
        )
        result.append((info.base or 0, info.size, name.value))
    return result


def _wait_done(process):
    """完了応答を待ち、応答前の EOF を測定失敗として返す。

    Raises:
        RuntimeError: 完了応答を受け取る前に標準出力が閉じた場合。

    """
    while True:
        line = process.stdout.readline()
        if not line:
            raise RuntimeError(
                f"Benchmark closed stdout before DONE (exit code: {process.poll()})"
            )
        if line.strip() == "DONE":
            return


def _drive(process, rounds, done, errors):
    """終了通知を必ず行い、駆動スレッドの失敗を採取側へ渡す。"""
    try:
        for round_number in range(1, rounds + 1):
            process.stdin.write(f"{round_number}\n")
            process.stdin.flush()
            _wait_done(process)
    except BaseException as error:  # noqa: BLE001 - 主スレッドで同じ例外を送出する。
        errors.append(error)
    finally:
        done.set()


def _stop_process(process):
    """失敗・中断時も子プロセスを回収してパイプを閉じる。"""
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
    finally:
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass


def _sample(process, thread, rounds, kernel32, winmm):
    """採取中の例外でも停止したスレッドとタイマーを元に戻す。

    Returns:
        命令位置ごとの標本数と、採取した秒数。

    """
    buffer = ctypes.create_string_buffer(CONTEXT_SIZE + 16)
    context = (ctypes.addressof(buffer) + 15) & ~15
    counts = collections.Counter()
    done = threading.Event()
    errors = []
    driver = threading.Thread(target=_drive, args=(process, rounds, done, errors))
    timer_started = winmm.timeBeginPeriod(1) == 0
    started = time.perf_counter()
    try:
        driver.start()
        while not done.is_set():
            if kernel32.SuspendThread(thread) != 0xFFFFFFFF:
                try:
                    ctypes.c_uint32.from_address(
                        context + CONTEXT_FLAGS_OFFSET
                    ).value = CONTEXT_CONTROL
                    if kernel32.GetThreadContext(thread, ctypes.c_void_p(context)):
                        counts[
                            ctypes.c_uint64.from_address(
                                context + CONTEXT_RIP_OFFSET
                            ).value
                        ] += 1
                finally:
                    kernel32.ResumeThread(thread)
            time.sleep(SAMPLE_INTERVAL_SECONDS)
        driver.join()
        if errors:
            raise errors[0]
        return counts, time.perf_counter() - started
    except BaseException:
        _stop_process(process)
        raise
    finally:
        try:
            if driver.ident is not None:
                driver.join(timeout=5)
        finally:
            if timer_started:
                winmm.timeEndPeriod(1)


def _resolve_counts(counts, process, binary, kernel32, psapi, dbghelp):
    """関数名の解決に使うプロセスハンドルとシンボル情報を解放する。

    Returns:
        関数別とモジュール別の標本数。

    Raises:
        OSError: 対象のプロセスやシンボル情報を開けない場合。

    """
    target = kernel32.OpenProcess(
        PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, process.pid
    )
    if not target:
        raise OSError("Cannot open benchmark process for symbol lookup")
    initialized = False
    try:
        modules = _modules(psapi, target)
        dbghelp.SymSetOptions(SYMOPT_UNDNAME | SYMOPT_DEFERRED_LOADS)
        initialized = bool(
            dbghelp.SymInitializeW(
                target, os.path.dirname(os.path.abspath(binary)), True
            )
        )
        if not initialized:
            raise OSError("Cannot initialize benchmark symbols")
        by_function = collections.Counter()
        by_module = collections.Counter()
        symbol = _SymbolInfo()
        displacement = ctypes.c_uint64()
        for address, count in counts.items():
            module = next(
                (name for base, size, name in modules if base <= address < base + size),
                "?",
            )
            by_module[module] += count
            symbol.size = SYMBOL_INFO_SIZE
            symbol.max_name_length = 511
            resolved = dbghelp.SymFromAddrW(
                target, address, ctypes.byref(displacement), ctypes.byref(symbol)
            )
            by_function["{}!{}".format(module, symbol.name if resolved else "?")] += (
                count
            )
        return by_function, by_module
    finally:
        try:
            if initialized:
                dbghelp.SymCleanup(target)
        finally:
            kernel32.CloseHandle(target)


def main():
    """ハーネスを起動して採取し、関数別・モジュール別の割合を保存する。

    Raises:
        OSError: 採取するスレッドや必要なハンドルが得られない場合。

    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--source-root", required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    kernel32, psapi, dbghelp = _win32()
    winmm = ctypes.WinDLL("winmm")

    process = subprocess.Popen(
        [args.binary, "serve", args.manifest, args.source_root, "ts"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        encoding="utf-8",
    )
    try:
        process.stdin.write("0\n")
        process.stdin.flush()
        _wait_done(process)
        thread_id = _busiest_thread(kernel32, process.pid)
        if thread_id is None:
            raise OSError("Benchmark has no thread to sample")
        thread = kernel32.OpenThread(
            THREAD_SUSPEND_RESUME | THREAD_GET_CONTEXT, False, thread_id
        )
        if not thread:
            raise OSError("Cannot open benchmark thread for sampling")
        try:
            counts, elapsed = _sample(process, thread, args.rounds, kernel32, winmm)
        finally:
            kernel32.CloseHandle(thread)
        by_function, by_module = _resolve_counts(
            counts, process, args.binary, kernel32, psapi, dbghelp
        )
    finally:
        _stop_process(process)

    samples = sum(counts.values())
    with open(args.output, "w", encoding="utf-8") as stream:
        json.dump(
            {
                "samples": samples,
                "elapsed_s": elapsed,
                "rounds": args.rounds,
                "by_module": by_module.most_common(),
                "by_function": by_function.most_common(100),
            },
            stream,
            ensure_ascii=False,
            indent=1,
        )
    print(f"samples={samples} elapsed={elapsed:.1f}s")
    for name, count in by_function.most_common(40):
        print(f"{100.0 * count / samples:6.2f}%  {name}")


if __name__ == "__main__":
    main()
