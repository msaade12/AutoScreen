"""
AutoScreen - Multi-monitor screenshot tool with hotkey support
"""
import os
import sys
import json
import threading
import queue
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import keyboard
import pystray
from PIL import Image, ImageDraw, ImageGrab, ImageFont
import mss

# Config file path
CONFIG_FILE = Path.home() / ".autoscreen_config.json"

DEFAULT_CONFIG = {
    "save_folder": str(Path.home() / "Screenshots"),
    "monitor": "all",
    "hotkey": "ctrl+shift+s",
}


class ScreenshotApp:
    def __init__(self):
        self.config = self.load_config()
        self.hotkey_registered = None
        self.tray_icon = None
        self.running = True
        self.settings_window = None
        self.root = None
        self.action_queue = queue.Queue()

    def load_config(self):
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, "r") as f:
                    config = json.load(f)
                    return {**DEFAULT_CONFIG, **config}
            except:
                pass
        return DEFAULT_CONFIG.copy()

    def save_config(self):
        with open(CONFIG_FILE, "w") as f:
            json.dump(self.config, f, indent=2)

    def get_monitors(self):
        with mss.mss() as sct:
            monitors = []
            for i, m in enumerate(sct.monitors):
                if i == 0:
                    monitors.append(("all", f"All Monitors ({m['width']}x{m['height']})"))
                else:
                    monitors.append((str(i), f"Monitor {i} ({m['width']}x{m['height']})"))
            return monitors

    def identify_monitors(self):
        """Show a big number on each monitor so user knows which is which."""
        with mss.mss() as sct:
            windows = []
            for i, m in enumerate(sct.monitors):
                if i == 0:
                    continue  # Skip "all monitors" virtual screen

                # Create a window for this monitor
                win = tk.Toplevel()
                win.title(f"Monitor {i}")
                win.overrideredirect(True)  # No window decorations
                win.attributes("-topmost", True)
                win.configure(bg="#0078D4")

                # Size and position on this monitor
                width = 300
                height = 200
                x = m["left"] + (m["width"] - width) // 2
                y = m["top"] + (m["height"] - height) // 2
                win.geometry(f"{width}x{height}+{x}+{y}")

                # Big number label
                label = tk.Label(
                    win,
                    text=f"Monitor {i}",
                    font=("Segoe UI", 48, "bold"),
                    bg="#0078D4",
                    fg="white"
                )
                label.pack(expand=True, fill="both")

                # Size info
                size_label = tk.Label(
                    win,
                    text=f"{m['width']} x {m['height']}",
                    font=("Segoe UI", 16),
                    bg="#0078D4",
                    fg="white"
                )
                size_label.pack(pady=(0, 20))

                windows.append(win)

            # Close all windows after 2 seconds
            if windows:
                def close_all():
                    for w in windows:
                        try:
                            w.destroy()
                        except:
                            pass

                windows[0].after(2000, close_all)

    def take_screenshot(self):
        try:
            os.makedirs(self.config["save_folder"], exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"screenshot_{timestamp}.png"
            filepath = os.path.join(self.config["save_folder"], filename)

            if self.config["monitor"] == "all":
                screenshot = ImageGrab.grab(all_screens=True)
            else:
                monitor_num = int(self.config["monitor"])
                with mss.mss() as sct:
                    if monitor_num < len(sct.monitors):
                        monitor = sct.monitors[monitor_num]
                        sct_img = sct.grab(monitor)
                        screenshot = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")
                    else:
                        screenshot = ImageGrab.grab(all_screens=True)

            screenshot.save(filepath, "PNG")
            print(f"Screenshot saved: {filepath}")

            if self.tray_icon:
                self.tray_icon.notify("Screenshot Saved", f"Saved to {filename}")

        except Exception as e:
            print(f"Error taking screenshot: {e}")

    def register_hotkey(self):
        if self.hotkey_registered:
            try:
                keyboard.remove_hotkey(self.hotkey_registered)
            except:
                pass

        hotkey = self.config["hotkey"]
        try:
            self.hotkey_registered = keyboard.add_hotkey(
                hotkey,
                self.take_screenshot,
                suppress=True
            )
            print(f"Hotkey registered: {hotkey}")
        except Exception as e:
            print(f"Error registering hotkey: {e}")

    def create_tray_icon(self):
        icon_size = 64
        image = Image.new("RGB", (icon_size, icon_size), color=(30, 30, 30))
        draw = ImageDraw.Draw(image)
        draw.rectangle([12, 20, 52, 48], fill=(100, 150, 255), outline=(255, 255, 255), width=2)
        draw.ellipse([24, 26, 40, 42], fill=(30, 30, 30), outline=(255, 255, 255), width=2)
        draw.rectangle([18, 14, 28, 20], fill=(100, 150, 255), outline=(255, 255, 255), width=1)

        menu = pystray.Menu(
            pystray.MenuItem("Take Screenshot", lambda: self.take_screenshot()),
            pystray.MenuItem("Settings", lambda: self.action_queue.put("settings")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Open Screenshots Folder", lambda: self.open_folder()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda: self.action_queue.put("quit"))
        )

        self.tray_icon = pystray.Icon("AutoScreen", image, "AutoScreen", menu)
        return self.tray_icon

    def open_folder(self):
        folder = self.config["save_folder"]
        if os.path.exists(folder):
            os.startfile(folder)
        else:
            os.makedirs(folder, exist_ok=True)
            os.startfile(folder)

    def show_settings(self, standalone=False):
        if self.settings_window:
            try:
                if self.settings_window.winfo_exists():
                    self.settings_window.lift()
                    self.settings_window.focus_force()
                    return
            except:
                pass

        if standalone:
            self.settings_window = tk.Tk()
        else:
            self.settings_window = tk.Toplevel(self.root)
        self.settings_window.title("AutoScreen Settings")
        self.settings_window.geometry("500x600")
        self.settings_window.resizable(False, False)

        # Center window
        self.settings_window.update_idletasks()
        x = (self.settings_window.winfo_screenwidth() - 500) // 2
        y = (self.settings_window.winfo_screenheight() - 600) // 2
        self.settings_window.geometry(f"500x600+{x}+{y}")

        main_frame = tk.Frame(self.settings_window, padx=20, pady=20)
        main_frame.pack(fill="both", expand=True)

        # Title
        title = tk.Label(main_frame, text="AutoScreen Settings", font=("Segoe UI", 18, "bold"))
        title.pack(pady=(0, 20))

        # === Save folder ===
        folder_label = tk.Label(main_frame, text="Save Location:", font=("Segoe UI", 10, "bold"), anchor="w")
        folder_label.pack(fill="x")

        folder_row = tk.Frame(main_frame)
        folder_row.pack(fill="x", pady=(5, 15))

        self.folder_var = tk.StringVar(value=self.config["save_folder"])
        folder_entry = tk.Entry(folder_row, textvariable=self.folder_var, font=("Segoe UI", 10))
        folder_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))

        browse_btn = tk.Button(folder_row, text="Browse...", command=self.browse_folder)
        browse_btn.pack(side="right")

        # === Monitor selection ===
        monitor_label = tk.Label(main_frame, text="Capture Screen:", font=("Segoe UI", 10, "bold"), anchor="w")
        monitor_label.pack(fill="x")

        monitor_row = tk.Frame(main_frame)
        monitor_row.pack(fill="x", pady=(5, 15))

        self.monitor_var = tk.StringVar(value=self.config["monitor"])
        monitors = self.get_monitors()

        monitors_list = tk.Frame(monitor_row)
        monitors_list.pack(side="left", fill="x", expand=True)

        for value, label in monitors:
            rb = tk.Radiobutton(monitors_list, text=label, value=value, variable=self.monitor_var,
                               font=("Segoe UI", 10), anchor="w")
            rb.pack(anchor="w")

        identify_btn = tk.Button(monitor_row, text="Identify\nMonitors", command=self.identify_monitors,
                                 font=("Segoe UI", 9), padx=10, pady=5)
        identify_btn.pack(side="right", padx=(15, 0))

        # === Hotkey section ===
        hotkey_label = tk.Label(main_frame, text="Screenshot Hotkey:", font=("Segoe UI", 10, "bold"), anchor="w")
        hotkey_label.pack(fill="x", pady=(10, 5))

        # Current hotkey
        current_frame = tk.Frame(main_frame)
        current_frame.pack(fill="x", pady=5)

        tk.Label(current_frame, text="Current:", font=("Segoe UI", 10)).pack(side="left")

        self.hotkey_var = tk.StringVar(value=self.config["hotkey"])
        hotkey_display = tk.Label(current_frame, textvariable=self.hotkey_var,
                                  font=("Segoe UI", 14, "bold"), fg="#0078D4")
        hotkey_display.pack(side="left", padx=(10, 0))

        # Record button
        tk.Label(main_frame, text="Click button, then press your key combo:",
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(10, 5))

        self.record_btn = tk.Button(
            main_frame,
            text="RECORD NEW HOTKEY",
            font=("Segoe UI", 14, "bold"),
            bg="#0078D4",
            fg="white",
            activebackground="#005a9e",
            activeforeground="white",
            cursor="hand2",
            padx=20,
            pady=15,
            command=self.start_recording
        )
        self.record_btn.pack(fill="x", pady=10)

        tk.Label(main_frame, text="Examples: Print Screen, Ctrl+Shift+S, F12, Alt+S",
                 font=("Segoe UI", 9, "italic"), fg="gray").pack(anchor="w")

        # === Buttons at bottom ===
        btn_frame = tk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=(30, 0))

        save_btn = tk.Button(
            btn_frame,
            text="SAVE & START",
            font=("Segoe UI", 12, "bold"),
            bg="#107c10",
            fg="white",
            activebackground="#0b5c0b",
            activeforeground="white",
            padx=30,
            pady=12,
            command=self.save_settings
        )
        save_btn.pack(side="right", padx=5)

        cancel_btn = tk.Button(btn_frame, text="Cancel", font=("Segoe UI", 10),
                               padx=15, pady=8, command=self.settings_window.destroy)
        cancel_btn.pack(side="right", padx=5)

        self.settings_window.protocol("WM_DELETE_WINDOW", self.settings_window.destroy)
        if standalone:
            self.settings_window.mainloop()

    def browse_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get())
        if folder:
            self.folder_var.set(folder)

    def start_recording(self):
        self.record_btn.config(
            text="⏺ Press your hotkey now...",
            bg="#d83b01"
        )
        self.settings_window.update()

        def record():
            try:
                hotkey = keyboard.read_hotkey(suppress=False)
                if self.settings_window and self.settings_window.winfo_exists():
                    self.settings_window.after(0, lambda: self.finish_recording(hotkey))
            except Exception as e:
                print(f"Error recording hotkey: {e}")
                if self.settings_window and self.settings_window.winfo_exists():
                    self.settings_window.after(0, lambda: self.finish_recording(self.config["hotkey"]))

        threading.Thread(target=record, daemon=True).start()

    def finish_recording(self, hotkey):
        self.hotkey_var.set(hotkey)
        self.record_btn.config(
            text="🎯 Click Here to Record New Hotkey",
            bg="#0078D4"
        )

    def save_settings(self):
        self.config["save_folder"] = self.folder_var.get()
        self.config["monitor"] = self.monitor_var.get()
        self.config["hotkey"] = self.hotkey_var.get()

        self.save_config()
        self.register_hotkey()

        # Create folder if needed
        os.makedirs(self.config["save_folder"], exist_ok=True)

        messagebox.showinfo("AutoScreen",
            f"Settings saved!\n\n"
            f"Hotkey: {self.config['hotkey']}\n"
            f"Folder: {self.config['save_folder']}\n\n"
            f"AutoScreen will now run in the system tray.\n"
            f"Press {self.config['hotkey']} to take a screenshot!")

        self.settings_window.destroy()
        self.settings_window = None

    def quit_app(self):
        self.running = False
        if self.hotkey_registered:
            try:
                keyboard.remove_hotkey(self.hotkey_registered)
            except:
                pass
        if self.tray_icon:
            self.tray_icon.stop()
        if self.root:
            self.root.quit()
            self.root.destroy()
        sys.exit(0)

    def process_queue(self):
        try:
            while True:
                action = self.action_queue.get_nowait()
                if action == "settings":
                    self.show_settings(standalone=False)
                elif action == "quit":
                    self.quit_app()
        except queue.Empty:
            pass
        if self.running and self.root:
            self.root.after(100, self.process_queue)

    def run(self):
        print("AutoScreen starting...")
        print(f"Save folder: {self.config['save_folder']}")
        print(f"Monitor: {self.config['monitor']}")
        print(f"Hotkey: {self.config['hotkey']}")

        self.register_hotkey()
        icon = self.create_tray_icon()

        print("\nAutoScreen is running in the system tray.")
        print("Right-click the tray icon for options.")

        # Create hidden root window for tkinter
        self.root = tk.Tk()
        self.root.withdraw()

        # Run tray icon in background thread
        tray_thread = threading.Thread(target=icon.run, daemon=True)
        tray_thread.start()

        # Process queue on main thread
        self.root.after(100, self.process_queue)
        self.root.mainloop()


def main():
    if not CONFIG_FILE.exists():
        app = ScreenshotApp()
        app.show_settings(standalone=True)
        if app.running:
            app.run()
    else:
        app = ScreenshotApp()
        app.run()


if __name__ == "__main__":
    main()
