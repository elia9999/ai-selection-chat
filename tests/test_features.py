# -*- coding: utf-8 -*-
"""临时脚本：三个核心功能的真实运行时验证。"""

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

VK_MENU = 0x12

root = main.tk.Tk()
app = main.AiChatApp(root)
root.update()

previous_clip = main.get_clipboard_text()

try:
    # ---- 1. 热键触发 → 划词捕获 ----
    app.hide_window()
    root.update()
    main.set_clipboard_text("TEST-SELECTION-123")
    _seq = [0]

    def fake_seq():
        _seq[0] += 1
        return _seq[0]

    main.clipboard_sequence = fake_seq
    # 沙箱拦截 SendInput 注入，这里直接把 WM_HOTKEY 消息投递给热键线程，
    # 等价于系统热键触发（RegisterHotKey 注册本身已验证成功）。
    ctypes.windll.user32.PostThreadMessageW(
        app.hotkeys._tid, 0x0312, 1, 0
    )

    deadline = time.time() + 8
    while time.time() < deadline and (
        app.popup.win is None or app.popup.win.state() == "withdrawn"
    ):
        root.update()
        time.sleep(0.1)
    root.update()
    assert app.popup.text == "TEST-SELECTION-123", (
        "热键未弹出划词浮窗: %r" % app.popup.text
    )
    assert root.state() == "withdrawn", "主窗口不应闪现"
    print("1. 热键触发 + 划词浮窗(主窗口不闪现): OK")
    app._handle_popup_action("translate", app.popup.text)
    root.update()
    assert root.state() != "withdrawn", "浮窗按钮后应回到主窗口"
    assert any("TEST-SELECTION-123" in m["content"] for m in app.history), app.history
    print("1b. 浮窗「翻译」回到主窗口并提交: OK")

    # ---- 2. 读取剪切板按钮 ----
    app.input.delete("1.0", "end")
    main.set_clipboard_text("CLIPBOARD-TEXT-456")
    app._on_clipboard_btn()
    root.update()
    content = app.input.get("1.0", "end-1c")
    assert "CLIPBOARD-TEXT-456" in content, content
    print("2. 剪切板按钮读取文本到输入框: OK")

    # ---- 3. 置顶固定 + 位置记忆 ----
    app.config["topmost"] = False
    app._apply_topmost()
    main.save_config(app.config)
    app._toggle_pin()
    root.update()
    assert app.config["topmost"] is True
    assert bool(root.attributes("-topmost")) is True
    assert main.load_config()["topmost"] is True
    app._toggle_pin()
    root.geometry("500x600+123+456")
    root.update_idletasks()
    app._save_geometry()
    saved = main.load_config()["window"]
    assert saved["width"] == 500 and saved["height"] == 600, saved
    assert saved["x"] == 123 and saved["y"] == 456, saved
    print("3. 置顶开关 + 位置大小记忆: OK")

    print("== 全部功能验证通过 ==")
finally:
    main.set_clipboard_text(previous_clip)
    app.quit_app()
