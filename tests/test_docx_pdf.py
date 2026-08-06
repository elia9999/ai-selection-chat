# -*- coding: utf-8 -*-
"""临时脚本：验证 Word 与 PDF 参考文件解析。"""

import os
import sys
import zipfile

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

import main  # noqa: E402

import tempfile  # noqa: E402
WORK = os.path.join(tempfile.gettempdir(), "ai_chat_tests")
os.makedirs(WORK, exist_ok=True)
main.CONFIG_PATH = os.path.join(WORK, "config_test.json")


def make_docx(path):
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
        "</Relationships>"
    )
    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        "<w:body>"
        "<w:p><w:r><w:t>Word 文档测试内容</w:t></w:r></w:p>"
        "<w:p><w:r><w:t>第二段：深度学习</w:t></w:r></w:p>"
        "</w:body></w:document>"
    )
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", content_types.encode("utf-8"))
        z.writestr("_rels/.rels", rels.encode("utf-8"))
        z.writestr("word/document.xml", document.encode("utf-8"))


def make_pdf(path):
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            b"/Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>"
        ),
        None,  # stream 对象稍后填充
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    stream = b"BT /F1 12 Tf 72 720 Td (PDF Document Test 123) Tj ET"
    objs[3] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)

    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, o in enumerate(objs, 1):
        offsets.append(len(data))
        data += b"%d 0 obj\n" % i + o + b"\nendobj\n"
    xref_pos = len(data)
    data += b"xref\n0 %d\n" % (len(objs) + 1)
    data += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        data += b"%010d 00000 n \n" % off
    data += (
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF"
        % (len(objs) + 1, xref_pos)
    )
    with open(path, "wb") as f:
        f.write(bytes(data))


root = main.tk.Tk()
app = main.AiChatApp(root)
root.update()

try:
    docx_path = os.path.join(WORK, "sample.docx")
    pdf_path = os.path.join(WORK, "sample.pdf")
    make_docx(docx_path)
    make_pdf(pdf_path)

    # 1. Word 解析
    content = app._read_reference_file(docx_path)
    assert content and "Word 文档测试内容" in content, content
    assert "第二段：深度学习" in content, content
    print("1. Word (.docx) 解析: OK")

    # 2. PDF 解析
    content = app._read_pdf(pdf_path)
    assert content and "PDF Document Test 123" in content, content
    assert "第 1 页" in content, content
    print("2. PDF 解析（含分页标注）: OK")

    # 3. 上传流程附带
    app.reference_files.append({"name": "sample.pdf", "content": content})
    app._submit("这份文档讲了什么", "这份文档讲了什么")
    root.update()
    assert "【参考文件：sample.pdf】" in app.history[0]["content"]
    assert "PDF Document Test 123" in app.history[0]["content"]
    print("3. PDF 作为参考随消息发送: OK")

    # 4. 损坏文件返回 None
    bad = os.path.join(WORK, "bad.docx")
    with open(bad, "wb") as f:
        f.write(b"not a real docx")
    assert app._read_reference_file(bad) is None
    print("4. 损坏文件拦截: OK")

    print("== Word / PDF 解析全部通过 ==")
finally:
    app.quit_app()
