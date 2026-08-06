# -*- coding: utf-8 -*-
"""临时脚本：验证关闭即退出与单实例保护。"""

import ctypes
import os
import sys

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, APP_DIR)
os.chdir(APP_DIR)

import main  # noqa: E402
import win_platform  # noqa: E402
import tempfile  # noqa: E402

_TMP = os.path.join(tempfile.gettempdir(), "ai_chat_tests")
os.makedirs(_TMP, exist_ok=True)
main.CONFIG_PATH = os.path.join(_TMP, "config_test.json")

# 1. 单实例互斥：第二次获取应失败
ok1 = main.acquire_single_instance("test_mutex_abc")
ok2 = main.acquire_single_instance("test_mutex_abc")
assert ok1 is True and ok2 is False, (ok1, ok2)
if win_platform._SINGLE_INSTANCE_MUTEX:
    ctypes.windll.kernel32.CloseHandle(win_platform._SINGLE_INSTANCE_MUTEX)
    win_platform._SINGLE_INSTANCE_MUTEX = None
print("1. 单实例互斥（防多开）: OK")

root = main.tk.Tk()
app = main.AiChatApp(root)
root.update()

try:
    # 2. 关闭窗口应真正退出（不再只是隐藏）
    handler = str(root.protocol("WM_DELETE_WINDOW"))
    assert "quit_app" in handler, handler
    print("2. 窗口关闭绑定为完全退出: OK")

    # 3. 退出后热键与鼠标监听停止、窗口销毁
    app.quit_app()
    assert app.hotkeys._thread is None or not app.hotkeys._thread.is_alive()
    assert app.selection_watcher._thread is None or not app.selection_watcher._thread.is_alive()
    destroyed = False
    try:
        root.winfo_exists()
    except Exception:
        destroyed = True
    assert destroyed, "窗口应已被销毁"
    print("3. 退出后后台监听停止、窗口销毁: OK")

    # 4. 唤醒已有窗口的函数可正常调用
    assert isinstance(main.bring_existing_to_front("AI 划词助手"), bool)
    print("4. 唤醒已有窗口函数: OK")

    print("== 单实例与退出行为全部通过 ==")
finally:
    try:
        app.quit_app()
    except Exception:
        pass
