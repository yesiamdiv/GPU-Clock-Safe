"""
GPU Clock Safe - GPUClockSafe
Single-file Tk/Tkinter + pystray tray app that controls nvidia-smi clocks,
supports tray, notifications, hotkeys, auto-temp mode, settings edit UI,
startup-on-boot, safe restore on exit, and admin auto-elevation.

Requirements (pip):
  pip install pystray pillow psutil pynvml win10toast keyboard pyinstaller

Notes:
- The app needs ADMIN privileges for nvidia-smi clock locking.
- If pynvml is missing or nvidia-smi not found, app will still run in CPU-only mode
  and expose the GUI and safe modes (but nvidia commands will display errors).
"""

import os
import sys
import json
import time
import threading
import subprocess
import ctypes
import tkinter as tk
from tkinter import filedialog, messagebox
from tkinter import ttk
from pathlib import Path
from PIL import Image, ImageTk
import logging

# third-party libs
try:
    import psutil
except Exception:
    psutil = None

try:
    import pynvml
    PYNVML_AVAILABLE = True
except Exception:
    pynvml = None
    PYNVML_AVAILABLE = False

try:
    from win10toast import ToastNotifier
    TOASTER_AVAILABLE = True
except Exception:
    TOASTER_AVAILABLE = False

try:
    import pystray
    from pystray import MenuItem as Item, Menu as Menu
    PYSTRAY_AVAILABLE = True
except Exception:
    pystray = None
    PYSTRAY_AVAILABLE = False

try:
    import keyboard  # for global hotkeys
    KEYBOARD_AVAILABLE = True
except Exception:
    keyboard = None
    KEYBOARD_AVAILABLE = False

APP_NAME = "GPU Clock Safe"
SETTINGS_FILE = Path.home() / ".gpu_clock_safe_settings.json"
LOG_FILE = Path.home() / "gpu_clock_safe.log"

# Setup logging
logging.basicConfig(filename=str(LOG_FILE), level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(APP_NAME)

# Default settings
DEFAULT_SETTINGS = {
    "stable_mhz": 1200,
    "boost_mhz": 1600,
    "battery_mhz": 900,
    "memory_mhz": None,  # optional; not used by default
    "temp_threshold_boost": 70,
    "temp_threshold_balanced": 80,
    "temp_threshold_force_normal": 85,
    "auto_temp_mode": False,
    "start_on_boot": False,
    "show_notifications": True,
    "icon_path": None,
    "hotkeys_enabled": True
}

# Global state
settings = {}
tray_icon = None
toaster = None
stop_event = threading.Event()
nvml_handle = None
current_mode = None
elevated = False


# -------------------------
# Utility functions
# -------------------------
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except Exception:
        return False


def relaunch_as_admin():
    """Relaunch the current python interpreter elevated."""
    if is_admin():
        return True
    # Build the command line
    params = " ".join([f'"{x}"' for x in sys.argv])
    try:
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return False
    except Exception as e:
        logger.exception("Failed to elevate: %s", e)
        return False


def load_settings():
    global settings
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except Exception:
            settings = DEFAULT_SETTINGS.copy()
    else:
        settings = DEFAULT_SETTINGS.copy()
        save_settings()
    # ensure defaults present
    for k, v in DEFAULT_SETTINGS.items():
        settings.setdefault(k, v)
    logger.info("Settings loaded: %s", settings)


def save_settings():
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        logger.info("Settings saved")
    except Exception as e:
        logger.exception("Failed to save settings: %s", e)


def notify(title, msg):
    if settings.get("show_notifications", True) and TOASTER_AVAILABLE:
        try:
            global toaster
            if toaster is None:
                toaster = ToastNotifier()
            toaster.show_toast(title, msg, threaded=True, icon_path=settings.get("icon_path") or None, duration=4)
        except Exception:
            logger.exception("Notification failed")
    else:
        logger.info("Notification: %s - %s", title, msg)


# -------------------------
# NVIDIA / nvidia-smi helpers
# -------------------------
def run_cmd(cmd):
    try:
        out = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, text=True)
        return out
    except subprocess.CalledProcessError as e:
        logger.warning("Command failed [%s]: %s", cmd, e.output)
        return None
    except FileNotFoundError:
        logger.warning("Command not found: %s", cmd)
        return None


