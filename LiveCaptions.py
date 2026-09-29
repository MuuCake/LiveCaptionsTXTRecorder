import os
import re
import time
import queue
import base64
import ctypes
import winreg
import subprocess
import threading

from datetime import datetime
from difflib import SequenceMatcher

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import win32gui
import win32api
import win32con
import pythoncom

from pywinauto import Desktop


# ============================================================
# Configuration
# ============================================================

POLL_INTERVAL = 0.25
LIVE_CAPTIONS_CHECK_INTERVAL = 750
THEME_CHECK_INTERVAL = 1500

MISMATCH_GRACE = 1.00
FUZZY_THRESHOLD = 0.80

MIN_FUZZY_LENGTH = 20
MIN_EXACT_OVERLAP = 8

RECENT_HISTORY_LIMIT = 20000
LONG_REPEAT_MIN = 80

INVALID_FILENAME_CHARS = r'[<>:"/\\|?*]'


# ============================================================
# High DPI support
# ============================================================

def enable_high_dpi_awareness():

    # Per-Monitor DPI Awareness V2
    try:
        user32 = ctypes.windll.user32

        user32.SetProcessDpiAwarenessContext.argtypes = [
            ctypes.c_void_p
        ]

        user32.SetProcessDpiAwarenessContext.restype = (
            ctypes.c_bool
        )

        result = (
            user32.SetProcessDpiAwarenessContext(
                ctypes.c_void_p(-4)
            )
        )

        if result:
            return

    except Exception:
        pass

    # Windows 8.1+ fallback
    try:
        shcore = ctypes.windll.shcore

        shcore.SetProcessDpiAwareness.argtypes = [
            ctypes.c_int
        ]

        shcore.SetProcessDpiAwareness.restype = (
            ctypes.c_long
        )

        shcore.SetProcessDpiAwareness(2)

        return

    except Exception:
        pass

    # Older Windows fallback
    try:
        ctypes.windll.user32.SetProcessDPIAware()

    except Exception:
        pass


def configure_tk_dpi(root):

    try:

        root.update_idletasks()

        hwnd = root.winfo_id()

        dpi = (
            ctypes.windll.user32.GetDpiForWindow(
                hwnd
            )
        )

        if dpi:

            scaling = (
                float(dpi)
                /
                72.0
            )

            root.tk.call(
                "tk",
                "scaling",
                scaling
            )

    except Exception:
        pass


# ============================================================
# Text helpers
# ============================================================

def normalize_text(text):

    if not text:
        return ""

    text = str(text)

    text = text.replace(
        "\r\n",
        "\n"
    )

    text = text.replace(
        "\r",
        "\n"
    )

    parts = []

    for line in text.split("\n"):

        line = line.strip()

        line = re.sub(
            r"[ \t]+",
            " ",
            line
        )

        if line:
            parts.append(
                line
            )

    return " ".join(parts).strip()


# ============================================================
# Windows theme detection
# ============================================================

def is_windows_dark_mode():

    try:

        key_path = (
            r"Software\Microsoft\Windows"
            r"\CurrentVersion\Themes\Personalize"
        )

        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            key_path
        ) as key:

            value, _ = (
                winreg.QueryValueEx(
                    key,
                    "AppsUseLightTheme"
                )
            )

        return value == 0

    except Exception:

        return False


# ============================================================
# Main application
# ============================================================

