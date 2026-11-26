import tempfile
import json
import unittest
from pathlib import Path
from unittest.mock import patch
import sys
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.knowledge.graphrag import GraphRetriever, build_graph_from_corpus
from modules.knowledge.models import Chunk
from modules.knowledge.retrieval import CORPUS_DIR, DEMO_SOURCES, Retriever, VectorIndex


class GraphRetrievalTests(unittest.TestCase):
    def test_nei_patient_descriptions_retrieve_specific_source_sections(self):
        cases = {
            "像有帘子挡住视线": "nei-retinal-detachment-features",
            "孩子拍照瞳孔发白": "nei-retinoblastoma-features",
            "睫毛根部结痂": "nei-blepharitis-features",
            "干眼怎么检查泪膜稳定性": "nei-dry-eye-assessment",
        }
        for enabled in (False, True):
            retriever = Retriever.from_corpus(mode="bm25", graph_enabled=enabled)
            for query, expected in cases.items():
                with self.subTest(graph=enabled, query=query):
                    hits = {item["id"]: item for item in retriever.search(query)}
                    self.assertIn(expected, hits)
                    hit = hits[expected]
                    self.assertEqual(hit["jurisdiction"], "US")
                    self.assertTrue(hit["url"].startswith("https://www.nei.nih.gov/"))
                    self.assertTrue(all(hit[key] for key in ("section", "version", "scope")))
                    self.assertEqual(bool(hit.get("graph_path")), enabled)

    def test_vector_batches_preserve_chunk_order_across_boundaries(self):
        chunks = [Chunk(str(i), "test", "title", "section", str(i)) for i in range(65)]
        index = VectorIndex(chunks)
        batches = []

        def encode(texts):
            batches.append(len(texts))
            return np.array([[int(text.splitlines()[-1])] for text in texts])

        with patch("core.config.RAG_VECTOR_STORE_PATH", ""), patch.object(
                index, "_load"), patch.object(index, "_encode", side_effect=encode):
            index.ensure()
            index.ensure()
        # 分批编码（每批 32 条），且多次 ensure 不重复编码
        self.assertEqual(batches, [32, 32, 1])
        self.assertEqual(index._matrix[:, 0].tolist(), list(range(65)))

    def test_vector_store_reuses_unchanged_passages_and_drops_removed_ones(self):
        """语料变化时只重编码改动过的条目，删除的条目不再保留。"""
        chunks = [Chunk(str(i), "test", "title", "section", str(i)) for i in range(3)]
        with tempfile.TemporaryDirectory() as directory, patch(
            "core.config.RAG_VECTOR_STORE_PATH", str(Path(directory) / "store"),
        ), patch.object(VectorIndex, "_load"):
            def encode(texts):
                return np.array([[float(text.splitlines()[-1]), 1.0] for text in texts])

            with patch.object(VectorIndex, "_encode", side_effect=encode) as encoder:
                VectorIndex(chunks).ensure()
                self.assertEqual(len(encoder.call_args.args[0]), 3)
                encoder.reset_mock()

                # 同一份语料：完全复用，不重新编码
                restored = VectorIndex(chunks)
                restored.ensure()
                encoder.assert_not_called()
                self.assertEqual(restored._matrix[:, 0].tolist(), [0, 1, 2])

                # 只有第 3 条变化：只重编码这一条
                changed = chunks[:2] + [Chunk("2", "test", "title", "section", "9")]
                updated = VectorIndex(changed)
                updated.ensure()
                self.assertEqual(len(encoder.call_args.args[0]), 1)
                self.assertEqual(updated._matrix[:, 0].tolist(), [0, 1, 9])

                # 语料减少：被删掉的条目不应再出现在向量里
                encoder.reset_mock()
                shrunk = VectorIndex(chunks[:2])
                shrunk.ensure()
                self.assertEqual(shrunk._matrix.shape[0], 2)

    def test_unanchored_clause_survives_graph_fusion_and_bad_graph(self):
        data = {
            "schema_version": 1,
            "sources": {"test": {"title": "眼轴检查", "version": "1", "jurisdiction": "UK",
                                 "url": "https://example.org/guide"}},
            "evidence": [
                {"id": "plain", "source": "test", "section": "1", "scope": "英国",
                 "text": "眼轴测量术前检查，基础条款"},
                {"id": "linked", "source": "test", "section": "2", "scope": "英国",
                 "text": "Axial length", "lang": "en", "anchors": ["axial"]},
            ],
            "concepts": {"axial": {"label": "眼轴", "aliases": ["眼轴"]}},
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "guidelines").mkdir()
            path = root / "guidelines" / "test.json"
            path.write_text(json.dumps(data), encoding="utf-8")
            flat = Retriever.from_corpus(root, mode="bm25", graph_enabled=False)
            graph = Retriever.from_corpus(root, mode="bm25", graph_enabled=True)
            self.assertEqual({c.id for c in flat.chunks}, {c.id for c in graph.chunks})
            hits = {item["id"]: item for item in graph.search("英国眼轴检查")}
            self.assertIn("plain", hits)
            self.assertNotIn("graph_path", hits["plain"])
            self.assertTrue(hits["linked"]["graph_path"])
            self.assertEqual(hits["linked"]["lang"], "en")
            self.assertEqual(graph._graph.search("眼轴")[0]["lang"], "en")
            data["evidence"][1]["anchors"] = ["missing"]
            path.write_text(json.dumps(data), encoding="utf-8")
            fallback = Retriever.from_corpus(root, mode="bm25", graph_enabled=True)
            self.assertFalse(fallback.graph_available)
            self.assertEqual({c.id for c in fallback.chunks}, {"plain", "linked"})
            for concepts in ([], None):
                data["concepts"] = concepts
                path.write_text(json.dumps(data), encoding="utf-8")
                fallback = Retriever.from_corpus(root, mode="bm25", graph_enabled=True)
                self.assertFalse(fallback.graph_available)
                self.assertIn("plain", {item["id"] for item in fallback.search("基础条款")})

    def test_duplicate_ids_identify_both_files_or_the_single_file(self):
        guide = json.loads((CORPUS_DIR / "guidelines/nice-ng77.json").read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            guides = root / "guidelines"
            guides.mkdir()
            first = guides / "one.json"
            first.write_text(json.dumps(guide), encoding="utf-8")
            second = guides / "two.json"
            second.write_text(json.dumps(guide), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"nice-ng77-referral.*one\.json.*two\.json"):
                Retriever.from_corpus(root)
            guide["evidence"].append(guide["evidence"][0])
            first.write_text(json.dumps(guide), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, r"nice-ng77-referral.*one\.json.*one\.json"):
                Retriever.from_corpus(root)

    def test_graph_and_text_complement_each_other_on_compound_question(self):
        retriever = Retriever.from_corpus(mode="bm25", graph_enabled=True)
        hits = {hit["id"]: hit for hit in retriever.search("英国白内障术前眼轴和散光如何检查")}
        self.assertTrue(hits["nice-ng77-axial-length"]["graph_path"])
        self.assertNotIn("graph_path", hits["nice-ng77-cornea"])

    def test_guidelines_retrieve_with_and_without_graph(self):
        cases = [
            ("中国白内障术后首次随访", "nhc-cataract-2026-followup"),
            ("英国白内障术前眼轴生物测量", "nice-ng77-axial-length"),
            ("英国孕前已有糖尿病，孕期眼底检查如何安排", "nice-ng3-retina"),
            ("美国无症状成人青光眼筛查", "uspstf-poag-population"),
        ]
        for graph_enabled in (False, True):
            retriever = Retriever.from_corpus(mode="bm25", graph_enabled=graph_enabled)
            for query, expected in cases:
                with self.subTest(graph=graph_enabled, query=query):
                    hits = retriever.search(query)
                    hit = next(item for item in hits if item["id"] == expected)
                    self.assertTrue(hit["url"].startswith("https://"))
                    self.assertTrue(all(hit[key] for key in ("version", "scope", "section")))
                    self.assertEqual(bool(hit.get("graph_path")), graph_enabled)
                    self.assertTrue(all(not item.get("jurisdiction") or item["jurisdiction"] == hit["jurisdiction"]
                                        or item["jurisdiction"] == "INT" for item in hits))

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
        with patch("core.config.GRAPH_RAG_ENABLED", True):
            retriever = Retriever.from_corpus(mode="bm25")
        sources = {chunk.source for chunk in retriever.chunks}
        # 草稿语料参与检索（正式条款不覆盖随访、目标眼压与视野判读），
        # 但必须带草稿标记，不能冒充权威来源；有正式条款替代的 NEI 副本仍须排除。
        self.assertNotIn("macular-degeneration-nei.md", sources)
        self.assertTrue(DEMO_SOURCES <= sources)
        # 扩充正式条款后，草稿 .md 可能被挤出 top-k —— 这正是期望的方向。
        # 断言"只要草稿出现在结果里就必须带 draft 标记"，而不是强求它一定入选。
        draft_hits = [item for item in retriever.search("青光眼随访 目标眼压", k=20)
                      if item["source"] in DEMO_SOURCES]
        self.assertTrue(all(item.get("draft") for item in draft_hits))
        # 正式条款应当能独立支撑"随访 + 目标眼压"这两个主题。
        official = "\n".join(item["text"] for item in retriever.search(
            "青光眼随访 目标眼压", k=12) if item["source"] not in DEMO_SOURCES)
        self.assertIn("目标眼压", official)
        self.assertTrue(any(k in official for k in ("随访", "复查")))
        results = retriever.search("美国 EYLEA 阿柏西普 活动性眼内炎症")
        self.assertEqual(len({item["id"] for item in results}), len(results))
        self.assertEqual(results[0]["id"], "us-eylea-4.2")
        self.assertEqual(results[0]["sources"], "bm25,graph")
        self.assertTrue(results[0]["graph_path"])
        uk_results = retriever.search("英国 EYLEA 活动性眼内炎症")
        self.assertTrue(all(item.get("jurisdiction") in ("UK", "INT") for item in uk_results))
        diagnosis = retriever.search("英国慢性开角型青光眼，只看杯盘比能确诊吗？")
        # 新增 NG81 诊断章节条款后，同属该文档的诊断评估条款可排到首位；
        # 断言关注的是"取到 NICE 的英国诊断条款"，而非某一条的具体编号。
        self.assertTrue(diagnosis[0]["id"].startswith("nice-ng81"))
        self.assertIn("nice-ng81-1.2.1", {item["id"] for item in diagnosis})

    def test_amd_symptom_and_referral_retrieve_scoped_evidence(self):
        with patch("core.config.GRAPH_RAG_ENABLED", True):
            retriever = Retriever.from_corpus(mode="bm25")
        for query in ("看直线是弯的，需要查什么？", "straight lines look wavy"):
            with self.subTest(query=query):
                hits = {item["id"]: item for item in retriever.search(query)}
                self.assertEqual(len(hits["nei-amd-symptoms-and-exam"]["graph_path"]), 2)
        uk_hits = retriever.search("英国医院怀疑湿性黄斑变性，需要转诊和 OCT 吗？")
        self.assertTrue({"nice-ng82-1.4.6", "nice-ng82-1.4.7-9"} <= {item["id"] for item in uk_hits})
        self.assertTrue(all(item["jurisdiction"] in ("UK", "INT") for item in uk_hits))
        us_hits = retriever.search("美国患者直线变弯")
        self.assertEqual(us_hits[0]["id"], "nei-amd-symptoms-and-exam")
        self.assertTrue(all(item["jurisdiction"] in ("US", "INT") for item in us_hits))

    def test_chinese_amd_queries_observe_evidence_scope(self):
        with patch("core.config.GRAPH_RAG_ENABLED", True):
            retriever = Retriever.from_corpus(mode="bm25")
        for query in ("中国医院怀疑湿性黄斑变性，怎样检查？", "国内怀疑新生血管性 AMD，能用 OCTA 吗？"):
            with self.subTest(query=query):
                hits = retriever.search(query)
                self.assertIn("cn-amd-2023-neovascular-imaging", {item["id"] for item in hits})
                self.assertTrue(all(item["jurisdiction"] in ("CN", "INT") for item in hits))
        hits = retriever.search("中国患者直线变弯，有什么检查依据？")
        # 语料扩充后，与"视物变形自查/就诊"直接对应的条款可以排到首位；
        # 断言的是"能取到本文档体系的条款且地区正确"，不再锁定唯一第一名。
        self.assertIn(hits[0]["id"], {"cn-amd-2023-initial-exam", "cn-amd-amsler-self",
                                      "cn-amd-treat-followup"})
        self.assertTrue(all(item["jurisdiction"] in ("CN", "INT") for item in hits))
        self.assertEqual(retriever.search("英国停车收费是否有优惠？"), [])

    def test_amd_summary_remains_searchable_without_graph(self):
        with patch("core.config.GRAPH_RAG_ENABLED", False):
            retriever = Retriever.from_corpus(mode="bm25")
        results = retriever.search("年龄相关性黄斑变性 AMD 直线变弯 检查")
        self.assertEqual(results[0]["source"], "nei-amd")

    def test_chat_preference_uses_separate_indexes(self):
        from modules.knowledge.service import get_retriever

        with patch("modules.knowledge.service._RETRIEVERS", {}), patch("core.config.RAG_MODE", "bm25"):
            graph = get_retriever(True)
            flat = get_retriever(False)
            self.assertTrue(graph.graph_available)
            self.assertFalse(flat.graph_available)
            self.assertIs(graph, get_retriever(True))
            self.assertIs(flat, get_retriever(False))

    def test_missing_graph_preserves_flat_retrieval(self):
        from modules.knowledge.service import retrieve_with_status

        with tempfile.TemporaryDirectory() as directory:
            (Path(directory) / "test.md").write_text(
                "# Evidence\n\n## Exam\n\nGlaucoma visual field assessment.\n", encoding="utf-8"
            )
            with patch("core.config.GRAPH_RAG_ENABLED", True), patch("core.config.RAG_ENABLED", True):
                retriever = Retriever.from_corpus(Path(directory), mode="bm25")
                with patch("modules.knowledge.service.get_retriever", return_value=retriever):
                    hits, status = retrieve_with_status("visual field")
            self.assertEqual(hits[0]["id"], "test#1-1")
            self.assertEqual(status, {"result": "found", "graph": "unavailable"})