def nvidia_smi_available():
    return run_cmd("nvidia-smi -L") is not None


def set_gpu_clock(core_mhz):
    # Note: -lgc expects min,max; we set same same for locking
    cmd = f'nvidia-smi -lgc {core_mhz},{core_mhz}'
    out = run_cmd(cmd)
    if out is None:
        notify("GPUClockSafe", f"Failed to set clock to {core_mhz} MHz (nvidia-smi failed)")
        return False
    logger.info("Set GPU clock to %d MHz", core_mhz)
    return True


def restore_gpu_defaults():
    run_cmd("nvidia-smi -rgc")
    run_cmd("nvidia-smi -rac")
    logger.info("Restored GPU clock defaults")
    notify("GPUClockSafe", "GPU clocks restored to defaults")


def get_gpu_temp():
    # Try NVML first for better accuracy
    if PYNVML_AVAILABLE:
        try:
            if nvml_handle is None:
                pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            temp = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
            return int(temp)
        except Exception:
            logger.exception("pynvml read failed")
    # Fallback to nvidia-smi query
    out = run_cmd('nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits')
    if out:
        try:
            return int(out.strip().splitlines()[0].strip())
        except Exception:
            logger.exception("nvidia-smi parsing failed")
    return None


def get_vram_total():
    out = run_cmd('nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits')
    if out:
        try:
            val = int(out.strip().splitlines()[0].strip())
            # value in MiB -> convert to GiB approx
            return val // 1024
        except Exception:
            logger.exception("Failed parsing vram")
    return None


def is_on_ac_power():
    if psutil is None:
        return True
    bat = psutil.sensors_battery()
    if bat is None:
        # Desktop or unknown; assume AC
        return True
    return bool(bat.power_plugged)


# -------------------------
# Mode control
# -------------------------
def set_mode_normal():
    global current_mode
    mhz = settings.get("battery_mhz", DEFAULT_SETTINGS["battery_mhz"])
    ok = set_gpu_clock(mhz)
    if ok:
        current_mode = "Normal"
        notify(APP_NAME, f"Switched to Normal mode ({mhz} MHz)")
    return ok


def set_mode_balanced():
    global current_mode
    mhz = settings.get("stable_mhz", DEFAULT_SETTINGS["stable_mhz"])
    ok = set_gpu_clock(mhz)
    if ok:
        current_mode = "Balanced"
        notify(APP_NAME, f"Switched to Balanced mode ({mhz} MHz)")
    return ok


def set_mode_boost(force=False):
    global current_mode
    # safety checks: battery / temp
    if not force and not is_on_ac_power():
        notify(APP_NAME, "Boost mode blocked: running on battery")
        logger.info("Boost blocked on battery")
        return False
    # temp checks
    temp = get_gpu_temp()
    if temp is not None:
        thr = settings.get("temp_threshold_boost", DEFAULT_SETTINGS["temp_threshold_boost"])
        if temp >= thr:
            notify(APP_NAME, f"Boost blocked: GPU temp {temp}°C >= {thr}°C")
            logger.info("Boost blocked due to temp: %d >= %d", temp, thr)
            return False
    mhz = settings.get("boost_mhz", DEFAULT_SETTINGS["boost_mhz"])
    ok = set_gpu_clock(mhz)
    if ok:
        current_mode = "Boost"
        notify(APP_NAME, f"Switched to Boost mode ({mhz} MHz)")
    return ok


