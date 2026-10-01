import sys
sys.coinit_flags = 2
import os
import json
import re
import time
import queue
import base64
import ctypes
import winreg
import webbrowser
import warnings
import subprocess
import threading
from datetime import datetime
from difflib import SequenceMatcher
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import pythoncom
import sounddevice as sd
import win32api
import win32con
import win32gui
import win32process
from pywinauto import Desktop
from pycaw.pycaw import AudioUtilities
from pycaw.constants import DEVICE_STATE, EDataFlow, ERole
POLL_INTERVAL = 0.25
LIVE_CAPTIONS_CHECK_INTERVAL = 750
THEME_CHECK_INTERVAL = 1500
DEVICE_REFRESH_INTERVAL = 1500
LEVEL_REFRESH_INTERVAL = 80
MISMATCH_GRACE = 1.0
FUZZY_THRESHOLD = 0.8
MIN_FUZZY_LENGTH = 20
MIN_EXACT_OVERLAP = 8
RECENT_HISTORY_LIMIT = 20000
LONG_REPEAT_MIN = 80
INVALID_FILENAME_CHARS = '[<>:"/\\\\|?*]'
MODE_SYSTEM = 'system'
MODE_MICROPHONE = 'microphone'
GITHUB_URL = 'https://github.com/kidoyuyu/LiveCaptionsTXTRecorder'

def enable_high_dpi_awareness():
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        result = user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        if result:
            return
    except Exception:
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

def configure_tk_dpi(root):
    try:
        root.update_idletasks()
        dpi = ctypes.windll.user32.GetDpiForWindow(root.winfo_id())
        if dpi:
            root.tk.call('tk', 'scaling', float(dpi) / 72.0)
    except Exception:
        pass

def normalize_text(text):
    if not text:
        return ''
    text = str(text).replace('\r\n', '\n').replace('\r', '\n')
    lines = []
    for line in text.split('\n'):
        line = line.strip()
        line = re.sub('[ \\t]+', ' ', line)
        if line:
            lines.append(line)
    return ' '.join(lines).strip()

def is_windows_dark_mode():
    try:
        key_path = 'Software\\Microsoft\\Windows\\CurrentVersion\\Themes\\Personalize'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
            value, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        return value == 0
    except Exception:
        return False
