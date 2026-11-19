import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from graphrag import GraphRetriever, build_graph_from_corpus
from knowledge.retrieval import CORPUS_DIR, DEMO_SOURCES, Retriever


class GraphRetrievalTests(unittest.TestCase):
    def test_snapshot_roundtrip_preserves_multihop_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory) / "graph.json"
            build_graph_from_corpus(CORPUS_DIR, snapshot)
            graph = GraphRetriever()
            graph.load_graph(snapshot)

        query = "英国医院眼科发现硬性渗出"
        self.assertEqual(graph.search(query, hop=1), [])
        hit = graph.search(query, hop=2)[0]
        self.assertEqual(hit["id"], "nice-ng242-1.6.11")
        self.assertEqual([step["relation"] for step in hit["graph_path"]], ["提示评估", "关联条款"])
        self.assertTrue(hit["url"].startswith("https://"))
        self.assertEqual(graph.search("停车收费"), [])

    def test_graph_and_flat_channels_fuse_without_losing_provenance(self):
        with patch("utils.config.GRAPH_RAG_ENABLED", True):
            retriever = Retriever.from_corpus(mode="bm25")
        sources = {chunk.source for chunk in retriever.chunks}
        self.assertTrue(sources.isdisjoint(DEMO_SOURCES))
        self.assertNotIn("macular-degeneration-nei.md", sources)
        results = retriever.search("美国 EYLEA 阿柏西普 活动性眼内炎症")
        self.assertEqual(len({item["id"] for item in results}), len(results))
        self.assertEqual(results[0]["id"], "us-eylea-4.2")
        self.assertEqual(results[0]["sources"], "bm25,graph")
        self.assertTrue(results[0]["graph_path"])
        uk_results = retriever.search("英国 EYLEA 活动性眼内炎症")
        self.assertTrue(all(item.get("jurisdiction") in ("UK", "INT") for item in uk_results))
        diagnosis = retriever.search("英国慢性开角型青光眼，只看杯盘比能确诊吗？")
        self.assertEqual([item["id"] for item in diagnosis], ["nice-ng81-1.2.1"])

    def test_amd_symptom_and_referral_retrieve_scoped_evidence(self):
        with patch("utils.config.GRAPH_RAG_ENABLED", True):
            retriever = Retriever.from_corpus(mode="bm25")
        for query in ("看直线是弯的，需要查什么？", "straight lines look wavy"):
            with self.subTest(query=query):
                hits = {item["id"]: item for item in retriever.search(query)}
                self.assertEqual(len(hits["nei-amd-symptoms-and-exam"]["graph_path"]), 2)
        uk_hits = retriever.search("英国医院怀疑湿性黄斑变性，需要转诊和 OCT 吗？")
        self.assertTrue({"nice-ng82-1.4.6", "nice-ng82-1.4.7-9"} <= {item["id"] for item in uk_hits})
        self.assertTrue(all(item["jurisdiction"] in ("UK", "INT") for item in uk_hits))
        us_hits = retriever.search("美国患者直线变弯")
        self.assertEqual([item["id"] for item in us_hits], ["nei-amd-symptoms-and-exam"])

    def test_chinese_amd_queries_observe_evidence_scope(self):
        with patch("utils.config.GRAPH_RAG_ENABLED", True):
            retriever = Retriever.from_corpus(mode="bm25")
        for query in ("中国医院怀疑湿性黄斑变性，怎样检查？", "国内怀疑新生血管性 AMD，能用 OCTA 吗？"):
            with self.subTest(query=query):
                hits = retriever.search(query)
                self.assertIn("cn-amd-2023-neovascular-imaging", {item["id"] for item in hits})
                self.assertTrue(all(item["jurisdiction"] in ("CN", "INT") for item in hits))
        hits = retriever.search("中国患者直线变弯，有什么检查依据？")
        self.assertEqual([item["id"] for item in hits], ["cn-amd-2023-initial-exam"])
        self.assertEqual(retriever.search("英国停车收费是否有优惠？"), [])

    def test_amd_summary_remains_searchable_without_graph(self):
        with patch("utils.config.GRAPH_RAG_ENABLED", False):
            retriever = Retriever.from_corpus(mode="bm25")
        results = retriever.search("年龄相关性黄斑变性 AMD 直线变弯 检查")
        self.assertEqual(results[0]["source"], "macular-degeneration-nei.md")

    def test_missing_graph_preserves_flat_retrieval(self):
        from knowledge.service import retrieve_with_status

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "test.md").write_text(
                "# Evidence\n\n## Exam\n\nGlaucoma visual field assessment.\n", encoding="utf-8"
            )
            with patch("utils.config.GRAPH_RAG_ENABLED", True), patch("utils.config.RAG_ENABLED", True):
                retriever = Retriever.from_corpus(Path(directory), mode="bm25")
                with patch("knowledge.service.get_retriever", return_value=retriever):
                    hits, status = retrieve_with_status("visual field")
            self.assertEqual(hits[0]["id"], "test#1-1")
            self.assertEqual(status, {"result": "found", "graph": "unavailable"})
