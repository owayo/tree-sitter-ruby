"""原本を変更せず、Windows 用スキャナー計測バイナリを作る。"""

import argparse
import shutil
import subprocess
from pathlib import Path


def main():
    """新しいコピーへだけカウンターを挿入し、Releaseでビルドする。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    project = Path(__file__).resolve().parents[2]
    destination = args.destination.resolve()
    if destination.exists():
        raise RuntimeError("Destination must be a new directory")
    source_copy = destination / "grammar"
    source_copy.mkdir(parents=True)
    shutil.copytree(project / "src", source_copy / "src")
    shutil.copytree(project / "queries", source_copy / "queries")
    shutil.copytree(project / "bindings" / "rust", source_copy / "bindings" / "rust")
    shutil.copy2(project / "Cargo.toml", source_copy / "Cargo.toml")
    scanner = source_copy / "src" / "scanner.c"
    text = scanner.read_text(encoding="utf-8")
    text = (
        (project / "tools" / "parse-benchmark" / "scanner_profile.h").read_text(
            encoding="utf-8"
        )
        + "\n"
        + text
    )
    for phase, expression in enumerate(
        (
            "return scan(scanner, lexer, valid_symbols);",
            "return serialize(scanner, buffer);",
            "deserialize(scanner, buffer, length);",
        )
    ):
        if text.count(expression) != 1:
            raise RuntimeError("Instrumentation site changed: " + expression)
        start = f"profile_phase = {phase}; profile_calls[{phase}]++; uint64_t begin = profile_clock();\n"
        if phase == 0:
            body = "bool result = scan(scanner, lexer, valid_symbols);"
        elif phase == 1:
            body = "unsigned result = serialize(scanner, buffer);"
        else:
            body = expression
        finish = (
            f"\nprofile_ticks[{phase}] += profile_clock() - begin; profile_phase = 3;"
        )
        if phase != 2:
            finish += " return result;"
        text = text.replace(expression, start + body + finish)
    scanner.write_text(text, encoding="utf-8")
    harness = destination / "harness"
    shutil.copytree(project / "tools" / "parse-benchmark" / "src", harness / "src")
    shutil.copy2(
        project / "tools" / "parse-benchmark" / "Cargo.lock", harness / "Cargo.lock"
    )
    manifest = (project / "tools" / "parse-benchmark" / "Cargo.toml").read_text(
        encoding="utf-8"
    )
    (harness / "Cargo.toml").write_text(
        manifest.replace('path = "../.."', 'path = "../grammar"'), encoding="utf-8"
    )
    log = destination / "build.log"
    with log.open("w", encoding="utf-8") as stream:
        result = subprocess.run(
            [
                "cargo",
                "build",
                "--release",
                "--locked",
                "--manifest-path",
                str(harness / "Cargo.toml"),
            ],
            stdout=stream,
            stderr=subprocess.STDOUT,
            check=False,
        )
    if result.returncode:
        raise RuntimeError("Build failed; inspect " + str(log))
    print(harness / "target" / "release" / "ruby-parse-benchmark.exe")


if __name__ == "__main__":
    main()