# -------------------------
# Auto-temp thread
# -------------------------
def auto_temp_loop():
    logger.info("Auto-temp thread started")
    while not stop_event.is_set():
        try:
            if settings.get("auto_temp_mode", False):
                temp = get_gpu_temp()
                if temp is None:
                    # cannot read temp, skip
                    time.sleep(5)
                    continue
                t_boost = settings.get("temp_threshold_boost", 70)
                t_bal = settings.get("temp_threshold_balanced", 80)
                t_force = settings.get("temp_threshold_force_normal", 85)
                ac = is_on_ac_power()
                # Logic: highest priority: forced normal if > force threshold
                if temp >= t_force:
                    if current_mode != "Normal":
                        set_mode_normal()
                elif temp >= t_bal:
                    if current_mode != "Balanced":
                        set_mode_balanced()
                else:
                    # temp < t_boost, and only allow boost if AC
                    if ac and temp < t_boost:
                        if current_mode != "Boost":
                            set_mode_boost(force=True)
                    else:
                        if current_mode != "Balanced":
                            set_mode_balanced()
            time.sleep(5)
        except Exception:
            logger.exception("Auto-temp loop exception")
            time.sleep(5)
    logger.info("Auto-temp thread exiting")


# -------------------------
# Hotkeys
# -------------------------
def hotkey_worker():
    if not KEYBOARD_AVAILABLE:
        logger.info("Global hotkeys not available (keyboard module missing)")
        return
    logger.info("Hotkey thread starting")
    try:
        # Only register if enabled
        if settings.get("hotkeys_enabled", True):
            # Ctrl+Alt+1 -> Normal
            keyboard.add_hotkey('ctrl+alt+1', lambda: set_mode_normal())
            # Ctrl+Alt+2 -> Balanced
            keyboard.add_hotkey('ctrl+alt+2', lambda: set_mode_balanced())
            # Ctrl+Alt+3 -> Boost
            keyboard.add_hotkey('ctrl+alt+3', lambda: set_mode_boost())
            logger.info("Hotkeys registered")
            # block until stop_event is set
            while not stop_event.is_set():
                time.sleep(0.1)
            keyboard.unhook_all_hotkeys()
    except Exception:
        logger.exception("Hotkey worker failed")
    logger.info("Hotkey thread exiting")


