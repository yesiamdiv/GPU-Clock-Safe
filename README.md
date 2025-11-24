# GPU Clock Safe

<!-- ![GPU Clock Safe](https://github.com/yesiamdiv/GPU-Clock-Safe/assets/icon.ico)   -->
*A lightweight Windows tray app that locks your NVIDIA GPU core clock to safe values — preventing Ollama / LLM crashes on laptops when overclocked (in my case that is).*

[![Windows](https://img.shields.io/badge/platform-Windows-blue?logo=windows)](https://github.com/yourusername/gpu-clock-safe)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
[![Downloads](https://img.shields.io/github/downloads/yesiamdiv/GPU-Clock-Safe/total)](https://github.com/yesiamdiv/GPU-Clock-Safe)

---

### Features

- **One-click GPU clock locking** via `nvidia-smi` (`-lgc`)
- **Three safe presets**:
  - Normal (Battery-safe: ~900 MHz)
  - Balanced (Stable max: ~1200 MHz) ← **recommended**
  - Boost (Risky: up to 1600+ MHz — blocked on battery)
- **System tray icon** with right-click menu
- **Global hotkeys** (`Ctrl+Alt+1/2/3`)
- **Auto temperature governor** (toggleable)
- **Battery detection** → blocks Boost mode automatically
- **Temperature safety checks** before allowing Boost
- **Full settings editor** (MHz values, thresholds, icon)
- **Custom tray icon support** (PNG → preview + apply)
- **Safe clock restore on exit**
- **Auto-start on login** (optional)
- **Windows toast notifications**
- **Admin auto-elevation** (UAC prompt on launch)
- **Single portable EXE** (no install needed) or optional installer

---

### Screenshots


| Main Window | Tray Menu | Settings Editor |
|-------------|-----------|-----------------|
| ![Main](https://github.com/yesiamdiv/GPU-Clock-Safe/blob/main/assets/main-window.png) | ![Tray](https://github.com/yesiamdiv/GPU-Clock-Safe/blob/main/assets/setting-editor.png) | ![Settings](https://github.com/yesiamdiv/GPU-Clock-Safe/blob/main/assets/tray-menu.png) |

---

### Installation

#### Option 1: Portable EXE (Recommended)
Download the latest release from [Releases](https://github.com/yesiamdiv/GPU-Clock-Safe/releases):
```
GPU Clock Safe.exe
```
Double-click → accept UAC → done.

#### Option 2: Installer (Full Setup) // NOT IMPLEMENTED YET
Download:
```
GPUClockSafeInstaller.exe
```
Includes Start Menu shortcut and optional startup launch.

#### Option 3: Build from Source
```bash
git clone https://github.com/yesiamdiv/GPU-Clock-Safe.git
cd GPU-Clock-Safe
pip install -r requirements.txt
python -m venv venv
venv\Scripts\activate
python gpu_clock_safe.py
```

To build EXE:
```bash
pip install pyinstaller
pyinstaller --noconsole --onefile --icon=assets/icon.ico --name "GPU Clock Safe" gpu_clock_safe.py
```

---

### Recommended Settings (For RTX 3050 4GB VRAM Laptop & Similar)

| Mode           | Core Clock | Safe For         | Recommendation       |
|----------------|------------|------------------|----------------------|
| Normal         | 900 MHz    | Battery + Safety | Always safe          |
| Balanced       | 1200 MHz   | Daily use        | Best balance         |
| Boost          | 1600 MHz   | Only if cool     | Blocked on battery   |

**Pro tip**: Enable **Auto Temperature Mode** → app will automatically downclock if GPU gets too hot.

---

### Compatibility

- Windows 10 / 11 (64-bit)
- NVIDIA GPUs with `nvidia-smi` support (GeForce, RTX, Quadro)
- Tested on: ASUS TUF A15 (RTX 3050), Legion 5, Acer Nitro, etc.
- Works even if you don’t use Ollama — great for Stable Diffusion, mining, or any CUDA app

---

### Known Limitations

- Requires **Administrator privileges** (auto-requested)
- Only controls **core clock** (memory clock locking coming soon)
- Does **not** work on AMD or Intel GPUs
- Some antivirus may flag PyInstaller EXEs (false positive)

---

### Why I Built This

When running local AI models (Ollama, LM Studio, etc.) on my laptop with an **RTX 3050**.  
On battery everything is rock-solid. The moment I plug in the charger the models start crashing during loading or inference with cryptic CUDA errors.

After digging around I found the cause: when the laptop is on AC power the RTX 3050 aggressively boosts well past ~1600 MHz. On my particular card the CUDA kernel would crash.

Power-plan tweaking wouldnt fixe it.  
The only reliable workaround is to cap the core clock at a value the card can actually sustain under load.

That’s exactly what **GPU Clock Safe** does:  
- locks the GPU to a safe clock when you want stability  
- lets you switch to a higher “boost” clock when you need the extra performance and are willing to keep an eye on temps  
- automatically falls back to safe clocks if the GPU gets too hot  
- restores stock clocks on exit

Simple, tiny, works perfectly.

---

### Contributing

Pull requests are welcome! Especially:
- Memory clock locking (`-lmc`)
- Dark mode UI
- Per-game profiles
- Power limit control (`-pl`)
- Linux version (using `nvidia-settings`)

---

### License

[MIT License](LICENSE) — feel free to fork, modify, and share.

---

### Thank You

This tool saved my sanity.  
If it helps even one person avoid hours of debugging "CUDA error" crashes — it was worth it.

Made with frustration, coffee, and love by **iamdiv**

---
