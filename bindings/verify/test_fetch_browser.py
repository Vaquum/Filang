"""Release downloads must fail before writing if integrity or member types differ."""

import hashlib
import io
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fetch_browser import main


class BrowserDownloadTests(unittest.TestCase):
    def download(self, *, corrupt=False, symlink=False):
        payload = io.BytesIO()
        with tarfile.open(fileobj=payload, mode="w:gz") as archive:
            for name in ("index.mjs", "worker-client.mjs", "worker.mjs", "filang_engine.wasm"):
                member = tarfile.TarInfo(f"browser/{name}")
                content = name.encode()
                member.size = len(content)
                if symlink and name == "index.mjs":
                    member.type = tarfile.SYMTYPE
                    member.linkname = "/tmp/should-not-be-written"
                archive.addfile(member, io.BytesIO(content))
        data = payload.getvalue()
        digest = "0" * 64 if corrupt else hashlib.sha256(data).hexdigest()
        sums = f"{digest}  filang-browser-0.10.0.post1.tar.gz\n".encode()
        return [io.BytesIO(sums), io.BytesIO(data)]

    def run_download(self, output, responses):
        with patch("sys.argv", ["fetch_browser.py", "0.10.0.post1", "--out", str(output)]), \
                patch("fetch_browser.urlopen", side_effect=responses):
            main()

    def test_download_writes_only_the_four_verified_files(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "engine"
            self.run_download(output, self.download())
            self.assertEqual(len(list(output.iterdir())), 4)
            self.assertEqual((output / "filang_engine.wasm").read_bytes(), b"filang_engine.wasm")

    def test_corrupted_download_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "engine"
            with self.assertRaisesRegex(SystemExit, "checksum mismatch"):
                self.run_download(output, self.download(corrupt=True))
            self.assertFalse(output.exists())

    def test_symlink_is_rejected_before_writing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "engine"
            with self.assertRaisesRegex(SystemExit, "invalid browser asset"):
                self.run_download(output, self.download(symlink=True))
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
