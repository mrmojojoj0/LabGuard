import subprocess
import time
import win32gui
import win32process
import pyautogui

p = subprocess.Popen([
    "winget", "uninstall",
    "--id", "Mozilla.Firefox",
    "--exact"
])

print("Waiting for confirmation...")

confirmed = False

for _ in range(60):
    def check(hwnd, _):
        global confirmed

        if confirmed or not win32gui.IsWindowVisible(hwnd):
            return

        title = win32gui.GetWindowText(hwnd)
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        print(f"Window: {title}, PID: {pid}")
        if pid == p.pid and any(
            word in title.lower()
            for word in ["firefox", "uninstall"]
        ):
            print("Detected:", title)
            pyautogui.press("left")
            pyautogui.press("enter")
            confirmed = True

    win32gui.EnumWindows(check, None)

    if confirmed or p.poll() is not None:
        break

    time.sleep(1)

print("Exit code:", p.wait() if p.poll() is None else p.returncode)