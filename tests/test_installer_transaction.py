import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from modagent import installer


class InstallerTransactionTests(unittest.TestCase):
    def test_transaction_rolls_back_every_destination(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / "game"
            game.mkdir()
            source_a = root / "a.new"
            source_b = root / "b.new"
            source_a.write_text("new-a", encoding="utf-8")
            source_b.write_text("new-b", encoding="utf-8")
            destination_a = game / "a.txt"
            destination_b = game / "b.txt"
            destination_a.write_text("old-a", encoding="utf-8")
            real_replace = os.replace
            committed = 0

            def fail_second_commit(src, dest):
                nonlocal committed
                if os.path.basename(os.path.dirname(src)) == "stage":
                    committed += 1
                    if committed == 2:
                        raise OSError("simulated commit failure")
                return real_replace(src, dest)

            operations = [
                {"src": str(source_a), "dest": str(destination_a), "record": {"file": "a"}},
                {"src": str(source_b), "dest": str(destination_b), "record": {"file": "b"}},
            ]
            with mock.patch.object(installer.os, "replace", side_effect=fail_second_commit):
                with self.assertRaisesRegex(OSError, "simulated commit failure"):
                    installer._commit_files_transactionally(operations, str(game), "test")
            self.assertEqual(destination_a.read_text(encoding="utf-8"), "old-a")
            self.assertFalse(destination_b.exists())
            self.assertFalse(list(game.glob(".modagent-transaction-*")))

    def test_transaction_records_verified_hash_and_size(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            game = root / "game"
            game.mkdir()
            source = root / "source.bin"
            source.write_bytes(b"verified")
            destination = game / "mods" / "source.bin"
            installed = installer._commit_files_transactionally([
                {"src": str(source), "dest": str(destination), "record": {"file": "source.bin"}},
            ], str(game), "test")
            self.assertEqual(destination.read_bytes(), b"verified")
            self.assertEqual(installed[0]["size"], 8)
            self.assertEqual(len(installed[0]["sha256"]), 64)
            self.assertFalse(installed[0]["overwrote"])


if __name__ == "__main__":
    unittest.main()