# -------------------------
# Tray & GUI
# -------------------------
class MainApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_NAME)
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)  # hide instead of quit
        self.root.geometry("520x340")
        self.icon_image = None
        self.setup_ui()
        self.tray_thread = None
        self.tray_icon = None
        self.tray_running = False

    def setup_ui(self):
        # Top menu: Edit
        menubar = tk.Menu(self.root)
        editmenu = tk.Menu(menubar, tearoff=0)
        editmenu.add_command(label="Settings", command=self.open_settings_window)
        editmenu.add_command(label="Choose Icon", command=self.choose_icon)
        editmenu.add_separator()
        editmenu.add_command(label="Exit & Restore Clocks", command=self.exit_and_restore)
        menubar.add_cascade(label="Edit", menu=editmenu)
        self.root.config(menu=menubar)

        # Main controls
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        lbl = ttk.Label(frm, text="GPU Clock Safe", font=("Segoe UI", 18, "bold"))
        lbl.pack(pady=(0, 10))

        # Current mode label
        self.mode_var = tk.StringVar(value="Unknown")
        ttk.Label(frm, textvariable=self.mode_var, font=("Segoe UI", 12)).pack()

        btn_frame = ttk.Frame(frm)
        btn_frame.pack(pady=12, fill="x")

        ttk.Button(btn_frame, text="Normal Mode (battery-safe)", command=self.on_normal).pack(fill="x", padx=6, pady=6)
        ttk.Button(btn_frame, text="Balanced Mode (stable)", command=self.on_balanced).pack(fill="x", padx=6, pady=6)
        ttk.Button(btn_frame, text="Boost Mode (risky)", command=self.on_boost).pack(fill="x", padx=6, pady=6)

        # options
        self.auto_temp_var = tk.BooleanVar(value=settings.get("auto_temp_mode", False))
        chk = ttk.Checkbutton(frm, text="Enable auto temperature mode", variable=self.auto_temp_var,
                              command=self.on_toggle_auto_temp)
        chk.pack(pady=8)

        self.startup_var = tk.BooleanVar(value=settings.get("start_on_boot", False))
        chk2 = ttk.Checkbutton(frm, text="Start on login", variable=self.startup_var,
                               command=self.on_toggle_startup)
        chk2.pack(pady=2)

        self.notif_var = tk.BooleanVar(value=settings.get("show_notifications", True))
        chk3 = ttk.Checkbutton(frm, text="Show notifications", variable=self.notif_var, command=self.on_toggle_notif)
        chk3.pack(pady=2)

        # icon preview
        ttk.Separator(frm).pack(fill="x", pady=10)
        ip_frame = ttk.Frame(frm)
        ip_frame.pack(fill="x")
        ttk.Label(ip_frame, text="Tray icon preview:").pack(side="left", padx=(6, 12))
        self.icon_label = ttk.Label(ip_frame)
        self.icon_label.pack(side="left")

        self.update_mode_label()
        self.load_icon_preview()

        # bottom: log button
        ttk.Button(frm, text="Open log file", command=lambda: os.startfile(LOG_FILE)).pack(side="bottom", pady=6)

    def update_mode_label(self):
        self.mode_var.set(f"Mode: {current_mode or 'Unknown'}")

    def load_icon_preview(self):
        p = settings.get("icon_path")
        if p and os.path.exists(p):
            try:
                img = Image.open(p).resize((32, 32), Image.LANCZOS)
                self.icon_image = ImageTk.PhotoImage(img)
                self.icon_label.config(image=self.icon_image)
            except Exception:
                self.icon_label.config(text="(invalid icon)")
        else:
            self.icon_label.config(text="(no icon)")

    def open_settings_window(self):
        w = tk.Toplevel(self.root)
        w.title("Settings")
        w.geometry("420x360")
        w.transient(self.root)

        def add_row(parent, label_text, var):
            row = ttk.Frame(parent)
            ttk.Label(row, text=label_text, width=28, anchor="w").pack(side="left")
            ent = ttk.Entry(row, textvariable=var, width=12)
            ent.pack(side="left", padx=8)
            row.pack(pady=6, padx=12, anchor="w")
            return ent

        s = settings  # alias
        stable_var = tk.IntVar(value=s.get("stable_mhz"))
        boost_var = tk.IntVar(value=s.get("boost_mhz"))
        battery_var = tk.IntVar(value=s.get("battery_mhz"))
        temp_boost_var = tk.IntVar(value=s.get("temp_threshold_boost"))
        temp_bal_var = tk.IntVar(value=s.get("temp_threshold_balanced"))
        temp_force_var = tk.IntVar(value=s.get("temp_threshold_force_normal"))

        add_row(w, "Balanced (stable) core MHz:", stable_var)
        add_row(w, "Boost core MHz:", boost_var)
        add_row(w, "Battery-safe core MHz:", battery_var)
        ttk.Separator(w).pack(fill="x", pady=6)
        add_row(w, "Temp threshold for Boost (°C):", temp_boost_var)
        add_row(w, "Temp threshold for Balanced (°C):", temp_bal_var)
        add_row(w, "Temp threshold force Normal (°C):", temp_force_var)

        def save_and_close():
            s["stable_mhz"] = int(stable_var.get())
            s["boost_mhz"] = int(boost_var.get())
            s["battery_mhz"] = int(battery_var.get())
            s["temp_threshold_boost"] = int(temp_boost_var.get())
            s["temp_threshold_balanced"] = int(temp_bal_var.get())
            s["temp_threshold_force_normal"] = int(temp_force_var.get())
            save_settings()
            self.load_icon_preview()
            w.destroy()
            notify(APP_NAME, "Settings updated")

        ttk.Button(w, text="Save", command=save_and_close).pack(pady=12)

    def choose_icon(self):
        p = filedialog.askopenfilename(title="Choose tray icon PNG (prefer 64x64)", filetypes=[("PNG files", "*.png"), ("All", "*.*")])
        if not p:
            return
        settings["icon_path"] = p
        save_settings()
        self.load_icon_preview()
        # update tray icon if running
        if self.tray_running:
            self._update_tray_icon(p)

    def on_normal(self):
        ok = set_mode_normal()
        self.update_mode_label()
        return ok

    def on_balanced(self):
        ok = set_mode_balanced()
        self.update_mode_label()
        return ok

    def on_boost(self):
        ok = set_mode_boost()
        self.update_mode_label()
        return ok

    def on_toggle_auto_temp(self):
        settings["auto_temp_mode"] = bool(self.auto_temp_var.get())
        save_settings()
        notify(APP_NAME, f"Auto temperature mode {'enabled' if settings['auto_temp_mode'] else 'disabled'}")

    def on_toggle_startup(self):
        want = bool(self.startup_var.get())
        try:
            set_startup(want)
            settings["start_on_boot"] = want
            save_settings()
            notify(APP_NAME, "Startup on login " + ("enabled" if want else "disabled"))
        except Exception as e:
            logger.exception("Startup toggle failed")
            messagebox.showerror("Error", f"Failed to modify startup: {e}")

    def on_toggle_notif(self):
        settings["show_notifications"] = bool(self.notif_var.get())
        save_settings()

    def hide_window(self):
        self.root.withdraw()

    def show_window(self, icon_action=None):
        self.root.deiconify()
        self.root.lift()
        self.root.focus_force()

    # Tray handling
    def _make_icon_image(self):
        ip = settings.get("icon_path")
        if ip and os.path.exists(ip):
            try:
                img = Image.open(ip)
                # pystray wants PIL.Image
                return img
            except Exception:
                logger.exception("Invalid icon image")
        # fallback: create a small icon
        img = Image.new('RGBA', (64, 64), (40, 40, 40, 255))
        return img

    def _update_tray_icon(self, new_path):
        if not PYSTRAY_AVAILABLE or self.tray_icon is None:
            return
        try:
            self.tray_icon.icon = self._make_icon_image()
        except Exception:
            logger.exception("Failed to update tray icon")

    def create_tray(self):
        if not PYSTRAY_AVAILABLE:
            logger.info("pystray not available, skipping tray creation")
            return

        def on_open(_icon, _item):
            self.show_window()

        def on_quit(_icon, _item):
            # stop everything and quit
            stop_app()

        def on_normal_item(_icon, _item):
            set_mode_normal()
            self.update_mode_label()

        def on_bal_item(_icon, _item):
            set_mode_balanced()
            self.update_mode_label()

        def on_boost_item(_icon, _item):
            set_mode_boost()
            self.update_mode_label()

        menu = Menu(
            Item('Open', on_open),
            Item('Normal Mode', on_normal_item),
            Item('Balanced Mode', on_bal_item),
            Item('Boost Mode', on_boost_item),
            Item('---', lambda: None),
            Item('Settings', lambda _i, _j: self.show_window()),
            Item('Exit & Restore', on_quit),
        )
        icon_img = self._make_icon_image()
        self.tray_icon = pystray.Icon("gpu_clock_safe", icon_img, APP_NAME, menu)

        def run_tray():
            self.tray_running = True
            try:
                self.tray_icon.run()
            except Exception:
                logger.exception("Tray thread failed")
            finally:
                self.tray_running = False

        t = threading.Thread(target=run_tray, daemon=True)
        t.start()
        self.tray_thread = t

    def stop_tray(self):
        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except Exception:
            pass

    def exit_and_restore(self):
        if messagebox.askyesno("Exit and restore", "Restore GPU clocks to default and exit?"):
            stop_app()


