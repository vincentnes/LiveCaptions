# -*- coding: utf-8 -*-
"""
即時字幕 (Live Captions for Windows)

在背景擷取「電腦播放出來的聲音」→ 偵測有人說話 → 自動辨識語言並轉成文字
→ 字幕顯示在螢幕上指定的位置（可選擇加上第二語言翻譯）→ 同時寫入 .srt / .txt 檔。

有 NVIDIA 顯示卡時自動使用 GPU（大模型、較準、可邊說邊顯示），沒有就用 CPU。
"""
import os
import sys
import json
import time
import queue
import socket
import ctypes
import datetime
import threading
import traceback
from collections import deque
from concurrent.futures import ThreadPoolExecutor

import numpy as np

APP_NAME = "即時字幕"
APP_ID = "LiveCaptions.Desktop.1"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
SINGLE_INSTANCE_PORT = 47631
SR = 16000                       # Whisper 使用 16 kHz
UI_FONT = "Microsoft JhengHei UI"

os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import warnings
warnings.filterwarnings("ignore", message="data discontinuity in recording")


# ----------------------------------------------------------------------------
# 路徑、紀錄檔、設定
# ----------------------------------------------------------------------------
def _data_dir():
    d = os.path.join(os.environ.get("APPDATA", os.path.expanduser("~")), "LiveCaptions")
    os.makedirs(d, exist_ok=True)
    return d


DATA_DIR = _data_dir()
LOG_PATH = os.path.join(DATA_DIR, "log.txt")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")

try:  # 紀錄檔太大就重來
    if os.path.exists(LOG_PATH) and os.path.getsize(LOG_PATH) > 2 * 1024 * 1024:
        os.remove(LOG_PATH)
except Exception:
    pass

# 用 pythonw（沒有黑色視窗）執行時，沒有 stdout/stderr，導到紀錄檔避免當機
if sys.stdout is None or sys.stderr is None:
    _logf = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _logf
    if sys.stderr is None:
        sys.stderr = _logf

_log_lock = threading.Lock()


def log(*args):
    line = time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(a) for a in args)
    with _log_lock:
        try:
            with open(LOG_PATH, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
    try:
        if sys.__stdout__:
            print(line)
    except Exception:
        pass


def documents_dir():
    try:
        buf = ctypes.create_unicode_buffer(260)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # CSIDL_PERSONAL
        if buf.value:
            return buf.value
    except Exception:
        pass
    return os.path.join(os.path.expanduser("~"), "Documents")


DEFAULTS = {
    "second_language": "",          # "" = 不顯示第二語言
    "source_language": "",          # "" = 自動偵測
    "model": "auto",
    "font_size": 28,
    "text_color": "#FFFFFF",
    "second_color": "#FFE066",
    "overlay_x": None,
    "overlay_y": None,
    "overlay_w": 1100,
    "overlay_h": 150,
    "clear_after_sec": 6,
    "auto_start": True,
    "show_overlay": True,
    "to_traditional": True,
    "hotkey_toggle": "ctrl+alt+s",
    "hotkey_panel": "ctrl+alt+h",
    "output_dir": "",
    "source_mode": "all",
    "display_mode": "both",
    "translate_engine": "auto",
    "ui_lang": "auto",              # auto / zh / en     # auto / local / microsoft / google         # both / trans / orig          # all = 全部播放裝置；default = 只錄預設裝置
}

_cfg_lock = threading.Lock()


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except Exception:
        pass
    return cfg


def save_config(cfg):
    with _cfg_lock:
        try:
            tmp = CONFIG_PATH + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_PATH)
        except Exception as e:
            log("save_config failed", e)


def output_dir(cfg):
    d = cfg.get("output_dir") or os.path.join(documents_dir(), "即時字幕")
    os.makedirs(d, exist_ok=True)
    return d


# ----------------------------------------------------------------------------
# 介面語言（中文／English）
# ----------------------------------------------------------------------------
EN = {
    "尚未載入": "Not loaded",
    "缺少辨識元件，請重新執行 install.bat": "Speech components missing - please run install.bat again",
    "載入辨識模型 {name}（{where}）…第一次使用需下載，請稍候": "Loading speech model {name} ({where})... the first run downloads it, please wait",
    "辨識模型載入失敗（請看紀錄檔 log.txt）": "Speech model failed to load (see log.txt)",
    "找不到可以錄音的播放裝置（喇叭／耳機）": "No playback device (speakers/headphones) could be captured",
    "字幕": "Captions",
    "第一次使用離線翻譯，下載翻譯模型中（約 600 MB），請稍候…": "Downloading the offline translation model (about 600 MB) for first use, please wait...",
    "離線翻譯模型無法使用": "Offline translation model unavailable",
    "翻譯使用：": "Translating with: ",
    "沒有可用的翻譯方式": "No translation method available",
    "拖曳移動位置．右下角藍色方塊拖曳調整大小．完成後按控制面板的「完成調整」":
        "Drag to move. Drag the blue square (bottom-right) to resize. Click \"Done\" in the control panel when finished.",
    "字幕會顯示在這裡 Subtitles appear here": "Subtitles appear here 字幕會顯示在這裡",
    "這裡是翻譯": "Translation appears here",
    "顯示控制面板": "Show control panel",
    "■ 停止錄製": "■ Stop",
    "▶ 開始錄製": "▶ Start",
    "開啟字幕檔資料夾": "Open captions folder",
    "結束程式": "Quit",
    "即時字幕：已停止": "Live Captions: stopped",
    "即時字幕：錄製中": "Live Captions: running",
    "即時字幕 － 控制面板": "Live Captions - Control Panel",
    "■ 已停止": "■ Stopped",
    "音量": "Level",
    "準備中…": "Starting...",
    "載入中…": "Loading...",
    "狀態": "Status",
    "辨識引擎": "Engine",
    "偵測到的語言": "Detected language",
    "：": ": ",
    "聲音來源：": "Audio sources: ",
    " 設定 ": " Settings ",
    "原文語言": "Spoken language",
    "第二語言（翻譯）": "Second language (translation)",
    "螢幕字幕顯示": "On-screen display",
    "翻譯方式": "Translation method",
    "聲音來源": "Audio source",
    "辨識模型": "Speech model",
    "模型已更改：請「結束程式」後重新開啟才會生效": "Model changed: Quit and reopen the program for it to take effect",
    "字幕大小": "Font size",
    "   字幕停留秒數": "   Seconds on screen",
    "在螢幕上顯示字幕": "Show subtitles on screen",
    "中文一律顯示繁體字": "Always show Chinese in Traditional characters",
    "打開程式時自動開始錄製": "Start capturing when the program opens",
    "調整字幕位置／大小": "Move / resize subtitles",
    "位置重設": "Reset position",
    " 最近的字幕 ": " Recent captions ",
    "快速鍵：{a} 開始／停止　{b} 叫出此面板": "Shortcuts: {a} start/stop    {b} show this panel",
    "按右上角 ✕ 不會結束程式，只會縮到右下角工作列的圖示（點圖示就能再叫出來）。":
        "Closing this window (✕) does not quit - the program keeps running in the system tray (click the tray icon to bring this panel back).",
    "縮到工作列": "Hide to tray",
    "✔ 完成調整": "✔ Done",
    "● 錄製中": "● Running",
    "無法開始錄製：": "Cannot start capturing: ",
    "即時字幕": "Live Captions",
    "無法擷取電腦聲音：": "Cannot capture computer audio:",
    "請確認有喇叭或耳機（播放裝置）可用。": "Please make sure speakers or headphones (a playback device) are available.",
    "錄製中，等待有人說話…": "Running - waiting for speech...",
    "已停止": "Stopped",
    "已切換到新的聲音裝置，錄製中": "Switched to the new audio device - running",
    "正在等待播放裝置…（插上喇叭或耳機後會自動繼續）": "Waiting for a playback device... (continues automatically when speakers/headphones are connected)",
    "找不到可用的播放裝置：": "No usable playback device: ",
    "載入失敗": "Failed to load",
    "就緒，按「開始錄製」": "Ready - click \"Start\"",
    "電腦處理速度跟不上，已略過部分語音（可改用較小的模型）": "The computer can't keep up; some speech was skipped (try a smaller model)",
    "翻譯暫時失敗，稍後會自動再試（原文字幕照常）": "Translation failed for now; will retry automatically (original captions continue)",
    "錄製中": "Running",
    "正在下載並測試語音辨識模型，第一次需要幾分鐘…": "Downloading and testing the speech model; the first time takes a few minutes...",
    "完成！使用：": "Done! Using:",
    "下載離線翻譯模型（約 600 MB）…": "Downloading the offline translation model (about 600 MB)...",
    "離線翻譯可以使用": "Offline translation is ready",
    "離線翻譯模型下載失敗，翻譯會改用網路（詳情見 log.txt）": "Offline translation model download failed; online translation will be used (see log.txt)",
    "模型載入失敗，詳情請看：": "Model failed to load, see:",
    "程式發生錯誤，詳情請看：\n": "The program hit an error. Details:\n",
    "中文": "Chinese",
    "粵語": "Cantonese",
    "自動偵測": "Auto-detect",
    "不顯示": "None",
    "繁體中文": "Chinese (Traditional)",
    "简体中文": "Chinese (Simplified)",
    "原文＋翻譯": "Original + translation",
    "只顯示翻譯": "Translation only",
    "只顯示原文": "Original only",
    "自動（有 NVIDIA 用大模型，沒有用 small）": "Auto (large model with NVIDIA GPU, otherwise small)",
    "tiny（最快、最不準）": "tiny (fastest, least accurate)",
    "base（快）": "base (fast)",
    "small（CPU 建議）": "small (recommended for CPU)",
    "medium（較準、較慢）": "medium (more accurate, slower)",
    "large-v3-turbo（GPU 建議）": "large-v3-turbo (recommended for GPU)",
    "全部播放裝置（喇叭、耳機都錄，建議）": "All playback devices (speakers + headphones, recommended)",
    "只錄目前的預設播放裝置": "Default playback device only",
    "自動（先用離線翻譯，不行再用網路）": "Auto (offline first, online as fallback)",
    "離線翻譯（在自己電腦上，不需網路）": "Offline (on this computer, no internet needed)",
    "微軟翻譯（需要網路）": "Microsoft Translator (internet)",
    "Google 翻譯（需要網路，容易被限制次數）": "Google Translate (internet, often rate-limited)",
    "離線翻譯": "Offline translation",
    "微軟翻譯": "Microsoft Translator",
    "Google 翻譯": "Google Translate",
    "介面語言": "Language",
}

