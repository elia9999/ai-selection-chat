# -*- coding: utf-8 -*-
"""临时脚本：划词注入 → 快捷动作 → 一键提问流程测试。"""

import os
import sys

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
app._handle_popup_action("ask", "hello world")
root.update()
assert app.pending_context == "hello world", app.pending_context
kids = app.quick_frame.winfo_children()
assert len(kids) == 5, len(kids)
app._quick_ask("请解释这段内容：")
root.update()
assert len(app.history) == 1, app.history
assert "hello world" in app.history[0]["content"]
app.quit_app()
print("划词注入 + 快捷动作 + 消息组装: OK")
