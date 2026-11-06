import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from pydantic import TypeAdapter
from llm.models import LLMConfiguration
from report.models import ReportContent
from user.models import User

class TypedDictCompatibilityTests(unittest.TestCase):
    def test_schema_generation_on_pre_312_branch(self):
        # 当前解释器为 3.13；显式触发已安装 Pydantic 的 <3.12 兼容检查分支。
        with patch('pydantic._internal._generate_schema._SUPPORTS_TYPEDDICT', False):
            for model in (LLMConfiguration, ReportContent, User):
                with self.subTest(model=model.__name__):
                    schema = TypeAdapter(model).json_schema()
                    self.assertEqual(schema['type'], 'object')

if __name__ == '__main__':
    unittest.main()
