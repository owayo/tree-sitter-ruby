"""依存版を変更せず、2つのCargo.lockの自パッケージ版を同期する。"""

import re
from pathlib import Path


def package_version(manifest):
    """ルートのpackage節から、引用符付きのversionを1つだけ読む。

    Returns:
        自パッケージのバージョン文字列。

    Raises:
        ValueError: package節のversionが一意に決まらない場合。

    """
    section = re.search(r"(?ms)^\[package\]\r?\n(.*?)(?=^\[|\Z)", manifest)
    versions = (
        re.findall(r'^version = "([^"\r\n]+)"\r?$', section.group(1), re.MULTILINE)
        if section
        else []
    )
    if len(versions) != 1:
        raise ValueError("Expected one package version in Cargo.toml")
    return versions[0]


def update_lock(lock, version):
    """path依存のtree-sitter-rubyのversionだけを置き換える。

    Returns:
        他の依存版と改行を保持したlockの内容。

    Raises:
        ValueError: 対象が一意でないか、ローカルパッケージでない場合。

    """
    sections = list(re.finditer(r"(?ms)^\[\[package\]\]\r?\n.*?(?=^\[|\Z)", lock))
    packages = [
        section
        for section in sections
        if re.search(r'^name = "tree-sitter-ruby"\r?$', section.group(), re.MULTILINE)
    ]
    if len(packages) != 1:
        raise ValueError("Expected one tree-sitter-ruby package in Cargo.lock")
    package = packages[0]
    if re.search(r"^source =", package.group(), re.MULTILINE):
        raise ValueError("Expected a local tree-sitter-ruby package")
    updated, count = re.subn(
        r'(?m)^(version = ")[^"\r\n]+("\r?$)',
        lambda match: match.group(1) + version + match.group(2),
        package.group(),
    )
    if count != 1:
        raise ValueError("Expected one tree-sitter-ruby version in Cargo.lock")
    return lock[: package.start()] + updated + lock[package.end() :]


def sync_lock_versions(root):
    """両lockを検証し終えてから書き込み、入力不備での片側だけの更新を防ぐ。"""
    version = package_version((root / "Cargo.toml").read_bytes().decode("utf-8"))
    updates = []
    for relative in ["Cargo.lock", "tools/parse-benchmark/Cargo.lock"]:
        path = root / relative
        original = path.read_bytes().decode("utf-8")
        updates.append((path, update_lock(original, version).encode("utf-8")))
    for path, contents in updates:
        path.write_bytes(contents)


if __name__ == "__main__":
    sync_lock_versions(Path(__file__).resolve().parents[1])
