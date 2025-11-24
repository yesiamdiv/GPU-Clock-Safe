import subprocess
import sys
import os
import ctypes
import tkinter as tk
from tkinter import messagebox

# ---------------------------------------------------
# Auto Elevate to Administrator
# ---------------------------------------------------
def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin()
    except:
        return False

if not is_admin():
    # Relaunch as admin
    ctypes.windll.shell32.ShellExecuteW(
        None, "runas", sys.executable, " ".join(sys.argv), None, 1
    )
    sys.exit()

# ---------------------------------------------------
# Run a command
# ---------------------------------------------------
def run_command(cmd):
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            messagebox.showerror("Error", result.stderr.strip())
        return result.stdout
    except Exception as e:
        messagebox.showerror("Error", str(e))


# ---------------------------------------------------
# GPU Clock Modes
# ---------------------------------------------------
def set_clock(mhz):
    run_command(f"nvidia-smi -lgc {mhz},{mhz}")
    messagebox.showinfo("GPU Mode", f"GPU clock locked to {mhz} MHz.")


def restore_defaults():
    run_command("nvidia-smi -rgc")
    run_command("nvidia-smi -rac")
    messagebox.showinfo("GPU Mode", "GPU clocks restored to default.")


# ---------------------------------------------------
# GUI
# ---------------------------------------------------
app = tk.Tk()
app.title("GPU Clock Modes")
app.geometry("350x300")
app.resizable(False, False)

title_label = tk.Label(app, text="NVIDIA GPU Clock Controller", font=("Segoe UI", 14, "bold"))
title_label.pack(pady=15)

btn1 = tk.Button(app, text="Stable Mode (1200 MHz)", height=2, command=lambda: set_clock(1200))
btn1.pack(fill="x", padx=30, pady=5)

btn2 = tk.Button(app, text="Boost Mode (1600 MHz)", height=2, command=lambda: set_clock(1600))
btn2.pack(fill="x", padx=30, pady=5)

btn3 = tk.Button(app, text="Battery Mode (900 MHz)", height=2, command=lambda: set_clock(900))
btn3.pack(fill="x", padx=30, pady=5)

btn4 = tk.Button(app, text="Restore Default Clocks", height=2, bg="#d9534f", fg="white", command=restore_defaults)
btn4.pack(fill="x", padx=30, pady=12)

app.mainloop()
