"""リリース時の自パッケージ版同期と、他の依存版・改行の保持を検証する。"""

import tempfile
import unittest
from pathlib import Path

from sync_lock_versions import package_version, sync_lock_versions, update_lock

LOCK = """version = 4

[[package]]
name = "cc"
version = "1.10.0"
source = "registry+https://github.com/rust-lang/crates.io-index"

[[package]]
name = "tree-sitter-ruby"
version = "26.10.105"
dependencies = [
 "cc",
]

[[package]]
name = "tree-sitter"
version = "0.27.1"
"""


class SyncLockVersionsTests(unittest.TestCase):
    def test_repository_locks_match_the_manifest(self):
        root = Path(__file__).resolve().parents[1]
        version = package_version((root / "Cargo.toml").read_text(encoding="utf-8"))
        for relative in ["Cargo.lock", "tools/parse-benchmark/Cargo.lock"]:
            lock = (root / relative).read_bytes().decode("utf-8")
            with self.subTest(path=relative):
                self.assertEqual(lock, update_lock(lock, version))

    def test_updates_only_local_package_and_preserves_line_endings(self):
        for newline in ["\n", "\r\n"]:
            with self.subTest(newline=repr(newline)):
                lock = LOCK.replace("\n", newline)
                updated = update_lock(lock, "26.10.106")
                self.assertEqual(updated, lock.replace('"26.10.105"', '"26.10.106"'))
                self.assertEqual(update_lock(updated, "26.10.106"), updated)

    def test_rejects_missing_ambiguous_or_nonlocal_package(self):
        for lock in [
            "",
            LOCK.replace('name = "tree-sitter-ruby"', 'name = "other"'),
            LOCK + '\n[[package]]\nname = "tree-sitter-ruby"\nversion = "1.0.0"\n',
            LOCK.replace('version = "26.10.105"\n', ""),
            LOCK.replace(
                'version = "26.10.105"', 'version = "26.10.105"\nsource = "git+x"'
            ),
        ]:
            with self.subTest(lock=lock), self.assertRaises(ValueError):
                update_lock(lock, "26.10.106")

    def test_reads_package_version_without_using_dependency_versions(self):
        self.assertEqual(
            package_version(
                '[package]\nversion = "26.10.106"\n[dependencies]\ncc = "1"\n'
            ),
            "26.10.106",
        )
        for manifest in ["", '[dependencies]\nversion = "1"\n', "[package]\n"]:
            with self.subTest(manifest=manifest), self.assertRaises(ValueError):
                package_version(manifest)

    def test_validates_both_locks_before_writing_either(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tools/parse-benchmark").mkdir(parents=True)
            (root / "Cargo.toml").write_text('[package]\nversion = "26.10.106"\n')
            first = root / "Cargo.lock"
            second = root / "tools/parse-benchmark/Cargo.lock"
            first.write_bytes(LOCK.encode("utf-8"))
            second.write_bytes(b"invalid")
            with self.assertRaises(ValueError):
                sync_lock_versions(root)
            self.assertEqual(first.read_bytes(), LOCK.encode("utf-8"))
            self.assertEqual(second.read_bytes(), b"invalid")
            second.write_bytes(LOCK.replace("\n", "\r\n").encode("utf-8"))
            sync_lock_versions(root)
            self.assertEqual(
                first.read_bytes(), LOCK.replace("105", "106").encode("utf-8")
            )
            self.assertEqual(
                second.read_bytes(),
                LOCK.replace("105", "106").replace("\n", "\r\n").encode("utf-8"),
            )


if __name__ == "__main__":
    unittest.main()
