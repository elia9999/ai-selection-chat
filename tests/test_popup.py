# -*- coding: utf-8 -*-
"""临时脚本：验证有道式划词浮窗的完整流程。"""

import ctypes
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
    # 1. 热键 → 浮窗（主窗口不弹出）
    app.hide_window()
    root.update()
    main.set_clipboard_text("HELLO-POPUP-123")
    _seq = [0]

    def fake_seq():
        _seq[0] += 1
        return _seq[0]

    main.clipboard_sequence = fake_seq
    ctypes.windll.user32.PostThreadMessageW(app.hotkeys._tid, 0x0312, 1, 0)
    deadline = time.time() + 8
    while time.time() < deadline and (
        app.popup.win is None or app.popup.win.state() == "withdrawn"
    ):
        root.update()
        time.sleep(0.1)
    root.update()
    assert app.popup.text == "HELLO-POPUP-123", app.popup.text
    assert root.state() == "withdrawn", "主窗口不应弹出"
    assert app.popup.win.state() == "normal", "浮窗应可见"
    print("1. 热键划词浮现浮窗、主窗口保持隐藏: OK")

    # 2. 浮窗「翻译」→ 回主窗口并提交请求
    app.popup._trigger("translate")
    root.update()
    assert root.state() != "withdrawn", "点翻译后应回到主窗口"
    assert app.popup.win.state() == "withdrawn", "浮窗应已关闭"
    assert any(
        "HELLO-POPUP-123" in m["content"] and "翻译" in m["content"]
        for m in app.history
    ), app.history
    print("2. 浮窗「翻译」返回主窗口并提交翻译: OK")

    # 3. 浮窗「问答」→ 加入主窗口待提问
    app.hide_window()
    app._handle_popup_action("ask", "QUESTION-TEXT")
    root.update()
    assert app.pending_context == "QUESTION-TEXT", app.pending_context
    assert root.state() != "withdrawn", "点问答后应回到主窗口"
    assert len(app.quick_frame.winfo_children()) == 5, "快捷动作应显示"
    print("3. 浮窗「问答」加入主窗口并显示快捷动作: OK")

    # 4. 浮窗手动关闭 / 重新弹出
    app.popup.show("ANOTHER-TEXT", 10, 10)
    root.update()
    assert app.popup.win.state() == "normal"
    texts = []
    for w in app.popup.win.winfo_children():
        if isinstance(w, main.tk.Frame):
            for c in w.winfo_children():
                if isinstance(c, main.tk.Frame):
                    texts = [
                        b.cget("text")
                        for b in c.winfo_children()
                        if isinstance(b, main.tk.Button)
                    ]
    action_texts = [t for t in texts if t != "✕"]
    assert action_texts == ["翻译", "解释", "总结", "润色", "问答"], action_texts
    print("4b. 浮窗按钮顺序（润色已加、问答在最后）: OK")
    app.popup.hide()
    root.update()
    assert app.popup.win.state() == "withdrawn"
    print("4. 浮窗显示与手动关闭: OK")

    print("== 浮窗流程全部通过 ==")
finally:
    main.set_clipboard_text(previous_clip)
    app.quit_app()