# -------------------------
# Startup shortcut
# -------------------------
def set_startup(enable):
    # create shortcut in user's startup folder (for current user)
    startup_folder = Path(os.getenv('APPDATA')) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    startup_folder.mkdir(parents=True, exist_ok=True)
    exe_path = Path(sys.executable) if getattr(sys, "frozen", False) else Path(sys.argv[0]).resolve()
    shortcut_path = startup_folder / f"{APP_NAME}.lnk"
    if enable:
        # Use Windows shell via comtypes or power-shell fallback
        try:
            # Try using Python + ctypes COM via winshell (not using extra libs here)
            import pythoncom
            from win32com.shell import shell, shellcon
            shell_link = pythoncom.CoCreateInstance(shell.CLSID_ShellLink, None,
                                                    pythoncom.CLSCTX_INPROC_SERVER, shell.IID_IShellLink)
            shell_link.SetPath(str(exe_path))
            shell_link.SetWorkingDirectory(str(exe_path.parent))
            persist_file = shell_link.QueryInterface(pythoncom.IID_IPersistFile)
            persist_file.Save(str(shortcut_path), 0)
        except Exception:
            # As fallback, write a .bat in startup that launches app
            bat = startup_folder / f"{APP_NAME}.bat"
            with open(bat, "w", encoding="utf-8") as f:
                f.write(f'@echo off\nstart "" "{exe_path}"\n')
            logger.info("Created startup .bat at %s", bat)
    else:
        # remove both potential shortcut and bat
        for p in [shortcut_path, startup_folder / f"{APP_NAME}.bat"]:
            try:
                if p.exists():
                    p.unlink()
                    logger.info("Removed %s", p)
            except Exception:
                logger.exception("Failed to remove startup item %s", p)


