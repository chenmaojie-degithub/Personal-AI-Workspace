import unittest
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.chat import _needs_full_document
from app.rag.loaders import _normalize_pdf_text


class DocumentHandlingTests(unittest.TestCase):
    def test_pdf_normalization_and_whole_document_detection(self) -> None:
        self.assertEqual(_normalize_pdf_text("个⼈使⽤⺠族⻘年⻚面"), "个人使用民族青年页面")
        self.assertTrue(_needs_full_document("请评价整份简历"))
        self.assertFalse(_needs_full_document("电话号码是什么？"))
