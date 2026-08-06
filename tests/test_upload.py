# -*- coding: utf-8 -*-
"""临时脚本：验证上传参考文件功能。"""

import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

import main  # noqa: E402

import tempfile  # noqa: E402
WORK = os.path.join(tempfile.gettempdir(), "ai_chat_tests")
os.makedirs(WORK, exist_ok=True)
main.CONFIG_PATH = os.path.join(WORK, "config_test.json")

root = main.tk.Tk()
app = main.AiChatApp(root)
root.update()

try:
    # 1. 读取文本文件
    txt = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ref_sample.txt")
    content = app._read_reference_file(txt)
    assert content and "量子计算" in content, content
    print("1. 文本文件读取: OK")

    # 2. 二进制文件拦截
    bin_path = os.path.join(WORK, "ref_bin.bin")
    with open(bin_path, "wb") as f:
        f.write(b"\x00\x01\x02binary\x00data")
    assert app._read_reference_file(bin_path) is None
    print("2. 二进制文件拦截: OK")

    # 3. 上传后消息附带参考文件
    app.reference_files.append({"name": "ref_sample.txt", "content": content})
    app._submit("第一个问题", "第一个问题")
    root.update()
    assert "【参考文件：ref_sample.txt】" in app.history[0]["content"], app.history[0]["content"]
    assert "量子计算" in app.history[0]["content"]
    print("3. 消息附带参考文件内容: OK")

    # 4. 会话内持续参考
    app._submit("第二个问题", "第二个问题")
    root.update()
    assert "【参考文件：ref_sample.txt】" in app.history[1]["content"]
    print("4. 后续消息持续附带参考: OK")

    # 5. 清除参考与按钮显隐
    app._refresh_reference_ui()
    root.update()
    assert app.clear_ref_btn.winfo_ismapped(), "清除按钮应显示"
    app._clear_reference()
    root.update()
    assert app.reference_files == []
    assert not app.clear_ref_btn.winfo_ismapped(), "清除按钮应隐藏"
    print("5. 清除参考与按钮显隐: OK")

    # 6. 上传按钮就位
    texts = [
        c.cget("text")
        for c in app.send_btn.master.winfo_children()
        if isinstance(c, main.tk.Button)
    ]
    assert "上传" in texts, texts
    print("6. 上传按钮已就位: OK")

    print("== 上传参考文件功能全部通过 ==")
finally:
    app.quit_app()
