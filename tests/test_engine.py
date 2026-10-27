import tempfile
import unittest
from pathlib import Path
from engine import EngineRegistry, EngineUnavailable, OCRResult

class EngineContractTests(unittest.TestCase):
    def test_disabled_is_explicit(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "example.png"
            p.write_bytes(b"sample")
            with self.assertRaises(EngineUnavailable):
                EngineRegistry().transcribe(p)

    def test_replaceable_engine(self):
        class ExampleAdapter:
            name = "Test adapter"
            def available(self):
                return True
            def recognize(self, path):
                return OCRResult("שלום", self.name)
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder) / "example.png"
            p.write_bytes(b"sample")
            self.assertEqual(EngineRegistry(ExampleAdapter()).transcribe(p).text, "שלום")

    def test_missing_file_not_processed(self):
        with self.assertRaises(FileNotFoundError):
            EngineRegistry().transcribe("this-file-does-not-exist.jpg")

if __name__ == "__main__":
    unittest.main()
