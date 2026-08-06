# -*- coding: utf-8 -*-
"""临时脚本：验证划词模式开关 + 全局监听的完整流程。"""

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
    # 1. 开启划词模式：主窗口不消失
    assert root.state() == "normal"
    if app.config.get("selection_mode"):
        app._set_selection_mode(False)
    root.update()
    app._toggle_selection_mode()
    root.update()
    assert app.config["selection_mode"] is True
    assert app.capture_btn.cget("text") == "划词：开"
    assert root.state() == "normal", "开启划词模式后主窗口不应消失"
    time.sleep(0.5)
    root.update()
    print("1. 开启划词模式（主窗口保持可见）: OK")
    print("   mouse hook installed:", app.selection_watcher._hook is not None)

    # 2. 模拟划词完成：自动弹浮窗，主窗口仍不消失
    main.set_clipboard_text("MODE-SELECTION-789")
    _seq = [0]

    def fake_seq():
        _seq[0] += 1
        return _seq[0]

    main.clipboard_sequence = fake_seq
    app._handle_selection_event(300, 400)
    deadline = time.time() + 8
    while time.time() < deadline and (
        app.popup.win is None or app.popup.win.state() == "withdrawn"
    ):
        root.update()
        time.sleep(0.1)
    root.update()
    assert app.popup.text == "MODE-SELECTION-789", app.popup.text
    assert root.state() == "normal", "划词弹浮窗时主窗口不应消失"
    assert app.popup.win.state() == "normal"
    print("2. 划词完成自动弹浮窗、主窗口不消失: OK")

    # 3. 浮窗不会自动消失
    time.sleep(2.5)
    root.update()
    assert app.popup.win.state() == "normal", "浮窗不应自动消失"
    print("3. 浮窗不会几秒后自动消失: OK")

    # 4. 关闭划词模式：浮窗关闭，状态复位并保存
    app._toggle_selection_mode()
    root.update()
    assert app.config["selection_mode"] is False
    assert app.capture_btn.cget("text") == "划词"
    assert app.popup.win.state() == "withdrawn"
    assert main.load_config()["selection_mode"] is False
    print("4. 关闭划词模式（浮窗关闭、状态复位）: OK")

    print("== 划词模式全部通过 ==")
finally:
    main.set_clipboard_text(previous_clip)
    app.quit_app()
