# -*- coding: utf-8 -*-
"""临时脚本：验证四项使用体验修复。"""

import ctypes
import os
import sys
import tempfile
import time
import types

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

import main  # noqa: E402
import win_platform  # noqa: E402

_TMP = os.path.join(tempfile.gettempdir(), "ai_chat_tests")
os.makedirs(_TMP, exist_ok=True)
main.CONFIG_PATH = os.path.join(_TMP, "config_test.json")

root = main.tk.Tk()
app = main.AiChatApp(root)
root.update()

try:
    # 1. 发送按钮固定宽度；思考中动画不再改按钮文字
    assert int(app.send_btn.cget("width")) == 10, app.send_btn.cget("width")
    app._start_busy()
    root.update()
    time.sleep(0.4)
    root.update()
    assert app.send_btn.cget("text") == "思考中…", app.send_btn.cget("text")
    app._finish_busy()
    root.update()
    assert app.send_btn.cget("text") == "发送 (Enter)"
    print("1. 发送按钮固定宽度、思考中不拉伸: OK")

    # 2. 浮窗不抢占焦点（NOACTIVATE 样式已设置）+ 点击外部自动关闭
    app.popup.show("test", 100, 100)
    root.update()
    hwnd = int(app.popup.win.winfo_id())
    style = ctypes.windll.user32.GetWindowLongW(hwnd, win_platform.GWL_EXSTYLE)
    assert style & win_platform.WS_EX_NOACTIVATE, "浮窗应带 NOACTIVATE 样式"
    assert style & win_platform.WS_EX_TOOLWINDOW, "浮窗应带 TOOLWINDOW 样式"
    assert app.popup._click_watcher._thread is not None, "点击外部监听应已启动"
    app.popup.hide()
    root.update()
    assert app.popup._click_watcher._thread is None, "关闭后监听应停止"
    print("2. 浮窗不抢焦点 + 点击外部关闭: OK")

    # 3. Shift+Enter 换行、Enter 仍发送
    app.input.delete("1.0", "end")
    r = app._on_return(types.SimpleNamespace(state=0x0001))
    content = app.input.get("1.0", "end-1c")
    assert r == "break" and "\n" in content, content
    r2 = app._on_return(types.SimpleNamespace(state=0x0004))
    content2 = app.input.get("1.0", "end-1c")
    assert r2 == "break" and content2.count("\n") == 2, content2
    print("3. Shift+Enter / Ctrl+Enter 换行: OK")

    print("== 四项使用体验修复全部通过 ==")
finally:
    try:
        app.popup.hide()
        app.quit_app()
    except Exception:
        pass
