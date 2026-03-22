# Piper Phase 2 Setup & Testing Instructions

## 1. Install Dependencies

Ensure you have the required system tools installed.

```bash
# Arch / CachyOS
sudo pacman -S wl-clipboard ydotool grim xorg-xinit xdotool scrot python
# Note: ydotool may require starting the daemon:
# sudo systemctl enable --now ydotool
# Add yourself to input group if needed:
# sudo usermod -aG input $USER
```

## 2. Verify File Structure

Ensure the following files exist (created by this agent):

- `Piper/bin/piper_proxy.py`
- `Piper/bin/lib/fs.py`
- `Piper/bin/drivers/desktop_x11.py`
- `Piper/systemd/piper-proxy.service`
- `Piper/systemd/piper-proxy.path`

## 3. Enable Systemd Units

Link and enable the user units.

```bash
mkdir -p ~/.config/systemd/user
ln -sf ~/Code/Piper/systemd/piper-proxy.service ~/.config/systemd/user/
ln -sf ~/Code/Piper/systemd/piper-proxy.path ~/.config/systemd/user/

systemctl --user daemon-reload
systemctl --user enable --now piper-proxy.path
```

## 4. Manual Test Run (Driver Mode)

This version uses a "Blind Click" to focus the browser.

**CRITICAL PREREQUISITE:**

1. Open your default browser (Firefox/Chrome).
2. **Maximize** the window.
3. Ensure the ChatGPT input box is near the bottom-center of the screen.
4. Ensure your terminal does **NOT** cover the bottom-center of the screen (move it to the side or top).

**Run the Proxy:**

```bash
python3 bin/piper_proxy.py --once
```

**What should happen:**

- Links open via `xdg-open`.
- Mouse moves to bottom-center and clicks.
- "Briefing" is typed directly (no clipboard).
- Screenshot is taken.

## 5. Troubleshooting

- **Typed in Terminal?**: This means the "Blind Click" focused your terminal instead of the browser. **Move your terminal window aside!**
- **Input fails**: Verify `xdotool` is installed (`sudo pacman -S xdotool`).
- **Screenshot black/empty?**: On Wayland/KDE, ensure `spectacle` is installed or fallback to `scrot` on X11.
