import unittest
import sys
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routes.chat import _needs_full_document
from app.rag.chunking import chunk_documents
from app.rag.loaders import _normalize_pdf_text, load_pdf_parts


class DocumentHandlingTests(unittest.TestCase):
    def test_pdf_normalization_and_whole_document_detection(self) -> None:
        self.assertEqual(_normalize_pdf_text("个⼈使⽤⺠族⻘年⻚面"), "个人使用民族青年页面")
        self.assertTrue(_needs_full_document("请评价整份简历"))
        self.assertFalse(_needs_full_document("电话号码是什么？"))

    def test_pdf_page_metadata_survives_chunking(self) -> None:
        class Page:
            def __init__(self, text: str) -> None:
                self.text = text

            def extract_text(self, extraction_mode: str) -> str:
                self.assert_layout = extraction_mode
                return self.text

        with patch("app.rag.loaders.PdfReader") as reader:
            reader.return_value.pages = [Page("first page"), Page("second page")]
            parts = load_pdf_parts(Path("report.pdf"))
        documents = [
            {"content": part["content"], "document_id": "doc-1", "filename": "report.pdf", "metadata": part["metadata"]}
            for part in parts
        ]
        chunks = chunk_documents(documents)
        self.assertEqual([item["chunk_index"] for item in chunks], [0, 1])
        self.assertEqual([item["metadata"]["page_number"] for item in chunks], [1, 2])