# Five UI languages. This does not change Windows Live Captions recognition language.
LANGUAGE_NAMES = {"en": "English", "ko": "한국어", "zh_CN": "简体中文", "zh_TW": "繁體中文", "ja": "日本語"}
ENGLISH_UI = ('Choose an audio mode', 'System Audio\n\nCapture speech played by this PC', 'Microphone\n\nCaption speech from a microphone', 'Windows Live Captions will open after you choose a mode.', 'Back', 'Current Output', 'Automatically follows the current Windows default output device.', 'Microphone', 'Input Level', 'For microphone-only transcription, avoid playing other speech audio on the PC.', 'Save Location:', 'Choose Save...', 'File Name:', 'Start Recording', 'Pause', 'Continue', 'Stop & Save', 'System Audio Mode', 'Capture speech played by this PC', 'Microphone Mode', 'Caption speech from your selected microphone', 'Opening Windows Live Captions...', 'Waiting for Windows Live Captions...', 'Configuring Live Captions...', 'No microphone found', 'Connecting...', 'Unable to read input level', 'Input detected', 'Windows default output', 'Live Captions is not open. Press Win + Ctrl + L to open it.', 'Ready - Live Captions connected', 'Connected to Windows Live Captions. Waiting for speech...', 'Paused', 'Microphone mode selected - manual Live Captions microphone setting may be required.', 'System Audio mode selected - manual Live Captions microphone setting may be required.', 'Please Wait', 'Audio mode is still being configured.', 'Live Captions Not Open', 'Windows Live Captions is not open.\n\nPress Win + Ctrl + L to open it, then try again.', 'Error', 'Please choose a save location.', 'The selected save location does not exist.', 'Please enter a file name.', 'The file name cannot contain: < > : " / \\ | ? *', 'File Already Exists', 'This TXT file already exists.\n\nOverwrite it?', 'Unable to Create TXT', 'Unable to Change Microphone', 'Windows could not change the default microphone.\n\n', 'Saved', 'TXT saved successfully:\n\n', 'Recording Stopped', 'Windows Live Captions was closed.\n\nThe current recording session was stopped and the TXT file was saved successfully:\n\n', 'Live Captions Setting', '\n\nPlease set it manually in:\n\nLive Captions > Settings > Preferences > Include microphone audio', 'Recording in Progress', 'Recording is still active.\n\nClosing the application will stop recording and save the current TXT file.\n\nContinue?', 'Choose TXT Save Location', 'Text file', 'All files', 'Windows Live Captions is not open.', 'Could not find the Live Captions Settings button.', 'Could not open Live Captions Settings.', 'Could not find Preferences in Live Captions.', 'Could not open Live Captions Preferences.', 'Could not find the Include microphone audio option.', 'Could not change the microphone option.', 'Unable to read the selected file path.', 'Language')
LOCALIZED_UI = {'ko': {'Choose an audio mode': '오디오 모드를 선택해 주세요',
        'System Audio\n\nCapture speech played by this PC': '시스템 오디오\n\nPC에서 재생되는 음성을 자막으로 기록',
        'Microphone\n\nCaption speech from a microphone': '마이크\n\n마이크로 들리는 음성을 자막으로 기록',
        'Windows Live Captions will open after you choose a mode.': '모드를 선택하면 Windows 라이브 캡션이 열립니다.',
        'Back': '뒤로',
        'Current Output': '현재 출력 장치',
        'Automatically follows the current Windows default output device.': 'Windows의 기본 출력 장치를 자동으로 따라갑니다.',
        'Microphone': '마이크',
        'Input Level': '입력 음량',
        'For microphone-only transcription, avoid playing other speech audio on the PC.': '마이크 음성만 기록하려면 '
                                                                                          'PC에서 다른 사람의 목소리가 '
                                                                                          '나오는 소리는 재생하지 않는 '
                                                                                          '것이 좋습니다.',
        'Save Location:': '저장 위치:',
        'Choose Save...': '저장 위치 선택...',
        'File Name:': '파일 이름:',
        'Start Recording': '기록 시작',
        'Pause': '일시정지',
        'Continue': '계속하기',
        'Stop & Save': '중지 및 저장',
        'System Audio Mode': '시스템 오디오 모드',
        'Capture speech played by this PC': 'PC에서 재생되는 음성을 기록합니다',
        'Microphone Mode': '마이크 모드',
        'Caption speech from your selected microphone': '선택한 마이크로 들리는 음성을 기록합니다',
        'Opening Windows Live Captions...': 'Windows 라이브 캡션을 여는 중...',
        'Waiting for Windows Live Captions...': 'Windows 라이브 캡션 연결을 기다리는 중...',
        'Configuring Live Captions...': '라이브 캡션 설정 중...',
        'No microphone found': '마이크를 찾지 못했습니다',
        'Connecting...': '연결 중...',
        'Unable to read input level': '입력 음량을 확인할 수 없습니다',
        'Input detected': '입력 신호 감지됨',
        'Windows default output': 'Windows 기본 출력 장치',
        'Live Captions is not open. Press Win + Ctrl + L to open it.': '라이브 캡션이 닫혀 있습니다. Win + Ctrl + L을 눌러 '
                                                                       '열어 주세요.',
        'Ready - Live Captions connected': '준비 완료 · 라이브 캡션 연결됨',
        'Connected to Windows Live Captions. Waiting for speech...': '라이브 캡션에 연결되었습니다. 음성을 기다리는 중...',
        'Paused': '일시정지됨',
        'Microphone mode selected - manual Live Captions microphone setting may be required.': '마이크 모드를 '
                                                                                               '선택했습니다. 라이브 '
                                                                                               '캡션에서 마이크 사용을 '
                                                                                               '직접 켜야 할 수 '
                                                                                               '있습니다.',
        'System Audio mode selected - manual Live Captions microphone setting may be required.': '시스템 오디오 '
                                                                                                 '모드를 '
                                                                                                 '선택했습니다. '
                                                                                                 '라이브 캡션에서 '
                                                                                                 '마이크 사용을 직접 '
                                                                                                 '꺼야 할 수 '
                                                                                                 '있습니다.',
        'Please Wait': '잠시만 기다려 주세요',
        'Audio mode is still being configured.': '오디오 모드를 설정하고 있습니다. 잠시 후 다시 시도해 주세요.',
        'Live Captions Not Open': '라이브 캡션이 열려 있지 않습니다',
        'Windows Live Captions is not open.\n\nPress Win + Ctrl + L to open it, then try again.': 'Windows '
                                                                                                  '라이브 캡션이 '
                                                                                                  '열려 있지 '
                                                                                                  '않습니다.\n'
                                                                                                  '\n'
                                                                                                  'Win + '
                                                                                                  'Ctrl + L을 '
                                                                                                  '눌러 연 뒤 다시 '
                                                                                                  '시도해 주세요.',
        'Error': '오류',
        'Please choose a save location.': '저장 위치를 선택해 주세요.',
        'The selected save location does not exist.': '선택한 저장 폴더를 찾을 수 없습니다.',
        'Please enter a file name.': '파일 이름을 입력해 주세요.',
        'The file name cannot contain: < > : " / \\ | ? *': '파일 이름에 다음 문자를 사용할 수 없습니다: < > : " / \\ | ? *',
        'File Already Exists': '이미 있는 파일입니다',
        'This TXT file already exists.\n\nOverwrite it?': '같은 이름의 TXT 파일이 이미 있습니다.\n\n덮어쓸까요?',
        'Unable to Create TXT': 'TXT 파일을 만들 수 없습니다',
        'Unable to Change Microphone': '마이크를 변경할 수 없습니다',
        'Windows could not change the default microphone.\n\n': 'Windows에서 기본 마이크를 변경하지 못했습니다.\n\n',
        'Saved': '저장 완료',
        'TXT saved successfully:\n\n': 'TXT 파일을 저장했습니다:\n\n',
        'Recording Stopped': '기록 종료',
        'Windows Live Captions was closed.\n\nThe current recording session was stopped and the TXT file was saved successfully:\n\n': 'Windows '
                                                                                                                                       '라이브 '
                                                                                                                                       '캡션이 '
                                                                                                                                       '닫혀 '
                                                                                                                                       '녹음을 '
                                                                                                                                       '종료했습니다.\n'
                                                                                                                                       '\n'
                                                                                                                                       '현재 '
                                                                                                                                       '내용을 '
                                                                                                                                       'TXT '
                                                                                                                                       '파일로 '
                                                                                                                                       '저장했습니다:\n'
                                                                                                                                       '\n',
        'Live Captions Setting': '라이브 캡션 설정',
        '\n\nPlease set it manually in:\n\nLive Captions > Settings > Preferences > Include microphone audio': '\n'
                                                                                                               '\n'
                                                                                                               '다음 '
                                                                                                               '경로에서 '
                                                                                                               '직접 '
                                                                                                               '설정해 '
                                                                                                               '주세요:\n'
                                                                                                               '\n'
                                                                                                               '라이브 '
                                                                                                               '캡션 '
                                                                                                               '> '
                                                                                                               '설정 '
                                                                                                               '> '
                                                                                                               '기본 '
                                                                                                               '설정 '
                                                                                                               '> '
                                                                                                               '마이크 '
                                                                                                               '오디오 '
                                                                                                               '포함',
        'Recording in Progress': '기록 중',
        'Recording is still active.\n\nClosing the application will stop recording and save the current TXT file.\n\nContinue?': '현재 '
                                                                                                                                 '기록 '
                                                                                                                                 '중입니다.\n'
                                                                                                                                 '\n'
                                                                                                                                 '프로그램을 '
                                                                                                                                 '닫으면 '
                                                                                                                                 '기록을 '
                                                                                                                                 '중지하고 '
                                                                                                                                 'TXT '
                                                                                                                                 '파일을 '
                                                                                                                                 '저장합니다.\n'
                                                                                                                                 '\n'
                                                                                                                                 '종료할까요?',
        'Choose TXT Save Location': 'TXT 저장 위치 선택',
        'Text file': '텍스트 파일',
        'All files': '모든 파일',
        'Windows Live Captions is not open.': 'Windows 라이브 캡션이 열려 있지 않습니다.',
        'Could not find the Live Captions Settings button.': '라이브 캡션의 설정 버튼을 찾지 못했습니다.',
        'Could not open Live Captions Settings.': '라이브 캡션 설정을 열지 못했습니다.',
        'Could not find Preferences in Live Captions.': '라이브 캡션에서 기본 설정을 찾지 못했습니다.',
        'Could not open Live Captions Preferences.': '라이브 캡션 기본 설정을 열지 못했습니다.',
        'Could not find the Include microphone audio option.': '마이크 오디오 포함 항목을 찾지 못했습니다.',
        'Could not change the microphone option.': '마이크 오디오 설정을 변경하지 못했습니다.',
        'Unable to read the selected file path.': '선택한 파일 경로를 읽지 못했습니다.',
        'Language': '언어'},
 'zh_CN': {'Choose an audio mode': '请选择音频模式',
           'System Audio\n\nCapture speech played by this PC': '系统音频\n\n转写电脑正在播放的声音',
           'Microphone\n\nCaption speech from a microphone': '麦克风\n\n转写麦克风接收到的声音',
           'Windows Live Captions will open after you choose a mode.': '选择模式后，将自动打开 Windows 实时字幕。',
           'Back': '返回',
           'Current Output': '当前输出设备',
           'Automatically follows the current Windows default output device.': '自动使用 Windows 当前的默认输出设备。',
           'Microphone': '麦克风',
           'Input Level': '输入音量',
           'For microphone-only transcription, avoid playing other speech audio on the PC.': '如果只想转写麦克风声音，请尽量避免电脑同时播放其他人声。',
           'Save Location:': '保存位置：',
           'Choose Save...': '选择保存位置…',
           'File Name:': '文件名：',
           'Start Recording': '开始转写',
           'Pause': '暂停',
           'Continue': '继续',
           'Stop & Save': '停止并保存',
           'System Audio Mode': '系统音频模式',
           'Capture speech played by this PC': '转写电脑正在播放的声音',
           'Microphone Mode': '麦克风模式',
           'Caption speech from your selected microphone': '转写所选麦克风收到的声音',
           'Opening Windows Live Captions...': '正在打开 Windows 实时字幕…',
           'Waiting for Windows Live Captions...': '正在等待 Windows 实时字幕…',
           'Configuring Live Captions...': '正在设置实时字幕…',
           'No microphone found': '未找到麦克风',
           'Connecting...': '正在连接…',
           'Unable to read input level': '无法读取输入音量',
           'Input detected': '已检测到输入信号',
           'Windows default output': 'Windows 默认输出设备',
           'Live Captions is not open. Press Win + Ctrl + L to open it.': '实时字幕尚未打开，请按 Win + Ctrl + L 开启。',
           'Ready - Live Captions connected': '已就绪 · 实时字幕已连接',
           'Connected to Windows Live Captions. Waiting for speech...': '已连接实时字幕，正在等待语音…',
           'Paused': '已暂停',
           'Microphone mode selected - manual Live Captions microphone setting may be required.': '已选择麦克风模式，可能需要在实时字幕中手动开启麦克风输入。',
           'System Audio mode selected - manual Live Captions microphone setting may be required.': '已选择系统音频模式，可能需要在实时字幕中手动关闭麦克风输入。',
           'Please Wait': '请稍候',
           'Audio mode is still being configured.': '音频模式还在设置中，请稍后再试。',
           'Live Captions Not Open': '实时字幕未打开',
           'Windows Live Captions is not open.\n\nPress Win + Ctrl + L to open it, then try again.': 'Windows '
                                                                                                     '实时字幕尚未打开。\n'
                                                                                                     '\n'
                                                                                                     '请按 Win '
                                                                                                     '+ Ctrl '
                                                                                                     '+ L '
                                                                                                     '开启，然后重试。',
           'Error': '错误',
           'Please choose a save location.': '请选择保存位置。',
           'The selected save location does not exist.': '所选保存文件夹不存在。',
           'Please enter a file name.': '请输入文件名。',
           'The file name cannot contain: < > : " / \\ | ? *': '文件名不能包含以下字符：< > : " / \\ | ? *',
           'File Already Exists': '文件已存在',
           'This TXT file already exists.\n\nOverwrite it?': '该 TXT 文件已存在。\n\n要覆盖它吗？',
           'Unable to Create TXT': '无法创建 TXT 文件',
           'Unable to Change Microphone': '无法切换麦克风',
           'Windows could not change the default microphone.\n\n': 'Windows 无法切换默认麦克风。\n\n',
           'Saved': '已保存',
           'TXT saved successfully:\n\n': 'TXT 已保存至：\n\n',
           'Recording Stopped': '录制已结束',
           'Windows Live Captions was closed.\n\nThe current recording session was stopped and the TXT file was saved successfully:\n\n': 'Windows '
                                                                                                                                          '实时字幕已关闭，转写也已自动停止。\n'
                                                                                                                                          '\n'
                                                                                                                                          '当前 '
                                                                                                                                          'TXT '
                                                                                                                                          '已成功保存至：\n'
                                                                                                                                          '\n',
           'Live Captions Setting': '实时字幕设置',
           '\n\nPlease set it manually in:\n\nLive Captions > Settings > Preferences > Include microphone audio': '\n'
                                                                                                                  '\n'
                                                                                                                  '请在以下位置手动设置：\n'
                                                                                                                  '\n'
                                                                                                                  '实时字幕 '
                                                                                                                  '> '
                                                                                                                  '设置 '
                                                                                                                  '> '
                                                                                                                  '首选项 '
                                                                                                                  '> '
                                                                                                                  '包含麦克风音频',
           'Recording in Progress': '正在转写',
           'Recording is still active.\n\nClosing the application will stop recording and save the current TXT file.\n\nContinue?': '当前仍在转写。\n'
                                                                                                                                    '\n'
                                                                                                                                    '关闭程序将停止转写并保存当前 '
                                                                                                                                    'TXT。\n'
                                                                                                                                    '\n'
                                                                                                                                    '确定退出吗？',
           'Choose TXT Save Location': '选择 TXT 保存位置',
           'Text file': '文本文件',
           'All files': '所有文件',
           'Windows Live Captions is not open.': 'Windows 实时字幕尚未打开。',
           'Could not find the Live Captions Settings button.': '未找到实时字幕的设置按钮。',
           'Could not open Live Captions Settings.': '无法打开实时字幕设置。',
           'Could not find Preferences in Live Captions.': '未找到实时字幕的首选项。',
           'Could not open Live Captions Preferences.': '无法打开实时字幕首选项。',
           'Could not find the Include microphone audio option.': '未找到“包含麦克风音频”选项。',
           'Could not change the microphone option.': '无法更改麦克风音频设置。',
           'Unable to read the selected file path.': '无法读取所选文件路径。',
           'Language': '语言'},
 'zh_TW': {'Choose an audio mode': '請選擇音訊模式',
           'System Audio\n\nCapture speech played by this PC': '系統音訊\n\n轉寫電腦正在播放的聲音',
           'Microphone\n\nCaption speech from a microphone': '麥克風\n\n轉寫麥克風收到的聲音',
           'Windows Live Captions will open after you choose a mode.': '選擇模式後，將自動開啟 Windows 即時字幕。',
           'Back': '返回',
           'Current Output': '目前輸出裝置',
           'Automatically follows the current Windows default output device.': '自動使用 Windows 目前的預設輸出裝置。',
           'Microphone': '麥克風',
           'Input Level': '輸入音量',
           'For microphone-only transcription, avoid playing other speech audio on the PC.': '如果只想轉寫麥克風聲音，請盡量避免電腦同時播放其他人聲。',
           'Save Location:': '儲存位置：',
           'Choose Save...': '選擇儲存位置…',
           'File Name:': '檔案名稱：',
           'Start Recording': '開始轉寫',
           'Pause': '暫停',
           'Continue': '繼續',
           'Stop & Save': '停止並儲存',
           'System Audio Mode': '系統音訊模式',
           'Capture speech played by this PC': '轉寫電腦正在播放的聲音',
           'Microphone Mode': '麥克風模式',
           'Caption speech from your selected microphone': '轉寫所選麥克風收到的聲音',
           'Opening Windows Live Captions...': '正在開啟 Windows 即時字幕…',
           'Waiting for Windows Live Captions...': '正在等待 Windows 即時字幕…',
           'Configuring Live Captions...': '正在設定即時字幕…',
           'No microphone found': '找不到麥克風',
           'Connecting...': '正在連線…',
           'Unable to read input level': '無法讀取輸入音量',
           'Input detected': '已偵測到輸入訊號',
           'Windows default output': 'Windows 預設輸出裝置',
           'Live Captions is not open. Press Win + Ctrl + L to open it.': '即時字幕尚未開啟，請按 Win + Ctrl + L 開啟。',
           'Ready - Live Captions connected': '已就緒 · 即時字幕已連線',
           'Connected to Windows Live Captions. Waiting for speech...': '已連線即時字幕，正在等待語音…',
           'Paused': '已暫停',
           'Microphone mode selected - manual Live Captions microphone setting may be required.': '已選擇麥克風模式，可能需要在即時字幕中手動開啟麥克風輸入。',
           'System Audio mode selected - manual Live Captions microphone setting may be required.': '已選擇系統音訊模式，可能需要在即時字幕中手動關閉麥克風輸入。',
           'Please Wait': '請稍候',
           'Audio mode is still being configured.': '音訊模式仍在設定中，請稍後再試。',
           'Live Captions Not Open': '即時字幕尚未開啟',
           'Windows Live Captions is not open.\n\nPress Win + Ctrl + L to open it, then try again.': 'Windows '
                                                                                                     '即時字幕尚未開啟。\n'
                                                                                                     '\n'
                                                                                                     '請按 Win '
                                                                                                     '+ Ctrl '
                                                                                                     '+ L '
                                                                                                     '開啟，然後重試。',
           'Error': '錯誤',
           'Please choose a save location.': '請選擇儲存位置。',
           'The selected save location does not exist.': '找不到所選的儲存資料夾。',
           'Please enter a file name.': '請輸入檔案名稱。',
           'The file name cannot contain: < > : " / \\ | ? *': '檔案名稱不可包含以下字元：< > : " / \\ | ? *',
           'File Already Exists': '檔案已存在',
           'This TXT file already exists.\n\nOverwrite it?': '這個 TXT 檔案已存在。\n\n要覆寫嗎？',
           'Unable to Create TXT': '無法建立 TXT 檔案',
           'Unable to Change Microphone': '無法切換麥克風',
           'Windows could not change the default microphone.\n\n': 'Windows 無法切換預設麥克風。\n\n',
           'Saved': '已儲存',
           'TXT saved successfully:\n\n': 'TXT 已儲存至：\n\n',
           'Recording Stopped': '錄製已結束',
           'Windows Live Captions was closed.\n\nThe current recording session was stopped and the TXT file was saved successfully:\n\n': 'Windows '
                                                                                                                                          '即時字幕已關閉，轉寫已自動停止。\n'
                                                                                                                                          '\n'
                                                                                                                                          '目前的 '
                                                                                                                                          'TXT '
                                                                                                                                          '已成功儲存至：\n'
                                                                                                                                          '\n',
           'Live Captions Setting': '即時字幕設定',
           '\n\nPlease set it manually in:\n\nLive Captions > Settings > Preferences > Include microphone audio': '\n'
                                                                                                                  '\n'
                                                                                                                  '請在以下位置手動設定：\n'
                                                                                                                  '\n'
                                                                                                                  '即時字幕 '
                                                                                                                  '> '
                                                                                                                  '設定 '
                                                                                                                  '> '
                                                                                                                  '喜好設定 '
                                                                                                                  '> '
                                                                                                                  '包含麥克風音訊',
           'Recording in Progress': '正在轉寫',
           'Recording is still active.\n\nClosing the application will stop recording and save the current TXT file.\n\nContinue?': '目前仍在轉寫。\n'
                                                                                                                                    '\n'
                                                                                                                                    '關閉程式會停止轉寫並儲存目前的 '
                                                                                                                                    'TXT。\n'
                                                                                                                                    '\n'
                                                                                                                                    '確定要離開嗎？',
           'Choose TXT Save Location': '選擇 TXT 儲存位置',
           'Text file': '文字檔案',
           'All files': '所有檔案',
           'Windows Live Captions is not open.': 'Windows 即時字幕尚未開啟。',
           'Could not find the Live Captions Settings button.': '找不到即時字幕的設定按鈕。',
           'Could not open Live Captions Settings.': '無法開啟即時字幕設定。',
           'Could not find Preferences in Live Captions.': '找不到即時字幕的喜好設定。',
           'Could not open Live Captions Preferences.': '無法開啟即時字幕喜好設定。',
           'Could not find the Include microphone audio option.': '找不到「包含麥克風音訊」選項。',
           'Could not change the microphone option.': '無法變更麥克風音訊設定。',
           'Unable to read the selected file path.': '無法讀取所選檔案路徑。',
           'Language': '語言'},
 'ja': {'Choose an audio mode': '音声モードを選択してください',
        'System Audio\n\nCapture speech played by this PC': 'システム音声\n\nPCで再生中の音声を文字に変換',
        'Microphone\n\nCaption speech from a microphone': 'マイク\n\nマイクからの音声を文字に変換',
        'Windows Live Captions will open after you choose a mode.': 'モードを選択すると Windows ライブ キャプションが開きます。',
        'Back': '戻る',
        'Current Output': '現在の出力先',
        'Automatically follows the current Windows default output device.': 'Windows の既定の出力デバイスに自動で切り替わります。',
        'Microphone': 'マイク',
        'Input Level': '入力レベル',
        'For microphone-only transcription, avoid playing other speech audio on the PC.': 'マイクの音声だけを記録する場合は、PCでほかの人の声を再生しないことをおすすめします。',
        'Save Location:': '保存先：',
        'Choose Save...': '保存先を選択…',
        'File Name:': 'ファイル名：',
        'Start Recording': '記録を開始',
        'Pause': '一時停止',
        'Continue': '再開',
        'Stop & Save': '停止して保存',
        'System Audio Mode': 'システム音声モード',
        'Capture speech played by this PC': 'PCで再生中の音声を記録します',
        'Microphone Mode': 'マイクモード',
        'Caption speech from your selected microphone': '選択したマイクの音声を記録します',
        'Opening Windows Live Captions...': 'Windows ライブ キャプションを開いています…',
        'Waiting for Windows Live Captions...': 'Windows ライブ キャプションを待っています…',
        'Configuring Live Captions...': 'ライブ キャプションを設定しています…',
        'No microphone found': 'マイクが見つかりません',
        'Connecting...': '接続しています…',
        'Unable to read input level': '入力レベルを取得できません',
        'Input detected': '入力を検出しました',
        'Windows default output': 'Windows の既定の出力先',
        'Live Captions is not open. Press Win + Ctrl + L to open it.': 'ライブ キャプションは開いていません。Win + Ctrl + L '
                                                                       'で開いてください。',
        'Ready - Live Captions connected': '準備完了 · ライブ キャプションに接続済み',
        'Connected to Windows Live Captions. Waiting for speech...': 'ライブ キャプションに接続済みです。音声を待っています…',
        'Paused': '一時停止中',
        'Microphone mode selected - manual Live Captions microphone setting may be required.': 'マイクモードを選択しました。ライブ '
                                                                                               'キャプションでマイク入力を手動で有効にする必要がある場合があります。',
        'System Audio mode selected - manual Live Captions microphone setting may be required.': 'システム音声モードを選択しました。ライブ '
                                                                                                 'キャプションでマイク入力を手動で無効にする必要がある場合があります。',
        'Please Wait': 'しばらくお待ちください',
        'Audio mode is still being configured.': '音声モードを設定中です。しばらくしてからもう一度お試しください。',
        'Live Captions Not Open': 'ライブ キャプションが開いていません',
        'Windows Live Captions is not open.\n\nPress Win + Ctrl + L to open it, then try again.': 'Windows '
                                                                                                  'ライブ '
                                                                                                  'キャプションが開いていません。\n'
                                                                                                  '\n'
                                                                                                  'Win + '
                                                                                                  'Ctrl + L '
                                                                                                  'で開いてから、もう一度お試しください。',
        'Error': 'エラー',
        'Please choose a save location.': '保存先を選択してください。',
        'The selected save location does not exist.': '選択した保存先フォルダーが見つかりません。',
        'Please enter a file name.': 'ファイル名を入力してください。',
        'The file name cannot contain: < > : " / \\ | ? *': 'ファイル名に次の文字は使用できません：< > : " / \\ | ? *',
        'File Already Exists': 'ファイルがすでに存在します',
        'This TXT file already exists.\n\nOverwrite it?': '同じ名前の TXT ファイルがすでにあります。\n\n上書きしますか？',
        'Unable to Create TXT': 'TXT ファイルを作成できません',
        'Unable to Change Microphone': 'マイクを変更できません',
        'Windows could not change the default microphone.\n\n': 'Windows で既定のマイクを変更できませんでした。\n\n',
        'Saved': '保存しました',
        'TXT saved successfully:\n\n': 'TXT を保存しました：\n\n',
        'Recording Stopped': '記録を終了しました',
        'Windows Live Captions was closed.\n\nThe current recording session was stopped and the TXT file was saved successfully:\n\n': 'Windows '
                                                                                                                                       'ライブ '
                                                                                                                                       'キャプションが閉じられたため、記録を終了しました。\n'
                                                                                                                                       '\n'
                                                                                                                                       '現在の内容は '
                                                                                                                                       'TXT '
                                                                                                                                       'ファイルに保存されました：\n'
                                                                                                                                       '\n',
        'Live Captions Setting': 'ライブ キャプションの設定',
        '\n\nPlease set it manually in:\n\nLive Captions > Settings > Preferences > Include microphone audio': '\n'
                                                                                                               '\n'
                                                                                                               '以下の項目を手動で設定してください：\n'
                                                                                                               '\n'
                                                                                                               'ライブ '
                                                                                                               'キャプション '
                                                                                                               '> '
                                                                                                               '設定 '
                                                                                                               '> '
                                                                                                               '基本設定 '
                                                                                                               '> '
                                                                                                               'マイク音声を含める',
        'Recording in Progress': '記録中',
        'Recording is still active.\n\nClosing the application will stop recording and save the current TXT file.\n\nContinue?': 'まだ記録中です。\n'
                                                                                                                                 '\n'
                                                                                                                                 'アプリを閉じると記録を停止し、現在の '
                                                                                                                                 'TXT '
                                                                                                                                 'を保存します。\n'
                                                                                                                                 '\n'
                                                                                                                                 '終了しますか？',
        'Choose TXT Save Location': 'TXT の保存先を選択',
        'Text file': 'テキストファイル',
        'All files': 'すべてのファイル',
        'Windows Live Captions is not open.': 'Windows ライブ キャプションが開いていません。',
        'Could not find the Live Captions Settings button.': 'ライブ キャプションの設定ボタンが見つかりません。',
        'Could not open Live Captions Settings.': 'ライブ キャプションの設定を開けませんでした。',
        'Could not find Preferences in Live Captions.': 'ライブ キャプションの基本設定が見つかりません。',
        'Could not open Live Captions Preferences.': 'ライブ キャプションの基本設定を開けませんでした。',
        'Could not find the Include microphone audio option.': '「マイク音声を含める」が見つかりません。',
        'Could not change the microphone option.': 'マイク音声の設定を変更できませんでした。',
        'Unable to read the selected file path.': '選択したファイルパスを読み取れませんでした。',
        'Language': '言語'}}
