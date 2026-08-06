# -*- coding: utf-8 -*-
"""
Windows 平台适配层：剪切板、全局热键、全局鼠标监听、按键模拟、窗口外观。

这是迁移到其他系统（如 macOS）时唯一需要整体替换的模块：
换平台时，保持函数名与类名不变，另写一个同接口的实现即可。
"""

import ctypes
import threading
import time
from ctypes import wintypes

# ---------------- Win32 常量 ----------------
CF_UNICODETEXT = 13
CF_TEXT = 1
GMEM_MOVEABLE = 0x0002
VK_CONTROL = 0x11
VK_C = 0x43
VK_SPACE = 0x20
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
KEYEVENTF_KEYUP = 0x0002
INPUT_KEYBOARD = 1

HOTKEY_PRESETS = {
    "Ctrl+Alt+Space": (MOD_CONTROL | MOD_ALT, VK_SPACE),
    "Ctrl+Shift+Space": (MOD_CONTROL | MOD_SHIFT, VK_SPACE),
    "Ctrl+Alt+C": (MOD_CONTROL | MOD_ALT, VK_C),
    "Ctrl+Shift+C": (MOD_CONTROL | MOD_SHIFT, VK_C),
}


# ---------------- 剪切板 ----------------
def get_clipboard_text():
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    if not user32.OpenClipboard(None):
        return ""
    try:
        # 优先读 Unicode 文本
        handle = user32.GetClipboardData(CF_UNICODETEXT)
        if handle:
            ptr = kernel32.GlobalLock(handle)
            if ptr:
                try:
                    return ctypes.wstring_at(ptr)
                finally:
                    kernel32.GlobalUnlock(handle)
        # 回退读 ANSI 文本
        handle = user32.GetClipboardData(CF_TEXT)
        if handle:
            ptr = kernel32.GlobalLock(handle)
            if ptr:
                size = kernel32.GlobalSize(handle)
                try:
                    raw = ctypes.string_at(ptr, size)
                    return raw.split(b"\x00")[0].decode("utf-8", errors="replace")
                finally:
                    kernel32.GlobalUnlock(handle)
        return ""
    finally:
        user32.CloseClipboard()


def set_clipboard_text(text):
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    data = (text + "\0").encode("utf-16-le")
    handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        return False
    ptr = kernel32.GlobalLock(handle)
    if not ptr:
        kernel32.GlobalFree(handle)
        return False
    ctypes.memmove(ptr, data, len(data))
    kernel32.GlobalUnlock(handle)
    if not user32.OpenClipboard(None):
        kernel32.GlobalFree(handle)
        return False
    try:
        user32.EmptyClipboard()
        if not user32.SetClipboardData(CF_UNICODETEXT, handle):
            return False
        handle = None  # 所有权已转移给系统
        return True
    finally:
        if handle:
            kernel32.GlobalFree(handle)
        user32.CloseClipboard()


def clipboard_sequence():
    """当前剪切板序列号：任何一次复制都会使其变化。"""
    return ctypes.windll.user32.GetClipboardSequenceNumber()


# ---------------- 模拟按键（SendInput） ----------------
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


def key_event(vk, keyup):
    user32 = ctypes.windll.user32
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.ki.wVk = vk
    if keyup:
        inp.ki.dwFlags = KEYEVENTF_KEYUP
    return user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def press_ctrl_c():
    """模拟 Ctrl+C。若用户正物理按住 Ctrl，则只按 C，避免按键状态错乱。"""
    user32 = ctypes.windll.user32
    ctrl_held = bool(user32.GetAsyncKeyState(VK_CONTROL) & 0x8000)
    try:
        if not ctrl_held:
            key_event(VK_CONTROL, False)
        key_event(VK_C, False)
        time.sleep(0.03)
    finally:
        key_event(VK_C, True)
        if not ctrl_held:
            key_event(VK_CONTROL, True)


def get_cursor_pos():
    """获取当前鼠标位置（屏幕坐标）。"""
    pt = wintypes.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def foreground_hwnd():
    """当前前台窗口句柄（无则返回 0）。"""
    return int(ctypes.windll.user32.GetForegroundWindow() or 0)


def real_hwnd(winfo_id):
    """tk 的 winfo_id 可能是子窗口，向上取真实顶层句柄。"""
    hwnd = int(winfo_id)
    parent = ctypes.windll.user32.GetParent(hwnd)
    return parent if parent else hwnd


def apply_dark_titlebar(hwnd):
    """启用深色标题栏（Win10 1809+，失败则忽略）。"""
    try:
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 20, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def enable_dpi_awareness():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


