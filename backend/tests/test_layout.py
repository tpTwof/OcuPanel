"""Resource locations must remain stable when business packages move."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core import paths, storage
from modules.knowledge import retrieval
from modules.knowledge.graphrag import builder
from modules.report import assets


class ResourceLocationTests(unittest.TestCase):
    def test_runtime_data_stays_under_backend(self):
        backend = Path(__file__).resolve().parents[1]
        self.assertEqual(storage.DB_PATH, backend / "ocupanel.db")
        self.assertEqual(paths.OUTPUT_DIR, backend / "output")
        self.assertEqual(paths.IMG_STORE_DIR, backend / "img_store")
        self.assertEqual(assets.ORIGINAL_STORE_DIR, backend / "original_store")

    def test_text_and_graph_retrieval_share_existing_corpus(self):
        corpus = Path(__file__).resolve().parents[1] / "knowledge" / "corpus"
        self.assertEqual(retrieval.CORPUS_DIR, corpus)
        self.assertEqual(builder.DEFAULT_CORPUS, corpus)
        self.assertTrue((corpus / builder.SEED_NAME).is_file())