class LiveCaptionsRecorder:

    def __init__(self, root):

        self.root = root

        self.root.title(
            "Live Captions TXT Recorder"
        )

        self.root.geometry(
            "860x510"
        )

        self.root.minsize(
            780,
            480
        )

        self.root.resizable(
            True,
            True
        )

        pythoncom.CoInitialize()

        # ----------------------------------------------------
        # Recording state
        # ----------------------------------------------------

        self.recording = False
        self.paused = False
        self.auto_stopping = False

        self.stop_event = (
            threading.Event()
        )

        self.worker_thread = None

        self.message_queue = (
            queue.Queue()
        )

        # ----------------------------------------------------
        # Windows Live Captions state
        # ----------------------------------------------------

        self.live_available = False

        self.live_hwnd = None
        self.live_window = None
        self.caption_control = None

        # ----------------------------------------------------
        # Caption processing state
        # ----------------------------------------------------

        self.last_snapshot = ""
        self.history_text = ""

        self.mismatch_started = None
        self.mismatch_latest = ""

        # ----------------------------------------------------
        # Output
        # ----------------------------------------------------

        self.file_handle = None
        self.output_path = None

        default_folder = os.path.join(
            os.path.expanduser("~"),
            "Documents"
        )

        self.save_folder = tk.StringVar(
            value=default_folder
        )

        self.filename = tk.StringVar(
            value=self.make_default_filename()
        )

        self.status_text = tk.StringVar(
            value=(
                "Checking Windows Live Captions..."
            )
        )

        # ----------------------------------------------------
        # Theme
        # ----------------------------------------------------

        self.current_dark_mode = None

        self.style = ttk.Style(
            self.root
        )

        # ----------------------------------------------------
        # Build UI
        # ----------------------------------------------------

        self.build_ui()

        self.apply_system_theme(
            force=True
        )

        self.root.after(
            200,
            lambda: self.apply_system_theme(
                force=True
            )
        )

        # ----------------------------------------------------
        # Background UI timers
        # ----------------------------------------------------

        self.root.after(
            100,
            self.process_messages
        )

        self.root.after(
            THEME_CHECK_INTERVAL,
            self.watch_system_theme
        )

        self.root.protocol(
            "WM_DELETE_WINDOW",
            self.on_close
        )

        # ----------------------------------------------------
        # Automatically open Windows Live Captions
        # ----------------------------------------------------

        self.root.after(
            500,
            self.startup_live_captions
        )

    # ========================================================
    # Default file name
    # ========================================================

    def make_default_filename(self):

        return datetime.now().strftime(
            "LiveCaptions_%Y-%m-%d_%H-%M-%S.txt"
        )

    # ========================================================
    # Build interface
    # ========================================================

    def build_ui(self):

        self.main_frame = ttk.Frame(
            self.root,
            style="App.TFrame",
            padding=(34, 26)
        )

        self.main_frame.pack(
            fill="both",
            expand=True
        )

        # ----------------------------------------------------
        # Title
        # ----------------------------------------------------

        self.title_label = ttk.Label(
            self.main_frame,
            text="Live Captions TXT Recorder",
            style="Title.TLabel"
        )

        self.title_label.pack(
            anchor="w",
            pady=(0, 5)
        )

        self.subtitle_label = ttk.Label(
            self.main_frame,
            text="Windows Live Captions  ->  TXT",
            style="Subtitle.TLabel"
        )

        self.subtitle_label.pack(
            anchor="w",
            pady=(0, 28)
        )

        # ----------------------------------------------------
        # Settings card
        # ----------------------------------------------------

        self.form_frame = ttk.Frame(
            self.main_frame,
            style="Card.TFrame",
            padding=(22, 20)
        )

        self.form_frame.pack(
            fill="x"
        )

        self.form_frame.columnconfigure(
            1,
            weight=1
        )

        # Save location

        self.save_location_label = ttk.Label(
            self.form_frame,
            text="Save Location:",
            style="Body.TLabel"
        )

        self.save_location_label.grid(
            row=0,
            column=0,
            sticky="w",
            padx=(0, 14),
            pady=(0, 14)
        )

        self.folder_entry = ttk.Entry(
            self.form_frame,
            textvariable=self.save_folder,
            style="Modern.TEntry"
        )

        self.folder_entry.grid(
            row=0,
            column=1,
            sticky="ew",
            pady=(0, 14)
        )

        self.choose_button = ttk.Button(
            self.form_frame,
            text="Choose Save...",
            style="Secondary.TButton",
            command=self.choose_save_path
        )

        self.choose_button.grid(
            row=0,
            column=2,
            padx=(12, 0),
            pady=(0, 14)
        )

        # File name

        self.filename_label = ttk.Label(
            self.form_frame,
            text="File Name:",
            style="Body.TLabel"
        )

        self.filename_label.grid(
            row=1,
            column=0,
            sticky="w",
            padx=(0, 14)
        )

        self.filename_entry = ttk.Entry(
            self.form_frame,
            textvariable=self.filename,
            style="Modern.TEntry"
        )

        self.filename_entry.grid(
            row=1,
            column=1,
            columnspan=2,
            sticky="ew"
        )

        # ----------------------------------------------------
        # Main buttons
        # ----------------------------------------------------

        self.button_frame = ttk.Frame(
            self.main_frame,
            style="App.TFrame"
        )

        self.button_frame.pack(
            fill="x",
            pady=(26, 18)
        )

        for column in range(3):

            self.button_frame.columnconfigure(
                column,
                weight=1
            )

        self.start_button = ttk.Button(
            self.button_frame,
            text="Start Recording",
            style="Primary.TButton",
            state="disabled",
            command=self.start_recording
        )

        self.start_button.grid(
            row=0,
            column=0,
            sticky="ew",
            padx=(0, 8)
        )

        self.pause_button = ttk.Button(
            self.button_frame,
            text="Pause",
            style="Secondary.TButton",
            state="disabled",
            command=self.toggle_pause
        )

        self.pause_button.grid(
            row=0,
            column=1,
            sticky="ew",
            padx=8
        )

        self.stop_button = ttk.Button(
            self.button_frame,
            text="Stop & Save",
            style="Secondary.TButton",
            state="disabled",
            command=self.stop_recording
        )

        self.stop_button.grid(
            row=0,
            column=2,
            sticky="ew",
            padx=(8, 0)
        )

        # ----------------------------------------------------
        # Status
        # ----------------------------------------------------

        self.status_frame = ttk.Frame(
            self.main_frame,
            style="Status.TFrame",
            padding=(16, 14)
        )

        self.status_frame.pack(
            fill="x"
        )

        self.status_label = ttk.Label(
            self.status_frame,
            textvariable=self.status_text,
            style="Status.TLabel"
        )

        self.status_label.pack(
            anchor="w"
        )

        # ----------------------------------------------------
        # Help text
        # ----------------------------------------------------

        self.tip1 = ttk.Label(
            self.main_frame,
            text=(
                "Windows Live Captions opens automatically "
                "when this application starts."
            ),
            style="Hint.TLabel"
        )

        self.tip1.pack(
            anchor="w",
            pady=(18, 4)
        )

        self.tip2 = ttk.Label(
            self.main_frame,
            text=(
                "Supports all languages recognized "
                "by Windows Live Captions."
            ),
            style="Hint.TLabel"
        )

        self.tip2.pack(
            anchor="w"
        )

    # ========================================================
    # Windows Light / Dark theme
    # ========================================================

    def apply_system_theme(
        self,
        force=False
    ):

        dark_mode = (
            is_windows_dark_mode()
        )

        if (
            not force
            and
            dark_mode
            ==
            self.current_dark_mode
        ):

            return

        self.current_dark_mode = (
            dark_mode
        )

        try:

            self.style.theme_use(
                "clam"
            )

        except Exception:

            pass

        if dark_mode:

            colors = {
                "bg": "#202020",
                "card": "#2b2b2b",
                "status": "#262626",
                "text": "#f3f3f3",
                "muted": "#b5b5b5",
                "entry": "#333333",
                "border": "#505050",
                "button": "#333333",
                "button_hover": "#414141",
                "button_pressed": "#4a4a4a",
                "disabled": "#777777",
                "accent": "#0f6cbd",
                "accent_hover": "#115ea3",
            }

        else:

            colors = {
                "bg": "#f5f5f5",
                "card": "#ffffff",
                "status": "#ffffff",
                "text": "#1a1a1a",
                "muted": "#666666",
                "entry": "#ffffff",
                "border": "#d0d0d0",
                "button": "#ffffff",
                "button_hover": "#eeeeee",
                "button_pressed": "#e2e2e2",
                "disabled": "#9a9a9a",
                "accent": "#0f6cbd",
                "accent_hover": "#115ea3",
            }

        self.root.configure(
            bg=colors["bg"]
        )

        # Frames

        self.style.configure(
            "App.TFrame",
            background=colors["bg"]
        )

        self.style.configure(
            "Card.TFrame",
            background=colors["card"]
        )

        self.style.configure(
            "Status.TFrame",
            background=colors["status"],
            relief="solid",
            borderwidth=1,
            bordercolor=colors["border"]
        )

        # Labels

        self.style.configure(
            "Title.TLabel",
            background=colors["bg"],
            foreground=colors["text"],
            font=(
                "Segoe UI Variable Display",
                19,
                "bold"
            )
        )

        self.style.configure(
            "Subtitle.TLabel",
            background=colors["bg"],
            foreground=colors["muted"],
            font=(
                "Segoe UI",
                10
            )
        )

        self.style.configure(
            "Body.TLabel",
            background=colors["card"],
            foreground=colors["text"],
            font=(
                "Segoe UI",
                10
            )
        )

        self.style.configure(
            "Status.TLabel",
            background=colors["status"],
            foreground=colors["text"],
            font=(
                "Segoe UI",
                10
            )
        )

        self.style.configure(
            "Hint.TLabel",
            background=colors["bg"],
            foreground=colors["muted"],
            font=(
                "Segoe UI",
                9
            )
        )

        # Entry

        self.style.configure(
            "Modern.TEntry",
            fieldbackground=colors["entry"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            lightcolor=colors["border"],
            darkcolor=colors["border"],
            padding=(10, 8)
        )

        self.style.map(
            "Modern.TEntry",
            fieldbackground=[
                (
                    "disabled",
                    colors["card"]
                )
            ],
            foreground=[
                (
                    "disabled",
                    colors["disabled"]
                )
            ]
        )

        # Secondary button

        self.style.configure(
            "Secondary.TButton",
            background=colors["button"],
            foreground=colors["text"],
            bordercolor=colors["border"],
            lightcolor=colors["border"],
            darkcolor=colors["border"],
            padding=(14, 11),
            font=(
                "Segoe UI",
                10
            )
        )

        self.style.map(
            "Secondary.TButton",
            background=[
                (
                    "pressed",
                    colors["button_pressed"]
                ),
                (
                    "active",
                    colors["button_hover"]
                ),
                (
                    "disabled",
                    colors["card"]
                )
            ],
            foreground=[
                (
                    "disabled",
                    colors["disabled"]
                )
            ]
        )

        # Primary button

        self.style.configure(
            "Primary.TButton",
            background=colors["accent"],
            foreground="#ffffff",
            bordercolor=colors["accent"],
            lightcolor=colors["accent"],
            darkcolor=colors["accent"],
            padding=(14, 11),
            font=(
                "Segoe UI",
                10,
                "bold"
            )
        )

        self.style.map(
            "Primary.TButton",
            background=[
                (
                    "pressed",
                    colors["accent_hover"]
                ),
                (
                    "active",
                    colors["accent_hover"]
                ),
                (
                    "disabled",
                    colors["card"]
                )
            ],
            foreground=[
                (
                    "disabled",
                    colors["disabled"]
                )
            ]
        )

        self.apply_dark_title_bar(
            dark_mode
        )

    # ========================================================
    # Watch Windows theme
    # ========================================================

    def watch_system_theme(self):

        self.apply_system_theme()

        self.root.after(
            THEME_CHECK_INTERVAL,
            self.watch_system_theme
        )

    # ========================================================
    # Windows title bar theme
    # ========================================================

    def apply_dark_title_bar(
        self,
        dark_mode
    ):

        try:

            self.root.update_idletasks()

            child_hwnd = (
                self.root.winfo_id()
            )

            parent_hwnd = (
                ctypes.windll.user32.GetParent(
                    child_hwnd
                )
            )

            handles = [
                child_hwnd
            ]

            if parent_hwnd:

                handles.append(
                    parent_hwnd
                )

            value = ctypes.c_int(
                1
                if dark_mode
                else 0
            )

            dwmapi = (
                ctypes.windll.dwmapi
            )

            for hwnd in handles:

                try:

                    dwmapi.DwmSetWindowAttribute(
                        hwnd,
                        20,
                        ctypes.byref(value),
                        ctypes.sizeof(value)
                    )

                except Exception:

                    pass

                try:

                    dwmapi.DwmSetWindowAttribute(
                        hwnd,
                        19,
                        ctypes.byref(value),
                        ctypes.sizeof(value)
                    )

                except Exception:

                    pass

        except Exception:

            pass

    # ========================================================
    # Choose Save
    # ========================================================

    def choose_save_path(self):

        current_folder = (
            self.save_folder
            .get()
            .strip()
        )

        if not os.path.isdir(
            current_folder
        ):

            current_folder = (
                os.path.expanduser("~")
            )

        current_name = (
            self.filename
            .get()
            .strip()
        )

        if not current_name:

            current_name = (
                self.make_default_filename()
            )

        try:

            selected_file = (
                self.windows_save_dialog(
                    current_folder,
                    current_name
                )
            )

        except Exception:

            # Fallback if Windows dialog is unavailable.
            selected_file = (
                filedialog.asksaveasfilename(
                    parent=self.root,
                    title="Choose TXT Save Location",
                    initialdir=current_folder,
                    initialfile=current_name,
                    defaultextension=".txt",
                    filetypes=[
                        (
                            "Text file",
                            "*.txt"
                        ),
                        (
                            "All files",
                            "*.*"
                        )
                    ]
                )
            )

        if selected_file:

            self.save_folder.set(
                os.path.dirname(
                    selected_file
                )
            )

            self.filename.set(
                os.path.basename(
                    selected_file
                )
            )

    # ========================================================
    # High-DPI Windows SaveFileDialog
    # ========================================================

    def windows_save_dialog(
        self,
        initial_folder,
        initial_name
    ):

        def ps_escape(value):

            return str(value).replace(
                "'",
                "''"
            )

        safe_folder = (
            ps_escape(
                initial_folder
            )
        )

        safe_name = (
            ps_escape(
                initial_name
            )
        )

        powershell_script = f"""
$ErrorActionPreference = 'Stop'

try
{{
    Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;

public static class HighDpiNative
{{
    [DllImport("user32.dll", SetLastError=true)]
    public static extern bool SetProcessDpiAwarenessContext(
        IntPtr dpiContext
    );

    [DllImport("user32.dll", SetLastError=true)]
    public static extern bool SetProcessDPIAware();
}}
"@

    try
    {{
        [HighDpiNative]::SetProcessDpiAwarenessContext(
            [IntPtr]::new(-4)
        ) | Out-Null
    }}
    catch
    {{
        try
        {{
            [HighDpiNative]::SetProcessDPIAware() | Out-Null
        }}
        catch
        {{
        }}
    }}

    Add-Type -AssemblyName System.Windows.Forms

    try
    {{
        [System.Windows.Forms.Application]::EnableVisualStyles()
    }}
    catch
    {{
    }}

    $dialog = New-Object System.Windows.Forms.SaveFileDialog

    $dialog.Title = 'Choose TXT Save Location'

    $dialog.Filter = 'Text file (*.txt)|*.txt|All files (*.*)|*.*'

    $dialog.FilterIndex = 1

    $dialog.DefaultExt = 'txt'

    $dialog.AddExtension = $true

    $dialog.OverwritePrompt = $true

    $dialog.CheckPathExists = $true

    $dialog.AutoUpgradeEnabled = $true

    $dialog.RestoreDirectory = $true

    $dialog.InitialDirectory = '{safe_folder}'

    $dialog.FileName = '{safe_name}'

    $result = $dialog.ShowDialog()

    if ($result -eq [System.Windows.Forms.DialogResult]::OK)
    {{
        $bytes = [System.Text.Encoding]::UTF8.GetBytes(
            $dialog.FileName
        )

        $encoded = [Convert]::ToBase64String(
            $bytes
        )

        Write-Output $encoded
    }}
    else
    {{
        Write-Output '__CANCEL__'
    }}

    $dialog.Dispose()
}}
catch
{{
    [Console]::Error.WriteLine(
        $_.Exception.Message
    )

    exit 1
}}
"""

        encoded_script = (
            base64.b64encode(
                powershell_script.encode(
                    "utf-16le"
                )
            )
            .decode(
                "ascii"
            )
        )

        system_root = (
            os.environ.get(
                "SystemRoot",
                r"C:\Windows"
            )
        )

        powershell_path = (
            os.path.join(
                system_root,
                "System32",
                "WindowsPowerShell",
                "v1.0",
                "powershell.exe"
            )
        )

        if not os.path.exists(
            powershell_path
        ):

            powershell_path = (
                "powershell.exe"
            )

        creation_flags = 0

        if os.name == "nt":

            creation_flags = (
                subprocess.CREATE_NO_WINDOW
            )

        result = subprocess.run(
            [
                powershell_path,
                "-NoLogo",
                "-NoProfile",
                "-STA",
                "-EncodedCommand",
                encoded_script
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=creation_flags
        )

        stdout = (
            result.stdout.decode(
                "utf-8",
                errors="replace"
            )
            .strip()
        )

        stderr = (
            result.stderr.decode(
                "utf-8",
                errors="replace"
            )
            .strip()
        )

        if result.returncode != 0:

            raise RuntimeError(
                stderr
                if stderr
                else
                "Windows SaveFileDialog failed."
            )

        if not stdout:

            return None

        output_line = (
            stdout
            .splitlines()[-1]
            .strip()
        )

        if (
            output_line
            ==
            "__CANCEL__"
        ):

            return None

        try:

            selected_file = (
                base64.b64decode(
                    output_line
                )
                .decode(
                    "utf-8"
                )
            )

        except Exception as error:

            raise RuntimeError(
                "Unable to read the selected file path."
            ) from error

        return selected_file

    # ========================================================
    # Send Win + Ctrl + L
    # ========================================================

    def send_live_captions_hotkey(self):

        try:

            win32api.keybd_event(
                win32con.VK_LWIN,
                0,
                0,
                0
            )

            win32api.keybd_event(
                win32con.VK_CONTROL,
                0,
                0,
                0
            )

            win32api.keybd_event(
                ord("L"),
                0,
                0,
                0
            )

            win32api.keybd_event(
                ord("L"),
                0,
                win32con.KEYEVENTF_KEYUP,
                0
            )

            win32api.keybd_event(
                win32con.VK_CONTROL,
                0,
                win32con.KEYEVENTF_KEYUP,
                0
            )

            win32api.keybd_event(
                win32con.VK_LWIN,
                0,
                win32con.KEYEVENTF_KEYUP,
                0
            )

            return True

        except Exception:

            return False

    # ========================================================
    # Startup Live Captions
    # ========================================================

    def startup_live_captions(self):

        hwnd = (
            self.find_livecaptions_hwnd()
        )

        # Already open

        if hwnd:

            self.live_available = True

            self.start_button.config(
                state="normal"
            )

            self.status_text.set(
                "Ready - Live Captions connected"
            )

            self.root.after(
                LIVE_CAPTIONS_CHECK_INTERVAL,
                self.monitor_live_captions
            )

            return

        # Not open

        self.live_available = False

        self.start_button.config(
            state="disabled"
        )

        self.status_text.set(
            "Opening Windows Live Captions..."
        )

        self.send_live_captions_hotkey()

        self.root.after(
            1500,
            self.monitor_live_captions
        )

    # ========================================================
    # Monitor Live Captions
    # ========================================================

    def monitor_live_captions(self):

        hwnd = (
            self.find_livecaptions_hwnd()
        )

        available_now = bool(
            hwnd
        )

        # ----------------------------------------------------
        # Live Captions closed
        # ----------------------------------------------------

        if not available_now:

            self.live_available = False

            if (
                self.recording
                and
                not self.auto_stopping
            ):

                self.auto_stopping = True

                self.auto_stop_live_captions_closed()

            elif not self.recording:

                self.start_button.config(
                    state="disabled"
                )

                self.status_text.set(
                    "Live Captions is not open. "
                    "Press Win + Ctrl + L to open it."
                )

        # ----------------------------------------------------
        # Live Captions available
        # ----------------------------------------------------

        else:

            self.live_available = True

            if not self.recording:

                self.start_button.config(
                    state="normal"
                )

                self.status_text.set(
                    "Ready - Live Captions connected"
                )

        self.root.after(
            LIVE_CAPTIONS_CHECK_INTERVAL,
            self.monitor_live_captions
        )

    # ========================================================
    # Find Live Captions window
    # ========================================================

    def find_livecaptions_hwnd(self):

        try:

            hwnd = win32gui.FindWindow(
                "LiveCaptionsDesktopWindow",
                None
            )

            if hwnd:
                return hwnd

        except Exception:

            pass

        found = []

        def enum_callback(
            hwnd,
            extra
        ):

            try:

                class_name = (
                    win32gui.GetClassName(
                        hwnd
                    )
                )

                if (
                    class_name
                    ==
                    "LiveCaptionsDesktopWindow"
                ):

                    found.append(
                        hwnd
                    )

            except Exception:

                pass

            return True

        try:

            win32gui.EnumWindows(
                enum_callback,
                None
            )

        except Exception:

            pass

        if found:

            return found[0]

        return None

    # ========================================================
    # Connect to Live Captions using UI Automation
    # ========================================================

    def connect_livecaptions(self):

        hwnd = (
            self.find_livecaptions_hwnd()
        )

        if not hwnd:

            self.live_hwnd = None
            self.live_window = None
            self.caption_control = None

            return False

        try:

            if (
                self.live_hwnd
                !=
                hwnd
                or
                self.live_window
                is None
            ):

                self.live_hwnd = (
                    hwnd
                )

                self.live_window = (
                    Desktop(
                        backend="uia"
                    )
                    .window(
                        handle=hwnd
                    )
                )

                self.caption_control = (
                    None
                )

            return True

        except Exception:

            self.live_hwnd = None
            self.live_window = None
            self.caption_control = None

            return False

    # ========================================================
    # Find caption text control
    # ========================================================

    def find_caption_control(self):

        if not self.connect_livecaptions():

            return None

        try:

            control = (
                self.live_window
                .child_window(
                    auto_id="CaptionsTextBlock"
                )
            )

            if control.exists(
                timeout=0.15
            ):

                return (
                    control.wrapper_object()
                )

        except Exception:

            pass

        try:

            descendants = (
                self.live_window
                .descendants()
            )

            for control in descendants:

                try:

                    automation_id = (
                        control
                        .element_info
                        .automation_id
                    )

                    if (
                        automation_id
                        ==
                        "CaptionsTextBlock"
                    ):

                        return control

                except Exception:

                    continue

        except Exception:

            pass

        return None

    # ========================================================
    # Read current caption
    # ========================================================

    def get_caption_text(self):

        if not self.connect_livecaptions():

            return None

        if self.caption_control is None:

            self.caption_control = (
                self.find_caption_control()
            )

        if self.caption_control is None:

            return ""

        try:

            text = (
                self.caption_control
                .element_info
                .name
            )

            if not text:

                try:

                    text = (
                        self.caption_control
                        .window_text()
                    )

                except Exception:

                    text = ""

            return normalize_text(
                text
            )

        except Exception:

            self.caption_control = None

            return ""

    # ========================================================
    # Exact suffix-prefix overlap
    # ========================================================

    def longest_overlap(
        self,
        old_text,
        new_text
    ):

        if not old_text:
            return 0

        if not new_text:
            return 0

        maximum = min(
            len(old_text),
            len(new_text)
        )

        for length in range(
            maximum,
            0,
            -1
        ):

            if (
                old_text[-length:]
                ==
                new_text[:length]
            ):

                return length

        return 0

    # ========================================================
    # Detect repeated old prefix
    # ========================================================

    def longest_existing_prefix(
        self,
        history,
        candidate
    ):

        if not history:
            return 0

        if not candidate:
            return 0

        maximum = min(
            len(history),
            len(candidate)
        )

        if maximum < LONG_REPEAT_MIN:

            return 0

        if (
            candidate[:LONG_REPEAT_MIN]
            not in history
        ):

            return 0

        low = LONG_REPEAT_MIN
        high = maximum

        best = LONG_REPEAT_MIN

        while low <= high:

            middle = (
                low
                +
                high
            ) // 2

            prefix = (
                candidate[:middle]
            )

            if prefix in history:

                best = middle

                low = (
                    middle
                    +
                    1
                )

            else:

                high = (
                    middle
                    -
                    1
                )

        return best

    # ========================================================
    # Fuzzy suffix-prefix matching
    # ========================================================

    def fuzzy_suffix_prefix(
        self,
        previous,
        current
    ):

        if not previous:
            return None

        if not current:
            return None

        if (
            len(previous)
            <
            MIN_FUZZY_LENGTH
        ):

            return None

        matcher = SequenceMatcher(
            None,
            previous,
            current,
            autojunk=False
        )

        blocks = (
            matcher.get_matching_blocks()
        )

        useful_blocks = [
            block
            for block in blocks
            if block.size >= 4
        ]

        useful_blocks.sort(
            key=lambda block: block.size,
            reverse=True
        )

        candidate_starts = {
            0
        }

        for block in useful_blocks[:10]:

            offset = (
                block.a
                -
                block.b
            )

            for adjust in (
                -15,
                -10,
                -5,
                0,
                5,
                10,
                15
            ):

                start = (
                    offset
                    +
                    adjust
                )

                if (
                    start >= 0
                    and
                    start < len(previous)
                ):

                    candidate_starts.add(
                        start
                    )

        best_ratio = 0.0
        best_start = None
        best_prefix_length = None

        for start in candidate_starts:

            suffix = (
                previous[start:]
            )

            if (
                len(suffix)
                <
                MIN_FUZZY_LENGTH
            ):

                continue

            base_length = (
                len(suffix)
            )

            margin = max(
                25,
                min(
                    120,
                    int(
                        base_length
                        *
                        0.25
                    )
                )
            )

            minimum_length = max(
                MIN_FUZZY_LENGTH,
                base_length
                -
                margin
            )

            maximum_length = min(
                len(current),
                base_length
                +
                margin
            )

            if (
                minimum_length
                >
                maximum_length
            ):

                continue

            lengths = list(
                range(
                    minimum_length,
                    maximum_length + 1,
                    2
                )
            )

            if (
                maximum_length
                not in lengths
            ):

                lengths.append(
                    maximum_length
                )

            for prefix_length in lengths:

                prefix = (
                    current[
                        :prefix_length
                    ]
                )

                ratio = (
                    SequenceMatcher(
                        None,
                        suffix,
                        prefix,
                        autojunk=False
                    )
                    .ratio()
                )

                if ratio > best_ratio:

                    best_ratio = (
                        ratio
                    )

                    best_start = (
                        start
                    )

                    best_prefix_length = (
                        prefix_length
                    )

        if best_start is None:

            return None

        return (
            best_start,
            best_prefix_length,
            best_ratio
        )

    # ========================================================
    # Write finalized unique text
    # ========================================================

    def write_unique_text(
        self,
        candidate
    ):

        if not self.file_handle:

            return

        candidate = (
            normalize_text(
                candidate
            )
        )

        if not candidate:

            return

        history = (
            self.history_text[
                -RECENT_HISTORY_LIMIT:
            ]
        )

        # Exact duplicate

        if (
            len(candidate) >= 20
            and
            candidate in history
        ):

            return

        # Normal rolling overlap

        overlap = (
            self.longest_overlap(
                history,
                candidate
            )
        )

        if (
            overlap
            >=
            MIN_EXACT_OVERLAP
        ):

            candidate = (
                candidate[
                    overlap:
                ]
                .strip()
            )

        if not candidate:

            return

        history = (
            self.history_text[
                -RECENT_HISTORY_LIMIT:
            ]
        )

        # Long repeated prefix

        existing_prefix = (
            self.longest_existing_prefix(
                history,
                candidate
            )
        )

        if (
            existing_prefix
            >=
            LONG_REPEAT_MIN
        ):

            candidate = (
                candidate[
                    existing_prefix:
                ]
                .strip()
            )

        if not candidate:

            return

        # Final duplicate check

        if (
            len(candidate) >= 20
            and
            candidate in history
        ):

            return

        try:

            self.file_handle.write(
                candidate
            )

            self.file_handle.write(
                "\n"
            )

            self.file_handle.flush()

            self.history_text = (
                self.history_text
                +
                " "
                +
                candidate
            )[-RECENT_HISTORY_LIMIT:]

        except Exception as error:

            self.message_queue.put(
                (
                    "error",
                    "Failed to write TXT:\n"
                    +
                    str(error)
                )
            )

    # ========================================================
    # Process new caption snapshot
    # ========================================================

    def process_snapshot(
        self,
        current
    ):

        current = (
            normalize_text(
                current
            )
        )

        if not current:

            return

        previous = (
            self.last_snapshot
        )

        # First snapshot

        if not previous:

            self.last_snapshot = (
                current
            )

            self.mismatch_started = None
            self.mismatch_latest = ""

            return

        # No change

        if current == previous:

            self.mismatch_started = None
            self.mismatch_latest = ""

            return

        # Caption grew normally

        if current.startswith(
            previous
        ):

            self.last_snapshot = (
                current
            )

            self.mismatch_started = None
            self.mismatch_latest = ""

            return

        # Caption became shorter

        if previous.startswith(
            current
        ):

            self.last_snapshot = (
                current
            )

            self.mismatch_started = None
            self.mismatch_latest = ""

            return

        # Exact rolling overlap

        exact_overlap = (
            self.longest_overlap(
                previous,
                current
            )
        )

        if (
            exact_overlap
            >=
            MIN_EXACT_OVERLAP
        ):

            finished_part = (
                previous[
                    :-exact_overlap
                ]
                .strip()
            )

            if finished_part:

                self.write_unique_text(
                    finished_part
                )

            self.last_snapshot = (
                current
            )

            self.mismatch_started = None
            self.mismatch_latest = ""

            return

        # Fuzzy correction / rolling overlap

        fuzzy = (
            self.fuzzy_suffix_prefix(
                previous,
                current
            )
        )

        if fuzzy is not None:

            start_position = (
                fuzzy[0]
            )

            similarity = (
                fuzzy[2]
            )

            if (
                similarity
                >=
                FUZZY_THRESHOLD
            ):

                if start_position > 0:

                    finished_part = (
                        previous[
                            :start_position
                        ]
                        .strip()
                    )

                    if finished_part:

                        self.write_unique_text(
                            finished_part
                        )

                self.last_snapshot = (
                    current
                )

                self.mismatch_started = None
                self.mismatch_latest = ""

                return

        # Completely different block

        now = (
            time.monotonic()
        )

        if self.mismatch_started is None:

            self.mismatch_started = (
                now
            )

            self.mismatch_latest = (
                current
            )

            return

        self.mismatch_latest = (
            current
        )

        if (
            now
            -
            self.mismatch_started
            >=
            MISMATCH_GRACE
        ):

            self.write_unique_text(
                previous
            )

            self.last_snapshot = (
                self.mismatch_latest
            )

            self.mismatch_started = None
            self.mismatch_latest = ""

    # ========================================================
    # Start recording
    # ========================================================

    def start_recording(self):

        if self.recording:

            return

        # ----------------------------------------------------
        # Live Captions must be open
        # ----------------------------------------------------

        hwnd = (
            self.find_livecaptions_hwnd()
        )

        if not hwnd:

            self.live_available = False

            self.start_button.config(
                state="disabled"
            )

            self.status_text.set(
                "Live Captions is not open. "
                "Press Win + Ctrl + L to open it."
            )

            messagebox.showwarning(
                "Live Captions Not Open",
                "Windows Live Captions is not open.\n\n"
                "Press Win + Ctrl + L to open it, "
                "then try again."
            )

            return

        # ----------------------------------------------------
        # Validate save location
        # ----------------------------------------------------

        folder = (
            self.save_folder
            .get()
            .strip()
        )

        filename = (
            self.filename
            .get()
            .strip()
        )

        if not folder:

            messagebox.showerror(
                "Error",
                "Please choose a save location."
            )

            return

        if not os.path.isdir(
            folder
        ):

            messagebox.showerror(
                "Error",
                "The selected save location does not exist."
            )

            return

        if not filename:

            messagebox.showerror(
                "Error",
                "Please enter a file name."
            )

            return

        if re.search(
            INVALID_FILENAME_CHARS,
            filename
        ):

            messagebox.showerror(
                "Error",
                'The file name cannot contain: '
                '< > : " / \\ | ? *'
            )

            return

        if not filename.lower().endswith(
            ".txt"
        ):

            filename += ".txt"

            self.filename.set(
                filename
            )

        self.output_path = (
            os.path.join(
                folder,
                filename
            )
        )

        # ----------------------------------------------------
        # Existing file
        # ----------------------------------------------------

        if os.path.exists(
            self.output_path
        ):

            overwrite = (
                messagebox.askyesno(
                    "File Already Exists",
                    "This TXT file already exists.\n\n"
                    "Overwrite it?"
                )
            )

            if not overwrite:

                return

        # ----------------------------------------------------
        # Create TXT
        # ----------------------------------------------------

        try:

            self.file_handle = open(
                self.output_path,
                "w",
                encoding="utf-8-sig",
                newline=""
            )

        except Exception as error:

            messagebox.showerror(
                "Unable to Create TXT",
                str(error)
            )

            return

        # ----------------------------------------------------
        # Reset processing state
        # ----------------------------------------------------

        self.live_hwnd = None
        self.live_window = None
        self.caption_control = None

        self.last_snapshot = ""
        self.history_text = ""

        self.mismatch_started = None
        self.mismatch_latest = ""

        self.auto_stopping = False

        # ----------------------------------------------------
        # Current visible caption becomes baseline
        # ----------------------------------------------------

        try:

            baseline = (
                self.get_caption_text()
            )

            baseline = (
                normalize_text(
                    baseline
                )
            )

            if baseline:

                self.last_snapshot = (
                    baseline
                )

                self.history_text = (
                    baseline[
                        -RECENT_HISTORY_LIMIT:
                    ]
                )

        except Exception:

            pass

        # ----------------------------------------------------
        # Start session
        # ----------------------------------------------------

        self.recording = True
        self.paused = False

        self.stop_event.clear()

        self.start_button.config(
            state="disabled"
        )

        self.pause_button.config(
            state="normal",
            text="Pause"
        )

        self.stop_button.config(
            state="normal"
        )

        self.folder_entry.config(
            state="disabled"
        )

        self.filename_entry.config(
            state="disabled"
        )

        self.choose_button.config(
            state="disabled"
        )

        self.status_text.set(
            "Recording..."
        )

        self.worker_thread = (
            threading.Thread(
                target=self.record_loop,
                daemon=True
            )
        )

        self.worker_thread.start()

    # ========================================================
    # Recording worker
    # ========================================================

    def record_loop(self):

        pythoncom.CoInitialize()

        waiting_reported = False

        try:

            while not self.stop_event.is_set():

                if self.paused:

                    time.sleep(
                        POLL_INTERVAL
                    )

                    continue

                current = (
                    self.get_caption_text()
                )

                # Live Captions disappeared.
                # The main monitor will Stop & Save.

                if current is None:

                    time.sleep(
                        POLL_INTERVAL
                    )

                    continue

                # Waiting for speech

                if not current:

                    if not waiting_reported:

                        self.message_queue.put(
                            (
                                "status",
                                "Connected to Windows Live Captions. "
                                "Waiting for speech..."
                            )
                        )

                        waiting_reported = True

                    time.sleep(
                        POLL_INTERVAL
                    )

                    continue

                waiting_reported = False

                self.message_queue.put(
                    (
                        "status",
                        "Recording..."
                    )
                )

                self.process_snapshot(
                    current
                )

                time.sleep(
                    POLL_INTERVAL
                )

        finally:

            pythoncom.CoUninitialize()

    # ========================================================
    # Pause / Continue
    # ========================================================

    def toggle_pause(self):

        if not self.recording:

            return

        # ----------------------------------------------------
        # Pause
        # ----------------------------------------------------

        if not self.paused:

            if self.last_snapshot.strip():

                self.write_unique_text(
                    self.last_snapshot
                )

            self.last_snapshot = ""

            self.mismatch_started = None
            self.mismatch_latest = ""

            self.paused = True

            self.pause_button.config(
                text="Continue"
            )

            self.status_text.set(
                "Paused"
            )

        # ----------------------------------------------------
        # Continue same session
        # ----------------------------------------------------

        else:

            if not self.find_livecaptions_hwnd():

                return

            self.paused = False

            self.caption_control = None

            current = (
                self.get_caption_text()
            )

            current = (
                normalize_text(
                    current
                )
            )

            if current:

                self.last_snapshot = (
                    current
                )

                self.history_text = (
                    self.history_text
                    +
                    " "
                    +
                    current
                )[-RECENT_HISTORY_LIMIT:]

            else:

                self.last_snapshot = ""

            self.mismatch_started = None
            self.mismatch_latest = ""

            self.pause_button.config(
                text="Pause"
            )

            self.status_text.set(
                "Recording..."
            )

    # ========================================================
    # Finish recording session
    # ========================================================

    def finish_recording(
        self,
        automatic=False
    ):

        if not self.recording:

            return

        self.stop_event.set()

        self.recording = False
        self.paused = False

        if self.worker_thread:

            self.worker_thread.join(
                timeout=2
            )

        # ----------------------------------------------------
        # Save last visible caption
        # ----------------------------------------------------

        if self.last_snapshot.strip():

            self.write_unique_text(
                self.last_snapshot
            )

        self.last_snapshot = ""

        # ----------------------------------------------------
        # Close TXT
        # ----------------------------------------------------

        if self.file_handle:

            try:

                self.file_handle.flush()

                self.file_handle.close()

            except Exception:

                pass

        self.file_handle = None

        saved_path = (
            self.output_path
        )

        # ----------------------------------------------------
        # Clear UI Automation objects
        # ----------------------------------------------------

        self.live_hwnd = None
        self.live_window = None
        self.caption_control = None

        # ----------------------------------------------------
        # Restore controls
        # ----------------------------------------------------

        self.pause_button.config(
            state="disabled",
            text="Pause"
        )

        self.stop_button.config(
            state="disabled"
        )

        self.folder_entry.config(
            state="normal"
        )

        self.filename_entry.config(
            state="normal"
        )

        self.choose_button.config(
            state="normal"
        )

        # New default file name for next session.

        self.filename.set(
            self.make_default_filename()
        )

        # ----------------------------------------------------
        # Automatic stop because Live Captions was closed
        # ----------------------------------------------------

        if automatic:

            self.live_available = False

            self.start_button.config(
                state="disabled"
            )

            self.status_text.set(
                "Live Captions is not open. "
                "Press Win + Ctrl + L to open it."
            )

            self.auto_stopping = False

            messagebox.showinfo(
                "Recording Stopped",
                "Windows Live Captions was closed.\n\n"
                "The current recording session was stopped "
                "and the TXT file was saved successfully:\n\n"
                +
                str(saved_path)
            )

        # ----------------------------------------------------
        # Normal Stop & Save
        # ----------------------------------------------------

        else:

            if self.find_livecaptions_hwnd():

                self.live_available = True

                self.start_button.config(
                    state="normal"
                )

                self.status_text.set(
                    "Ready - Live Captions connected"
                )

            else:

                self.live_available = False

                self.start_button.config(
                    state="disabled"
                )

                self.status_text.set(
                    "Live Captions is not open. "
                    "Press Win + Ctrl + L to open it."
                )

            self.auto_stopping = False

            messagebox.showinfo(
                "Saved",
                "TXT saved successfully:\n\n"
                +
                str(saved_path)
            )

    # ========================================================
    # Stop & Save
    # ========================================================

    def stop_recording(self):

        self.finish_recording(
            automatic=False
        )

    # ========================================================
    # Live Captions closed
    # ========================================================

    def auto_stop_live_captions_closed(self):

        if not self.recording:

            self.auto_stopping = False

            return

        self.finish_recording(
            automatic=True
        )

    # ========================================================
    # Worker messages
    # ========================================================

    def process_messages(self):

        try:

            while True:

                msg_type, msg = (
                    self.message_queue
                    .get_nowait()
                )

                if msg_type == "status":

                    if self.recording:

                        self.status_text.set(
                            msg
                        )

                elif msg_type == "error":

                    messagebox.showerror(
                        "Error",
                        msg
                    )

        except queue.Empty:

            pass

        self.root.after(
            100,
            self.process_messages
        )

    # ========================================================
    # Close application
    # ========================================================

    def on_close(self):

        if self.recording:

            answer = (
                messagebox.askyesno(
                    "Recording in Progress",
                    "Recording is still active.\n\n"
                    "Closing the application will stop recording "
                    "and save the current TXT file.\n\n"
                    "Continue?"
                )
            )

            if not answer:

                return

            self.stop_event.set()

            self.recording = False
            self.paused = False

            if self.worker_thread:

                self.worker_thread.join(
                    timeout=1
                )

            if self.last_snapshot.strip():

                self.write_unique_text(
                    self.last_snapshot
                )

            if self.file_handle:

                try:

                    self.file_handle.flush()

                    self.file_handle.close()

                except Exception:

                    pass

        try:

            pythoncom.CoUninitialize()

        except Exception:

            pass

        self.root.destroy()


# ============================================================
# Application entry point
# ============================================================

if __name__ == "__main__":

    # Must run before Tk creates any window.
    enable_high_dpi_awareness()

    root = tk.Tk()

    # Adjust Tk font/widget scaling for the current monitor DPI.
    configure_tk_dpi(
        root
    )

    app = LiveCaptionsRecorder(
        root
    )

    root.mainloop()