# ---------------- 全局热键（RegisterHotKey 消息循环） ----------------
class HotkeyManager:
    def __init__(self):
        self._thread = None
        self._tid = None

    def start(self, combo, on_hotkey, on_error):
        self.stop()
        mods, vk = HOTKEY_PRESETS.get(combo, HOTKEY_PRESETS["Ctrl+Alt+Space"])

        def loop():
            self._tid = threading.get_ident()
            user32 = ctypes.windll.user32
            ok = user32.RegisterHotKey(None, 1, mods | MOD_NOREPEAT, vk)
            if not ok:
                on_error("无法注册热键 %s（可能已被其他程序占用）" % combo)
            msg = wintypes.MSG()
            while True:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret <= 0:
                    break
                if msg.message == WM_HOTKEY and msg.wParam == 1:
                    on_hotkey()
            user32.UnregisterHotKey(None, 1)

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        self._thread = thread

    def stop(self):
        thread, tid = self._thread, self._tid
        self._thread = None
        self._tid = None
        if thread is not None and thread.is_alive() and tid:
            ctypes.windll.user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            thread.join(timeout=1.0)


# ---------------- 划词模式：全局鼠标监听 ----------------
WH_MOUSE_LL = 14
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202

LowLevelMouseProc = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
)


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class SelectionWatcher:
    """监听全局鼠标：用户在其他窗口拖选或双击选中文字后，回调选区位置。"""

    def __init__(self, on_selection):
        self.on_selection = on_selection
        self._thread = None
        self._tid = None
        self._proc = None
        self._hook = None
        self._drag = False
        self._moved = False
        self._double = False
        self._last_up_time = 0.0
        self._last_up_pos = None
        self._down_pos = None

    def start(self, on_error=None):
        if self._thread is not None and self._thread.is_alive():
            return

        def loop():
            self._tid = threading.get_ident()
            user32 = ctypes.windll.user32

            def callback(n_code, w_param, l_param):
                if n_code >= 0:
                    try:
                        pt = ctypes.cast(
                            l_param, ctypes.POINTER(MSLLHOOKSTRUCT)
                        ).contents.pt
                    except Exception:
                        pt = None
                    if w_param == WM_LBUTTONDOWN:
                        now = time.time()
                        self._double = (
                            self._last_up_pos is not None
                            and now - self._last_up_time < 0.4
                            and abs(pt.x - self._last_up_pos[0]) < 8
                            and abs(pt.y - self._last_up_pos[1]) < 8
                        )
                        self._drag = True
                        self._moved = False
                        self._down_pos = (pt.x, pt.y) if pt else None
                    elif w_param == WM_MOUSEMOVE and self._drag:
                        self._moved = True
                    elif w_param == WM_LBUTTONUP:
                        was_drag, moved, double = self._drag, self._moved, self._double
                        down = self._down_pos
                        up = (pt.x, pt.y) if pt else None
                        self._drag = False
                        self._moved = False
                        self._double = False
                        self._down_pos = None
                        self._last_up_time = time.time()
                        self._last_up_pos = up
                        if was_drag and up is not None and down is not None:
                            dist = max(abs(up[0] - down[0]), abs(up[1] - down[1]))
                            if double or (moved and dist >= 8):
                                self.on_selection(up[0], up[1])
                return user32.CallNextHookEx(None, n_code, w_param, l_param)

            self._proc = LowLevelMouseProc(callback)
            self._hook = user32.SetWindowsHookExW(
                WH_MOUSE_LL, self._proc, None, 0
            )
            if not self._hook:
                self._hook = None
                if on_error:
                    on_error("划词模式监控启动失败，请重试")
            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
                pass
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None

        thread = threading.Thread(target=loop, daemon=True)
        thread.start()
        self._thread = thread

    def stop(self):
        thread, tid = self._thread, self._tid
        self._thread = None
        self._tid = None
        if thread is not None and thread.is_alive() and tid:
            ctypes.windll.user32.PostThreadMessageW(tid, WM_QUIT, 0, 0)
            thread.join(timeout=1.0)


# ---------------- 单实例保护 ----------------
_SINGLE_INSTANCE_MUTEX = None


def acquire_single_instance(name="AI划词助手_SingleInstance"):
    """防止多开：返回 True 表示本进程是唯一实例。"""
    global _SINGLE_INSTANCE_MUTEX
    handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        if handle:
            ctypes.windll.kernel32.CloseHandle(handle)
        return False
    _SINGLE_INSTANCE_MUTEX = handle
    return True


def bring_existing_to_front(title="AI 划词助手"):
    """唤醒已存在的实例窗口（还原并置前）。"""
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    if hwnd:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
    return bool(hwnd)