# -------------------------
# App lifecycle
# -------------------------
def stop_app():
    logger.info("Stopping app")
    stop_event.set()
    # restore clocks
    try:
        restore_gpu_defaults()
    except Exception:
        logger.exception("Restore failed")
    # stop tray
    try:
        if mainapp.tray_running:
            mainapp.stop_tray()
    except Exception:
        pass
    # exit python main loop
    try:
        mainapp.root.quit()
    except Exception:
        pass
    logger.info("App stopped")


def main():
    global mainapp, nvml_handle, elevated

    # Auto-elevate if not admin (necessary for nvidia-smi clock locking)
    if not is_admin():
        ok = relaunch_as_admin()
        if not ok:
            messagebox.showerror("GPU Clock Safe", "This app needs administrator privileges to manage GPU clocks.")
            # continue but warn user
    else:
        elevated = True

    load_settings()

    # init nvml if available
    if PYNVML_AVAILABLE:
        try:
            pynvml.nvmlInit()
        except Exception:
            logger.exception("nvml init failed")

    # create GUI root
    root = tk.Tk()
    global mainapp
    mainapp = MainApp(root)

    # Show tray icon
    if PYSTRAY_AVAILABLE:
        mainapp.create_tray()

    # Start threads
    t_auto = threading.Thread(target=auto_temp_loop, daemon=True)
    t_auto.start()

    t_hot = threading.Thread(target=hotkey_worker, daemon=True)
    t_hot.start()

    # If start_on_boot was set, ensure startup
    if settings.get("start_on_boot", False):
        try:
            set_startup(True)
        except Exception:
            logger.exception("Failed ensuring startup")

    # Attempt to set balanced on start for safety
    try:
        set_mode_balanced()
    except Exception:
        logger.exception("Failed initial balanced set")

    # start tkinter mainloop (this blocks)
    try:
        root.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        stop_app()


if __name__ == "__main__":
    main()