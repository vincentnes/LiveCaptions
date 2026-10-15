# -*- coding: utf-8 -*-
"""Called by install.bat: makes the icon, downloads the models and creates the desktop shortcut.
install.bat 會呼叫這個檔：做圖示、下載模型、建立桌面捷徑。"""
import os
import sys
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import app  # noqa: E402

def _chosen_lang():
    """Language picked in install.bat (--lang en / --lang zh); saved so the app uses it too."""
    if "--lang" in sys.argv:
        i = sys.argv.index("--lang")
        if i + 1 < len(sys.argv) and sys.argv[i + 1] in ("en", "zh"):
            code = sys.argv[i + 1]
            cfg = app.load_config()
            cfg["ui_lang"] = code
            app.save_config(cfg)
            return code
    return app.load_config().get("ui_lang", "auto")


app.set_ui_lang(_chosen_lang())
T = app.T

app.EN.update({
    "[1/3] 製作圖示…": "[1/3] Creating icon...",
    "[2/3] 下載語音辨識模型（有 NVIDIA 約 1.6 GB，沒有約 0.5 GB）…":
        "[2/3] Downloading the speech model (about 1.6 GB with an NVIDIA GPU, 0.5 GB without)...",
    "[3/3] 建立桌面捷徑「{name}」…": "[3/3] Creating desktop shortcut \"{name}\"...",
    "      完成！": "      Done!",
    "      建立捷徑失敗，可以直接對 app.py 按右鍵 → 開啟方式 → venv\\Scripts\\pythonw.exe":
        "      Could not create the shortcut. You can right-click app.py -> Open with -> venv\\Scripts\\pythonw.exe",
    "要不要讓它「開機後自動在背景執行」？ (y = 要 / 直接按 Enter = 不要)：":
        "Start automatically in the background when Windows starts? (y = yes / Enter = no): ",
    "      已設定開機自動執行（不想要時，刪除「啟動」資料夾裡的捷徑即可）":
        "      Autostart enabled (to undo, delete the shortcut in your Startup folder)",
    " 安裝完成！到桌面點兩下「{name}」即可使用": " Setup complete! Double-click \"{name}\" on your desktop to start",
    "即時字幕：電腦聲音自動轉字幕": "Live Captions: real-time subtitles for your computer's audio",
})


def ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def make_shortcut(special_folder, name):
    target = os.path.join(HERE, "venv", "Scripts", "pythonw.exe")
    script = os.path.join(HERE, "app.py")
    icon = os.path.join(HERE, "icon.ico")
    ps = (
        f"$d=[Environment]::GetFolderPath({ps_quote(special_folder)});"
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d {ps_quote(name + '.lnk')}));"
        f"$s.TargetPath={ps_quote(target)};"
        f"$s.Arguments={ps_quote(chr(34) + script + chr(34))};"
        f"$s.WorkingDirectory={ps_quote(HERE)};"
        f"$s.IconLocation={ps_quote(icon)};"
        f"$s.Description={ps_quote(T('即時字幕：電腦聲音自動轉字幕'))};"
        f"$s.Save()"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps])
    return r.returncode == 0


def main():
    name = T("即時字幕")          # shortcut name: 即時字幕 / Live Captions
    print()
    print(T("[1/3] 製作圖示…"))
    img = app.make_icon_image(False, 256)
    img.save(os.path.join(HERE, "icon.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])

    print(T("[2/3] 下載語音辨識模型（有 NVIDIA 約 1.6 GB，沒有約 0.5 GB）…"))
    app.preload()

    print()
    print(T("[3/3] 建立桌面捷徑「{name}」…").format(name=name))
    if make_shortcut("Desktop", name):
        print(T("      完成！"))
    else:
        print(T("      建立捷徑失敗，可以直接對 app.py 按右鍵 → 開啟方式 → venv\\Scripts\\pythonw.exe"))

    print()
    ans = input(T("要不要讓它「開機後自動在背景執行」？ (y = 要 / 直接按 Enter = 不要)：")).strip().lower()
    if ans in ("y", "yes", "要"):
        if make_shortcut("Startup", name):
            print(T("      已設定開機自動執行（不想要時，刪除「啟動」資料夾裡的捷徑即可）"))

    print()
    print("========================================")
    print(T(" 安裝完成！到桌面點兩下「{name}」即可使用").format(name=name))
    print("========================================")


if __name__ == "__main__":
    main()
