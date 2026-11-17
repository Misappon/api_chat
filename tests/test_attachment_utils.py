"""Attachment validation tests, including PDF text extraction."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from apichat.attachment_utils import (
    AttachmentError,
    apply_attachment_limits,
    attachment_from_bytes,
    attachment_text_content,
)
from apichat.llm import _openai_messages
from apichat.models import Provider


def _pdf_with_text(text: str) -> bytes:
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream
        + b"\nendstream",
    ]
    data = b"%PDF-1.4\n"
    offsets: list[int] = []
    for index, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data += f"{index} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(data)
    data += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        data += f"{offset:010d} 00000 n \n".encode()
    data += (
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref}\n%%EOF\n"
    ).encode()
    return data


class AttachmentTests(unittest.TestCase):
    def tearDown(self) -> None:
        apply_attachment_limits(10, 2, 20)

    def test_pdf_text_extraction(self) -> None:
        attachment = attachment_from_bytes(
            _pdf_with_text("Hello PDF"), "sample.pdf", mime_type="application/pdf"
        )
        self.assertEqual(attachment.kind, "pdf")
        self.assertEqual(attachment.mime_type, "application/pdf")
        self.assertGreater(attachment.token_count, 0)
        self.assertIn("Hello PDF", attachment_text_content(attachment))
        provider = Provider(id=0, alias="PDF", provider="openai", model="mock")
        payload = _openai_messages(
            provider,
            [{"role": "user", "content": "", "attachments": [attachment]}],
        )
        self.assertIn("Hello PDF", payload[0]["content"])
        dict_payload = _openai_messages(
            provider,
            [
                {
                    "role": "user",
                    "content": "",
                    "attachments": [
                        {
                            "kind": "pdf",
                            "filename": "sample.pdf",
                            "mime_type": "application/pdf",
                            "data": attachment.data,
                        }
                    ],
                }
            ],
        )
        self.assertIn("Hello PDF", dict_payload[0]["content"])

    def test_scanned_pdf_is_rejected_clearly(self) -> None:
        with self.assertRaises(AttachmentError) as ctx:
            attachment_from_bytes(
                _pdf_with_text(""),
                "empty.pdf",
                mime_type="application/pdf",
            )
        self.assertIn("没有可提取的文本", str(ctx.exception))

    def test_pdf_limit_is_applied(self) -> None:
        apply_attachment_limits(1, 1, 1)
        with self.assertRaises(AttachmentError):
            attachment_from_bytes(
                _pdf_with_text("too large") + b"\n" * (1024 * 1024),
                "large.pdf",
                mime_type="application/pdf",
            )


if __name__ == "__main__":
    unittest.main()
