import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from modules.knowledge.models import Chunk
from modules.knowledge.retrieval import Retriever
from core import config


class ReportRetrievalTests(unittest.TestCase):
    def test_sample_glaucoma_query_keeps_diagnostic_reference(self):
        from modules.knowledge.report_focus import disease_focus
        from modules.report.context import build_context
        from modules.vision.models import DiseaseResult
        retriever = Retriever.from_corpus(mode='bm25', graph_enabled=False)
        note = (Path(__file__).resolve().parents[2] / 'samples' / 'clinical_note.txt').read_text(encoding='utf-8')
        hits = retriever.search(build_context({'glaucoma': DiseaseResult(probability=.9)}, note),
                                k=config.RAG_TOP_K, boost=disease_focus('glaucoma'), disease='glaucoma')
        ids = {item['id'] for item in hits}
        self.assertIn('nice-ng81-1.2.1', ids)
        self.assertNotIn('nice-ng242-1.6.11', ids)

    def test_report_retrieval_covers_treatment_and_followup_topics(self):
        """报告必须同时取得诊断、治疗目标与随访依据，否则撰稿只能写无依据的处置句。"""
        from modules.knowledge.report_focus import disease_focus
        from modules.knowledge.service import retrieve_report_evidence
        from modules.report.context import build_context
        from modules.vision.models import DiseaseResult
        note = (Path(__file__).resolve().parents[2] / 'samples' / 'clinical_note.txt').read_text(encoding='utf-8')
        hits = retrieve_report_evidence(
            build_context({'glaucoma': DiseaseResult(probability=.9)}, note),
            'glaucoma', boost=disease_focus('glaucoma'))
        blob = '\n'.join(item['text'] for item in hits)
        for topic in ('目标眼压', '随访'):
            self.assertIn(topic, blob)
        # 视野判读依据可能写作「视野缺损」「视野损害」或「弓形暗点」
        self.assertTrue(any(t in blob for t in ('视野缺损', '视野损害', '弓形暗点')))

    def test_disease_filter_excludes_other_disease_sources(self):
        retriever = Retriever.from_corpus(mode='bm25', graph_enabled=False)
        note = '眼压 26 mmHg，C/D 0.7，视野缺损，青光眼随访复查'
        hits = retriever.search(note, k=config.RAG_TOP_K, boost='青光眼', disease='glaucoma')
        sources = {item['source'] for item in hits}
        # 妊娠期糖网与白内障条款不得进入青光眼报告
        self.assertNotIn('nice-ng3', sources)
        self.assertNotIn('nice-ng77', sources)
        self.assertNotIn('nhc-cataract-2026', sources)

    def test_disease_keyword_is_boosted_even_when_already_in_case_query(self):
        retriever = Retriever([
            Chunk('glaucoma', 'one', 'title', 'section', 'glaucoma exam'),
            Chunk('diabetes', 'two', 'title', 'section', 'diabetes exam'),
        ], mode='bm25')
        hits = retriever.search('glaucoma diabetes exam', boost='glaucoma', k=1)
        self.assertEqual(hits[0]['id'], 'glaucoma')

    def test_vector_topic_precedes_long_case_context(self):
        retriever = Retriever([], mode='vector')
        index = Mock()
        index.search.return_value = []
        with patch.object(retriever, '_get_vector', return_value=index):
            retriever._search_vector('long case ' * 600, k=4, boost='glaucoma')
        self.assertTrue(index.search.call_args.args[0].startswith('glaucoma'))


if __name__ == '__main__':
    unittest.main()
