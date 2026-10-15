# Live Captions / 即時字幕

**English** · [中文](#中文說明)

Real-time subtitles for anything your Windows PC plays — videos, meetings, live streams, games.
Live Captions runs in the background, listens to your computer's audio output, detects speech,
recognizes the language automatically, shows subtitles on screen wherever you like, and saves
them to `.srt` / `.txt` files. It can also show a second-language translation.

## Features

- **Captures computer audio, not the microphone** — speakers, wired headphones, Bluetooth headsets,
  HDMI monitors; all playback devices at once. Plugging/unplugging devices is handled automatically.
- **Automatic language detection** with [faster-whisper](https://github.com/SYSTRAN/faster-whisper).
  - NVIDIA GPU: `large-v3-turbo`, with live (in-progress) captions
  - CPU only: `small` model; captions appear after each sentence
- **Translation** to a second language — offline on your own PC (Meta NLLB-200, no rate limits),
  with Microsoft / Google online translation as fallback.
  Show original + translation, translation only, or original only.
- **On-screen overlay**: transparent, always on top, click-through, draggable and resizable,
  works on any monitor.
- **Saves captions** as standard `.srt` subtitle files and timestamped `.txt` transcripts.
- **Runs in the system tray**: desktop icon to launch, tray icon to show the control panel or
  start/stop; optional hotkeys (`Ctrl+Alt+S` start/stop, `Ctrl+Alt+H` show panel).
- **Chinese / English interface**, switchable at any time.

## Requirements

- Windows 10 / 11
- Internet for the first install (about 1–2.5 GB of models are downloaded once)
- Optional: NVIDIA GPU for faster, more accurate recognition

## Installation

1. Download this repository (**Code → Download ZIP**) and extract it to a permanent location,
   e.g. `C:\LiveCaptions`. (If you move the folder later, run `install.bat` again.)
2. Double-click **`install.bat`** and choose **1. English** or **2. 中文** (this also sets the program's interface language). It will then:
   - install Python 3.12 via winget if needed (then ask you to run `install.bat` once more),
   - create a private virtual environment (`venv`) and install the packages,
   - add GPU acceleration if an NVIDIA GPU is found,
   - download the speech and translation models,
   - create a **Live Captions** shortcut on your desktop (optionally also start with Windows).
3. Double-click the desktop shortcut.

To install on another PC, copy the folder (without `venv`) and run `install.bat` there.

## Usage

- On launch, the control panel opens and capturing starts automatically.
- Closing the panel (✕) does **not** quit — the program keeps running in the system tray.
  Click the tray icon to bring the panel back; right-click it to start/stop, open the captions
  folder, or quit.
  - Windows 11 hides tray icons under the **^** arrow. To keep it visible:
    Settings → Personalization → Taskbar → Other system tray icons → turn on *Python*.
- **Move / resize subtitles** in the panel, then drag the subtitle box; drag the blue corner to resize.
- Captions are saved to `Documents\即時字幕\` (one `.srt` + `.txt` pair per session).

### Settings

| Setting | Description |
|---|---|
| Audio source | All playback devices (recommended) or only the default device |
| Spoken language | Auto-detect, or force a language if detection is unreliable |
| Second language | Translation target, or none |
| On-screen display | Original + translation / translation only / original only |
| Translation method | Auto (offline first) / offline / Microsoft / Google |
| Speech model | Auto, or tiny / base / small / medium / large-v3-turbo (restart required) |
| Language | 中文 / English interface |

### Muted audio?

The program records the audio stream *before* it reaches your speakers:
- Windows volume turned down: usually still captured.
- Windows mute: captured on most PCs (a few sound drivers deliver silence).
- The player's own volume at 0 (e.g. YouTube muted): **not** captured — no audio is produced.
- Want captions with no sound at all? Install [VB-CABLE](https://vb-audio.com/Cable/) and set
  "CABLE Input" as your playback device.

## Troubleshooting

- **"Smart App Control blocked a file that may be unsafe"** (Windows 11): files downloaded from the internet
  are marked, and unsigned scripts like `install.bat` are blocked. Before extracting, right-click the ZIP →
  **Properties** → tick **Unblock** → OK, then extract again. For an already extracted folder, open PowerShell
  in it and run `Get-ChildItem -Recurse | Unblock-File`.
  Do **not** turn Smart App Control off — it cannot be turned back on without reinstalling Windows.
- Run **`debug_run.bat`** to see errors in a console window.
- Log file: `%APPDATA%\LiveCaptions\log.txt`
- The level bars next to each audio source show which device is receiving sound.

## Project files

| File | Purpose |
|---|---|
| `app.py` | The program |
| `install.bat` | One-click installer |
| `setup_helper.py` | Icon, model download, shortcuts (called by `install.bat`) |
| `debug_run.bat` | Run with a visible console for troubleshooting |
| `requirements.txt` / `requirements-gpu.txt` | Python packages (GPU extras for NVIDIA) |
| `使用說明.txt` | Detailed user guide (Chinese) |
| `LICENSE` | MIT License |

## Credits & licenses

This project's code is released under the [MIT License](LICENSE). Third-party components keep their own licenses:

- Speech recognition: [faster-whisper](https://github.com/SYSTRAN/faster-whisper) (MIT) with OpenAI Whisper models (MIT)
- Offline translation: [NLLB-200 distilled 600M](https://huggingface.co/facebook/nllb-200-distilled-600M), CTranslate2 conversion
  [`JustFrederik/nllb-200-distilled-600M-ct2-int8`](https://huggingface.co/JustFrederik/nllb-200-distilled-600M-ct2-int8) —
  **CC-BY-NC-4.0 (non-commercial use only)**. The model is downloaded at install time, not included in this repository.
- Audio capture: [soundcard](https://github.com/bastibe/SoundCard), [PyAudioWPatch](https://github.com/s0d3s/PyAudioWPatch)
- Online translation fallbacks use the public Microsoft Edge and Google Translate endpoints, which may be rate-limited.

---

## 中文說明

在背景擷取電腦**播放出來的聲音**（影片、會議、直播、遊戲），偵測到有人說話時，自動判斷語言並轉成字幕，
顯示在螢幕上你指定的位置，同時存成 `.srt` / `.txt` 字幕檔，也可以加上第二語言翻譯。

### 功能

- **錄電腦播放的聲音，不是麥克風**：喇叭、有線耳機、藍牙耳機、HDMI 螢幕同時錄；插拔裝置自動跟上。
- **自動辨識語言**（faster-whisper）：有 NVIDIA 顯示卡用 `large-v3-turbo`，字幕邊說邊出現；只有 CPU 用 `small`，說完一句才出現。
- **第二語言翻譯**：預設在自己電腦上離線翻譯（Meta NLLB-200，沒有次數限制），不行時改用微軟／Google 網路翻譯。
  可選擇「原文＋翻譯」、「只顯示翻譯」或「只顯示原文」。
- **螢幕字幕**：透明、永遠在最上層、滑鼠可穿透、可拖曳與調整大小、可放在任何螢幕。
- **自動存檔**：標準 `.srt` 字幕檔和含時間的 `.txt` 文字檔。
- **背景執行**：桌面圖示啟動，右下角工作列圖示叫出控制面板或開始／停止；可用快速鍵 `Ctrl+Alt+S`、`Ctrl+Alt+H`。
- **中文／English 介面**隨時切換。

### 安裝

1. 下載本專案（**Code → Download ZIP**），解壓縮到固定位置，例如 `C:\LiveCaptions`（之後搬動資料夾要重跑一次 `install.bat`）。
2. 點兩下 **`install.bat`**，先選 **2. 中文**（也會設定程式介面的語言），接著沒有 Python 會自動安裝（裝完再點一次）、安裝元件、偵測 NVIDIA 顯示卡、下載模型、建立桌面捷徑。
3. 點兩下桌面的「即時字幕」。

其他電腦：把資料夾（不含 `venv`）複製過去，在那台電腦上跑 `install.bat`。

### 使用

- 打開後出現控制面板並自動開始錄製；按 ✕ 只會縮到右下角工作列，不會結束。
- Windows 11 的工作列圖示預設藏在「^」裡：設定 → 個人化 → 工作列 → 其他系統匣圖示 → 打開「Python」。
- 「調整字幕位置／大小」後直接拖曳字幕框，拖右下角藍色方塊調整大小。
- 字幕檔存在「文件\即時字幕」。
- 詳細說明請看 [`使用說明.txt`](使用說明.txt)。

### 疑難排解

- **「智慧應用程式控制已封鎖可能不安全的檔案」**（Windows 11）：從網路下載的檔案會被加上標記，沒有簽章的 `install.bat` 因此被擋。
  解壓縮**前**，在 ZIP 檔按右鍵 →「內容」→ 勾選「**解除封鎖**」→ 確定，再重新解壓縮。
  已解壓縮的資料夾：在資料夾中開啟 PowerShell，執行 `Get-ChildItem -Recurse | Unblock-File`。
  **不要**關閉「智慧應用程式控制」，關掉後必須重灌 Windows 才能再開啟。
- 出問題時點兩下 `debug_run.bat` 查看錯誤訊息；紀錄檔在 `%APPDATA%\LiveCaptions\log.txt`。

### 授權

本專案程式碼採用 [MIT 授權](LICENSE)，可自由使用、修改與分享。
離線翻譯模型 NLLB-200 的授權為 **CC-BY-NC-4.0（僅限非商業使用）**；模型在安裝時下載，不包含在本專案中。
語音辨識使用 faster-whisper 與 OpenAI Whisper 模型（MIT）。
