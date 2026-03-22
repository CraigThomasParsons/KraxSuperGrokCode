import os
import time
import subprocess
import shutil

class DesktopX11Driver:
    """
    Driver for automating Desktop Linux (X11) interactions using standard CLI tools.
    Tools used: xdg-open, xdotool, scrot.
    """

    def __init__(self):
        self._check_deps()

    def _check_deps(self):
        deps = ["xdotool", "scrot", "xdg-open", "ydotool"]
        missing = [d for d in deps if not shutil.which(d)]
        if missing:
            raise RuntimeError(f"Missing dependencies for DesktopX11Driver: {', '.join(missing)}")

    def _ydotool_cmd(self, args):
        """Helper to run ydotool with correct socket."""
        env = os.environ.copy()
        env["YDOTOOL_SOCKET"] = "/tmp/.ydotool_socket"
        subprocess.run(["ydotool"] + args, env=env, check=True)

    def open_chat(self, url: str):
        """Opens the URL in the default browser."""
        print(f"[X11] Opening {url}...")
        subprocess.run(["xdg-open", url], check=True)
        # Wait for browser to launch and load
        print("\n[!!!] Please CLICK the browser window if it is not focused [!!!]\n")
        time.sleep(5)

    def focus_input(self):
        """
        Focuses the input area by clicking the bottom-center of the screen.
        This is a robust fallback for when window management is flaky.
        """
        print("[X11] Focusing input via screen click...")
        try:
            # Get screen dimensions
            out = subprocess.check_output(["xdotool", "getdisplaygeometry"]).decode().strip()
            width, height = map(int, out.split())
            
            # Target: Center X, Bottom Y (minus padding for panel/margin)
            # Assuming 1920x1080, we want approx (960, 950)
            target_x = width // 2
            target_y = height - 150 # Lift up to avoid taskbar
            
            # Move mouse using xdotool (usually works for placement)
            subprocess.run(["xdotool", "mousemove", str(target_x), str(target_y)], check=True)
            time.sleep(0.5)
            
            # Click using ydotool (Hardware level injection - more reliable on Wayland/Hybrid)
            # 0xC0 is left button down+up? verification needed. 
            # ydotool click 0xC0 is typical usage for "Left Click"
            self._ydotool_cmd(["click", "0xC0"])
            
            time.sleep(1) # Wait for focus
            
        except Exception as e:
            print(f"[!] focus_input failed: {e}")

    def type_text(self, text: str):
        """Types text directly using xdotool."""
        print(f"[X11] Typing {len(text)} chars...")
        # xdotool type is requested, but we should fallback to ydotool if needed?
        # User requested xdotool typing explicitly in prompt.
        subprocess.run(["xdotool", "type", "--delay", "12", text], check=True)

    def send(self):
        """Sends the message (Press Enter)."""
        print("[X11] Sending...")
        time.sleep(0.5)
        subprocess.run(["xdotool", "key", "Return"], check=True)

    def screenshot(self, path: str):
        """Takes a screenshot using scrot."""
        print(f"[X11] Screenshot -> {path}")
        subprocess.run(["scrot", path], check=True)
