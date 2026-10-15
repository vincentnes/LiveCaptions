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
    "      建立捷徑失敗。可以自己建立：在桌面按右鍵 → 新增 → 捷徑，位置貼上下面這一行：":
        "      Could not create the shortcut. To create it yourself: right-click the desktop -> New -> Shortcut, and paste this line as the location:",
    "原因：": "Reason: ",
    "要不要讓它「開機後自動在背景執行」？ (y = 要 / 直接按 Enter = 不要)：":
        "Start automatically in the background when Windows starts? (y = yes / Enter = no): ",
    "      已設定開機自動執行（不想要時，刪除「啟動」資料夾裡的捷徑即可）":
        "      Autostart enabled (to undo, delete the shortcut in your Startup folder)",
    " 安裝完成！到桌面點兩下「{name}」即可使用": " Setup complete! Double-click \"{name}\" on your desktop to start",
    "即時字幕：電腦聲音自動轉字幕": "Live Captions: real-time subtitles for your computer's audio",
})


def ps_quote(s):
    return "'" + s.replace("'", "''") + "'"


def special_folder_path(which):
    """Real path of the Desktop / Startup folder (also works when Desktop is moved to OneDrive)."""
    import ctypes
    from ctypes import wintypes
    guids = {
        "Desktop": "{B4BFCC3A-DB2C-424C-B029-7FE99A87C641}",
        "Startup": "{B97D20BB-F46A-4C97-BA10-5E3608430854}",
    }
    try:
        class GUID(ctypes.Structure):
            _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD),
                        ("Data3", wintypes.WORD), ("Data4", ctypes.c_ubyte * 8)]
        g = GUID()
        ctypes.windll.ole32.CLSIDFromString(ctypes.c_wchar_p(guids[which]), ctypes.byref(g))
        out = ctypes.c_wchar_p()
        if ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(g), 0, None, ctypes.byref(out)) == 0:
            path = out.value
            ctypes.windll.ole32.CoTaskMemFree(out)
            if path:
                return path
    except Exception as e:
        app.log("SHGetKnownFolderPath failed", which, repr(e))
    if which == "Desktop":
        return os.path.join(os.path.expanduser("~"), "Desktop")
    return os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup")


def _shortcut_comtypes(lnk, target, args, workdir, icon, desc):
    # Creates the .lnk directly through the Windows Shell API.
    # Not affected by PowerShell's restricted mode (Smart App Control / WDAC).
    import comtypes
    import comtypes.client
    from comtypes.shelllink import ShellLink, IShellLinkW
    from comtypes.persist import IPersistFile
    comtypes.CoInitialize()
    link = comtypes.client.CreateObject(ShellLink, interface=IShellLinkW)
    link.SetPath(target)
    link.SetArguments(args)
    link.SetWorkingDirectory(workdir)
    if os.path.exists(icon):
        link.SetIconLocation(icon, 0)
    link.SetDescription(desc)
    link.QueryInterface(IPersistFile).Save(lnk, True)


def _shortcut_powershell(lnk, target, args, workdir, icon, desc):
    ps = (
        f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut({ps_quote(lnk)});"
        f"$s.TargetPath={ps_quote(target)};"
        f"$s.Arguments={ps_quote(args)};"
        f"$s.WorkingDirectory={ps_quote(workdir)};"
        f"$s.IconLocation={ps_quote(icon)};"
        f"$s.Description={ps_quote(desc)};"
        f"$s.Save()"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout or "").strip()[:300])


def make_shortcut(special_folder, name):
    target = os.path.join(HERE, "venv", "Scripts", "pythonw.exe")
    script = os.path.join(HERE, "app.py")
    icon = os.path.join(HERE, "icon.ico")
    args = chr(34) + script + chr(34)
    desc = T("即時字幕：電腦聲音自動轉字幕")
    folder = special_folder_path(special_folder)
    os.makedirs(folder, exist_ok=True)
    lnk = os.path.join(folder, name + ".lnk")
    errors = []
    for method in (_shortcut_comtypes, _shortcut_powershell):
        try:
            method(lnk, target, args, workdir=HERE, icon=icon, desc=desc)
            if os.path.exists(lnk):
                return True
            errors.append(f"{method.__name__}: file not created")
        except Exception as e:
            errors.append(f"{method.__name__}: {e!r}")
    app.log("shortcut failed:", lnk, " | ".join(errors))
    print("      " + T("原因：") + errors[0][:200])
    return False


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
        print(T("      建立捷徑失敗。可以自己建立：在桌面按右鍵 → 新增 → 捷徑，位置貼上下面這一行："))
        print("      " + chr(34) + os.path.join(HERE, "venv", "Scripts", "pythonw.exe") + chr(34)
              + " " + chr(34) + os.path.join(HERE, "app.py") + chr(34))

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
