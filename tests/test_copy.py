# -*- coding: utf-8 -*-
"""临时脚本：验证对话区选中与复制功能。"""

import os
import sys
import types

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
    # 1. 对话区保持可编辑状态（允许选中复制）
    assert app.chat.cget("state") == "normal", app.chat.cget("state")
    print("1. 对话区可选中（不再禁用）: OK")

    # 1b. 回复通栏显示（不再只占左半边），且选中标签已置顶
    assert app.chat.tag_cget("assistant", "rmargin") == "10", app.chat.tag_cget("assistant", "rmargin")
    assert app.chat.tag_cget("user", "justify") == "left", app.chat.tag_cget("user", "justify")
    assert app.chat.tag_cget("user", "lmargin1") == "120", app.chat.tag_cget("user", "lmargin1")
    app.chat.tag_raise("sel")
    print("1b. 回复通栏 + 用户气泡左对齐 + 选中高亮置顶: OK")

    # 2. 拦截普通输入，放行导航与复制快捷键
    assert app._block_chat_edit(types.SimpleNamespace(keysym="a", state=0)) == "break"
    assert app._block_chat_edit(types.SimpleNamespace(keysym="BackSpace", state=0)) == "break"
    assert app._block_chat_edit(types.SimpleNamespace(keysym="Left", state=0)) is None
    assert app._block_chat_edit(types.SimpleNamespace(keysym="c", state=0x0004)) is None
    assert app._block_chat_edit(types.SimpleNamespace(keysym="a", state=0x0004)) is None
    print("2. 输入拦截与复制快捷键放行: OK")

    # 3. 插入消息后全选复制
    app._append_chat("AI", "这是需要复制的回答内容。", "assistant")
    app._select_all_chat()
    app._copy_chat_selection()
    root.update()
    copied = main.get_clipboard_text()
    assert "这是需要复制的回答内容" in copied, copied
    print("3. 全选并复制回答内容: OK")

    # 4. 右键菜单就位
    labels = [app.chat_menu.entrycget(i, "label") for i in range(app.chat_menu.index("end") + 1)]
    assert "复制" in labels and "全选" in labels, labels
    print("4. 右键菜单（复制/全选）: OK")

    print("== 复制功能全部通过 ==")
finally:
    main.set_clipboard_text(previous_clip)
    app.quit_app()
