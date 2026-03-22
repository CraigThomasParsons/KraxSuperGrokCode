import subprocess
import shutil

def take_screenshot(filepath: str):
    """
    Takes a screenshot and saves it to filepath.
    Prefers grim (Wayland), falls back to spectacle (KDE), then scrot (X11).
    """
    if shutil.which("grim"):
        try:
            subprocess.run(["grim", filepath], check=True)
            return
        except subprocess.CalledProcessError:
            print("Warning: grim failed, trying fallback...")

    if shutil.which("spectacle"):
        try:
            # KDE spectacle: -b (background), -n (non-notify), -o (output)
            subprocess.run(["spectacle", "-b", "-n", "-o", filepath], check=True)
            return
        except subprocess.CalledProcessError:
             print("Warning: spectacle failed, trying fallback...")

    if shutil.which("scrot"):
        subprocess.run(["scrot", filepath], check=True)
        return

    raise RuntimeError("No suitable screenshot tool found (grim or scrot needed).")