class LiveCaptionsRecorder:

    @staticmethod
    def _language_path():
        folder = os.path.join(os.environ.get('APPDATA', os.path.expanduser('~')), 'LiveCaptionsTXTRecorder')
        return os.path.join(folder, 'ui_settings.json')

    def load_language(self):
        try:
            with open(self._language_path(), 'r', encoding='utf-8') as f:
                choice = json.load(f).get('language', 'en')
            return choice if choice in LANGUAGE_NAMES else 'en'
        except (OSError, ValueError, TypeError, AttributeError):
            return 'en'

    def save_language(self):
        try:
            path = self._language_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            temporary = path + '.tmp'
            with open(temporary, 'w', encoding='utf-8') as f:
                json.dump({'language': self.language_code}, f, ensure_ascii=False)
            os.replace(temporary, path)
        except OSError:
            pass

    def t(self, value):
        """Translate UI text only; leave audio device names and TXT contents unchanged."""
        if not isinstance(value, str) or not value:
            return value
        canonical = value
        for language, mapping in LOCALIZED_UI.items():
            for english, localized in mapping.items():
                if canonical == localized:
                    canonical = english
                    break
            if canonical != value:
                break
        if canonical.startswith('Recording - ') and canonical.endswith(' mode'):
            what = canonical[len('Recording - '):-len(' mode')]
            modes = {'System Audio': ('시스템 오디오', '系统音频', '系統音訊', 'システム音声'), 'Microphone': ('마이크', '麦克风', '麥克風', 'マイク')}
            if what in modes:
                formats = {'en': 'Recording - {} mode', 'ko': '기록 중 · {}', 'zh_CN': '转写中 · {}', 'zh_TW': '轉寫中 · {}', 'ja': '記録中 · {}'}
                code = self.language_code
                if code == 'en':
                    return formats[code].format(what)
                return formats[code].format(modes[what][('ko', 'zh_CN', 'zh_TW', 'ja').index(code)])
        for code, label_fmt in (('ko', '기록 중 · '), ('zh_CN', '转写中 · '), ('zh_TW', '轉寫中 · '), ('ja', '記録中 · ')):
            if value.startswith(label_fmt):
                displayed = value[len(label_fmt):]
                for mode_name, translated in (('System Audio', ('시스템 오디오', '系统音频', '系統音訊', 'システム音声')), ('Microphone', ('마이크', '麦克风', '麥克風', 'マイク'))):
                    if displayed == translated[('ko', 'zh_CN', 'zh_TW', 'ja').index(code)]:
                        return self.t('Recording - ' + mode_name + ' mode')
        translations = LOCALIZED_UI.get(self.language_code, {})
        if canonical in ENGLISH_UI:
            return translations.get(canonical, canonical)
        for english in sorted(ENGLISH_UI, key=len, reverse=True):
            if english.endswith(('\n\n', ':\n\n')) and canonical.startswith(english):
                return translations.get(english, english) + canonical[len(english):]
        for english in sorted(ENGLISH_UI, key=len, reverse=True):
            if english.startswith('\n\n') and canonical.endswith(english):
                return canonical[:-len(english)] + translations.get(english, english)
        return value

    def change_language(self, event=None):
        choice = self.language_choice.get()
        self.language_code = next((code for code, name in LANGUAGE_NAMES.items() if name == choice), 'en')
        self.save_language()
        self.translate_all_ui()

    def translate_all_ui(self):
        """Update the home page, hidden detail page, button states and status immediately."""

        def visit(widget):
            try:
                old = widget.cget('text')
                new = self.t(old)
                if new != old:
                    widget.configure(text=new)
            except (tk.TclError, AttributeError, TypeError):
                pass
            for child in widget.winfo_children():
                visit(child)
        visit(self.root)
        for variable in (self.status_text, self.level_status_text, self.system_output_text):
            old = variable.get()
            new = self.t(old)
            if old != new:
                variable.set(new)

    def __init__(self, root):
        self.root = root
        self.root.title('Live Captions TXT Recorder')
        self.root.geometry('920x690')
        self.root.minsize(840, 620)
        self.root.resizable(True, True)
        pythoncom.CoInitialize()
        self.recording = False
        self.paused = False
        self.auto_stopping = False
        self.stop_event = threading.Event()
        self.worker_thread = None
        self.message_queue = queue.Queue()
        self.current_mode = None
        self.mode_configuring = False
        self.mode_startup_pending = False
        self.mode_startup_serial = 0
        self.desired_livecaptions_mic = False
        self.assumed_livecaptions_mic = False
        self.live_available = False
        self.live_hwnd = None
        self.live_window = None
        self.caption_control = None
        self.last_snapshot = ''
        self.history_text = ''
        self.mismatch_started = None
        self.mismatch_latest = ''
        self.file_handle = None
        self.output_path = None
        self.save_folder = tk.StringVar(value=os.path.join(os.path.expanduser('~'), 'Documents'))
        self.filename = tk.StringVar(value=self.make_default_filename())
        self.status_text = tk.StringVar(value='Choose an audio mode')
        self.system_output_text = tk.StringVar(value='Detecting...')
        self.microphone_text = tk.StringVar(value='')
        self.microphone_level = tk.DoubleVar(value=0.0)
        self.level_status_text = tk.StringVar(value='')
        self.microphone_map = {}
        self.selected_microphone_id = None
        self.original_defaults = {}
        self.defaults_saved = False
        self.meter_stream = None
        self.latest_peak = 0.0
        self.current_dark_mode = None
        self.colors = {}
        self.style = ttk.Style(self.root)
        self.language_code = self.load_language()
        self.language_choice = tk.StringVar(value=LANGUAGE_NAMES[self.language_code])
        self.build_ui()
        self.translate_all_ui()
        self.enable_window_drag()
        self.apply_system_theme(force=True)
        self.root.after(200, lambda: self.apply_system_theme(force=True))
        self.live_available = bool(self.find_livecaptions_hwnd())
        self.status_text.set(self.t('Choose an audio mode'))
        self.update_start_button_state()
        self.root.after(100, self.process_messages)
        self.root.after(THEME_CHECK_INTERVAL, self.watch_system_theme)
        self.root.after(DEVICE_REFRESH_INTERVAL, self.refresh_devices)
        self.root.after(LEVEL_REFRESH_INTERVAL, self.update_microphone_level)
        self.root.after(LIVE_CAPTIONS_CHECK_INTERVAL, self.monitor_live_captions)
        self.root.protocol('WM_DELETE_WINDOW', self.on_close)

    # ------------------------------------------------------------
    # Drag the regular window by any non-interactive area.
    # The native title bar continues to behave normally.
    # ------------------------------------------------------------

    def enable_window_drag(self):
        self._drag_anchor = None
        # Binding on the toplevel bindtag also receives child frame/label
        # events. Unlike bind_all(), it does not alter unrelated dialogs.
        self.root.bind('<ButtonPress-1>', self._drag_press, add='+')
        self.root.bind('<B1-Motion>', self._drag_motion, add='+')
        self.root.bind('<ButtonRelease-1>', self._drag_release, add='+')

    def _drag_surface_allowed(self, widget):
        # Do not steal a click/drag from functional controls. In particular,
        # the save path and filename must remain editable and text-selectable.
        excluded = {
            'TButton', 'Button', 'TCombobox', 'Combobox',
            'TEntry', 'Entry', 'Text', 'TCheckbutton', 'Checkbutton',
            'TRadiobutton', 'Radiobutton', 'TScale', 'Scale',
            'TScrollbar', 'Scrollbar', 'TSpinbox', 'Spinbox',
            'Listbox', 'Treeview', 'TNotebook', 'TProgressbar',
        }
        while widget is not None:
            if widget is self.author_link:
                return False  # preserve the GitHub footer click
            try:
                if widget.winfo_class() in excluded:
                    return False
            except tk.TclError:
                return False
            if widget is self.root:
                break
            widget = widget.master
        return True

    def _drag_press(self, event):
        self._drag_anchor = None
        if event.widget.winfo_toplevel() is not self.root:
            return
        if self.root.state() != 'normal':
            return
        if not self._drag_surface_allowed(event.widget):
            return
        self._drag_anchor = (
            event.x_root, event.y_root,
            self.root.winfo_x(), self.root.winfo_y()
        )

    def _drag_motion(self, event):
        anchor = self._drag_anchor
        if anchor is None:
            return
        pointer_x, pointer_y, left, top = anchor
        shift_x = event.x_root - pointer_x
        shift_y = event.y_root - pointer_y
        # Prevent tiny hand movements from moving the window on a click.
        if abs(shift_x) < 5 and abs(shift_y) < 5:
            return
        self.root.geometry(f'+{left + shift_x}+{top + shift_y}')

    def _drag_release(self, event):
        self._drag_anchor = None

    def make_default_filename(self):
        return datetime.now().strftime('LiveCaptions_%Y-%m-%d_%H-%M-%S.txt')

    def build_ui(self):
        self.footer_frame = ttk.Frame(self.root, style='App.TFrame')
        self.footer_frame.pack(side='bottom', fill='x', padx=34, pady=(0, 16))
        self.footer_prefix = ttk.Label(self.footer_frame, text=self.t('LiveCaptionsTXTRecorder  ·  '), style='Footer.TLabel')
        self.footer_prefix.pack(side='left')
        self.author_link = tk.Label(self.footer_frame, text=self.t('by kidoyuyu'), font=('Segoe UI', 9), cursor='hand2', bd=0, highlightthickness=0)
        self.author_link.pack(side='left')
        self.author_link.bind('<Button-1>', lambda event: webbrowser.open(GITHUB_URL))
        self.author_link.bind('<Enter>', self.on_author_enter)
        self.author_link.bind('<Leave>', self.on_author_leave)
        self.main = ttk.Frame(self.root, style='App.TFrame', padding=(34, 26))
        self.main.pack(fill='both', expand=True)
        self.build_home_page()
        self.build_detail_page()
        self.show_home()

    def build_home_page(self):
        self.home_page = ttk.Frame(self.main, style='App.TFrame')
        language_bar = ttk.Frame(self.home_page, style='App.TFrame')
        language_bar.pack(side='top', fill='x', pady=(0, 10))
        language_group = ttk.Frame(language_bar, style='App.TFrame')
        language_group.pack(side='right')
        ttk.Label(language_group, text=self.t('Language'), style='Hint.TLabel').pack(side='left', padx=(0, 9))
        self.language_combo = ttk.Combobox(language_group, textvariable=self.language_choice, values=list(LANGUAGE_NAMES.values()), state='readonly', width=14, style='Audio.TCombobox')
        self.language_combo.pack(side='left')
        self.language_combo.bind('<<ComboboxSelected>>', self.change_language)
        title = ttk.Label(self.home_page, text=self.t('Live Captions TXT Recorder'), style='Title.TLabel')
        title.pack(anchor='w')
        subtitle = ttk.Label(self.home_page, text=self.t('Choose an audio mode'), style='Subtitle.TLabel')
        subtitle.pack(anchor='w', pady=(5, 34))
        cards = ttk.Frame(self.home_page, style='App.TFrame')
        cards.pack(fill='x')
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)
        self.system_mode_button = ttk.Button(cards, text=self.t('System Audio\n\nCapture speech played by this PC'), style='Mode.TButton', command=lambda: self.open_mode(MODE_SYSTEM))
        self.system_mode_button.grid(row=0, column=0, sticky='nsew', padx=(0, 10))
        self.microphone_mode_button = ttk.Button(cards, text=self.t('Microphone\n\nCaption speech from a microphone'), style='Mode.TButton', command=lambda: self.open_mode(MODE_MICROPHONE))
        self.microphone_mode_button.grid(row=0, column=1, sticky='nsew', padx=(10, 0))
        note = ttk.Label(self.home_page, text=self.t('Windows Live Captions will open after you choose a mode.'), style='Hint.TLabel')
        note.pack(anchor='w', pady=(20, 0))

    def build_detail_page(self):
        self.detail_page = ttk.Frame(self.main, style='App.TFrame')
        header = ttk.Frame(self.detail_page, style='App.TFrame')
        header.pack(fill='x', pady=(0, 18))
        self.back_button = ttk.Button(header, text=self.t('Back'), style='Secondary.TButton', command=self.go_back)
        self.back_button.pack(side='left', padx=(0, 18))
        title_area = ttk.Frame(header, style='App.TFrame')
        title_area.pack(side='left', fill='x', expand=True)
        self.detail_title = ttk.Label(title_area, text=self.t(''), style='Title.TLabel')
        self.detail_title.pack(anchor='w')
        self.detail_subtitle = ttk.Label(title_area, text=self.t(''), style='Subtitle.TLabel')
        self.detail_subtitle.pack(anchor='w', pady=(3, 0))
        self.audio_card = ttk.Frame(self.detail_page, style='Card.TFrame', padding=22)
        self.audio_card.pack(fill='x', pady=(0, 16))
        self.system_frame = ttk.Frame(self.audio_card, style='Card.TFrame')
        system_label = ttk.Label(self.system_frame, text=self.t('Current Output'), style='Body.TLabel')
        system_label.pack(anchor='w')
        self.system_device_label = ttk.Label(self.system_frame, textvariable=self.system_output_text, style='Device.TLabel')
        self.system_device_label.pack(anchor='w', pady=(7, 0))
        system_note = ttk.Label(self.system_frame, text=self.t('Automatically follows the current Windows default output device.'), style='CardHint.TLabel')
        system_note.pack(anchor='w', pady=(7, 0))
        self.microphone_frame = ttk.Frame(self.audio_card, style='Card.TFrame')
        self.microphone_frame.columnconfigure(1, weight=1)
        mic_label = ttk.Label(self.microphone_frame, text=self.t('Microphone'), style='Body.TLabel')
        mic_label.grid(row=0, column=0, sticky='w', padx=(0, 16))
        self.microphone_combo = ttk.Combobox(self.microphone_frame, textvariable=self.microphone_text, state='readonly', style='Audio.TCombobox')
        self.microphone_combo.grid(row=0, column=1, sticky='ew')
        self.microphone_combo.bind('<<ComboboxSelected>>', self.on_microphone_selected)
        level_label = ttk.Label(self.microphone_frame, text=self.t('Input Level'), style='Body.TLabel')
        level_label.grid(row=1, column=0, sticky='w', padx=(0, 16), pady=(18, 0))
        self.input_bar = ttk.Progressbar(self.microphone_frame, variable=self.microphone_level, maximum=100, mode='determinate', style='Audio.Horizontal.TProgressbar')
        self.input_bar.grid(row=1, column=1, sticky='ew', pady=(18, 0))
        self.level_status_label = ttk.Label(self.microphone_frame, textvariable=self.level_status_text, style='CardHint.TLabel')
        self.level_status_label.grid(row=2, column=1, sticky='w', pady=(5, 0))
        warning = ttk.Label(self.microphone_frame, text=self.t('For microphone-only transcription, avoid playing other speech audio on the PC.'), style='Warning.TLabel', wraplength=720)
        warning.grid(row=3, column=0, columnspan=2, sticky='w', pady=(16, 0))
        self.form_frame = ttk.Frame(self.detail_page, style='Card.TFrame', padding=(22, 20))
        self.form_frame.pack(fill='x')
        self.form_frame.columnconfigure(1, weight=1)
        self.save_location_label = ttk.Label(self.form_frame, text=self.t('Save Location:'), style='Body.TLabel')
        self.save_location_label.grid(row=0, column=0, sticky='w', padx=(0, 14), pady=(0, 14))
        self.folder_entry = ttk.Entry(self.form_frame, textvariable=self.save_folder, style='Modern.TEntry')
        self.folder_entry.grid(row=0, column=1, sticky='ew', pady=(0, 14))
        self.choose_button = ttk.Button(self.form_frame, text=self.t('Choose Save...'), style='Secondary.TButton', command=self.choose_save_path)
        self.choose_button.grid(row=0, column=2, padx=(12, 0), pady=(0, 14))
        self.filename_label = ttk.Label(self.form_frame, text=self.t('File Name:'), style='Body.TLabel')
        self.filename_label.grid(row=1, column=0, sticky='w', padx=(0, 14))
        self.filename_entry = ttk.Entry(self.form_frame, textvariable=self.filename, style='Modern.TEntry')
        self.filename_entry.grid(row=1, column=1, columnspan=2, sticky='ew')
        self.button_frame = ttk.Frame(self.detail_page, style='App.TFrame')
        self.button_frame.pack(fill='x', pady=(22, 16))
        for column in range(3):
            self.button_frame.columnconfigure(column, weight=1)
        self.start_button = ttk.Button(self.button_frame, text=self.t('Start Recording'), style='Primary.TButton', state='disabled', command=self.start_recording)
        self.start_button.grid(row=0, column=0, sticky='ew', padx=(0, 8))
        self.pause_button = ttk.Button(self.button_frame, text=self.t('Pause'), style='Secondary.TButton', state='disabled', command=self.toggle_pause)
        self.pause_button.grid(row=0, column=1, sticky='ew', padx=8)
        self.stop_button = ttk.Button(self.button_frame, text=self.t('Stop & Save'), style='Secondary.TButton', state='disabled', command=self.stop_recording)
        self.stop_button.grid(row=0, column=2, sticky='ew', padx=(8, 0))
        self.status_frame = ttk.Frame(self.detail_page, style='Status.TFrame', padding=(16, 13))
        self.status_frame.pack(fill='x')
        self.status_label = ttk.Label(self.status_frame, textvariable=self.status_text, style='Status.TLabel')
        self.status_label.pack(anchor='w')

    def show_home(self):
        self.detail_page.pack_forget()
        self.home_page.pack(fill='both', expand=True)

    def open_mode(self, mode):
        if self.recording:
            return
        self.mode_startup_serial += 1
        startup_serial = self.mode_startup_serial
        self.current_mode = mode
        self.mode_startup_pending = True
        if mode == MODE_SYSTEM:
            self.desired_livecaptions_mic = False
        else:
            self.desired_livecaptions_mic = True
        self.home_page.pack_forget()
        self.detail_page.pack(fill='both', expand=True)
        if mode == MODE_SYSTEM:
            self.stop_meter()
            self.restore_original_default_microphones()
            self.detail_title.config(text=self.t('System Audio Mode'))
            self.detail_subtitle.config(text=self.t('Capture speech played by this PC'))
            self.microphone_frame.pack_forget()
            self.system_frame.pack(fill='x')
            self.refresh_system_output()
        else:
            self.detail_title.config(text=self.t('Microphone Mode'))
            self.detail_subtitle.config(text=self.t('Caption speech from your selected microphone'))
            self.system_frame.pack_forget()
            self.microphone_frame.pack(fill='x')
            self.save_original_default_microphones()
            self.refresh_microphones(select_default=True)
        if self.find_livecaptions_hwnd():
            self.live_available = True
            self.finish_mode_startup(startup_serial, mode)
            return
        self.live_available = False
        self.status_text.set(self.t('Opening Windows Live Captions...'))
        self.update_start_button_state()
        self.send_live_captions_hotkey()
        self.root.after(1200, lambda: self.finish_mode_startup(startup_serial, mode))

    def finish_mode_startup(self, startup_serial, expected_mode):
        if startup_serial != self.mode_startup_serial:
            return
        if self.current_mode != expected_mode:
            return
        hwnd = self.find_livecaptions_hwnd()
        if not hwnd:
            self.live_available = False
            self.status_text.set(self.t('Waiting for Windows Live Captions...'))
            self.update_start_button_state()
            self.root.after(400, lambda: self.finish_mode_startup(startup_serial, expected_mode))
            return
        self.live_available = True
        self.mode_startup_pending = False
        self.status_text.set(self.t('Configuring Live Captions...'))
        self.update_start_button_state()
        if expected_mode == MODE_MICROPHONE:
            self.apply_livecaptions_microphone_async(True, show_errors=True)
        else:
            self.apply_livecaptions_microphone_async(False, show_errors=False)

    def go_back(self):
        if self.recording:
            return
        self.mode_startup_serial += 1
        self.mode_startup_pending = False
        self.stop_meter()
        if self.current_mode == MODE_MICROPHONE:
            self.restore_original_default_microphones()
            if self.find_livecaptions_hwnd():
                self.apply_livecaptions_microphone_async(False, show_errors=False)
        self.current_mode = None
        self.desired_livecaptions_mic = False
        self.microphone_level.set(0)
        self.level_status_text.set(self.t(''))
        self.status_text.set(self.t('Choose an audio mode'))
        self.show_home()

    def apply_system_theme(self, force=False):
        dark_mode = is_windows_dark_mode()
        if not force and dark_mode == self.current_dark_mode:
            return
        self.current_dark_mode = dark_mode
        try:
            self.style.theme_use('clam')
        except Exception:
            pass
        if dark_mode:
            colors = {'bg': '#202020', 'card': '#2b2b2b', 'status': '#262626', 'text': '#f3f3f3', 'muted': '#b5b5b5', 'entry': '#333333', 'border': '#505050', 'button': '#333333', 'button_hover': '#414141', 'button_pressed': '#4a4a4a', 'disabled': '#777777', 'accent': '#0f6cbd', 'accent_hover': '#115ea3', 'warning': '#f2c94c', 'link': '#66b3ff'}
        else:
            colors = {'bg': '#f5f5f5', 'card': '#ffffff', 'status': '#ffffff', 'text': '#1a1a1a', 'muted': '#666666', 'entry': '#ffffff', 'border': '#d0d0d0', 'button': '#ffffff', 'button_hover': '#eeeeee', 'button_pressed': '#e2e2e2', 'disabled': '#9a9a9a', 'accent': '#0f6cbd', 'accent_hover': '#115ea3', 'warning': '#8a5a00', 'link': '#0067c0'}
        self.colors = colors
        self.root.configure(bg=colors['bg'])
        self.style.configure('App.TFrame', background=colors['bg'])
        self.style.configure('Card.TFrame', background=colors['card'])
        self.style.configure('Status.TFrame', background=colors['status'], relief='solid', borderwidth=1, bordercolor=colors['border'])
        self.style.configure('Title.TLabel', background=colors['bg'], foreground=colors['text'], font=('Segoe UI Variable Display', 19, 'bold'))
        self.style.configure('Subtitle.TLabel', background=colors['bg'], foreground=colors['muted'], font=('Segoe UI', 10))
        self.style.configure('Footer.TLabel', background=colors['bg'], foreground=colors['muted'], font=('Segoe UI', 9))
        self.style.configure('Hint.TLabel', background=colors['bg'], foreground=colors['muted'], font=('Segoe UI', 9))
        self.style.configure('Body.TLabel', background=colors['card'], foreground=colors['text'], font=('Segoe UI', 10))
        self.style.configure('Device.TLabel', background=colors['card'], foreground=colors['text'], font=('Segoe UI', 11, 'bold'))
        self.style.configure('CardHint.TLabel', background=colors['card'], foreground=colors['muted'], font=('Segoe UI', 9))
        self.style.configure('Warning.TLabel', background=colors['card'], foreground=colors['warning'], font=('Segoe UI', 9))
        self.style.configure('Status.TLabel', background=colors['status'], foreground=colors['text'], font=('Segoe UI', 10))
        self.style.configure('Modern.TEntry', fieldbackground=colors['entry'], foreground=colors['text'], bordercolor=colors['border'], lightcolor=colors['border'], darkcolor=colors['border'], padding=(10, 8))
        self.style.map('Modern.TEntry', fieldbackground=[('disabled', colors['card'])], foreground=[('disabled', colors['disabled'])])
        self.style.configure('Audio.TCombobox', fieldbackground=colors['entry'], background=colors['button'], foreground=colors['text'], arrowcolor=colors['text'], bordercolor=colors['border'], padding=(8, 7))
        self.style.configure('Audio.Horizontal.TProgressbar', troughcolor=colors['entry'], background=colors['accent'], bordercolor=colors['border'], thickness=14)
        self.style.configure('Mode.TButton', background=colors['card'], foreground=colors['text'], bordercolor=colors['border'], lightcolor=colors['border'], darkcolor=colors['border'], padding=(24, 32), font=('Segoe UI', 11, 'bold'))
        self.style.map('Mode.TButton', background=[('active', colors['button_hover']), ('pressed', colors['button_pressed'])])
        self.style.configure('Secondary.TButton', background=colors['button'], foreground=colors['text'], bordercolor=colors['border'], lightcolor=colors['border'], darkcolor=colors['border'], padding=(14, 11), font=('Segoe UI', 10))
        self.style.map('Secondary.TButton', background=[('pressed', colors['button_pressed']), ('active', colors['button_hover']), ('disabled', colors['card'])], foreground=[('disabled', colors['disabled'])])
        self.style.configure('Primary.TButton', background=colors['accent'], foreground='#ffffff', bordercolor=colors['accent'], lightcolor=colors['accent'], darkcolor=colors['accent'], padding=(14, 11), font=('Segoe UI', 10, 'bold'))
        self.style.map('Primary.TButton', background=[('pressed', colors['accent_hover']), ('active', colors['accent_hover']), ('disabled', colors['card'])], foreground=[('disabled', colors['disabled'])])
        self.author_link.configure(bg=colors['bg'], fg=colors['muted'])
        self.apply_dark_title_bar(dark_mode)

    def watch_system_theme(self):
        self.apply_system_theme()
        self.root.after(THEME_CHECK_INTERVAL, self.watch_system_theme)

    def on_author_enter(self, event=None):
        if self.colors:
            self.author_link.configure(fg=self.colors['link'])

    def on_author_leave(self, event=None):
        if self.colors:
            self.author_link.configure(fg=self.colors['muted'])

    def apply_dark_title_bar(self, dark_mode):
        try:
            self.root.update_idletasks()
            child_hwnd = self.root.winfo_id()
            parent_hwnd = ctypes.windll.user32.GetParent(child_hwnd)
            handles = [child_hwnd]
            if parent_hwnd:
                handles.append(parent_hwnd)
            value = ctypes.c_int(1 if dark_mode else 0)
            for hwnd in handles:
                for attribute in (20, 19):
                    try:
                        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value))
                    except Exception:
                        pass
        except Exception:
            pass

    def refresh_devices(self):
        if self.current_mode == MODE_SYSTEM:
            self.refresh_system_output()
        elif self.current_mode == MODE_MICROPHONE:
            self.refresh_microphones(select_default=False)
        self.root.after(DEVICE_REFRESH_INTERVAL, self.refresh_devices)

    def refresh_system_output(self):
        try:
            device = AudioUtilities.GetSpeakers()
            if device and device.FriendlyName:
                self.system_output_text.set(self.t(device.FriendlyName))
            else:
                self.system_output_text.set(self.t('Windows default output'))
        except Exception:
            self.system_output_text.set(self.t('Windows default output'))

    def get_default_capture_id(self, role):
        try:
            enumerator = AudioUtilities.GetDeviceEnumerator()
            device = enumerator.GetDefaultAudioEndpoint(EDataFlow.eCapture.value, role.value)
            if device:
                return device.GetId()
        except Exception:
            pass
        return None

    def save_original_default_microphones(self):
        if self.defaults_saved:
            return
        self.original_defaults = {}
        for role in (ERole.eConsole, ERole.eMultimedia, ERole.eCommunications):
            device_id = self.get_default_capture_id(role)
            if device_id:
                self.original_defaults[role] = device_id
        self.defaults_saved = True

    def restore_original_default_microphones(self):
        if not self.defaults_saved:
            return
        for role, device_id in self.original_defaults.items():
            try:
                AudioUtilities.SetDefaultDevice(device_id, roles=[role])
            except Exception:
                pass
        self.original_defaults = {}
        self.defaults_saved = False
        self.selected_microphone_id = None

    def get_microphones(self):
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                devices = AudioUtilities.GetAllDevices(data_flow=EDataFlow.eCapture.value, device_state=DEVICE_STATE.ACTIVE.value)
            return devices
        except Exception:
            return []

    def refresh_microphones(self, select_default=False):
        devices = self.get_microphones()
        self.microphone_map = {}
        display_names = []
        counts = {}
        for device in devices:
            base_name = device.FriendlyName or 'Microphone'
            counts[base_name] = counts.get(base_name, 0) + 1
            if counts[base_name] == 1:
                display_name = base_name
            else:
                display_name = f'{base_name} ({counts[base_name]})'
            self.microphone_map[display_name] = device
            display_names.append(display_name)
        self.microphone_combo['values'] = display_names
        if not devices:
            self.microphone_text.set(self.t('No microphone found'))
            self.selected_microphone_id = None
            self.stop_meter()
            self.level_status_text.set(self.t('No microphone found'))
            return
        default_id = self.get_default_capture_id(ERole.eMultimedia)
        target_name = None
        target_device = None
        if not select_default and self.selected_microphone_id:
            for name, device in self.microphone_map.items():
                if device.id == self.selected_microphone_id:
                    target_name = name
                    target_device = device
                    break
        if target_device is None:
            for name, device in self.microphone_map.items():
                if device.id == default_id:
                    target_name = name
                    target_device = device
                    break
        if target_device is None:
            target_name = display_names[0]
            target_device = self.microphone_map[target_name]
        changed = self.selected_microphone_id != target_device.id
        self.microphone_text.set(target_name)
        self.selected_microphone_id = target_device.id
        if changed or self.meter_stream is None:
            self.start_meter_for_name(target_device.FriendlyName)

    def on_microphone_selected(self, event=None):
        if self.recording:
            return
        display_name = self.microphone_text.get()
        device = self.microphone_map.get(display_name)
        if not device:
            return
        self.save_original_default_microphones()
        try:
            AudioUtilities.SetDefaultDevice(device.id, roles=[ERole.eConsole, ERole.eMultimedia, ERole.eCommunications])
            self.selected_microphone_id = device.id
            self.start_meter_for_name(device.FriendlyName)
        except Exception as error:
            messagebox.showerror(self.t('Unable to Change Microphone'), self.t('Windows could not change the default microphone.\n\n' + str(error)))
            self.refresh_microphones(select_default=True)

    def normalize_device_name(self, name):
        name = str(name).lower().strip()
        name = re.sub('[\\(\\)\\[\\],._\\-]+', ' ', name)
        name = re.sub('\\s+', ' ', name)
        return name

    def find_sounddevice_input(self, windows_name):
        try:
            devices = sd.query_devices()
        except Exception:
            return None
        windows_normal = self.normalize_device_name(windows_name)
        best_index = None
        best_score = 0.0
        for index, info in enumerate(devices):
            try:
                if int(info['max_input_channels']) <= 0:
                    continue
                sd_name = str(info['name'])
                sd_normal = self.normalize_device_name(sd_name)
                if windows_normal in sd_normal or sd_normal in windows_normal:
                    score = 1.0
                else:
                    score = SequenceMatcher(None, windows_normal, sd_normal).ratio()
                if score > best_score:
                    best_score = score
                    best_index = index
            except Exception:
                continue
        if best_score < 0.3:
            return None
        return best_index

    def start_meter_for_name(self, windows_name):
        self.stop_meter()
        self.latest_peak = 0.0
        self.level_status_text.set(self.t('Connecting...'))
        device_index = self.find_sounddevice_input(windows_name)
        if device_index is None:
            self.level_status_text.set(self.t('Unable to read input level'))
            return
        try:
            info = sd.query_devices(device_index)
            sample_rate = float(info['default_samplerate'])

            def callback(indata, frames, time_info, status):
                try:
                    samples = memoryview(indata).cast('h')
                    peak = 0
                    for sample in samples:
                        value = abs(int(sample))
                        if value > peak:
                            peak = value
                    self.latest_peak = min(1.0, peak / 32768.0)
                except Exception:
                    self.latest_peak = 0.0
            self.meter_stream = sd.RawInputStream(device=device_index, samplerate=sample_rate, channels=1, dtype='int16', blocksize=0, latency='low', callback=callback)
            self.meter_stream.start()
            self.level_status_text.set(self.t('Input detected'))
        except Exception as error:
            self.meter_stream = None
            self.level_status_text.set(self.t('Unable to read input level'))
            print('Microphone meter error:', error)

    def stop_meter(self):
        if self.meter_stream is not None:
            try:
                self.meter_stream.stop()
            except Exception:
                pass
            try:
                self.meter_stream.close()
            except Exception:
                pass
        self.meter_stream = None
        self.latest_peak = 0.0
        self.microphone_level.set(0)

    def update_microphone_level(self):
        if self.current_mode == MODE_MICROPHONE:
            peak = max(0.0, min(1.0, self.latest_peak))
            visible_level = peak ** 0.45 * 100.0
            self.microphone_level.set(visible_level)
        else:
            self.microphone_level.set(0)
        self.root.after(LEVEL_REFRESH_INTERVAL, self.update_microphone_level)

    def choose_save_path(self):
        current_folder = self.save_folder.get().strip()
        if not os.path.isdir(current_folder):
            current_folder = os.path.expanduser('~')
        current_name = self.filename.get().strip()
        if not current_name:
            current_name = self.make_default_filename()
        try:
            selected_file = self.windows_save_dialog(current_folder, current_name)
        except Exception:
            selected_file = filedialog.asksaveasfilename(parent=self.root, title=self.t('Choose TXT Save Location'), initialdir=current_folder, initialfile=current_name, defaultextension='.txt', filetypes=[(self.t('Text file'), '*.txt'), (self.t('All files'), '*.*')])
        if selected_file:
            self.save_folder.set(os.path.dirname(selected_file))
            self.filename.set(os.path.basename(selected_file))

    def windows_save_dialog(self, initial_folder, initial_name):

        def ps_escape(value):
            return str(value).replace("'", "''")
        safe_folder = ps_escape(initial_folder)
        safe_title = str(self.t('Choose TXT Save Location')).replace("'", "''")
        safe_text_file = str(self.t('Text file')).replace("'", "''")
        safe_all_files = str(self.t('All files')).replace("'", "''")
        safe_name = ps_escape(initial_name)
        powershell_script = f"""\n$ErrorActionPreference = 'Stop'\n\ntry\n{{\n    Add-Type -TypeDefinition @"\nusing System;\nusing System.Runtime.InteropServices;\n\npublic static class HighDpiNative\n{{\n    [DllImport("user32.dll", SetLastError=true)]\n    public static extern bool SetProcessDpiAwarenessContext(\n        IntPtr dpiContext\n    );\n\n    [DllImport("user32.dll", SetLastError=true)]\n    public static extern bool SetProcessDPIAware();\n}}\n"@\n\n    try\n    {{\n        [HighDpiNative]::SetProcessDpiAwarenessContext(\n            [IntPtr]::new(-4)\n        ) | Out-Null\n    }}\n    catch\n    {{\n        try\n        {{\n            [HighDpiNative]::SetProcessDPIAware() | Out-Null\n        }}\n        catch\n        {{\n        }}\n    }}\n\n    Add-Type -AssemblyName System.Windows.Forms\n\n    try\n    {{\n        [System.Windows.Forms.Application]::EnableVisualStyles()\n    }}\n    catch\n    {{\n    }}\n\n    $dialog = New-Object System.Windows.Forms.SaveFileDialog\n\n    $dialog.Title = '{safe_title}'\n\n    $dialog.Filter =\n        '{safe_text_file} (*.txt)|*.txt|{safe_all_files} (*.*)|*.*'\n\n    $dialog.FilterIndex = 1\n    $dialog.DefaultExt = 'txt'\n    $dialog.AddExtension = $true\n    $dialog.OverwritePrompt = $true\n    $dialog.CheckPathExists = $true\n    $dialog.AutoUpgradeEnabled = $true\n    $dialog.RestoreDirectory = $true\n\n    $dialog.InitialDirectory = '{safe_folder}'\n    $dialog.FileName = '{safe_name}'\n\n    $result = $dialog.ShowDialog()\n\n    if ($result -eq [System.Windows.Forms.DialogResult]::OK)\n    {{\n        $bytes = [System.Text.Encoding]::UTF8.GetBytes(\n            $dialog.FileName\n        )\n\n        $encoded = [Convert]::ToBase64String(\n            $bytes\n        )\n\n        Write-Output $encoded\n    }}\n    else\n    {{\n        Write-Output '__CANCEL__'\n    }}\n\n    $dialog.Dispose()\n}}\ncatch\n{{\n    [Console]::Error.WriteLine(\n        $_.Exception.Message\n    )\n\n    exit 1\n}}\n"""
        encoded_script = base64.b64encode(powershell_script.encode('utf-16le')).decode('ascii')
        system_root = os.environ.get('SystemRoot', 'C:\\Windows')
        powershell_path = os.path.join(system_root, 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe')
        if not os.path.exists(powershell_path):
            powershell_path = 'powershell.exe'
        creation_flags = 0
        if os.name == 'nt':
            creation_flags = subprocess.CREATE_NO_WINDOW
        result = subprocess.run([powershell_path, '-NoLogo', '-NoProfile', '-STA', '-EncodedCommand', encoded_script], stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=creation_flags)
        stdout = result.stdout.decode('utf-8', errors='replace').strip()
        stderr = result.stderr.decode('utf-8', errors='replace').strip()
        if result.returncode != 0:
            raise RuntimeError(stderr if stderr else 'Windows SaveFileDialog failed.')
        if not stdout:
            return None
        output_line = stdout.splitlines()[-1].strip()
        if output_line == '__CANCEL__':
            return None
        try:
            return base64.b64decode(output_line).decode('utf-8')
        except Exception as error:
            raise RuntimeError('Unable to read the selected file path.') from error

    def apply_livecaptions_microphone_async(self, enabled, show_errors=False):
        self.desired_livecaptions_mic = bool(enabled)
        if self.mode_configuring:
            return
        if not self.find_livecaptions_hwnd():
            return
        self.mode_configuring = True
        self.update_start_button_state()
        worker = threading.Thread(target=self.livecaptions_microphone_worker, args=(bool(enabled), show_errors), daemon=True)
        worker.start()

    def livecaptions_microphone_worker(self, enabled, show_errors):
        pythoncom.CoInitialize()
        try:
            success, detail = self.set_livecaptions_microphone_enabled(enabled)
            self.message_queue.put(('mic_mode_result', (enabled, success, detail, show_errors)))
        finally:
            pythoncom.CoUninitialize()

    def get_livecaptions_uia_roots(self, hwnd):
        desktop = Desktop(backend='uia')
        roots = []
        try:
            roots.append(desktop.window(handle=hwnd))
        except Exception:
            pass
        try:
            process_id = win32process.GetWindowThreadProcessId(hwnd)[1]
            known_handles = {getattr(root, 'handle', None) for root in roots}
            for window in desktop.windows():
                try:
                    if window.element_info.process_id == process_id:
                        handle = getattr(window, 'handle', None)
                        if handle not in known_handles:
                            roots.append(window)
                            known_handles.add(handle)
                except Exception:
                    continue
        except Exception:
            pass
        return roots

    def find_uia_control(self, roots, name_terms=None, automation_terms=None, control_types=None):
        name_terms = [term.lower() for term in name_terms or []]
        automation_terms = [term.lower() for term in automation_terms or []]
        for root in roots:
            try:
                controls = [root]
                controls.extend(root.descendants())
            except Exception:
                continue
            for control in controls:
                try:
                    info = control.element_info
                    name = (info.name or '').strip().lower()
                    automation_id = (info.automation_id or '').strip().lower()
                    control_type = info.control_type or ''
                    if control_types and control_type not in control_types:
                        continue
                    name_match = any((term in name for term in name_terms)) if name_terms else False
                    automation_match = any((term in automation_id for term in automation_terms)) if automation_terms else False
                    if name_match or automation_match:
                        return control
                except Exception:
                    continue
        return None

    def click_uia_control(self, control):
        if control is None:
            return False
        try:
            control.invoke()
            return True
        except Exception:
            pass
        try:
            control.toggle()
            return True
        except Exception:
            pass
        try:
            control.set_focus()
            win32api.keybd_event(win32con.VK_SPACE, 0, 0, 0)
            win32api.keybd_event(win32con.VK_SPACE, 0, win32con.KEYEVENTF_KEYUP, 0)
            return True
        except Exception:
            pass
        return False

    def get_toggle_state(self, control):
        try:
            state = int(control.get_toggle_state())
            if state in (0, 1):
                return state
        except Exception:
            pass
        try:
            state = int(control.iface_toggle.CurrentToggleState)
            if state in (0, 1):
                return state
        except Exception:
            pass
        return None

    def close_livecaptions_menu(self):
        try:
            for _ in range(2):
                win32api.keybd_event(win32con.VK_ESCAPE, 0, 0, 0)
                win32api.keybd_event(win32con.VK_ESCAPE, 0, win32con.KEYEVENTF_KEYUP, 0)
                time.sleep(0.05)
        except Exception:
            pass

    def find_microphone_control(self, roots):
        return self.find_uia_control(roots, name_terms=['include microphone audio', 'microphone audio', 'include mic audio', '包括麦克风音频', '包含麦克风音频', '包括麥克風音訊', '包含麥克風音訊', '마이크 오디오 포함', '마이크', 'マイク オーディオ', 'マイク音声'], automation_terms=['microphone', 'mic'])

    def set_livecaptions_microphone_enabled(self, enabled):
        hwnd = self.find_livecaptions_hwnd()
        if not hwnd:
            return (False, 'Windows Live Captions is not open.')
        roots = self.get_livecaptions_uia_roots(hwnd)
        settings_control = self.find_uia_control(roots, name_terms=['settings', '设置', '設定', '설정'], automation_terms=['settings'], control_types=['Button'])
        if settings_control is None:
            return (False, 'Could not find the Live Captions Settings button.')
        if not self.click_uia_control(settings_control):
            return (False, 'Could not open Live Captions Settings.')
        time.sleep(0.35)
        roots = self.get_livecaptions_uia_roots(hwnd)
        mic_control = self.find_microphone_control(roots)
        if mic_control is None:
            preferences_control = self.find_uia_control(roots, name_terms=['preferences', '首选项', '偏好設定', '喜好設定', '기본 설정', '환경 설정'], automation_terms=['preference'])
            if preferences_control is None:
                self.close_livecaptions_menu()
                return (False, 'Could not find Preferences in Live Captions.')
            if not self.click_uia_control(preferences_control):
                self.close_livecaptions_menu()
                return (False, 'Could not open Live Captions Preferences.')
            time.sleep(0.35)
            roots = self.get_livecaptions_uia_roots(hwnd)
            mic_control = self.find_microphone_control(roots)
        if mic_control is None:
            self.close_livecaptions_menu()
            return (False, 'Could not find the Include microphone audio option.')
        toggle_state = self.get_toggle_state(mic_control)
        if toggle_state is not None:
            current_enabled = toggle_state == 1
        else:
            current_enabled = self.assumed_livecaptions_mic
        if current_enabled != enabled:
            if not self.click_uia_control(mic_control):
                self.close_livecaptions_menu()
                return (False, 'Could not change the microphone option.')
            time.sleep(0.2)
        self.assumed_livecaptions_mic = enabled
        self.close_livecaptions_menu()
        return (True, '')

    def send_live_captions_hotkey(self):
        try:
            win32api.keybd_event(win32con.VK_LWIN, 0, 0, 0)
            win32api.keybd_event(win32con.VK_CONTROL, 0, 0, 0)
            win32api.keybd_event(ord('L'), 0, 0, 0)
            win32api.keybd_event(ord('L'), 0, win32con.KEYEVENTF_KEYUP, 0)
            win32api.keybd_event(win32con.VK_CONTROL, 0, win32con.KEYEVENTF_KEYUP, 0)
            win32api.keybd_event(win32con.VK_LWIN, 0, win32con.KEYEVENTF_KEYUP, 0)
            return True
        except Exception:
            return False

    def monitor_live_captions(self):
        was_available = self.live_available
        hwnd = self.find_livecaptions_hwnd()
        available_now = bool(hwnd)
        if not available_now:
            self.live_available = False
            self.assumed_livecaptions_mic = False
            if self.recording and (not self.auto_stopping):
                self.auto_stopping = True
                self.auto_stop_live_captions_closed()
            elif not self.recording:
                if self.current_mode is None:
                    self.status_text.set(self.t('Choose an audio mode'))
                elif not self.mode_startup_pending:
                    self.status_text.set(self.t('Live Captions is not open. Press Win + Ctrl + L to open it.'))
        else:
            self.live_available = True
            if not self.recording:
                if self.current_mode is None:
                    self.status_text.set(self.t('Choose an audio mode'))
                elif not self.mode_startup_pending:
                    self.status_text.set(self.t('Ready - Live Captions connected'))
            if not was_available and self.current_mode is not None and (not self.mode_startup_pending) and (not self.recording):
                self.root.after(500, lambda: self.apply_livecaptions_microphone_async(self.desired_livecaptions_mic, show_errors=False))
        self.update_start_button_state()
        self.root.after(LIVE_CAPTIONS_CHECK_INTERVAL, self.monitor_live_captions)

    def find_livecaptions_hwnd(self):
        try:
            hwnd = win32gui.FindWindow('LiveCaptionsDesktopWindow', None)
            if hwnd:
                return hwnd
        except Exception:
            pass
        found = []

        def enum_callback(hwnd, extra):
            try:
                class_name = win32gui.GetClassName(hwnd)
                if class_name == 'LiveCaptionsDesktopWindow':
                    found.append(hwnd)
            except Exception:
                pass
            return True
        try:
            win32gui.EnumWindows(enum_callback, None)
        except Exception:
            pass
        if found:
            return found[0]
        return None

    def connect_livecaptions(self):
        hwnd = self.find_livecaptions_hwnd()
        if not hwnd:
            self.live_hwnd = None
            self.live_window = None
            self.caption_control = None
            return False
        try:
            if self.live_hwnd != hwnd or self.live_window is None:
                self.live_hwnd = hwnd
                self.live_window = Desktop(backend='uia').window(handle=hwnd)
                self.caption_control = None
            return True
        except Exception:
            self.live_hwnd = None
            self.live_window = None
            self.caption_control = None
            return False

    def find_caption_control(self):
        if not self.connect_livecaptions():
            return None
        try:
            control = self.live_window.child_window(auto_id='CaptionsTextBlock')
            if control.exists(timeout=0.15):
                return control.wrapper_object()
        except Exception:
            pass
        try:
            descendants = self.live_window.descendants()
            for control in descendants:
                try:
                    automation_id = control.element_info.automation_id
                    if automation_id == 'CaptionsTextBlock':
                        return control
                except Exception:
                    continue
        except Exception:
            pass
        return None

    def get_caption_text(self):
        if not self.connect_livecaptions():
            return None
        if self.caption_control is None:
            self.caption_control = self.find_caption_control()
        if self.caption_control is None:
            return ''
        try:
            text = self.caption_control.element_info.name
            if not text:
                try:
                    text = self.caption_control.window_text()
                except Exception:
                    text = ''
            return normalize_text(text)
        except Exception:
            self.caption_control = None
            return ''

    def longest_overlap(self, old_text, new_text):
        if not old_text:
            return 0
        if not new_text:
            return 0
        maximum = min(len(old_text), len(new_text))
        for length in range(maximum, 0, -1):
            if old_text[-length:] == new_text[:length]:
                return length
        return 0

    def longest_existing_prefix(self, history, candidate):
        if not history:
            return 0
        if not candidate:
            return 0
        maximum = min(len(history), len(candidate))
        if maximum < LONG_REPEAT_MIN:
            return 0
        if candidate[:LONG_REPEAT_MIN] not in history:
            return 0
        low = LONG_REPEAT_MIN
        high = maximum
        best = LONG_REPEAT_MIN
        while low <= high:
            middle = (low + high) // 2
            prefix = candidate[:middle]
            if prefix in history:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        return best

    def fuzzy_suffix_prefix(self, previous, current):
        if not previous:
            return None
        if not current:
            return None
        if len(previous) < MIN_FUZZY_LENGTH:
            return None
        matcher = SequenceMatcher(None, previous, current, autojunk=False)
        blocks = matcher.get_matching_blocks()
        useful_blocks = [block for block in blocks if block.size >= 4]
        useful_blocks.sort(key=lambda block: block.size, reverse=True)
        candidate_starts = {0}
        for block in useful_blocks[:10]:
            offset = block.a - block.b
            for adjust in (-15, -10, -5, 0, 5, 10, 15):
                start = offset + adjust
                if start >= 0 and start < len(previous):
                    candidate_starts.add(start)
        best_ratio = 0.0
        best_start = None
        best_prefix_length = None
        for start in candidate_starts:
            suffix = previous[start:]
            if len(suffix) < MIN_FUZZY_LENGTH:
                continue
            base_length = len(suffix)
            margin = max(25, min(120, int(base_length * 0.25)))
            minimum_length = max(MIN_FUZZY_LENGTH, base_length - margin)
            maximum_length = min(len(current), base_length + margin)
            if minimum_length > maximum_length:
                continue
            lengths = list(range(minimum_length, maximum_length + 1, 2))
            if maximum_length not in lengths:
                lengths.append(maximum_length)
            for prefix_length in lengths:
                prefix = current[:prefix_length]
                ratio = SequenceMatcher(None, suffix, prefix, autojunk=False).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_start = start
                    best_prefix_length = prefix_length
        if best_start is None:
            return None
        return (best_start, best_prefix_length, best_ratio)

    def write_unique_text(self, candidate):
        if not self.file_handle:
            return
        candidate = normalize_text(candidate)
        if not candidate:
            return
        history = self.history_text[-RECENT_HISTORY_LIMIT:]
        if len(candidate) >= 20 and candidate in history:
            return
        overlap = self.longest_overlap(history, candidate)
        if overlap >= MIN_EXACT_OVERLAP:
            candidate = candidate[overlap:].strip()
        if not candidate:
            return
        history = self.history_text[-RECENT_HISTORY_LIMIT:]
        existing_prefix = self.longest_existing_prefix(history, candidate)
        if existing_prefix >= LONG_REPEAT_MIN:
            candidate = candidate[existing_prefix:].strip()
        if not candidate:
            return
        if len(candidate) >= 20 and candidate in history:
            return
        try:
            self.file_handle.write(candidate)
            self.file_handle.write('\n')
            self.file_handle.flush()
            self.history_text = (self.history_text + ' ' + candidate)[-RECENT_HISTORY_LIMIT:]
        except Exception as error:
            self.message_queue.put(('error', 'Failed to write TXT:\n' + str(error)))

    def process_snapshot(self, current):
        current = normalize_text(current)
        if not current:
            return
        previous = self.last_snapshot
        if not previous:
            self.last_snapshot = current
            self.mismatch_started = None
            self.mismatch_latest = ''
            return
        if current == previous:
            self.mismatch_started = None
            self.mismatch_latest = ''
            return
        if current.startswith(previous):
            self.last_snapshot = current
            self.mismatch_started = None
            self.mismatch_latest = ''
            return
        if previous.startswith(current):
            self.last_snapshot = current
            self.mismatch_started = None
            self.mismatch_latest = ''
            return
        exact_overlap = self.longest_overlap(previous, current)
        if exact_overlap >= MIN_EXACT_OVERLAP:
            finished_part = previous[:-exact_overlap].strip()
            if finished_part:
                self.write_unique_text(finished_part)
            self.last_snapshot = current
            self.mismatch_started = None
            self.mismatch_latest = ''
            return
        fuzzy = self.fuzzy_suffix_prefix(previous, current)
        if fuzzy is not None:
            start_position = fuzzy[0]
            similarity = fuzzy[2]
            if similarity >= FUZZY_THRESHOLD:
                if start_position > 0:
                    finished_part = previous[:start_position].strip()
                    if finished_part:
                        self.write_unique_text(finished_part)
                self.last_snapshot = current
                self.mismatch_started = None
                self.mismatch_latest = ''
                return
        now = time.monotonic()
        if self.mismatch_started is None:
            self.mismatch_started = now
            self.mismatch_latest = current
            return
        self.mismatch_latest = current
        if now - self.mismatch_started >= MISMATCH_GRACE:
            self.write_unique_text(previous)
            self.last_snapshot = self.mismatch_latest
            self.mismatch_started = None
            self.mismatch_latest = ''

    def update_start_button_state(self):
        if self.recording:
            self.start_button.config(state='disabled')
            return
        enabled = self.current_mode is not None and self.live_available and (not self.mode_configuring) and (not self.mode_startup_pending)
        self.start_button.config(state='normal' if enabled else 'disabled')

    def set_session_controls(self, active):
        if active:
            self.start_button.config(state='disabled')
            self.pause_button.config(state='normal', text=self.t('Pause'))
            self.stop_button.config(state='normal')
            self.folder_entry.config(state='disabled')
            self.filename_entry.config(state='disabled')
            self.choose_button.config(state='disabled')
            self.back_button.config(state='disabled')
            if self.current_mode == MODE_MICROPHONE:
                self.microphone_combo.config(state='disabled')
        else:
            self.pause_button.config(state='disabled', text=self.t('Pause'))
            self.stop_button.config(state='disabled')
            self.folder_entry.config(state='normal')
            self.filename_entry.config(state='normal')
            self.choose_button.config(state='normal')
            self.back_button.config(state='normal')
            if self.current_mode == MODE_MICROPHONE:
                self.microphone_combo.config(state='readonly')
            self.update_start_button_state()

    def start_recording(self):
        if self.recording:
            return
        if self.current_mode is None:
            return
        if self.mode_configuring or self.mode_startup_pending:
            messagebox.showinfo(self.t('Please Wait'), self.t('Audio mode is still being configured.'))
            return
        hwnd = self.find_livecaptions_hwnd()
        if not hwnd:
            self.live_available = False
            self.status_text.set(self.t('Live Captions is not open. Press Win + Ctrl + L to open it.'))
            self.update_start_button_state()
            messagebox.showwarning(self.t('Live Captions Not Open'), self.t('Windows Live Captions is not open.\n\nPress Win + Ctrl + L to open it, then try again.'))
            return
        folder = self.save_folder.get().strip()
        filename = self.filename.get().strip()
        if not folder:
            messagebox.showerror(self.t('Error'), self.t('Please choose a save location.'))
            return
        if not os.path.isdir(folder):
            messagebox.showerror(self.t('Error'), self.t('The selected save location does not exist.'))
            return
        if not filename:
            messagebox.showerror(self.t('Error'), self.t('Please enter a file name.'))
            return
        if re.search(INVALID_FILENAME_CHARS, filename):
            messagebox.showerror(self.t('Error'), self.t('The file name cannot contain: < > : " / \\ | ? *'))
            return
        if not filename.lower().endswith('.txt'):
            filename += '.txt'
            self.filename.set(filename)
        self.output_path = os.path.join(folder, filename)
        if os.path.exists(self.output_path):
            overwrite = messagebox.askyesno(self.t('File Already Exists'), self.t('This TXT file already exists.\n\nOverwrite it?'))
            if not overwrite:
                return
        try:
            self.file_handle = open(self.output_path, 'w', encoding='utf-8-sig', newline='')
        except Exception as error:
            messagebox.showerror(self.t('Unable to Create TXT'), self.t(str(error)))
            return
        self.live_hwnd = None
        self.live_window = None
        self.caption_control = None
        self.last_snapshot = ''
        self.history_text = ''
        self.mismatch_started = None
        self.mismatch_latest = ''
        self.auto_stopping = False
        try:
            baseline = self.get_caption_text()
            baseline = normalize_text(baseline)
            if baseline:
                self.last_snapshot = baseline
                self.history_text = baseline[-RECENT_HISTORY_LIMIT:]
        except Exception:
            pass
        self.recording = True
        self.paused = False
        self.stop_event.clear()
        self.set_session_controls(True)
        if self.current_mode == MODE_MICROPHONE:
            mode_name = 'Microphone'
        else:
            mode_name = 'System Audio'
        self.status_text.set(self.t(f'Recording - {mode_name} mode'))
        self.worker_thread = threading.Thread(target=self.record_loop, daemon=True)
        self.worker_thread.start()

    def record_loop(self):
        pythoncom.CoInitialize()
        waiting_reported = False
        try:
            while not self.stop_event.is_set():
                if self.paused:
                    time.sleep(POLL_INTERVAL)
                    continue
                current = self.get_caption_text()
                if current is None:
                    time.sleep(POLL_INTERVAL)
                    continue
                if not current:
                    if not waiting_reported:
                        self.message_queue.put(('status', 'Connected to Windows Live Captions. Waiting for speech...'))
                        waiting_reported = True
                    time.sleep(POLL_INTERVAL)
                    continue
                waiting_reported = False
                if self.current_mode == MODE_MICROPHONE:
                    mode_name = 'Microphone'
                else:
                    mode_name = 'System Audio'
                self.message_queue.put(('status', f'Recording - {mode_name} mode'))
                self.process_snapshot(current)
                time.sleep(POLL_INTERVAL)
        finally:
            pythoncom.CoUninitialize()

    def toggle_pause(self):
        if not self.recording:
            return
        if not self.paused:
            if self.last_snapshot.strip():
                self.write_unique_text(self.last_snapshot)
            self.last_snapshot = ''
            self.mismatch_started = None
            self.mismatch_latest = ''
            self.paused = True
            self.pause_button.config(text=self.t('Continue'))
            self.status_text.set(self.t('Paused'))
            return
        if not self.find_livecaptions_hwnd():
            return
        self.paused = False
        self.caption_control = None
        current = self.get_caption_text()
        current = normalize_text(current)
        if current:
            self.last_snapshot = current
            self.history_text = (self.history_text + ' ' + current)[-RECENT_HISTORY_LIMIT:]
        else:
            self.last_snapshot = ''
        self.mismatch_started = None
        self.mismatch_latest = ''
        self.pause_button.config(text=self.t('Pause'))
        if self.current_mode == MODE_MICROPHONE:
            mode_name = 'Microphone'
        else:
            mode_name = 'System Audio'
        self.status_text.set(self.t(f'Recording - {mode_name} mode'))

    def finish_recording(self, automatic=False, show_message=True):
        if not self.recording:
            return
        self.stop_event.set()
        self.recording = False
        self.paused = False
        if self.worker_thread:
            self.worker_thread.join(timeout=2)
        if self.last_snapshot.strip():
            self.write_unique_text(self.last_snapshot)
        self.last_snapshot = ''
        if self.file_handle:
            try:
                self.file_handle.flush()
                self.file_handle.close()
            except Exception:
                pass
        self.file_handle = None
        saved_path = self.output_path
        self.live_hwnd = None
        self.live_window = None
        self.caption_control = None
        self.set_session_controls(False)
        self.filename.set(self.make_default_filename())
        if automatic:
            self.live_available = False
            self.status_text.set(self.t('Live Captions is not open. Press Win + Ctrl + L to open it.'))
            self.auto_stopping = False
            self.update_start_button_state()
            if show_message:
                messagebox.showinfo(self.t('Recording Stopped'), self.t('Windows Live Captions was closed.\n\nThe current recording session was stopped and the TXT file was saved successfully:\n\n' + str(saved_path)))
            return
        if self.find_livecaptions_hwnd():
            self.live_available = True
            self.status_text.set(self.t('Ready - Live Captions connected'))
        else:
            self.live_available = False
            self.status_text.set(self.t('Live Captions is not open. Press Win + Ctrl + L to open it.'))
        self.auto_stopping = False
        self.update_start_button_state()
        if show_message:
            messagebox.showinfo(self.t('Saved'), self.t('TXT saved successfully:\n\n' + str(saved_path)))

    def stop_recording(self):
        self.finish_recording(automatic=False, show_message=True)

    def auto_stop_live_captions_closed(self):
        if not self.recording:
            self.auto_stopping = False
            return
        self.finish_recording(automatic=True, show_message=True)

    def process_messages(self):
        try:
            while True:
                msg_type, msg = self.message_queue.get_nowait()
                if msg_type == 'status':
                    if self.recording:
                        self.status_text.set(self.t(msg))
                elif msg_type == 'error':
                    messagebox.showerror(self.t('Error'), self.t(msg))
                elif msg_type == 'mic_mode_result':
                    enabled, success, detail, show_errors = msg
                    self.mode_configuring = False
                    self.update_start_button_state()
                    if bool(enabled) != bool(self.desired_livecaptions_mic) and self.current_mode is not None and self.find_livecaptions_hwnd():
                        self.root.after(50, lambda: self.apply_livecaptions_microphone_async(self.desired_livecaptions_mic, show_errors=False))
                    if success:
                        if not self.recording and self.current_mode is not None:
                            self.status_text.set(self.t('Ready - Live Captions connected'))
                    else:
                        if self.current_mode is None:
                            continue
                        if enabled:
                            self.status_text.set(self.t('Microphone mode selected - manual Live Captions microphone setting may be required.'))
                        else:
                            self.status_text.set(self.t('System Audio mode selected - manual Live Captions microphone setting may be required.'))
                        if show_errors:
                            messagebox.showwarning(self.t('Live Captions Setting'), self.t(detail + '\n\nPlease set it manually in:\n\nLive Captions > Settings > Preferences > Include microphone audio'))
        except queue.Empty:
            pass
        self.root.after(100, self.process_messages)

    def on_close(self):
        if self.recording:
            answer = messagebox.askyesno(self.t('Recording in Progress'), self.t('Recording is still active.\n\nClosing the application will stop recording and save the current TXT file.\n\nContinue?'))
            if not answer:
                return
            self.finish_recording(automatic=False, show_message=False)
        self.mode_startup_serial += 1
        self.mode_startup_pending = False
        self.stop_meter()
        self.restore_original_default_microphones()
        try:
            if self.find_livecaptions_hwnd():
                self.set_livecaptions_microphone_enabled(False)
        except Exception:
            pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
        self.root.destroy()
if __name__ == '__main__':
    enable_high_dpi_awareness()
    root = tk.Tk()
    configure_tk_dpi(root)
    app = LiveCaptionsRecorder(root)
    root.mainloop()
