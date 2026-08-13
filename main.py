#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 划词助手 —— 轻量级桌面 AI 对话框

功能：
  1. 划词对话：选中任意程序中的文字，按全局热键，自动捕获选中内容并弹出对话框提问
  2. 读取剪切板：一键把剪切板中的文本放入输入框
  3. 固定于屏幕：置顶开关 + 记住窗口位置与大小

仅依赖 Python 标准库（tkinter + urllib + ctypes），无需安装任何第三方包。
平台相关能力（剪切板 / 全局热键 / 鼠标监听）集中在 win_platform.py，
迁移到其他系统时只需替换该模块。
"""

import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import urllib.error
import urllib.request

from win_platform import (
    ClickAwayWatcher,
    HOTKEY_PRESETS,
    SelectionWatcher,
    HotkeyManager,
    acquire_single_instance,
    apply_dark_titlebar,
    bring_existing_to_front,
    clipboard_sequence,
    enable_dpi_awareness,
    foreground_hwnd,
    get_clipboard_text,
    get_cursor_pos,
    press_ctrl_c,
    real_hwnd,
    set_clipboard_text,
    set_no_activate,
)

if getattr(sys, "frozen", False):
    # PyInstaller 打包后：配置放在 exe 旁边，资源从解包目录读取
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
    BUNDLE_DIR = getattr(sys, "_MEIPASS", APP_DIR)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))
    BUNDLE_DIR = APP_DIR

CONFIG_PATH = os.path.join(APP_DIR, "config.json")
ICON_PATH = os.path.join(BUNDLE_DIR, "icon.ico")

# ---------------- 外观配色 ----------------
BG = "#0e1116"
BG2 = "#161b23"
BG3 = "#1d2430"
INPUT_BG = "#12161d"
BORDER = "#2a3140"
FG = "#e8ecf1"
DIM = "#97a1b1"
FAINT = "#5f6b7d"
ACCENT = "#3d7eff"
ACCENT_ON = "#2f6ae0"
ACCENT_TINT = "#1c2740"
ACCENT_TEXT = "#cfe0ff"
ERROR = "#ff7d7d"
ERROR_TINT = "#3a2226"
ERROR_TEXT = "#ffd0d0"
DANGER = "#7d3a3a"
DANGER_ON = "#a34a4a"
FONT = ("Microsoft YaHei UI", 10)
FONT_SMALL = ("Microsoft YaHei UI", 9)
FONT_TINY = ("Microsoft YaHei UI", 8)
if sys.platform == "darwin":
    FONT = ("PingFang SC", 13)
    FONT_SMALL = ("PingFang SC", 12)
    FONT_TINY = ("PingFang SC", 11)

def styled_button(parent, text, command, kind="ghost", width=None):
    """统一风格的按钮：primary 主操作 / danger 危险 / ghost 常规。"""
    if kind == "primary":
        bg, fg, act = ACCENT_ON, "#ffffff", "#2a5fc9"
    elif kind == "danger":
        bg, fg, act = DANGER, "#ffe3e3", DANGER_ON
    elif kind == "surface":
        bg, fg, act = BG3, FG, "#232c3a"
    else:
        bg, fg, act = BG2, FG, BG3
    border = 0 if kind in ("primary", "danger") else 1
    return tk.Button(
        parent,
        text=text,
        command=command,
        width=width,
        bg=bg,
        fg=fg,
        activebackground=act,
        activeforeground=fg,
        relief="flat",
        bd=0,
        highlightthickness=border,
        highlightbackground=BORDER,
        highlightcolor=ACCENT,
        disabledforeground="#8a94a6",
        padx=10,
        pady=4,
        font=FONT_SMALL,
        cursor="hand2",
    )

# ---------------- 配置 ----------------
DEFAULT_CONFIG = {
    "api": {
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
        "model": "gpt-4o-mini",
        "temperature": 0.7,
        "timeout": 120,
    },
    "hotkey": "Ctrl+Alt+Space",
    "topmost": False,
    "selection_mode": False,
    "system_prompt": "你是一个简洁、可靠的 AI 助手，请用中文回答。",
    "window": {"width": 480, "height": 680, "x": None, "y": None},
}


def _deep_merge(base, override):
    """把用户配置覆盖到默认配置上，保留缺失的默认字段。"""
    out = dict(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            out[key] = _deep_merge(base[key], value)
        else:
            out[key] = value
    return out


def load_config():
    if not os.path.exists(CONFIG_PATH) and os.path.exists(CONFIG_PATH + ".bak"):
        # 主配置意外丢失时，尝试从备份恢复（保留 API 等关键设置）
        try:
            with open(CONFIG_PATH + ".bak", "r", encoding="utf-8") as f:
                data = json.load(f)
            save_config(data)
            return _deep_merge(DEFAULT_CONFIG, data)
        except Exception:
            pass
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return _deep_merge(DEFAULT_CONFIG, json.load(f))
    except Exception:
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(cfg):
    try:
        if os.path.exists(CONFIG_PATH):
            # 覆盖前先备份旧配置，避免设置意外丢失
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    old = json.load(f)
                if old != cfg:
                    with open(CONFIG_PATH + ".bak", "w", encoding="utf-8") as f:
                        json.dump(old, f, ensure_ascii=False, indent=2)
            except Exception:
                pass
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------- API 客户端（兼容 OpenAI 格式） ----------------
def chat_completion(api, messages):
    api_key = (api.get("api_key") or "").strip()
    if not api_key:
        raise RuntimeError("尚未配置 API Key，请点击顶部「设置」填写。")
    url = api["base_url"].rstrip("/") + "/chat/completions"
    payload = {
        "model": api["model"],
        "messages": messages,
        "temperature": float(api.get("temperature", 0.7)),
        "stream": False,
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key,
    }
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), headers=headers
    )
    try:
        with urllib.request.urlopen(request, timeout=int(api.get("timeout", 120))) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("接口返回 HTTP %s：%s" % (exc.code, body[:300]))
    except urllib.error.URLError as exc:
        raise RuntimeError("网络错误：%s" % exc.reason)
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError):
        raise RuntimeError(
            "接口返回格式异常：" + json.dumps(data, ensure_ascii=False)[:300]
        )


def _shorten(text, limit):
    text = text.replace("\r\n", " ").replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


# ---------------- 划词浮窗（仿有道划词） ----------------
class PopupWindow:
    """划词后出现在鼠标附近的迷你浮窗，提供翻译 / 解释 / 问答 / 总结。"""

    def __init__(self, root, on_action):
        self.root = root
        self.on_action = on_action
        self.text = ""
        self.win = None
        self._label = None
        self._click_watcher = ClickAwayWatcher(self.hide, self._popup_rect)

    def _ensure(self):
        if self.win is not None:
            try:
                if self.win.winfo_exists():
                    return
            except tk.TclError:
                pass
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg=BORDER)
        self.win = win
        try:
            set_no_activate(int(win.winfo_id()))
        except Exception:
            pass

        inner = tk.Frame(win, bg=BG2)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        header = tk.Frame(inner, bg=BG2)
        header.pack(fill="x", padx=10, pady=(7, 0))
        tk.Label(
            header,
            text="划词",
            bg=BG2,
            fg=ACCENT,
            font=("Microsoft YaHei UI", 8, "bold"),
        ).pack(side="left")
        tk.Button(
            header,
            text="✕",
            command=self.hide,
            bg=BG2,
            fg=DIM,
            activebackground=DANGER_ON,
            activeforeground="white",
            relief="flat",
            bd=0,
            padx=4,
            pady=1,
            font=FONT_SMALL,
            cursor="hand2",
        ).pack(side="right")

        self._label = tk.Label(
            inner,
            text="",
            bg=BG2,
            fg=FG,
            font=FONT_SMALL,
            wraplength=320,
            justify="left",
            anchor="w",
        )
        self._label.pack(fill="x", padx=10, pady=(3, 2))

        btn_row = tk.Frame(inner, bg=BG2)
        btn_row.pack(fill="x", padx=6, pady=(2, 7))
        for name, action in (
            ("翻译", "translate"),
            ("解释", "explain"),
            ("总结", "summarize"),
            ("润色", "polish"),
            ("问答", "ask"),
        ):
            kind = "primary" if action == "translate" else "ghost"
            button = styled_button(
                btn_row, name, lambda a=action: self._trigger(a), kind
            )
            button.config(padx=8, pady=3)
            button.pack(side="left", padx=2)

        win.bind("<FocusOut>", self._on_focus_out)
        win.bind("<Escape>", lambda e: self.hide())

    def show(self, text, x, y):
        self._ensure()
        self.text = text
        self._label.config(text=_shorten(text, 180))
        win = self.win
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        x = max(0, min(x + 14, max(0, sw - w - 4)))
        y = max(0, min(y + 14, max(0, sh - h - 4)))
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))
        win.deiconify()
        win.lift()
        self._click_watcher.start()

    def hide(self):
        self._click_watcher.stop()
        if self.win is not None:
            try:
                self.win.withdraw()
            except tk.TclError:
                pass

    def _popup_rect(self):
        if self.win is None:
            return (0, 0, 0, 0)
        try:
            x = self.win.winfo_rootx()
            y = self.win.winfo_rooty()
            return (
                x,
                y,
                x + self.win.winfo_width(),
                y + self.win.winfo_height(),
            )
        except tk.TclError:
            return (0, 0, 0, 0)

    def _trigger(self, action):
        self.hide()
        self.on_action(action, self.text)

    def _on_focus_out(self, event):
        if getattr(event, "detail", "") != "NotifyInferior":
            self.hide()


# ---------------- 主界面 ----------------
class AiChatApp:
    def __init__(self, root):
        self.root = root
        self.config = load_config()
        self.history = []
        self.pending_context = ""
        self.busy = False
        self.capture_busy = False
        self._busy_timer = None
        self.reference_files = []  # [{"name": str, "content": str}]
        self.queue = queue.Queue()
        self.settings_win = None
        self.popup = PopupWindow(self.root, self._handle_popup_action)
        self.selection_watcher = SelectionWatcher(self._on_selection_event)

        self._init_window()
        self._build_ui()
        self._load_geometry()
        self._apply_topmost()

        self.hotkeys = HotkeyManager()
        self.hotkeys.start(
            self.config["hotkey"], self._on_hotkey, self._on_hotkey_error
        )
        if self.config.get("selection_mode"):
            self._set_selection_mode(True)
        self._poll_queue()
        self.root.protocol("WM_DELETE_WINDOW", self.quit_app)
        self._update_status()

    # ---------- 窗口基础 ----------
    def _init_window(self):
        self.root.title("AI 划词助手")
        self.root.configure(bg=BG)
        self.root.minsize(380, 500)
        try:
            self.root.iconbitmap(ICON_PATH)
        except Exception:
            pass
        self.root.update_idletasks()
        self._apply_dark_titlebar()

    def _window_hwnd(self):
        return real_hwnd(int(self.root.winfo_id()))

    def _apply_dark_titlebar(self):
        apply_dark_titlebar(self._window_hwnd())

    def _load_geometry(self):
        w = self.config["window"]
        width = max(380, int(w.get("width") or 480))
        height = max(500, int(w.get("height") or 680))
        x, y = w.get("x"), w.get("y")
        if x is None or y is None:
            sw = self.root.winfo_screenwidth()
            sh = self.root.winfo_screenheight()
            x, y = max(0, (sw - width) // 2 - 120), max(0, (sh - height) // 2 - 80)
        self.root.geometry("%dx%d+%d+%d" % (width, height, int(x), int(y)))

    def _save_geometry(self):
        try:
            match = re.match(
                r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", self.root.geometry()
            )
            if match:
                w, h, x, y = (int(v) for v in match.groups())
                self.config["window"].update(
                    {"width": w, "height": h, "x": x, "y": y}
                )
                save_config(self.config)
        except Exception:
            pass

    def _apply_topmost(self):
        self.root.attributes("-topmost", bool(self.config.get("topmost")))

    def _show_window(self):
        if self.root.state() == "withdrawn":
            self.root.deiconify()
        if bool(self.config.get("topmost")) != bool(self.root.attributes("-topmost")):
            self._apply_topmost()
        self.root.lift()
        self.root.focus_force()
        self.input.focus_set()

    def hide_window(self):
        self._save_geometry()
        self.root.withdraw()

    def quit_app(self):
        self._save_geometry()
        self.hotkeys.stop()
        self.selection_watcher.stop()
        self.popup.hide()
        self.root.destroy()

    # ---------- 界面搭建 ----------
    def _build_ui(self):
        self.root.grid_rowconfigure(1, weight=1)
        self.root.grid_columnconfigure(0, weight=1)

        # 顶栏
        topbar = tk.Frame(self.root, bg=BG)
        topbar.grid(row=0, column=0, sticky="ew")
        mark = tk.Label(topbar, text="", bg=ACCENT, width=2)
        mark.pack(side="left", padx=(12, 7), pady=13)
        title = tk.Label(
            topbar,
            text="AI 划词助手",
            bg=BG,
            fg=FG,
            font=("Microsoft YaHei UI", 10, "bold"),
        )
        title.pack(side="left", pady=7)

        self.pin_btn = styled_button(topbar, "固定", self._toggle_pin, "ghost", width=6)
        self.pin_btn.config(padx=6)
        self.pin_btn.pack(side="right", padx=(2, 10), pady=6)
        self.capture_btn = styled_button(
            topbar, "划词", self._toggle_selection_mode, "ghost", width=7
        )
        self.capture_btn.config(padx=6)
        self.capture_btn.pack(side="right", padx=2, pady=6)
        clip_btn = styled_button(
            topbar, "剪切板", self._on_clipboard_btn, "ghost", width=7
        )
        clip_btn.config(padx=6)
        clip_btn.pack(side="right", padx=2, pady=6)
        set_btn = styled_button(topbar, "设置", self.open_settings, "ghost", width=6)
        set_btn.config(padx=6)
        set_btn.pack(side="right", padx=2, pady=6)
        hide_btn = styled_button(topbar, "隐藏", self.hide_window, "ghost", width=6)
        hide_btn.config(padx=6)
        hide_btn.pack(side="right", padx=2, pady=6)

        # 对话区
        chat_frame = tk.Frame(self.root, bg=BG)
        chat_frame.grid(row=1, column=0, sticky="nsew", padx=8, pady=(0, 4))
        chat_frame.grid_rowconfigure(0, weight=1)
        chat_frame.grid_columnconfigure(0, weight=1)
        self.chat = tk.Text(
            chat_frame,
            bg=BG,
            fg=FG,
            wrap="word",
            font=FONT,
            relief="flat",
            bd=0,
            padx=12,
            pady=10,
            selectbackground=ACCENT_ON,
            selectforeground="#ffffff",
            insertbackground=BG,
        )
        scroll = tk.Scrollbar(
            chat_frame,
            command=self.chat.yview,
            bg=BG2,
            troughcolor=BG,
            activebackground=ACCENT,
            relief="flat",
        )
        self.chat.configure(yscrollcommand=scroll.set)
        self.chat.grid(row=0, column=0, sticky="nsew")
        scroll.grid(row=0, column=1, sticky="ns")
        # 对话区保持可选中/可复制，但拦截输入键防止编辑
        self.chat.bind("<Key>", self._block_chat_edit)
        self.chat_menu = tk.Menu(self.chat, tearoff=0, bg=BG2, fg=FG,
                                 activebackground=ACCENT_ON, activeforeground="white")
        self.chat_menu.add_command(label="复制", command=self._copy_chat_selection)
        self.chat_menu.add_command(label="全选", command=self._select_all_chat)
        self.chat.bind("<Button-3>", self._show_chat_menu)
        self._config_chat_tags()
        self._append_chat(
            "提示",
            "欢迎使用 AI 划词助手\n\n开启顶部「划词」后，在其他窗口选中文字即可弹出浮窗；\n也可以选中文字后按 Ctrl+Alt+Space。\n在「设置」中配置 API 后即可开始对话。",
            "meta",
        )

        # 划词快捷动作（有划词内容时显示）
        self.quick_frame = tk.Frame(self.root, bg=BG)
        self.quick_frame.grid(row=2, column=0, sticky="ew", padx=8)
        self.quick_frame.grid_remove()
        self.quick_actions = [
            ("翻译", "请把这段内容翻译成中文，简洁准确："),
            ("解释", "请解释这段内容："),
            ("总结", "请用 3 点总结这段内容的要点："),
            ("润色", "请将这段内容润色为学术英语，保持原意，用词正式、表达严谨："),
        ]

        # 输入区
        input_frame = tk.Frame(self.root, bg=BG)
        input_frame.grid(row=3, column=0, sticky="ew", padx=8, pady=(6, 4))
        input_frame.grid_columnconfigure(0, weight=1)
        self.input = tk.Text(
            input_frame,
            height=3,
            bg=INPUT_BG,
            fg=FG,
            insertbackground=FG,
            wrap="word",
            font=FONT,
            relief="flat",
            bd=0,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
            padx=12,
            pady=8,
            selectbackground=ACCENT_ON,
            selectforeground="#ffffff",
        )
        self.input.grid(row=0, column=0, sticky="ew")
        self.input.bind("<Return>", self._on_return)
        self.input.bind("<Control-Return>", self._on_return)
        self.input.bind("<Shift-Return>", self._on_return)

        # 发送行
        send_row = tk.Frame(self.root, bg=BG)
        send_row.grid(row=4, column=0, sticky="ew", padx=8, pady=(2, 4))
        send_row.grid_columnconfigure(0, weight=1)
        self.status_label = tk.Label(
            send_row, text="", bg=BG, fg=DIM, font=FONT_TINY, anchor="w"
        )
        self.status_label.grid(row=0, column=0, sticky="w")
        self.upload_btn = styled_button(send_row, "上传", self._on_upload_btn, "ghost")
        self.upload_btn.config(padx=8)
        self.upload_btn.grid(row=0, column=1, sticky="e", padx=(0, 4))
        self.clear_ref_btn = styled_button(
            send_row, "清除参考", self._clear_reference, "ghost"
        )
        self.clear_ref_btn.config(padx=8)
        self.clear_ref_btn.grid(row=0, column=2, sticky="e", padx=(0, 4))
        self.clear_ref_btn.grid_remove()
        self.test_btn = styled_button(send_row, "测试接口", self._test_api, "ghost")
        self.test_btn.config(padx=8)
        self.test_btn.grid(row=0, column=3, sticky="e", padx=(0, 6))
        self.send_btn = styled_button(send_row, "发送 (Enter)", self._send, "primary")
        self.send_btn.config(width=10)
        self.send_btn.grid(row=0, column=4, sticky="e")

    def _config_chat_tags(self):
        self.chat.tag_configure(
            "user",
            background=ACCENT_TINT,
            foreground=ACCENT_TEXT,
            lmargin1=120,
            lmargin2=120,
            rmargin=10,
            spacing1=8,
            spacing3=4,
            justify="left",
        )
        self.chat.tag_configure(
            "assistant",
            background=BG2,
            foreground=FG,
            lmargin1=10,
            lmargin2=10,
            rmargin=10,
            spacing1=8,
            spacing3=4,
            justify="left",
        )
        self.chat.tag_configure(
            "context",
            foreground=DIM,
            font=FONT_SMALL,
            justify="center",
            spacing1=8,
            spacing3=2,
        )
        self.chat.tag_configure(
            "meta",
            foreground=DIM,
            font=FONT_SMALL,
            justify="center",
            spacing1=8,
            spacing3=2,
        )
        self.chat.tag_configure(
            "error",
            background=ERROR_TINT,
            foreground=ERROR_TEXT,
            lmargin1=10,
            lmargin2=10,
            rmargin=10,
            spacing1=8,
            spacing3=4,
            justify="left",
        )
        # 选中高亮置于气泡背景之上，保证拖动选词时有明显高亮
        self.chat.tag_raise("sel")

    def _append_chat(self, who, content, kind):
        self.chat.insert("end", "\n")
        if kind == "user":
            self.chat.insert("end", content, "user")
        elif kind == "assistant":
            self.chat.insert("end", content, "assistant")
        elif kind == "context":
            self.chat.insert("end", "已划词  " + content, "context")
        elif kind == "error":
            self.chat.insert("end", "提示  " + content, "error")
        else:
            self.chat.insert("end", content, "meta")
        self.chat.insert("end", "\n")
        self.chat.see("end")

    _CHAT_ALLOW_KEYS = {
        "Home", "End", "Left", "Right", "Up", "Down", "Next", "Prior",
        "Shift_L", "Shift_R", "Control_L", "Control_R", "Alt_L", "Alt_R",
        "Escape", "Tab",
    }

    def _block_chat_edit(self, event):
        """对话区允许复制/导航，但禁止输入与删除。"""
        ctrl = bool(event.state & 0x0004)
        key = getattr(event, "keysym", "")
        if ctrl and key.lower() in ("c", "a", "insert"):
            return None
        if key in self._CHAT_ALLOW_KEYS:
            return None
        return "break"

    def _show_chat_menu(self, event):
        try:
            self.chat_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.chat_menu.grab_release()

    def _copy_chat_selection(self):
        try:
            selected = self.chat.get("sel.first", "sel.last")
        except tk.TclError:
            selected = ""
        if selected:
            set_clipboard_text(selected)
            self._update_status("已复制 %d 字" % len(selected))

    def _select_all_chat(self):
        self.chat.tag_add("sel", "1.0", "end-1c")
        self.chat.mark_set("insert", "end-1c")

    def _update_quick_actions(self):
        for child in self.quick_frame.winfo_children():
            child.destroy()
        if not self.pending_context:
            self.quick_frame.grid_remove()
            return
        label = tk.Label(
            self.quick_frame, text="划词内容已就绪", bg=BG, fg=DIM, font=FONT_TINY
        )
        label.pack(side="left", padx=(0, 6))
        for name, prompt in self.quick_actions:
            button = styled_button(
                self.quick_frame,
                name,
                lambda p=prompt: self._quick_ask(p),
                "surface",
            )
            button.config(padx=8, pady=3)
            button.pack(side="left", padx=2, pady=3)
        self.quick_frame.grid()

    # ---------- 状态 ----------
    def _default_status(self):
        parts = []
        if self.reference_files:
            parts.append("参考 %d 个文件" % len(self.reference_files))
        parts.append("热键 %s" % self.config["hotkey"])
        parts.append("模型 %s" % self.config["api"].get("model", ""))
        return " · ".join(parts)

    def _update_status(self, message=None):
        self.status_label.config(text=message if message is not None else self._default_status())

    # ---------- 功能：置顶固定 ----------
    def _toggle_pin(self):
        self.config["topmost"] = not bool(self.config.get("topmost"))
        self._apply_topmost()
        save_config(self.config)
        self.pin_btn.config(
            text="固定：开" if self.config["topmost"] else "固定",
            bg=ACCENT_ON if self.config["topmost"] else BG2,
            activebackground="#2a5fc9" if self.config["topmost"] else BG3,
        )
        self._update_status("已固定于屏幕" if self.config["topmost"] else "已取消固定")

    # ---------- 功能：划词模式（开关 + 全局鼠标监听） ----------
    def _on_hotkey(self):
        self.queue.put({"type": "hotkey"})

    def _on_hotkey_error(self, message):
        self.queue.put({"type": "hotkey_error", "message": message})

    def _handle_hotkey(self):
        # 热键是备用方式：主窗口始终不隐藏
        if self._window_is_foreground():
            self._show_window()
            return
        x, y = get_cursor_pos()
        self._capture_and_popup(x, y, show_window_if_empty=True)

    def _on_selection_event(self, x, y):
        self.queue.put({"type": "selection", "x": x, "y": y})

    def _handle_selection_event(self, x, y):
        # 稍等目标程序完成选区处理，再模拟复制
        self.root.after(160, lambda: self._capture_and_popup(x, y, False))

    def _toggle_selection_mode(self):
        self._set_selection_mode(not bool(self.config.get("selection_mode")))

    def _set_selection_mode(self, on):
        self.config["selection_mode"] = bool(on)
        save_config(self.config)
        if on:
            self.selection_watcher.start(self._on_watcher_error)
            self.capture_btn.config(
                text="划词：开", bg=ACCENT_ON, activebackground="#2a5fc9"
            )
            self._update_status("划词模式已开启：请在其他窗口用鼠标选中文字")
        else:
            self.selection_watcher.stop()
            self.capture_btn.config(text="划词", bg=BG2, activebackground=BG3)
            self.popup.hide()
            self._update_status("划词模式已关闭")

    def _on_watcher_error(self, message):
        self.queue.put({"type": "watcher_error", "message": message})

    def _capture_and_popup(self, x, y, show_window_if_empty=False):
        if self.capture_busy:
            return
        if self._our_window_foreground():
            if show_window_if_empty:
                self._show_window()
            return
        self.capture_busy = True
        try:
            captured = self._capture_selection()
        except Exception:
            captured = ""
        self.capture_busy = False
        if captured:
            self.popup.show(captured, x, y)
        elif show_window_if_empty:
            self._show_window()
            self._update_status("未捕获到选中文字，可直接输入提问")
            self.input.focus_set()

    def _capture_selection(self):
        # 只有复制真正发生后（剪切板序列号变化）才视为划词成功，
        # 避免把剪切板里的旧内容误当成划词结果。
        seq_before = clipboard_sequence()
        previous = get_clipboard_text()
        captured = ""
        try:
            press_ctrl_c()
            time.sleep(0.15)
            if clipboard_sequence() != seq_before:
                captured = (get_clipboard_text() or "").strip()
        finally:
            set_clipboard_text(previous)
        return captured

    def _our_window_foreground(self):
        fg = foreground_hwnd()
        if not fg:
            return False
        ours = [self._window_hwnd()]
        if self.popup.win is not None:
            try:
                ours.append(int(self.popup.win.winfo_id()))
            except tk.TclError:
                pass
        if self.settings_win is not None and self.settings_win.winfo_exists():
            ours.append(int(self.settings_win.winfo_id()))
        return fg in ours

    def _handle_popup_action(self, action, text):
        """浮窗按钮：翻译/解释/总结 直接回主窗口发起请求，问答进入待提问状态。"""
        if not text:
            return
        self.pending_context = text
        self._append_chat("划词", _shorten(text, 260), "context")
        self._update_quick_actions()
        if action == "ask":
            self._show_window()
            self._update_status("已划词 %d 字，可直接提问" % len(text))
            return
        if self.busy:
            self._show_window()
            self._update_status("正在处理上一条，请稍候")
            return
        prompts = {
            "translate": "请把这段内容翻译成中文，简洁准确：",
            "explain": "请解释这段内容：",
            "summarize": "请用 3 点总结这段内容的要点：",
            "polish": "请将这段内容润色为学术英语，保持原意，用词正式、表达严谨：",
        }
        prompt = prompts.get(action, prompts["explain"])
        self._show_window()
        self._submit(prompt, prompt)

    def _window_is_foreground(self):
        foreground = foreground_hwnd()
        return bool(foreground) and foreground == self._window_hwnd()

    # ---------- 功能：读取剪切板 ----------
    def _on_clipboard_btn(self):
        try:
            text = (get_clipboard_text() or "").strip()
        except Exception:
            text = ""
        if not text:
            self._update_status("剪切板中没有文本内容")
            return
        self.input.insert("insert", text + "\n")
        self.input.focus_set()
        self._update_status("已读取剪切板（%d 字）" % len(text))

    # ---------- 功能：上传参考文件 ----------
    MAX_FILE_BYTES = 512 * 1024
    MAX_FILE_CHARS = 30000

    def _on_upload_btn(self):
        paths = filedialog.askopenfilenames(
            parent=self.root,
            title="选择参考文件（可多选）",
            filetypes=[
                ("支持的文件", "*.pdf *.docx *.txt *.md *.py *.json *.csv *.log *.c *.cpp *.h *.js *.ts *.html *.css *.xml *.yaml *.yml *.ini *.toml *.sql *.doc"),
                ("PDF 文档", "*.pdf"),
                ("Word 文档", "*.docx *.doc"),
                ("所有文件", "*.*"),
            ],
        )
        if not paths:
            return
        added, skipped = [], []
        for path in paths:
            name = os.path.basename(path)
            content = self._read_reference_file(path)
            if content is None:
                skipped.append(name)
                continue
            self.reference_files.append({"name": name, "content": content})
            added.append((name, len(content)))
        if added:
            for name, size in added:
                self._append_chat("参考", "%s（%d 字）" % (name, size), "context")
            self._refresh_reference_ui()
            self._update_status("已添加 %d 个参考文件" % len(added))
        if skipped:
            self._update_status("无法读取：%s（格式不支持或内容为空）" % "、".join(skipped[:3]))

    def _read_reference_file(self, path):
        """按扩展名分发读取参考文件；失败返回 None。"""
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            return self._read_pdf(path)
        if ext in (".docx", ".docm"):
            return self._read_docx(path)
        return self._read_text_file(path)

    def _cap_text(self, text):
        if len(text) > self.MAX_FILE_CHARS:
            text = text[: self.MAX_FILE_CHARS] + "\n…（内容过长已截断）"
        return text

    def _read_text_file(self, path):
        """读取纯文本文件；二进制/不可读返回 None。"""
        try:
            with open(path, "rb") as f:
                raw = f.read(self.MAX_FILE_BYTES)
        except OSError:
            return None
        if not raw or b"\x00" in raw[:4096]:
            return None
        text = None
        for enc in ("utf-8", "gbk"):
            try:
                text = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            text = raw.decode("utf-8", errors="replace")
        return self._cap_text(text.strip())

    def _read_docx(self, path):
        """读取 Word .docx 文本（docx 本质是 zip+XML，纯标准库解析）。"""
        try:
            import zipfile
            from xml.etree import ElementTree as ET

            with zipfile.ZipFile(path) as z:
                xml_data = z.read("word/document.xml")
            root = ET.fromstring(xml_data)
            ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
            paras = []
            for p in root.iter(ns + "p"):
                text = "".join(t.text or "" for t in p.iter(ns + "t")).strip()
                if text:
                    paras.append(text)
            content = self._cap_text("\n".join(paras))
            return content if content.strip() else None
        except Exception:
            return None

    def _read_pdf(self, path):
        """读取 PDF 文本（使用 pypdf，支持中文字体与分页）。"""
        try:
            from pypdf import PdfReader
        except ImportError:
            return None
        try:
            reader = PdfReader(path)
            parts = []
            total = 0
            for i, page in enumerate(reader.pages):
                text = (page.extract_text() or "").strip()
                if text:
                    parts.append("（第 %d 页）\n%s" % (i + 1, text))
                    total += len(text)
                    if total >= self.MAX_FILE_CHARS:
                        break
            content = self._cap_text("\n\n".join(parts))
            return content if content.strip() else None
        except Exception:
            return None

    def _refresh_reference_ui(self):
        if self.reference_files:
            self.clear_ref_btn.grid()
        else:
            self.clear_ref_btn.grid_remove()
        self._update_status()

    def _clear_reference(self):
        if not self.reference_files:
            return
        self.reference_files = []
        self._refresh_reference_ui()
        self._append_chat("提示", "已清除参考文件。", "meta")

    # ---------- 发送与回复 ----------
    def _on_return(self, event=None):
        if event is not None and (event.state & (0x0004 | 0x0001)):
            self.input.insert("insert", "\n")
            return "break"
        self._send()
        return "break"

    def _send(self):
        text = self.input.get("1.0", "end-1c").strip()
        if not text or self.busy:
            return
        self.input.delete("1.0", "end")
        self._submit(text, text)

    def _quick_ask(self, prompt):
        if self.busy:
            return
        self._submit(prompt, prompt)

    def _submit(self, user_content, display_text):
        parts = []
        if self.pending_context:
            parts.append("【划词内容】\n%s" % self.pending_context)
            self.pending_context = ""
        for rf in self.reference_files:
            parts.append("【参考文件：%s】\n%s" % (rf["name"], rf["content"]))
        if parts:
            parts.append(user_content)
            user_content = "\n\n".join(parts)
        self._update_quick_actions()
        self.history.append({"role": "user", "content": user_content})
        self._append_chat("你", display_text, "user")
        self._start_busy()
        threading.Thread(
            target=self._worker, args=(list(self.history),), daemon=True
        ).start()

    def _start_busy(self):
        self.busy = True
        self.send_btn.config(state="disabled", text="思考中…")
        self._update_status("思考中…")
        dots = [0]

        def tick():
            if not self.busy:
                return
            dots[0] = (dots[0] + 1) % 4
            self._update_status("思考中" + "." * dots[0])
            self._busy_timer = self.root.after(320, tick)

        self._busy_timer = self.root.after(320, tick)

    def _finish_busy(self):
        self.busy = False
        if self._busy_timer:
            try:
                self.root.after_cancel(self._busy_timer)
            except Exception:
                pass
            self._busy_timer = None
        self.send_btn.config(state="normal", text="发送 (Enter)")

    def _worker(self, messages):
        try:
            system_prompt = (self.config.get("system_prompt") or "").strip()
            payload = []
            if system_prompt:
                payload.append({"role": "system", "content": system_prompt})
            payload.extend(messages)
            reply = chat_completion(self.config["api"], payload)
            self.queue.put({"type": "assistant", "content": reply})
        except Exception as exc:
            self.queue.put({"type": "error", "message": str(exc)})

    def _poll_queue(self):
        try:
            while True:
                item = self.queue.get_nowait()
                self._handle_item(item)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _handle_item(self, item):
        kind = item.get("type")
        if kind == "hotkey":
            self._handle_hotkey()
        elif kind == "selection":
            self._handle_selection_event(item.get("x", 0), item.get("y", 0))
        elif kind == "watcher_error":
            self._set_selection_mode(False)
            self._update_status(item.get("message", "划词模式启动失败"))
        elif kind == "hotkey_error":
            self._append_chat("提示", item.get("message", ""), "error")
            self._update_status("热键注册失败")
        elif kind == "assistant":
            self.history.append({"role": "assistant", "content": item["content"]})
            self._append_chat("AI", item["content"], "assistant")
            self._finish_busy()
            self._update_status()
        elif kind == "error":
            self._append_chat("提示", item["message"], "error")
            self._finish_busy()
            self._update_status()
        elif kind == "test_result":
            parent = self.settings_win or self.root
            if item.get("ok"):
                messagebox.showinfo("测试成功", item.get("message"), parent=parent)
            else:
                messagebox.showerror("测试失败", item.get("message"), parent=parent)

    # ---------- 设置窗口 ----------
    def open_settings(self):
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            self.settings_win.focus_force()
            return
        win = tk.Toplevel(self.root)
        win.title("设置")
        win.configure(bg=BG)
        win.attributes("-topmost", True)
        win.resizable(True, True)
        win.minsize(430, 380)
        self.settings_win = win
        win.protocol("WM_DELETE_WINDOW", lambda: self.settings_win.destroy())
        win.bind("<Destroy>", lambda e: setattr(self, "settings_win", None) if e.widget is win else None)

        api = self.config["api"]
        self.base_url_var = tk.StringVar(value=api.get("base_url", ""))
        self.api_key_var = tk.StringVar(value=api.get("api_key", ""))
        self.model_var = tk.StringVar(value=api.get("model", ""))
        self.temp_var = tk.StringVar(value=str(api.get("temperature", 0.7)))
        self.hotkey_var = tk.StringVar(value=self.config.get("hotkey", "Ctrl+Alt+Space"))

        def row(label, widget, r):
            tk.Label(win, text=label, bg=BG, fg=FG, font=FONT_SMALL, anchor="w").grid(
                row=r, column=0, sticky="w", padx=(12, 8), pady=6
            )
            widget.grid(row=r, column=1, sticky="ew", padx=(0, 12), pady=6)

        win.grid_columnconfigure(1, weight=1)

        entry_bg = tk.Entry(win, textvariable=self.base_url_var, bg=INPUT_BG, fg=FG,
                            insertbackground=FG, relief="flat", bd=0,
                            highlightthickness=1, highlightbackground=BORDER,
                            highlightcolor=ACCENT, font=FONT_SMALL)
        row("API 地址", entry_bg, 0)

        key_frame = tk.Frame(win, bg=BG)
        key_entry = tk.Entry(key_frame, textvariable=self.api_key_var, show="*", bg=INPUT_BG,
                             fg=FG, insertbackground=FG, relief="flat", bd=0,
                             highlightthickness=1, highlightbackground=BORDER,
                             highlightcolor=ACCENT, font=FONT_SMALL)
        key_entry.pack(side="left", fill="x", expand=True)
        show_var = tk.BooleanVar(value=False)
        tk.Checkbutton(key_frame, text="显示", variable=show_var, bg=BG, fg=DIM,
                       activebackground=BG, selectcolor=BG2,
                       command=lambda: key_entry.config(show="" if show_var.get() else "*"),
                       font=FONT_TINY).pack(side="left", padx=6)
        row("API Key", key_frame, 1)

        model_entry = tk.Entry(win, textvariable=self.model_var, bg=INPUT_BG, fg=FG,
                               insertbackground=FG, relief="flat", bd=0,
                               highlightthickness=1, highlightbackground=BORDER,
                               highlightcolor=ACCENT, font=FONT_SMALL)
        row("模型", model_entry, 2)

        temp_entry = tk.Entry(win, textvariable=self.temp_var, width=8, bg=INPUT_BG,
                              fg=FG, insertbackground=FG, relief="flat", bd=0,
                              highlightthickness=1, highlightbackground=BORDER,
                              highlightcolor=ACCENT, font=FONT_SMALL)
        row("温度 (0-2)", temp_entry, 3)

        combo = ttk.Combobox(win, textvariable=self.hotkey_var, values=list(HOTKEY_PRESETS),
                             state="readonly", font=FONT_SMALL)
        try:
            style = ttk.Style(win)
            style.theme_use("clam")
            style.configure("TCombobox", fieldbackground=INPUT_BG, background=INPUT_BG,
                            foreground=FG, arrowcolor=FG)
        except Exception:
            pass
        row("全局热键", combo, 4)

        tk.Label(win, text="系统提示词", bg=BG, fg=FG, font=FONT_SMALL, anchor="w").grid(
            row=5, column=0, sticky="nw", padx=(12, 8), pady=6
        )
        self.system_var = tk.Text(win, height=4, bg=INPUT_BG, fg=FG, insertbackground=FG,
                                  relief="flat", bd=0, highlightthickness=1,
                                  highlightbackground=BORDER, highlightcolor=ACCENT,
                                  font=FONT_SMALL, wrap="word")
        self.system_var.insert("1.0", self.config.get("system_prompt", ""))
        self.system_var.grid(row=5, column=1, sticky="ew", padx=(0, 12), pady=6)

        btn_row = tk.Frame(win, bg=BG)
        btn_row.grid(row=6, column=0, columnspan=2, sticky="ew", padx=12, pady=(4, 10))
        for text, command, kind in (
            ("测试连接", lambda: self._test_api(), "ghost"),
            ("保存", self._save_settings, "primary"),
            ("清空对话", self._clear_history, "ghost"),
            ("退出应用", self.quit_app, "danger"),
        ):
            styled_button(btn_row, text, command, kind).pack(side="left", padx=3)

        hint = tk.Label(win, text="接口需兼容 OpenAI Chat Completions 格式（OpenAI / DeepSeek / Kimi / Qwen 等均可）。",
                        bg=BG, fg=DIM, font=FONT_TINY, wraplength=380, justify="left")
        hint.grid(row=7, column=0, columnspan=2, sticky="w", padx=12, pady=(0, 10))

        win.update_idletasks()
        self._center_toplevel(win)

    def _center_toplevel(self, win):
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w = min(win.winfo_reqwidth(), max(430, sw - 40))
        h = min(win.winfo_reqheight(), max(380, sh - 60))
        x = self.root.winfo_x() + max(0, (self.root.winfo_width() - w) // 2)
        y = self.root.winfo_y() + max(0, (self.root.winfo_height() - h) // 2)
        x = max(0, min(x, max(0, sw - w)))
        y = max(0, min(y, max(0, sh - h)))
        win.geometry("%dx%d+%d+%d" % (w, h, x, y))

    def _test_api(self):
        if self.settings_win is not None and self.settings_win.winfo_exists():
            api = self._settings_to_api()
            self.settings_win.attributes("-topmost", False)
        else:
            api = dict(self.config["api"])

        def worker():
            try:
                payload = [{"role": "user", "content": "请只回复：连接成功"}]
                system_prompt = self.config.get("system_prompt", "").strip()
                if self.settings_win is not None and self.settings_win.winfo_exists():
                    system_prompt = self.system_var.get("1.0", "end-1c").strip()
                if system_prompt:
                    payload.insert(0, {"role": "system", "content": system_prompt})
                reply = chat_completion(api, payload)
                self.queue.put({"type": "test_result", "ok": True, "message": reply})
            except Exception as exc:
                self.queue.put({"type": "test_result", "ok": False, "message": str(exc)})

        threading.Thread(target=worker, daemon=True).start()

    def _settings_to_api(self):
        api = dict(self.config["api"])
        api["base_url"] = self.base_url_var.get().strip()
        api["api_key"] = self.api_key_var.get().strip()
        api["model"] = self.model_var.get().strip()
        try:
            api["temperature"] = max(0.0, min(2.0, float(self.temp_var.get())))
        except ValueError:
            api["temperature"] = 0.7
        return api

    def _save_settings(self):
        api = self._settings_to_api()
        self.config["api"] = api
        self.config["system_prompt"] = self.system_var.get("1.0", "end-1c").strip()
        combo = self.hotkey_var.get()
        if combo in HOTKEY_PRESETS:
            self.config["hotkey"] = combo
        save_config(self.config)
        self.hotkeys.start(self.config["hotkey"], self._on_hotkey, self._on_hotkey_error)
        self._update_status("设置已保存 · 热键 " + self.config["hotkey"])
        if self.settings_win is not None:
            self.settings_win.destroy()

    def _clear_history(self):
        self.history = []
        self.pending_context = ""
        self._update_quick_actions()
        self.chat.delete("1.0", "end")
        self._append_chat("提示", "对话已清空。", "meta")


# ---------------- 自检 ----------------
def _log(message=""):
    """打包为无控制台 exe 时 sys.stdout 为 None，打印前先判断。"""
    if sys.stdout:
        print(message)


def selftest():
    _log("== AI 划词助手自检 ==")
    previous = get_clipboard_text()
    set_clipboard_text("AI划词助手自检文本")
    got = get_clipboard_text()
    set_clipboard_text(previous)
    if got != "AI划词助手自检文本":
        _log("剪切板读写失败：%r" % got)
        return False
    _log("剪切板读写: OK")

    root = tk.Tk()
    app = AiChatApp(root)
    root.update_idletasks()
    root.after(700, root.destroy)
    root.mainloop()
    app.hotkeys.stop()
    _log("界面与热键初始化: OK")
    return True


def main():
    enable_dpi_awareness()
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    if not acquire_single_instance():
        # 已有实例在运行：唤醒它的窗口，本进程直接退出
        bring_existing_to_front()
        return
    root = tk.Tk()
    AiChatApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