UI_LANG_CHOICES = [("中文", "zh"), ("English", "en")]
_ui_lang = {"value": "zh"}


def system_ui_lang():
    """Windows 顯示語言是中文就用中文介面，否則用英文。"""
    try:
        lid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        return "zh" if (lid & 0x3FF) == 0x04 else "en"
    except Exception:
        return "zh"


def set_ui_lang(code):
    if code not in ("zh", "en"):
        code = system_ui_lang()
    _ui_lang["value"] = code


def T(s):
    if _ui_lang["value"] == "en":
        return EN.get(s, s)
    return s


# ----------------------------------------------------------------------------
# 語言選項
# ----------------------------------------------------------------------------
LANG_NAMES = {
    "zh": "中文", "yue": "粵語", "en": "English", "ja": "日本語", "ko": "한국어",
    "es": "Español", "fr": "Français", "de": "Deutsch", "ru": "Русский",
    "vi": "Tiếng Việt", "th": "ไทย", "id": "Indonesia", "ms": "Melayu",
    "it": "Italiano", "pt": "Português", "ar": "العربية", "hi": "हिन्दी",
    "tl": "Tagalog", "nl": "Nederlands", "tr": "Türkçe", "pl": "Polski",
    "uk": "Українська", "pa": "ਪੰਜਾਬੀ", "fa": "فارسی",
}

SOURCE_CHOICES = [
    ("自動偵測", ""), ("中文", "zh"), ("English", "en"), ("日本語", "ja"),
    ("한국어", "ko"), ("Español", "es"), ("Français", "fr"), ("Deutsch", "de"),
    ("Tiếng Việt", "vi"), ("ไทย", "th"), ("Русский", "ru"),
]

SECOND_CHOICES = [
    ("不顯示", ""), ("繁體中文", "zh-TW"), ("简体中文", "zh-CN"), ("English", "en"),
    ("日本語", "ja"), ("한국어", "ko"), ("Español", "es"), ("Français", "fr"),
    ("Deutsch", "de"), ("Tiếng Việt", "vi"), ("ไทย", "th"),
    ("Bahasa Indonesia", "id"), ("Русский", "ru"),
]

DISPLAY_CHOICES = [
    ("原文＋翻譯", "both"),
    ("只顯示翻譯", "trans"),
    ("只顯示原文", "orig"),
]

MODEL_CHOICES = [
    ("自動（有 NVIDIA 用大模型，沒有用 small）", "auto"),
    ("tiny（最快、最不準）", "tiny"),
    ("base（快）", "base"),
    ("small（CPU 建議）", "small"),
    ("medium（較準、較慢）", "medium"),
    ("large-v3-turbo（GPU 建議）", "large-v3-turbo"),
]

# Whisper 在沒有人說話時常會「幻聽」出這些句子
HALLUCINATIONS = [
    "謝謝觀看", "谢谢观看", "謝謝收看", "谢谢收看", "感謝觀看", "請不吝點贊", "请不吝点赞",
    "訂閱", "订阅", "字幕由", "字幕志愿者", "字幕志願者", "明镜与点点", "明鏡與點點",
    "amara.org", "thanks for watching", "thank you for watching", "please subscribe",
    "ご視聴ありがとうございました", "チャンネル登録", "시청해주셔서", "구독",
]


def is_hallucination(text):
    t = text.strip()
    if not t:
        return True
    low = t.lower()
    if len(t) < 40 and any(h in low for h in HALLUCINATIONS):
        return True
    if len(t) > 6 and len(set(t.replace(" ", ""))) <= 2:
        return True
    return False


def same_language(whisper_lang, target):
    if not whisper_lang or not target:
        return False
    base = target.split("-")[0].lower()
    if whisper_lang == "yue":
        whisper_lang = "zh"
    return whisper_lang == base


# ----------------------------------------------------------------------------
# 圖示
# ----------------------------------------------------------------------------
def make_icon_image(recording=False, size=256):
    from PIL import Image, ImageDraw, ImageFont
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([s * .04, s * .10, s * .96, s * .90], radius=int(s * .16), fill=(30, 41, 59, 255))
    d.rounded_rectangle([s * .14, s * .56, s * .70, s * .66], radius=int(s * .05), fill=(255, 255, 255, 255))
    d.rounded_rectangle([s * .14, s * .72, s * .86, s * .82], radius=int(s * .05), fill=(255, 214, 10, 255))
    fonts_dir = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    font = None
    for name in ("msjhbd.ttc", "msjh.ttc", "msyhbd.ttc", "msyh.ttc"):
        try:
            font = ImageFont.truetype(os.path.join(fonts_dir, name), int(s * .34))
            break
        except Exception:
            pass
    if font is not None:
        d.text((s * .14, s * .12), "字", font=font, fill=(255, 255, 255, 255))
    else:
        d.rounded_rectangle([s * .14, s * .22, s * .50, s * .40], radius=int(s * .05), fill=(255, 255, 255, 255))
    dot = (239, 68, 68, 255) if recording else (148, 163, 184, 255)
    d.ellipse([s * .64, s * .18, s * .86, s * .40], fill=dot)
    return img


# ----------------------------------------------------------------------------
# 語音辨識引擎（faster-whisper）
# ----------------------------------------------------------------------------
def setup_cuda_dlls():
    """讓 Windows 找得到 pip 安裝的 NVIDIA cuBLAS / cuDNN DLL。"""
    if os.name != "nt":
        return
    try:
        import site
        paths = list(site.getsitepackages())
        try:
            paths.append(site.getusersitepackages())
        except Exception:
            pass
    except Exception:
        paths = list(sys.path)
    for sp in paths:
        base = os.path.join(sp, "nvidia")
        if not os.path.isdir(base):
            continue
        for sub in os.listdir(base):
            b = os.path.join(base, sub, "bin")
            if os.path.isdir(b):
                try:
                    os.add_dll_directory(b)
                except Exception:
                    pass
                os.environ["PATH"] = b + os.pathsep + os.environ.get("PATH", "")


