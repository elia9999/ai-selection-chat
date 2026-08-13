# -*- coding: utf-8 -*-
"""临时脚本：回归验证“未划词却弹出剪切板旧内容”的问题。"""

import os
import sys
import time

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

import main  # noqa: E402
import tempfile  # noqa: E402

_TMP = os.path.join(tempfile.gettempdir(), "ai_chat_tests")
os.makedirs(_TMP, exist_ok=True)
main.CONFIG_PATH = os.path.join(_TMP, "config_test.json")

root = main.tk.Tk()
app = main.AiChatApp(root)
root.update()
previous_clip = main.get_clipboard_text()

try:
    # 1. 剪切板有旧内容，但复制没有发生（序列号不变）→ 不得弹窗
    main.set_clipboard_text("OLD-CLIPBOARD-CONTENT")
    # 模拟在别的程序划词：隐形窗口抢占前台
    dummy = main.tk.Toplevel(root)
    dummy.overrideredirect(True)
    dummy.geometry("+50+50")
    dummy.attributes("-alpha", 0.01)
    dummy.focus_force()
    root.update()
    main.clipboard_sequence = lambda: 1
    app._handle_selection_event(200, 200)
    deadline = time.time() + 2
    while time.time() < deadline:
        root.update()
        time.sleep(0.1)
    root.update()
    hidden = app.popup.win is None or app.popup.win.state() == "withdrawn"
    assert hidden, "未发生复制时不应弹出剪切板旧内容"
    print("1. 未真正复制时不再弹出旧剪切板内容: OK")

    # 2. 复制确实发生（序列号变化）→ 正常弹窗且显示新内容
    _seq = [100]

    def fake_seq():
        _seq[0] += 1
        return _seq[0]

    main.clipboard_sequence = fake_seq
    main.set_clipboard_text("FRESH-SELECTION-TEXT")
    app._handle_selection_event(250, 250)
    deadline = time.time() + 6
    while time.time() < deadline and (
        app.popup.win is None or app.popup.win.state() == "withdrawn"
    ):
        root.update()
        time.sleep(0.1)
    root.update()
    assert app.popup.text == "FRESH-SELECTION-TEXT", app.popup.text
    assert app.popup.text != "OLD-CLIPBOARD-CONTENT"
    dummy.destroy()
    root.update()
    print("2. 复制成功后正常弹出且显示新划词内容: OK")

    print("== 剪切板旧内容回归测试通过 ==")
finally:
    main.set_clipboard_text(previous_clip)
    app.quit_app()
