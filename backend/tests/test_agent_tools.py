import sys
from pathlib import Path
import unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agents.specialist import SpecialistAgent
from agents.tools.evidence import EvidenceTools

class AgentToolsTests(unittest.TestCase):
    def setUp(self):
        self.evidence=[{'id':'a','title':'Guide','section':'test','source':'fixture','text':'optic disc evidence'}]

    def test_search_read_final_loop(self):
        llm=Mock(side_effect=['{"action":"search_evidence","query":"optic"}', '{"action":"read_evidence","id":"a"}', '{"action":"final","text":"Analysis [1]"}'])
        agent=SpecialistAgent('Eye',llm,lambda *a,**k:[])
        self.assertEqual(agent.execute('case',self.evidence,{'a':1}),'Analysis [1]')
        self.assertIn('optic disc evidence',llm.call_args.args[0])
        self.assertEqual(llm.call_count,3)

    def test_invalid_citation_and_access(self):
        tools=EvidenceTools(self.evidence,{'a':1})
        with self.assertRaises(ValueError):tools.read('other-case')
        with self.assertRaises(ValueError):tools.validate_citations('Invented [99]')

    def test_budget(self):
        llm=Mock(return_value='{"action":"read_evidence","id":"a"}')
        with self.assertRaises(RuntimeError):
            SpecialistAgent('Eye',llm,lambda *a,**k:[],max_tool_steps=1).execute('case',self.evidence,{'a':1})
        self.assertEqual(llm.call_count,2)

if __name__=='__main__':unittest.main()