class Engine:
    def __init__(self, cfg, status):
        self.cfg = cfg
        self.status = status
        self.model = None
        self.device = "cpu"
        self.model_name = ""
        self.ready = threading.Event()
        self.failed = False
        self._cc = None

    def describe(self):
        if not self.model:
            return T("尚未載入")
        return f"{'GPU (NVIDIA)' if self.device == 'cuda' else 'CPU'} · {self.model_name}"

    def load(self):
        try:
            setup_cuda_dlls()
            from faster_whisper import WhisperModel
        except Exception as e:
            log("import faster_whisper failed", repr(e))
            self.failed = True
            self.status(T("缺少辨識元件，請重新執行 install.bat"))
            return False

        gpu = 0
        try:
            import ctranslate2
            gpu = ctranslate2.get_cuda_device_count()
        except Exception as e:
            log("cuda check failed", repr(e))

        want = self.cfg.get("model", "auto")
        gpu_model = "large-v3-turbo" if want == "auto" else want
        cpu_model = "small" if want in ("auto", "large-v3-turbo", "large-v3") else want
        attempts = []
        if gpu > 0:
            attempts += [("cuda", "float16", gpu_model), ("cuda", "int8", gpu_model)]
        attempts.append(("cpu", "int8", cpu_model))
        threads = min(8, max(2, (os.cpu_count() or 4) // 2))

        for dev, ctype, name in attempts:
            try:
                where = "GPU" if dev == "cuda" else "CPU"
                self.status(T("載入辨識模型 {name}（{where}）…第一次使用需下載，請稍候").format(name=name, where=where))
                kw = {"device": dev, "compute_type": ctype}
                if dev == "cpu":
                    kw["cpu_threads"] = threads
                m = WhisperModel(name, **kw)
                # 實際跑一次，確認 GPU 元件真的能用（不能用會在這裡出錯）
                segs, _ = m.transcribe(np.zeros(SR, dtype=np.float32), beam_size=1,
                                       language="en", without_timestamps=True)
                list(segs)
                self.model, self.device, self.model_name = m, dev, name
                self.ready.set()
                log("model ready:", dev, ctype, name)
                return True
            except Exception as e:
                log("model load failed:", dev, ctype, name, repr(e))
        self.failed = True
        self.status(T("辨識模型載入失敗（請看紀錄檔 log.txt）"))
        return False

    def _to_trad(self, text):
        try:
            if self._cc is None:
                from opencc import OpenCC
                self._cc = OpenCC("s2tw")
            return self._cc.convert(text)
        except Exception:
            return text

    def transcribe(self, audio, final=True):
        lang = self.cfg.get("source_language") or None
        gpu = self.device == "cuda"
        beam = (5 if gpu else 1) if final else 1
        segs, info = self.model.transcribe(
            audio,
            language=lang,
            beam_size=beam,
            temperature=0.0,
            vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 500},
            condition_on_previous_text=False,
            without_timestamps=True,
        )
        parts = []
        for s in segs:
            if s.no_speech_prob > 0.6 and s.avg_logprob < -0.5:
                continue
            if s.avg_logprob < -1.0 or s.compression_ratio > 2.4:
                continue
            t = s.text.strip()
            if t:
                parts.append(t)
        language = info.language
        prob = float(getattr(info, "language_probability", 1.0) or 1.0)
        sep = "" if language in ("zh", "yue", "ja", "th") else " "
        text = sep.join(parts).strip()
        if language in ("zh", "yue") and self.cfg.get("to_traditional", True):
            text = self._to_trad(text)
        if is_hallucination(text):
            text = ""
        return text, language, prob


# ----------------------------------------------------------------------------
# 擷取系統聲音 + 偵測說話、斷句
# ----------------------------------------------------------------------------
class Recorder:
    FRAME = 480            # 30 ms @ 16 kHz
    END_SILENCE = 0.6      # 安靜多久算一句話結束（秒）
    MIN_VOICED = 0.3       # 至少要有多少秒的聲音才送去辨識

    """一個播放裝置一個：負責把該裝置的聲音切成一句一句。"""

    def __init__(self, on_final, on_partial, on_level, get_live, get_max, rate=SR, ch=1, name=""):
        self.on_final = on_final
        self.on_partial = on_partial
        self.on_level = on_level
        self.get_live = get_live
        self.get_max = get_max
        self.running = False
        self.thread = None
        self.device_name = name
        self.rate = rate
        self.ch = ch
        self.raw_q = queue.Queue()
        self._reset_state()

    def _reset_state(self):
        self._resid = np.zeros(0, np.float32)
        self._buf = np.zeros(0, np.float32)
        self._pre = deque(maxlen=10)        # 說話開始前 0.3 秒也保留
        self._seg = []
        self._seg_rms = []
        self._in_speech = False
        self._silence = 0.0
        self._sil_frames = 0
        self._voiced = 0.0
        self._hot = 0
        self._noise = 0.001
        self._last_partial = 0.0
        self._last_voice_t = 0.0
        self._seg_t0 = 0.0
        self._lvl_n = 0

    # ---- 開關 ----
    def start_thread(self):
        self.running = True
        self.thread = threading.Thread(target=self._run, name="seg:" + self.device_name, daemon=True)
        self.thread.start()

    def stop_thread(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=2)

    def _run(self):
        while self.running:
            try:
                data = self.raw_q.get(timeout=0.2)
            except queue.Empty:
                # 沒有任何聲音在播放時 Windows 不會送資料，視為安靜
                self._idle(0.2)
                continue
            try:
                self._feed(data)
            except Exception:
                log("feed error", traceback.format_exc())
        if self._in_speech:
            self._finish(time.time(), end=True)

    # ---- 聲音處理 ----
    def _resample(self, x):
        if self.rate == SR:
            return x.astype(np.float32, copy=False)
        if self.rate % SR == 0:
            k = self.rate // SR
            x = np.concatenate([self._resid, x])
            n = len(x) // k * k
            self._resid = x[n:]
            return x[:n].reshape(-1, k).mean(axis=1).astype(np.float32)
        if len(x) < 2:
            return np.zeros(0, np.float32)
        n_out = int(len(x) * SR / self.rate)
        return np.interp(np.linspace(0, len(x) - 1, n_out), np.arange(len(x)), x).astype(np.float32)

    def _feed(self, data, now=None):
        x = np.frombuffer(data, dtype=np.float32)
        if self.ch > 1:
            n = len(x) // self.ch * self.ch
            x = x[:n].reshape(-1, self.ch).mean(axis=1)
        x = self._resample(x)
        if len(x) == 0:
            return
        self._buf = np.concatenate([self._buf, x])
        F = self.FRAME
        nf = len(self._buf) // F
        if nf == 0:
            return
        now = time.time() if now is None else now
        for i in range(nf):
            self._frame(self._buf[i * F:(i + 1) * F], now - (nf - 1 - i) * F / SR)
        self._buf = self._buf[nf * F:].copy()

    def _idle(self, dt):
        self.on_level(0.0)
        if self._in_speech:
            self._silence += dt
            if self._silence >= self.END_SILENCE:
                self._finish(time.time(), end=True)

    NOISE_CAP = 0.006     # 背景雜音估計的上限：不會把「說話聲本身」當成雜音

    def _frame(self, f, t):
        fd = self.FRAME / SR
        rms = float(np.sqrt(np.mean(f * f)))
        thr = max(0.003, self._noise * 2.0)
        sp = rms > thr
        # 背景雜音：遇到更安靜的聲音馬上降低；否則只非常緩慢地上升，而且有上限。
        # （真正判斷是不是人聲，交給 Whisper 內建的語音偵測）
        if rms < self._noise:
            self._noise = 0.9 * self._noise + 0.1 * rms
        else:
            self._noise = min(self._noise * 1.0005, self.NOISE_CAP)
        self._noise = max(self._noise, 0.0003)

        self._lvl_n += 1
        if self._lvl_n % 4 == 0:
            self.on_level(rms)

        if not self._in_speech:
            self._pre.append((f, rms))
            self._hot = self._hot + 1 if sp else 0
            if self._hot >= 3:
                self._in_speech = True
                self._seg = [x for x, _ in self._pre]
                self._seg_rms = [r for _, r in self._pre]
                self._pre.clear()
                self._seg_t0 = t - len(self._seg) * fd
                self._silence = 0.0
                self._sil_frames = 0
                self._voiced = self._hot * fd
                self._last_partial = t
                self._last_voice_t = t
            return

        self._seg.append(f)
        self._seg_rms.append(rms)
        if sp:
            self._silence = 0.0
            self._sil_frames = 0
            self._voiced += fd
            self._last_voice_t = t
        else:
            self._silence += fd
            self._sil_frames += 1

        dur = len(self._seg) * fd
        if self._silence >= self.END_SILENCE:
            self._finish(t, end=True)
        elif dur >= self.get_max():
            self._split(t)
        elif self.get_live() and t - self._last_partial >= 1.0 and dur >= 0.8:
            self._last_partial = t
            self.on_partial(np.concatenate(self._seg))

    def _split(self, t):
        """一直有聲音、講太長：在後半段最安靜的地方切開，剩下的接到下一句。"""
        fd = self.FRAME / SR
        n = len(self._seg)
        start = n // 2
        idx = start + int(np.argmin(self._seg_rms[start:]))
        head = self._seg[:idx + 1]
        if self._voiced >= self.MIN_VOICED:
            t1 = self._seg_t0 + len(head) * fd
            self.on_final(np.concatenate(head), self._seg_t0, t1)
        else:
            t1 = self._seg_t0 + len(head) * fd
        self._seg = self._seg[idx + 1:]
        self._seg_rms = self._seg_rms[idx + 1:]
        thr = max(0.003, self._noise * 2.0)
        self._voiced = sum(fd for r in self._seg_rms if r > thr)
        self._seg_t0 = t1
        self._last_partial = t

    def _finish(self, t, end=True):
        if self._seg and self._voiced >= self.MIN_VOICED:
            audio = np.concatenate(self._seg)
            cut = int(max(0, self._sil_frames * self.FRAME - 0.3 * SR))
            if 0 < cut < len(audio):
                audio = audio[:-cut]
            self.on_final(audio, self._seg_t0, self._last_voice_t + 0.3)
        self._seg = []
        self._seg_rms = []
        self._voiced = 0.0
        self._silence = 0.0
        self._sil_frames = 0
        self._in_speech = False
        self._hot = 0


SOURCE_MODES = [
    ("全部播放裝置（喇叭、耳機都錄，建議）", "all"),
    ("只錄目前的預設播放裝置", "default"),
]


class Capture:
    """開啟一個或多個播放裝置的「播放聲音錄音」（loopback），每個裝置交給一個 Recorder 斷句。

    方式 A（優先）：soundcard 套件，直接走 Windows WASAPI，耳機／藍牙相容性較好，
                   由 Windows 直接轉成 16 kHz。
    方式 B（備用）：PyAudioWPatch。方式 A 某個裝置打不開時，自動改用方式 B 試一次。
    """

    def __init__(self, mode, make_recorder):
        self.mode = mode
        self.make_recorder = make_recorder
        self.pa = None
        self.items = []          # [(recorder, stopper)]
        self.backend_used = set()

    @staticmethod
    def _clean(name):
        return name.replace(" [Loopback]", "").strip()

    # ---------- 方式 A：soundcard ----------
    def _sc_devices(self):
        import soundcard as sc
        if self.mode == "all":
            mics = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
        else:
            spk = sc.default_speaker()
            mics = [sc.get_microphone(id=str(spk.name), include_loopback=True)]
        return mics

    def _sc_open(self, mic):
        name = self._clean(mic.name)
        last_err = None
        for rate in (SR, 48000, 44100):
            ctx = None
            try:
                ctx = mic.recorder(samplerate=rate, blocksize=int(rate * 0.05))
                r = ctx.__enter__()
            except Exception as e:
                last_err = e
                log("soundcard open failed:", name, rate, repr(e))
                continue
            rec = self.make_recorder(rate, 1, name)
            stop_evt = threading.Event()
            n = int(rate * 0.05)

            def reader(r=r, ctx=ctx, rec=rec, stop_evt=stop_evt, n=n):
                try:
                    while not stop_evt.is_set():
                        data = r.record(numframes=n)
                        if data is None or len(data) == 0:
                            continue
                        x = data.mean(axis=1) if data.ndim == 2 else data
                        rec.raw_q.put(np.ascontiguousarray(x, dtype=np.float32).tobytes())
                except Exception as e:
                    if not stop_evt.is_set():
                        log("soundcard read error:", rec.device_name, repr(e))
                finally:
                    try:
                        ctx.__exit__(None, None, None)
                    except Exception:
                        pass

            th = threading.Thread(target=reader, name="sc:" + name, daemon=True)

            def stopper(stop_evt=stop_evt, th=th):
                stop_evt.set()
                th.join(timeout=1.5)

            rec.start_thread()
            th.start()
            self.items.append((rec, stopper))
            self.backend_used.add("A")
            log("capturing (A):", name, rate, "Hz")
            return True
        raise RuntimeError(last_err)

    # ---------- 方式 B：PyAudioWPatch ----------
    def _pa_init(self):
        if self.pa is None:
            import pyaudiowpatch as pyaudio
            self._pyaudio = pyaudio
            self.pa = pyaudio.PyAudio()     # 每次重新建立，才會抓到新插上的裝置
        return self._pyaudio

    def _pa_devices(self):
        pyaudio = self._pa_init()
        loopbacks = list(self.pa.get_loopback_device_info_generator())
        if self.mode == "all":
            return loopbacks
        wasapi = self.pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        spk = self.pa.get_device_info_by_index(wasapi["defaultOutputDevice"])
        if spk.get("isLoopbackDevice"):
            return [spk]
        return [lb for lb in loopbacks if spk["name"] in lb["name"]][:1]

    def _pa_open(self, dev):
        pyaudio = self._pa_init()
        name = self._clean(dev["name"])
        rate = int(dev["defaultSampleRate"])
        ch = max(1, int(dev["maxInputChannels"]))
        rec = self.make_recorder(rate, ch, name)

        def cb(in_data, frame_count, time_info, status, q=rec.raw_q):
            q.put(in_data)
            return (None, pyaudio.paContinue)
        stream = self.pa.open(
            format=pyaudio.paFloat32, channels=ch, rate=rate, input=True,
            input_device_index=dev["index"], frames_per_buffer=int(rate * 0.05),
            stream_callback=cb)
        stream.start_stream()

        def stopper(stream=stream):
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
        rec.start_thread()
        self.items.append((rec, stopper))
        self.backend_used.add("B")
        log("capturing (B):", name, rate, "Hz", ch, "ch")

    # ---------- 開始 / 停止 ----------
    def start(self):
        try:
            failed = []          # 方式 A 打不開的裝置名稱
            sc_ok = False
            try:
                mics = self._sc_devices()
                sc_ok = True
                log("soundcard devices:", [self._clean(m.name) for m in mics])
                for mic in mics:
                    try:
                        self._sc_open(mic)
                    except Exception:
                        failed.append(self._clean(mic.name))
            except Exception as e:
                log("soundcard unavailable, using PyAudio:", repr(e))

            if not sc_ok or failed:
                try:
                    devs = self._pa_devices()
                    for dev in devs:
                        name = self._clean(dev["name"])
                        if sc_ok and not any(f in name or name in f for f in failed):
                            continue
                        try:
                            self._pa_open(dev)
                        except Exception as e:
                            log("PyAudio open failed:", name, repr(e))
                except Exception as e:
                    log("PyAudio unavailable:", repr(e))

            if not self.items:
                raise RuntimeError(T("找不到可以錄音的播放裝置（喇叭／耳機）"))
        except Exception:
            self.stop()
            raise

    def names(self):
        return [rec.device_name for rec, _ in self.items]

    def stop(self):
        for _, stopper in self.items:
            stopper()
        for rec, _ in self.items:     # 讓說到一半的句子也送出去
            rec.stop_thread()
        self.items = []
        try:
            if self.pa:
                self.pa.terminate()
        except Exception:
            pass
        self.pa = None


def audio_device_snapshot(enum_holder):
    """回傳 (預設播放裝置 id, 所有啟用中播放裝置 id)。用 Windows Core Audio，不影響錄音。"""
    from pycaw.pycaw import AudioUtilities
    if not enum_holder:
        enum_holder.append(AudioUtilities.GetDeviceEnumerator())
    enum = enum_holder[0]
    try:
        default = enum.GetDefaultAudioEndpoint(0, 1).GetId()   # eRender, eMultimedia
    except Exception:
        default = ""
    coll = enum.EnumAudioEndpoints(0, 1)                       # eRender, ACTIVE
    ids = tuple(sorted(coll.Item(i).GetId() for i in range(coll.GetCount())))
    return default, ids


# ----------------------------------------------------------------------------
# 寫入字幕檔
# ----------------------------------------------------------------------------
class CaptionWriter:
    def __init__(self, folder):
        self.folder = folder
        self.t0 = time.time()
        stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.srt_path = os.path.join(folder, f"{T('字幕')}_{stamp}.srt")
        self.txt_path = os.path.join(folder, f"{T('字幕')}_{stamp}.txt")
        self.n = 0
        self.lock = threading.Lock()

    @staticmethod
    def _ts(sec):
        ms = int(round(max(0.0, sec) * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def write(self, t_start, t_end, lang, text, trans):
        with self.lock:
            os.makedirs(self.folder, exist_ok=True)
            self.n += 1
            a = t_start - self.t0
            b = max(t_end - self.t0, a + 0.8)
            body = text + (("\n" + trans) if trans else "")
            with open(self.srt_path, "a", encoding="utf-8-sig") as f:
                f.write(f"{self.n}\n{self._ts(a)} --> {self._ts(b)}\n{body}\n\n")
            clock = datetime.datetime.fromtimestamp(t_start).strftime("%H:%M:%S")
            with open(self.txt_path, "a", encoding="utf-8-sig") as f:
                f.write(f"[{clock}] [{lang}] {text}\n")
                if trans:
                    f.write(f"           → {trans}\n")


class RateLimited(Exception):
    pass


UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36 Edg/126.0"}


# ---- 方式 1：在自己電腦上翻譯（NLLB 模型，離線、沒有次數限制） ----
NLLB_REPO = "JustFrederik/nllb-200-distilled-600M-ct2-int8"
WHISPER_TO_NLLB = {
    "zh": "zho_Hans", "yue": "yue_Hant", "en": "eng_Latn", "ja": "jpn_Jpan", "ko": "kor_Hang",
    "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn", "ru": "rus_Cyrl", "vi": "vie_Latn",
    "th": "tha_Thai", "id": "ind_Latn", "ms": "zsm_Latn", "it": "ita_Latn", "pt": "por_Latn",
    "ar": "arb_Arab", "hi": "hin_Deva", "tl": "tgl_Latn", "nl": "nld_Latn", "tr": "tur_Latn",
    "pl": "pol_Latn", "uk": "ukr_Cyrl", "pa": "pan_Guru", "fa": "pes_Arab", "sv": "swe_Latn",
    "he": "heb_Hebr", "el": "ell_Grek", "cs": "ces_Latn", "ro": "ron_Latn", "hu": "hun_Latn",
    "da": "dan_Latn", "fi": "fin_Latn", "no": "nob_Latn", "bn": "ben_Beng", "ta": "tam_Taml",
    "ur": "urd_Arab", "km": "khm_Khmr", "my": "mya_Mymr", "lo": "lao_Laoo",
}
TARGET_TO_NLLB = {
    "zh-TW": "zho_Hant", "zh-CN": "zho_Hans", "en": "eng_Latn", "ja": "jpn_Jpan",
    "ko": "kor_Hang", "es": "spa_Latn", "fr": "fra_Latn", "de": "deu_Latn",
    "vi": "vie_Latn", "th": "tha_Thai", "id": "ind_Latn", "ru": "rus_Cyrl",
}


class LocalTranslator:
    def __init__(self, status):
        self.status = status
        self.tr = None
        self.sp = None
        self.failed = False
        self.lock = threading.Lock()

    def load(self, download=True):
        with self.lock:
            if self.tr is not None:
                return True
            if self.failed:
                return False
            try:
                setup_cuda_dlls()
                import ctranslate2
                import sentencepiece as spm
                from huggingface_hub import snapshot_download
                try:
                    path = snapshot_download(NLLB_REPO, local_files_only=True)
                except Exception:
                    if not download:
                        return False
                    self.status(T("第一次使用離線翻譯，下載翻譯模型中（約 600 MB），請稍候…"))
                    path = snapshot_download(NLLB_REPO)
                gpu = 0
                try:
                    gpu = ctranslate2.get_cuda_device_count()
                except Exception:
                    pass
                tr = None
                if gpu > 0:
                    try:
                        tr = ctranslate2.Translator(path, device="cuda", compute_type="int8_float16")
                    except Exception as e:
                        log("nllb cuda failed", repr(e))
                if tr is None:
                    tr = ctranslate2.Translator(path, device="cpu", compute_type="int8",
                                                inter_threads=1, intra_threads=min(4, os.cpu_count() or 2))
                sp = spm.SentencePieceProcessor(model_file=os.path.join(path, "sentencepiece.bpe.model"))
                self.tr, self.sp = tr, sp
                log("local translator ready:", tr.device)
                return True
            except Exception as e:
                self.failed = True
                log("local translator unavailable:", repr(e))
                return False

    def translate(self, text, src_lang, target):
        src = WHISPER_TO_NLLB.get(src_lang)
        tgt = TARGET_TO_NLLB.get(target)
        if not src or not tgt:
            raise ValueError(f"local translation does not support {src_lang} -> {target}")
        if not self.load():
            raise RuntimeError(T("離線翻譯模型無法使用"))
        toks = self.sp.encode(text, out_type=str)[:400]
        res = self.tr.translate_batch([[src] + toks + ["</s>"]], target_prefix=[[tgt]],
                                      beam_size=2, max_decoding_length=300,
                                      repetition_penalty=1.15, no_repeat_ngram_size=4)
        out = res[0].hypotheses[0]
        if out and out[0] == tgt:
            out = out[1:]
        return self.sp.decode(out).strip()


# ---- 方式 2：微軟翻譯（Edge 瀏覽器內建翻譯用的介面） ----
_edge_token = {"value": "", "time": 0.0}


def _edge_translate(text, target):
    import requests
    to = {"zh-TW": "zh-Hant", "zh-CN": "zh-Hans"}.get(target, target)
    for attempt in range(2):
        if not _edge_token["value"] or time.time() - _edge_token["time"] > 480 or attempt:
            r = requests.get("https://edge.microsoft.com/translate/auth", headers=UA, timeout=6)
            if r.status_code == 429:
                raise RateLimited()
            r.raise_for_status()
            _edge_token.update(value=r.text.strip(), time=time.time())
        r = requests.post(
            "https://api-edge.cognitive.microsofttranslator.com/translate",
            params={"to": to, "api-version": "3.0"},
            headers=dict(UA, Authorization="Bearer " + _edge_token["value"]),
            json=[{"Text": text}], timeout=6)
        if r.status_code == 401 and attempt == 0:
            continue
        if r.status_code == 429:
            raise RateLimited()
        r.raise_for_status()
        return r.json()[0]["translations"][0]["text"].strip()
    raise RuntimeError("microsoft auth failed")


# ---- 方式 3：Google 翻譯 ----
def _gtx_translate(text, target):
    import requests
    r = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "auto", "tl": target, "dt": "t", "q": text},
        headers=UA, timeout=6)
    if r.status_code == 429:
        raise RateLimited()
    r.raise_for_status()
    data = r.json()
    return "".join(part[0] for part in data[0] if part and part[0]).strip()


def google_translate(text, target):
    return _gtx_translate(text, target)


TRANSLATE_CHOICES = [
    ("自動（先用離線翻譯，不行再用網路）", "auto"),
    ("離線翻譯（在自己電腦上，不需網路）", "local"),
    ("微軟翻譯（需要網路）", "microsoft"),
    ("Google 翻譯（需要網路，容易被限制次數）", "google"),
]
ENGINE_NAMES = {"local": "離線翻譯", "microsoft": "微軟翻譯", "google": "Google 翻譯"}


class TranslatorChain:
    """依序嘗試各種翻譯方式；被限制次數的方式會暫停一段時間，自動換下一個。"""

    def __init__(self, cfg, status):
        self.cfg = cfg
        self.status = status
        self.local = LocalTranslator(status)
        self.pause_until = {}
        self.backoff = {}
        self.last_engine = None

    def _order(self):
        choice = self.cfg.get("translate_engine", "auto")
        if choice == "auto":
            return ["local", "microsoft", "google"]
        rest = [e for e in ("local", "microsoft", "google") if e != choice]
        return [choice] + rest          # 選定的方式不能用時，還是會試其他方式

    def translate(self, text, src_lang, target):
        errors = []
        for eng in self._order():
            if time.time() < self.pause_until.get(eng, 0):
                continue
            try:
                if eng == "local":
                    out = self.local.translate(text, src_lang, target)
                elif eng == "microsoft":
                    out = _edge_translate(text, target)
                else:
                    out = _gtx_translate(text, target)
                if out:
                    self.backoff[eng] = 0
                    if eng != self.last_engine:
                        self.last_engine = eng
                        self.status(T("翻譯使用：") + T(ENGINE_NAMES[eng]))
                    return out
            except RateLimited:
                b = min(600, max(30, self.backoff.get(eng, 0) * 2))
                self.backoff[eng] = b
                self.pause_until[eng] = time.time() + b
                log(f"{eng} rate-limited; pause {b}s")
                errors.append(f"{eng}: 次數限制")
            except Exception as e:
                errors.append(f"{eng}: {e!r}")
                if eng != "local":       # 網路錯誤：短暫停一下再試
                    self.pause_until[eng] = time.time() + 10
        raise RuntimeError("; ".join(errors) or T("沒有可用的翻譯方式"))


# ----------------------------------------------------------------------------
# 只允許開一個：第二次點兩下桌面圖示時，叫出已在執行的控制面板
# ----------------------------------------------------------------------------
def acquire_single_instance():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", SINGLE_INSTANCE_PORT))
        s.listen(5)
        return s
    except OSError:
        s.close()
        try:
            c = socket.create_connection(("127.0.0.1", SINGLE_INSTANCE_PORT), timeout=2)
            c.sendall(b"show")
            c.close()
        except Exception:
            pass
        return None


# ----------------------------------------------------------------------------
# 螢幕字幕視窗（透明、置頂、滑鼠可穿透）
# ----------------------------------------------------------------------------
class Overlay:
    KEY = "#010203"   # 這個顏色會變透明

    def __init__(self, app):
        import tkinter as tk
        self.app = app
        self.cfg = app.cfg
        self.win = tk.Toplevel(app.root)
        self.win.withdraw()
        self.win.overrideredirect(True)
        self.win.attributes("-topmost", True)
        self.win.configure(bg=self.KEY)
        try:
            self.win.attributes("-transparentcolor", self.KEY)
        except Exception:
            pass
        self.canvas = tk.Canvas(self.win, bg=self.KEY, highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.orig = ""
        self.trans = ""
        self.trans_sid = 0
        self.trans_kind = "ok"
        self.sid = None
        self.partial = False
        self.last_update = 0.0
        self.adjusting = False
        self.visible = False
        self._drag = None
        self._load_geometry()
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self._keep_on_top()

    # ---- 位置 ----
    def _virtual_screen(self):
        try:
            u = ctypes.windll.user32
            return (u.GetSystemMetrics(76), u.GetSystemMetrics(77),
                    u.GetSystemMetrics(78), u.GetSystemMetrics(79))
        except Exception:
            return 0, 0, self.win.winfo_screenwidth(), self.win.winfo_screenheight()

    def _load_geometry(self):
        sw, sh = self.win.winfo_screenwidth(), self.win.winfo_screenheight()
        self.w = int(self.cfg.get("overlay_w") or 1100)
        self.h = int(self.cfg.get("overlay_h") or 150)
        self.w = min(self.w, sw)
        x, y = self.cfg.get("overlay_x"), self.cfg.get("overlay_y")
        vx, vy, vw, vh = self._virtual_screen()
        if (x is None or y is None or x < vx - self.w + 50 or x > vx + vw - 50
                or y < vy or y > vy + vh - 30):
            x = (sw - self.w) // 2
            y = sh - self.h - 90
        self.x, self.y = int(x), int(y)
        self._apply_geometry()

    def _apply_geometry(self):
        self.win.geometry(f"{self.w}x{self.h}+{self.x}+{self.y}")

    def _save_geometry(self):
        self.cfg.update(overlay_x=self.x, overlay_y=self.y, overlay_w=self.w, overlay_h=self.h)
        save_config(self.cfg)

    def reset_position(self):
        self.cfg.update(overlay_x=None, overlay_y=None, overlay_w=1100, overlay_h=150)
        self._load_geometry()
        self._save_geometry()
        self.render()

    # ---- 滑鼠穿透 ----
    def _hwnd(self):
        return ctypes.windll.user32.GetParent(self.win.winfo_id())

    def set_clickthrough(self, on):
        try:
            u = ctypes.windll.user32
            hwnd = self._hwnd()
            GWL_EXSTYLE = -20
            style = u.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style |= 0x80000 | 0x80 | 0x08000000      # LAYERED | TOOLWINDOW | NOACTIVATE
            if on:
                style |= 0x20                          # TRANSPARENT（滑鼠穿透）
            else:
                style &= ~0x20
            u.SetWindowLongW(hwnd, GWL_EXSTYLE, style)
        except Exception as e:
            log("clickthrough failed", e)

    def _keep_on_top(self):
        if self.visible and not self.adjusting:
            try:
                self.win.attributes("-topmost", True)
                self.win.lift()
            except Exception:
                pass
        self.win.after(2000, self._keep_on_top)

    # ---- 顯示/隱藏 ----
    def show(self):
        if not self.visible:
            self.win.deiconify()
            self.win.update_idletasks()
            self.set_clickthrough(not self.adjusting)
            self.visible = True
            self.render()

    def hide(self):
        if self.visible and not self.adjusting:
            self.win.withdraw()
            self.visible = False

    def sync_visibility(self):
        if self.adjusting or (self.app.recording and self.cfg.get("show_overlay", True)):
            self.show()
        else:
            self.hide()

    def start_adjust(self):
        self.adjusting = True
        self.show()
        self.set_clickthrough(False)
        self.render()

    def end_adjust(self):
        self.adjusting = False
        self._save_geometry()
        self.set_clickthrough(True)
        self.render()
        self.sync_visibility()

    def _press(self, e):
        if not self.adjusting:
            return
        mode = "resize" if (e.x > self.w - 28 and e.y > self.h - 28) else "move"
        self._drag = (mode, e.x_root, e.y_root, self.x, self.y, self.w, self.h)

    def _motion(self, e):
        if not self._drag:
            return
        mode, sx, sy, ox, oy, ow, oh = self._drag
        dx, dy = e.x_root - sx, e.y_root - sy
        if mode == "move":
            self.x, self.y = ox + dx, oy + dy
        else:
            self.w, self.h = max(300, ow + dx), max(70, oh + dy)
        self._apply_geometry()
        self.render()

    def _release(self, e):
        if self._drag:
            self._drag = None
            self._save_geometry()

    # ---- 文字 ----
    def display_mode(self):
        """both = 原文＋翻譯；trans = 只顯示翻譯；orig = 只顯示原文"""
        if not self.cfg.get("second_language"):
            return "orig"
        return self.cfg.get("display_mode", "both")

    def show_text(self, orig, partial=False, sid=None):
        self.orig, self.partial = orig, partial
        if sid is not None:
            self.sid = sid
        if self.display_mode() != "trans":
            self.last_update = time.time()
        self.render()

    def set_trans(self, sid, text, kind="ok"):
        """kind: ok = 翻譯成功；same = 原本就是目標語言；fail = 翻譯失敗（暫時用原文）"""
        if sid >= self.trans_sid:       # 只顯示最新一句的翻譯，不會被下一句的即時字幕蓋掉
            self.trans, self.trans_sid, self.trans_kind = text, sid, kind
            self.last_update = time.time()
            self.render()

    def clear(self):
        if self.orig or self.trans:
            self.orig = self.trans = ""
            self.render()

    def _outlined(self, x, y, text, font, color, width):
        c = self.canvas
        for dx, dy in ((-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2)):
            c.create_text(x + dx, y + dy, text=text, font=font, fill="#000000",
                          width=width, anchor="s", justify="center")
        item = c.create_text(x, y, text=text, font=font, fill=color, width=width,
                             anchor="s", justify="center")
        return c.bbox(item)

    def render(self):
        c = self.canvas
        c.delete("all")
        w, h = self.w, self.h
        mode = self.display_mode()
        orig, trans, kind = self.orig, self.trans, self.trans_kind
        if self.adjusting:
            c.create_rectangle(1, 1, w - 2, h - 2, outline="#38BDF8", width=2, dash=(6, 4), fill="#1E293B")
            c.create_rectangle(w - 24, h - 24, w - 2, h - 2, fill="#38BDF8", outline="")
            c.create_text(w // 2, 16, text=T("拖曳移動位置．右下角藍色方塊拖曳調整大小．完成後按控制面板的「完成調整」"),
                          fill="#E2E8F0", font=(UI_FONT, 10))
            if not orig and not trans:
                orig, trans, kind = T("字幕會顯示在這裡 Subtitles appear here"), T("這裡是翻譯"), "ok"
        fs = int(self.cfg.get("font_size", 28))
        y = h - 6
        wrap = max(100, w - 24)
        main_color = self.cfg.get("text_color", "#FFFFFF")

        if mode == "trans":
            # 只顯示翻譯：用大字顯示；原本就是同一種語言時直接顯示原文
            if trans:
                if len(trans) > 160:
                    trans = "…" + trans[-160:]
                color = "#CBD5E1" if kind == "fail" else main_color
                self._outlined(w // 2, y, trans, (UI_FONT, fs, "bold"), color, wrap)
            return

        if len(orig) > 160:
            orig = "…" + orig[-160:]
        if mode == "both" and trans and kind == "ok":
            bb = self._outlined(w // 2, y, trans, (UI_FONT, max(10, int(fs * 0.8)), "bold"),
                                self.cfg.get("second_color", "#FFE066"), wrap)
            if bb:
                y = bb[1] - 2
        if orig:
            color = "#CBD5E1" if self.partial else main_color
            self._outlined(w // 2, y, orig, (UI_FONT, fs, "bold"), color, wrap)


# ----------------------------------------------------------------------------
# 工作列（右下角）圖示
# ----------------------------------------------------------------------------
class Tray:
    def __init__(self, app):
        import pystray
        self.app = app
        cmd = app.cmd_q.put
        menu = pystray.Menu(
            pystray.MenuItem(lambda item: T("顯示控制面板"), lambda icon, item: cmd("show"), default=True),
            pystray.MenuItem(lambda item: T("■ 停止錄製") if app.recording else T("▶ 開始錄製"),
                             lambda icon, item: cmd("toggle")),
            pystray.MenuItem(lambda item: T("開啟字幕檔資料夾"), lambda icon, item: cmd("folder")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(lambda item: T("結束程式"), lambda icon, item: cmd("quit")),
        )
        self.icons = {False: make_icon_image(False, 64), True: make_icon_image(True, 64)}
        self.icon = pystray.Icon("LiveCaptions", self.icons[False], T("即時字幕：已停止"), menu)
        self.icon.run_detached()

    def update(self, recording):
        try:
            self.icon.icon = self.icons[recording]
            self.icon.title = T("即時字幕：錄製中") if recording else T("即時字幕：已停止")
            self.icon.update_menu()
        except Exception as e:
            log("tray update failed", e)

    def stop(self):
        try:
            self.icon.stop()
        except Exception:
            pass


# ----------------------------------------------------------------------------
# 主程式 / 控制面板
# ----------------------------------------------------------------------------
class App:
    def __init__(self, server_sock):
        import tkinter as tk
        from tkinter import ttk
        self.tk, self.ttk = tk, ttk
        self.cfg = load_config()
        set_ui_lang(self.cfg.get("ui_lang", "auto"))
        self.cmd_q = queue.Queue()
        self.ui_q = queue.Queue()
        self.final_q = queue.Queue()
        self.trans_q = queue.Queue()
        self.partial_lock = threading.Lock()
        self.partial_audio = None
        self.recording = False
        self.capture = None
        self._restart_job = None
        self._last_final = ("", 0.0)
        self.writer = None
        self.quitting = False
        self.seq = 0
        self.translate_warned = False
        self.translator = None

        self.root = tk.Tk()
        self.root.withdraw()
        ico = os.path.join(APP_DIR, "icon.ico")
        if os.path.exists(ico):
            try:
                self.root.iconbitmap(default=ico)
            except Exception:
                pass

        self.engine = Engine(self.cfg, lambda m: self.ui_q.put(("status", m)))
        self._build_panel()
        self.overlay = Overlay(self)
        self.tray = None
        try:
            self.tray = Tray(self)
        except Exception:
            log("tray failed", traceback.format_exc())
        self._setup_hotkeys()

        threading.Thread(target=self._server, args=(server_sock,), daemon=True).start()
        threading.Thread(target=self._transcribe_worker, name="asr", daemon=True).start()
        threading.Thread(target=self._translate_worker, name="translate", daemon=True).start()
        threading.Thread(target=self._device_watcher, name="devices", daemon=True).start()

        self.show_panel()
        if self.cfg.get("auto_start", True):
            self.root.after(300, self.start_recording)
        self.root.after(50, self._poll)

    # ---- 介面 ----
    def _build_panel(self):
        tk, ttk = self.tk, self.ttk
        r = self.root
        r.title(T("即時字幕 － 控制面板"))
        r.protocol("WM_DELETE_WINDOW", self.hide_panel)
        r.minsize(520, 560)
        st = ttk.Style()
        try:
            st.theme_use("vista")
        except Exception:
            pass
        st.configure(".", font=(UI_FONT, 10))
        st.configure("Big.TButton", font=(UI_FONT, 15, "bold"), padding=(10, 12))

        main = ttk.Frame(r, padding=14)
        main.pack(fill="both", expand=True)
        self.main_frame = main

        top = ttk.Frame(main)
        top.pack(fill="x")
        self.state_lbl = tk.Label(top, text=T("■ 已停止"), font=(UI_FONT, 16, "bold"), fg="#64748B")
        self.state_lbl.pack(side="left")
        self.level = tk.Canvas(top, width=160, height=12, bg="#E2E8F0", highlightthickness=0)
        self.level.pack(side="right", pady=6)
        ttk.Label(top, text=T("音量")).pack(side="right", padx=6)

        self.toggle_btn = ttk.Button(main, text=T("▶ 開始錄製"), style="Big.TButton",
                                     command=self.toggle_recording)
        self.toggle_btn.pack(fill="x", pady=(10, 8))

        info = ttk.Frame(main)
        info.pack(fill="x")
        self.status_var = tk.StringVar(value=T("準備中…"))
        self.engine_var = tk.StringVar(value=T("載入中…"))
        self.lang_var = tk.StringVar(value="—")
        for i, (label, var) in enumerate([(T("狀態"), self.status_var), (T("辨識引擎"), self.engine_var),
                                          (None, None), (T("偵測到的語言"), self.lang_var)]):
            if label is None:
                continue
            ttk.Label(info, text=label + T("："), foreground="#475569").grid(row=i, column=0, sticky="w", pady=1)
            ttk.Label(info, textvariable=var, wraplength=400).grid(row=i, column=1, sticky="w", pady=1)
        ttk.Label(info, text=T("聲音來源："), foreground="#475569").grid(row=2, column=0, sticky="nw", pady=1)
        self.dev_frame = ttk.Frame(info)
        self.dev_frame.grid(row=2, column=1, sticky="w", pady=1)
        self.dev_bars = {}
        self._set_devices([])

        sf = ttk.LabelFrame(main, text=T(" 設定 "), padding=10)
        sf.pack(fill="x", pady=(10, 6))
        sf.columnconfigure(1, weight=1)

        def combo(row, label, choices, key, on_change=None):
            ttk.Label(sf, text=label).grid(row=row, column=0, sticky="w", pady=3)
            names = [T(n) for n, _ in choices]
            codes = [c for _, c in choices]
            cb = ttk.Combobox(sf, values=names, state="readonly")
            cur = self.cfg.get(key, "")
            cb.current(codes.index(cur) if cur in codes else 0)
            cb.grid(row=row, column=1, sticky="ew", pady=3)

            def changed(_e=None):
                self.cfg[key] = codes[cb.current()]
                save_config(self.cfg)
                if on_change:
                    on_change()
            cb.bind("<<ComboboxSelected>>", changed)
            return cb

        combo(1, T("原文語言"), SOURCE_CHOICES, "source_language")
        combo(2, T("第二語言（翻譯）"), SECOND_CHOICES, "second_language", lambda: self.overlay.render())
        combo(3, T("螢幕字幕顯示"), DISPLAY_CHOICES, "display_mode", lambda: self.overlay.render())
        combo(4, T("翻譯方式"), TRANSLATE_CHOICES, "translate_engine")
        combo(0, T("聲音來源"), SOURCE_MODES, "source_mode", lambda: self.schedule_restart(100))
        combo(5, T("辨識模型"), MODEL_CHOICES, "model",
              lambda: self.status_var.set(T("模型已更改：請「結束程式」後重新開啟才會生效")))

        ttk.Label(sf, text=T("字幕大小")).grid(row=6, column=0, sticky="w", pady=3)
        row3 = ttk.Frame(sf)
        row3.grid(row=6, column=1, sticky="w")
        self.font_var = tk.IntVar(value=int(self.cfg.get("font_size", 28)))
        tk.Spinbox(row3, from_=12, to=80, width=5, textvariable=self.font_var,
                   command=self._font_changed).pack(side="left")
        self.font_var.trace_add("write", lambda *a: self._font_changed())
        ttk.Label(row3, text=T("   字幕停留秒數")).pack(side="left")
        self.clear_var = tk.IntVar(value=int(self.cfg.get("clear_after_sec", 6)))
        tk.Spinbox(row3, from_=2, to=60, width=4, textvariable=self.clear_var).pack(side="left")
        self.clear_var.trace_add("write", lambda *a: self._set_int("clear_after_sec", self.clear_var))

        self.show_var = tk.BooleanVar(value=self.cfg.get("show_overlay", True))
        self.trad_var = tk.BooleanVar(value=self.cfg.get("to_traditional", True))
        self.auto_var = tk.BooleanVar(value=self.cfg.get("auto_start", True))
        ttk.Checkbutton(sf, text=T("在螢幕上顯示字幕"), variable=self.show_var,
                        command=self._show_changed).grid(row=7, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(sf, text=T("中文一律顯示繁體字"), variable=self.trad_var,
                        command=lambda: self._set_bool("to_traditional", self.trad_var)
                        ).grid(row=8, column=0, columnspan=2, sticky="w")
        ttk.Checkbutton(sf, text=T("打開程式時自動開始錄製"), variable=self.auto_var,
                        command=lambda: self._set_bool("auto_start", self.auto_var)
                        ).grid(row=9, column=0, columnspan=2, sticky="w")

        pos = ttk.Frame(sf)
        pos.grid(row=10, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.adjust_btn = ttk.Button(pos, text=T("調整字幕位置／大小"), command=self.toggle_adjust)
        self.adjust_btn.pack(side="left")
        ttk.Button(pos, text=T("位置重設"), command=lambda: self.overlay.reset_position()).pack(side="left", padx=6)

        hf = ttk.LabelFrame(main, text=T(" 最近的字幕 "), padding=6)
        hf.pack(fill="both", expand=True, pady=(4, 6))
        self.history = tk.Text(hf, height=8, wrap="word", font=(UI_FONT, 10), relief="flat",
                               bg="#F8FAFC", state="disabled")
        sb = ttk.Scrollbar(hf, command=self.history.yview)
        self.history.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.history.pack(fill="both", expand=True)
        self.history.tag_configure("tr", foreground="#B45309")
        self.history.tag_configure("meta", foreground="#94A3B8")

        hk = T("快速鍵：{a} 開始／停止　{b} 叫出此面板").format(a=self.cfg['hotkey_toggle'].upper(), b=self.cfg['hotkey_panel'].upper())
        ttk.Label(main, text=hk, foreground="#64748B").pack(anchor="w")
        ttk.Label(main, text=T("按右上角 ✕ 不會結束程式，只會縮到右下角工作列的圖示（點圖示就能再叫出來）。"),
                  foreground="#64748B", wraplength=500).pack(anchor="w", pady=(0, 6))

        bot = ttk.Frame(main)
        bot.pack(fill="x")
        ttk.Label(bot, text="介面語言 / Language").pack(side="left")
        lang_cb = ttk.Combobox(bot, values=[n for n, _ in UI_LANG_CHOICES], state="readonly", width=8)
        lang_cb.current(1 if _ui_lang["value"] == "en" else 0)
        lang_cb.pack(side="left", padx=(4, 10))
        lang_cb.bind("<<ComboboxSelected>>",
                     lambda e: self.change_ui_lang(UI_LANG_CHOICES[lang_cb.current()][1]))
        ttk.Button(bot, text=T("開啟字幕檔資料夾"), command=self.open_folder).pack(side="left")
        ttk.Button(bot, text=T("結束程式"), command=self.quit).pack(side="right")
        ttk.Button(bot, text=T("縮到工作列"), command=self.hide_panel).pack(side="right", padx=6)

    def change_ui_lang(self, code):
        """切換介面語言：重建控制面板，保留目前狀態。"""
        if code == _ui_lang["value"]:
            return
        self.cfg["ui_lang"] = code
        save_config(self.cfg)
        set_ui_lang(code)
        lang_text = self.lang_var.get()
        try:
            hist = self.history.get("1.0", "end-1c")
        except Exception:
            hist = ""
        if self.overlay.adjusting:
            self.toggle_adjust()
        self.main_frame.destroy()
        self._build_panel()
        self.engine_var.set(self.engine.describe() if self.engine.ready.is_set()
                            else (T("載入失敗") if self.engine.failed else T("載入中…")))
        self.status_var.set(T("錄製中，等待有人說話…") if self.recording else T("已停止"))
        self.lang_var.set(lang_text)
        if hist:
            self.history.configure(state="normal")
            self.history.insert("end", hist + "\n")
            self.history.see("end")
            self.history.configure(state="disabled")
        self._set_devices(self.capture.names() if self.capture else [])
        self._refresh_state()
        self.overlay.render()

    def _set_bool(self, key, var):
        self.cfg[key] = bool(var.get())
        save_config(self.cfg)

    def _set_int(self, key, var):
        try:
            self.cfg[key] = int(var.get())
            save_config(self.cfg)
        except Exception:
            pass

    def _font_changed(self):
        try:
            v = int(self.font_var.get())
        except Exception:
            return
        if 8 <= v <= 120:
            self.cfg["font_size"] = v
            save_config(self.cfg)
            self.overlay.render()

    def _show_changed(self):
        self._set_bool("show_overlay", self.show_var)
        self.overlay.sync_visibility()

    def toggle_adjust(self):
        if self.overlay.adjusting:
            self.overlay.end_adjust()
            self.adjust_btn.configure(text=T("調整字幕位置／大小"))
        else:
            self.overlay.start_adjust()
            self.adjust_btn.configure(text=T("✔ 完成調整"))

    def show_panel(self):
        r = self.root
        r.deiconify()
        r.lift()
        r.attributes("-topmost", True)
        r.after(300, lambda: r.attributes("-topmost", False))
        try:
            r.focus_force()
        except Exception:
            pass

    def hide_panel(self):
        if self.tray is None:      # 沒有工作列圖示就用最小化，避免找不到
            self.root.iconify()
        else:
            self.root.withdraw()

    def open_folder(self):
        try:
            os.startfile(output_dir(self.cfg))
        except Exception as e:
            log("open folder failed", e)

    def _append_history(self, lang, text, trans):
        h = self.history
        h.configure(state="normal")
        h.insert("end", time.strftime("%H:%M:%S ") + f"[{lang}] ", "meta")
        h.insert("end", text + "\n")
        if trans:
            h.insert("end", "    → " + trans + "\n", "tr")
        lines = int(h.index("end-1c").split(".")[0])
        if lines > 400:
            h.delete("1.0", f"{lines - 400}.0")
        h.see("end")
        h.configure(state="disabled")

    def _set_devices(self, names):
        """聲音來源：每個裝置一條音量條，看得出聲音從哪個裝置出來。"""
        tk, ttk = self.tk, self.ttk
        for w in self.dev_frame.winfo_children():
            w.destroy()
        self.dev_bars = {}
        if not names:
            ttk.Label(self.dev_frame, text="—").grid(row=0, column=0, sticky="w")
            return
        for i, n in enumerate(names):
            c = tk.Canvas(self.dev_frame, width=70, height=8, bg="#E2E8F0", highlightthickness=0)
            c.grid(row=i, column=0, sticky="w", padx=(0, 6), pady=2)
            ttk.Label(self.dev_frame, text=n).grid(row=i, column=1, sticky="w")
            self.dev_bars[n] = c

    @staticmethod
    def _level_frac(rms):
        return min(1.0, (np.log10(max(rms, 1e-4)) + 4) / 3.5) if rms > 0 else 0

    def _draw_dev_levels(self, levels):
        for n, c in self.dev_bars.items():
            v = self._level_frac(levels.get(n, 0.0))
            c.delete("all")
            if v > 0:
                c.create_rectangle(0, 0, int(70 * v), 8, fill="#22C55E", outline="")

    def _draw_level(self, rms):
        c = self.level
        c.delete("all")
        v = self._level_frac(rms)
        c.create_rectangle(0, 0, int(160 * v), 12, fill="#22C55E" if v < 0.85 else "#F97316", outline="")

    def _refresh_state(self):
        if self.recording:
            self.state_lbl.configure(text=T("● 錄製中"), fg="#DC2626")
            self.toggle_btn.configure(text=T("■ 停止錄製"))
        else:
            self.state_lbl.configure(text=T("■ 已停止"), fg="#64748B")
            self.toggle_btn.configure(text=T("▶ 開始錄製"))
            self._draw_level(0)
            self._draw_dev_levels({})
        if self.tray:
            self.tray.update(self.recording)
        self.overlay.sync_visibility()

    # ---- 錄製 ----
    def _is_live(self):
        return self.engine.device == "cuda"

    def _max_len(self):
        return 10.0 if self.engine.device == "cuda" else 6.0

    def _open_capture(self, writer):
        def make_recorder(rate, ch, name):
            return Recorder(
                on_final=lambda a, t0, t1: self.final_q.put((a, t0, t1, writer)),
                on_partial=self._set_partial,
                on_level=lambda v, n=name: self.ui_q.put(("level", v, n)),
                get_live=self._is_live,
                get_max=self._max_len,
                rate=rate, ch=ch, name=name,
            )
        cap = Capture(self.cfg.get("source_mode", "all"), make_recorder)
        cap.start()
        self.capture = cap
        self._set_devices(cap.names())

    def _close_capture(self):
        cap, self.capture = self.capture, None
        if cap:
            cap.stop()

    def start_recording(self):
        if self.recording:
            return
        writer = CaptionWriter(output_dir(self.cfg))
        try:
            self._open_capture(writer)
        except Exception as e:
            log("start recording failed", traceback.format_exc())
            self.status_var.set(T("無法開始錄製：") + str(e))
            from tkinter import messagebox
            self.show_panel()
            messagebox.showerror(T("即時字幕"), T("無法擷取電腦聲音：") + f"\n{e}\n\n" + T("請確認有喇叭或耳機（播放裝置）可用。"))
            return
        self.writer = writer
        self.recording = True
        if self.engine.ready.is_set():
            self.status_var.set(T("錄製中，等待有人說話…"))
        self._refresh_state()

    def stop_recording(self):
        if not self.recording:
            return
        self.recording = False
        self._cancel_restart()
        self._close_capture()
        with self.partial_lock:
            self.partial_audio = None
        self.status_var.set(T("已停止"))
        self._refresh_state()
        self.overlay.clear()

    # ---- 播放裝置改變時自動重新連接（同一個字幕檔繼續寫） ----
    def _cancel_restart(self):
        if self._restart_job:
            try:
                self.root.after_cancel(self._restart_job)
            except Exception:
                pass
            self._restart_job = None

    def schedule_restart(self, delay_ms=1200, attempt=0):
        self._cancel_restart()
        if self.recording:
            self._restart_job = self.root.after(delay_ms, lambda: self._restart_capture(attempt))

    def _restart_capture(self, attempt):
        self._restart_job = None
        if not self.recording:
            return
        self._close_capture()
        try:
            self._open_capture(self.writer)
            self.status_var.set(T("已切換到新的聲音裝置，錄製中"))
            log("capture restarted")
        except Exception as e:
            log("restart capture failed", attempt, repr(e))
            self._set_devices([])
            if attempt < 20:
                self.status_var.set(T("正在等待播放裝置…（插上喇叭或耳機後會自動繼續）"))
                self.schedule_restart(3000, attempt + 1)
            else:
                self.stop_recording()
                self.status_var.set(T("找不到可用的播放裝置：") + str(e))

    def _device_watcher(self):
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception as e:
            log("device watcher unavailable (請重新執行 install.bat):", repr(e))
            return
        holder = []
        last = None
        warned = False
        while not self.quitting:
            try:
                snap = audio_device_snapshot(holder)
            except Exception as e:
                holder.clear()
                if not warned:
                    log("device snapshot failed", repr(e))
                    warned = True
                snap = None
            if snap is not None:
                if last is not None and snap != last:
                    self.cmd_q.put(("devices", snap[0] != last[0], snap[1] != last[1]))
                last = snap
            time.sleep(1.5)

    def _on_devices_changed(self, default_changed, list_changed):
        mode = self.cfg.get("source_mode", "all")
        if list_changed or (mode == "default" and default_changed):
            log("audio devices changed; default:", default_changed, "list:", list_changed)
            self.schedule_restart()

    def toggle_recording(self):
        if self.recording:
            self.stop_recording()
        else:
            self.start_recording()

    def _set_partial(self, audio):
        with self.partial_lock:
            self.partial_audio = audio

    # ---- 背景工作 ----
    def _transcribe_worker(self):
        if not self.engine.load():
            self.ui_q.put(("engine", T("載入失敗")))
            return
        self.ui_q.put(("engine", self.engine.describe()))
        self.ui_q.put(("status", T("錄製中，等待有人說話…") if self.recording else T("就緒，按「開始錄製」")))
        while not self.quitting:
            try:
                audio, t0, t1, writer = self.final_q.get(timeout=0.1)
            except queue.Empty:
                with self.partial_lock:
                    p, self.partial_audio = self.partial_audio, None
                if p is not None and self.recording:
                    try:
                        text, lang, prob = self.engine.transcribe(p, final=False)
                        if text and self.final_q.empty():
                            self.ui_q.put(("partial", text))
                    except Exception:
                        log("partial error", traceback.format_exc())
                continue
            with self.partial_lock:
                self.partial_audio = None
            backlog = self.final_q.qsize()
            if backlog >= 6:     # 電腦太慢跟不上：丟掉最舊的，避免越拖越久
                try:
                    self.final_q.get_nowait()
                except queue.Empty:
                    pass
                self.ui_q.put(("status", T("電腦處理速度跟不上，已略過部分語音（可改用較小的模型）")))
            try:
                text, lang, prob = self.engine.transcribe(audio, final=True)
            except Exception:
                log("transcribe error", traceback.format_exc())
                continue
            if not text:
                continue
            # 同一段聲音同時從兩個裝置播出時，避免字幕重複
            last_text, last_t = self._last_final
            if text == last_text and abs(t0 - last_t) < 3.0:
                continue
            self._last_final = (text, t0)
            self.seq += 1
            sid = self.seq
            self.ui_q.put(("final", sid, text, lang, prob))
            self.trans_q.put((sid, text, lang, t0, t1, writer))

    def _translate_worker(self):
        chain = TranslatorChain(self.cfg, lambda m: self.ui_q.put(("status", m)))
        self.translator = chain
        while not self.quitting:
            item = self.trans_q.get()
            if item is None:
                break
            sid, text, lang, t0, t1, writer = item
            target = self.cfg.get("second_language", "")
            tr = ""
            if target and not same_language(lang, target):
                try:
                    tr = chain.translate(text, lang, target)
                    if tr and target == "zh-TW":
                        tr = self.engine._to_trad(tr)
                    self.translate_warned = False
                except Exception as e:
                    log("translate failed:", e)
                    if not self.translate_warned:
                        self.translate_warned = True
                        self.ui_q.put(("status", T("翻譯暫時失敗，稍後會自動再試（原文字幕照常）")))
            if target:
                if tr:
                    self.ui_q.put(("trans", sid, tr, "ok"))
                elif same_language(lang, target):
                    self.ui_q.put(("trans", sid, text, "same"))
                else:
                    self.ui_q.put(("trans", sid, text, "fail"))
            try:
                writer.write(t0, t1, lang, text, tr)
            except Exception:
                log("write failed", traceback.format_exc())
            self.ui_q.put(("history", lang, text, tr))

    def _server(self, sock):
        while not self.quitting:
            try:
                conn, _ = sock.accept()
                data = conn.recv(64)
                conn.close()
                if data.startswith(b"show"):
                    self.cmd_q.put("show")
            except Exception:
                time.sleep(0.5)

    def _setup_hotkeys(self):
        try:
            import keyboard
            keyboard.add_hotkey(self.cfg["hotkey_toggle"], lambda: self.cmd_q.put("toggle"))
            keyboard.add_hotkey(self.cfg["hotkey_panel"], lambda: self.cmd_q.put("show"))
        except Exception as e:
            log("hotkeys unavailable", repr(e))

    # ---- 主迴圈 ----
    def _poll(self):
        try:
            while True:
                cmd = self.cmd_q.get_nowait()
                if cmd == "show":
                    self.show_panel()
                elif cmd == "toggle":
                    self.toggle_recording()
                elif cmd == "folder":
                    self.open_folder()
                elif cmd == "quit":
                    self.quit()
                    return
                elif isinstance(cmd, tuple) and cmd[0] == "devices":
                    self._on_devices_changed(cmd[1], cmd[2])
        except queue.Empty:
            pass

        n = 0
        level = None
        dev_levels = {}
        try:
            while n < 300:
                n += 1
                m = self.ui_q.get_nowait()
                kind = m[0]
                if kind == "level":
                    level = max(level or 0.0, m[1])
                    dev_levels[m[2]] = max(dev_levels.get(m[2], 0.0), m[1])
                elif kind == "status":
                    self.status_var.set(m[1])
                elif kind == "engine":
                    self.engine_var.set(m[1])
                elif kind == "partial":
                    if self.recording:
                        self.overlay.show_text(m[1], partial=True)
                elif kind == "final":
                    _, sid, text, lang, prob = m
                    self.overlay.show_text(text, partial=False, sid=sid)
                    name = T(LANG_NAMES.get(lang, lang))
                    self.lang_var.set(f"{name} ({prob:.0%})" if not self.cfg.get("source_language") else name)
                    if self.recording:
                        self.status_var.set(T("錄製中"))
                elif kind == "trans":
                    self.overlay.set_trans(m[1], m[2], m[3])
                elif kind == "history":
                    self._append_history(m[1], m[2], m[3])
        except queue.Empty:
            pass
        if level is not None and self.recording:
            self._draw_level(level)
            self._draw_dev_levels(dev_levels)

        ov = self.overlay
        if ov.last_update and time.time() - ov.last_update > float(self.cfg.get("clear_after_sec", 6)):
            ov.last_update = 0
            ov.clear()
        self.root.after(50, self._poll)

    def quit(self):
        if self.quitting:
            return
        self.quitting = True
        try:
            self.stop_recording()
        except Exception:
            pass
        save_config(self.cfg)
        if self.tray:
            self.tray.stop()
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        self.trans_q.put(None)
        self.root.after(200, self.root.destroy)

    def run(self):
        self.root.mainloop()


# ----------------------------------------------------------------------------
def preload():
    """安裝時先下載模型（顯示下載進度）。"""
    set_ui_lang(load_config().get("ui_lang", "auto"))
    print(T("正在下載並測試語音辨識模型，第一次需要幾分鐘…"))
    eng = Engine(load_config(), lambda m: print(m))
    if eng.load():
        print(T("完成！使用："), eng.describe())
        print(T("下載離線翻譯模型（約 600 MB）…"))
        if LocalTranslator(lambda m: print(m)).load():
            print(T("離線翻譯可以使用"))
        else:
            print(T("離線翻譯模型下載失敗，翻譯會改用網路（詳情見 log.txt）"))
        return 0
    print(T("模型載入失敗，詳情請看："), LOG_PATH)
    return 1


def main():
    if "--download" in sys.argv:
        sys.exit(preload())
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:
        pass
    sock = acquire_single_instance()
    if sock is None:      # 已經在執行了，叫出它的控制面板就好
        return
    log("==== start ====")
    try:
        App(sock).run()
    except Exception:
        log("fatal", traceback.format_exc())
        try:
            from tkinter import messagebox
            messagebox.showerror(T("即時字幕"), T("程式發生錯誤，詳情請看：\n") + LOG_PATH)
        except Exception:
            pass
    finally:
        log("==== exit ====")
        os._exit(0)


if __name__ == "__main__":
    main()
