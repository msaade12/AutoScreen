"""
AutoScreen - Multi-monitor screenshot tool with hotkey support
"""
import os
import sys
import json
import threading
import queue
import subprocess
import tempfile
import platform
import io
from datetime import datetime
from pathlib import Path

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import pystray
from PIL import Image, ImageDraw, ImageGrab, ImageFont
import mss

# Platform-specific imports
if platform.system() == "Windows":
    import ctypes
    from ctypes import wintypes
    import keyboard
else:
    # Use pynput on macOS/Linux (doesn't require root)
    from pynput import keyboard as pynput_keyboard

# Lock file for single instance
LOCK_FILE = Path(tempfile.gettempdir()) / ".autoscreen.lock"


def is_already_running():
    """Check if another instance is already running using a lock file."""
    try:
        if platform.system() == "Windows":
            # Windows: try to create/open lock file exclusively
            if LOCK_FILE.exists():
                # Try to remove stale lock file
                try:
                    LOCK_FILE.unlink()
                except:
                    pass
            # Create lock file with our PID
            try:
                with open(LOCK_FILE, 'x') as f:
                    f.write(str(os.getpid()))
                return False
            except FileExistsError:
                # Check if the process is still running
                try:
                    with open(LOCK_FILE, 'r') as f:
                        pid = int(f.read().strip())
                    # Check if process exists
                    kernel32 = ctypes.windll.kernel32
                    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
                    if handle:
                        kernel32.CloseHandle(handle)
                        return True  # Process exists
                    else:
                        # Stale lock, remove and create new
                        LOCK_FILE.unlink()
                        with open(LOCK_FILE, 'x') as f:
                            f.write(str(os.getpid()))
                        return False
                except:
                    return True
        else:
            # macOS/Linux: use fcntl for file locking
            import fcntl
            global lock_file_handle
            lock_file_handle = open(LOCK_FILE, 'w')
            try:
                fcntl.flock(lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                lock_file_handle.write(str(os.getpid()))
                lock_file_handle.flush()
                return False
            except (IOError, OSError):
                return True
    except Exception as e:
        print(f"Lock check error: {e}")
        return False


def copy_image_to_clipboard(image):
    """Copy a PIL Image to the system clipboard."""
    try:
        if platform.system() == "Darwin":  # macOS
            # Save to temp file and use osascript
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                image.save(tmp.name, 'PNG')
                tmp_path = tmp.name

            script = f'''
            set the clipboard to (read (POSIX file "{tmp_path}") as «class PNGf»)
            '''
            subprocess.run(['osascript', '-e', script], check=True)
            os.unlink(tmp_path)
            print("Screenshot copied to clipboard")

        elif platform.system() == "Windows":
            # Use win32clipboard from pywin32
            import win32clipboard
            from io import BytesIO

            # Convert to BMP format for clipboard
            output = BytesIO()
            image.convert('RGB').save(output, 'BMP')
            bmp_data = output.getvalue()[14:]  # Skip BMP file header
            output.close()

            win32clipboard.OpenClipboard()
            try:
                win32clipboard.EmptyClipboard()
                win32clipboard.SetClipboardData(win32clipboard.CF_DIB, bmp_data)
                print("Screenshot copied to clipboard")
            finally:
                win32clipboard.CloseClipboard()

        else:  # Linux
            # Try xclip
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                image.save(tmp.name, 'PNG')
                tmp_path = tmp.name
            subprocess.run(['xclip', '-selection', 'clipboard', '-t', 'image/png', '-i', tmp_path], check=True)
            os.unlink(tmp_path)
            print("Screenshot copied to clipboard")

    except Exception as e:
        print(f"Failed to copy to clipboard: {e}")


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

    def get_monitor_mapping(self):
        """Get monitors sorted by left position. Returns (all_monitors, sorted_list, display_to_mss_map)."""
        with mss.mss() as sct:
            monitors = sct.monitors
            # monitors[0] is "all", monitors[1+] are individual
            individual = [(i, m) for i, m in enumerate(monitors) if i > 0]
            # Sort by left position (leftmost = Monitor 1)
            sorted_mons = sorted(individual, key=lambda x: x[1]['left'])
            # Map display number (1, 2, ...) to mss index
            mapping = {disp_num: mss_idx for disp_num, (mss_idx, _) in enumerate(sorted_mons, start=1)}
            return monitors, sorted_mons, mapping

    def get_monitors(self):
        monitors_list, sorted_mons, self.monitor_map = self.get_monitor_mapping()
        result = []
        # "All Monitors" first
        m = monitors_list[0]
        result.append(("all", f"All Monitors ({m['width']}x{m['height']})"))
        # Individual monitors - display_num is 1, 2, ... (leftmost first)
        for display_num, (mss_idx, m) in enumerate(sorted_mons, start=1):
            result.append((str(mss_idx), f"Monitor {display_num} ({m['width']}x{m['height']})"))
        return result

    def identify_monitors(self):
        """Show a big number on each monitor so user knows which is which."""
        monitors_list, sorted_mons, _ = self.get_monitor_mapping()
        windows = []
        for display_num, (mss_idx, m) in enumerate(sorted_mons, start=1):
            # Create a window for this monitor
            win = tk.Toplevel()
            win.title(f"Monitor {display_num}")
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
                text=f"Monitor {display_num}",
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

    def play_sound(self):
        """Play screenshot sound."""
        try:
            if platform.system() == "Windows":
                import winsound
                winsound.PlaySound("SystemAsterisk", winsound.SND_ALIAS | winsound.SND_ASYNC)
            elif platform.system() == "Darwin":
                subprocess.Popen(['afplay', '/System/Library/Components/CoreAudio.component/Contents/SharedSupport/SystemSounds/system/acknowledgment_sent.caf'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except:
            pass

    def take_screenshot(self):
        try:
            self.play_sound()
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

            # Copy to clipboard
            copy_image_to_clipboard(screenshot)

            if self.tray_icon:
                self.tray_icon.notify("Screenshot Saved", f"Saved to {filename} (copied to clipboard)")

        except Exception as e:
            print(f"Error taking screenshot: {e}")

    def register_hotkey(self):
        hotkey = self.config["hotkey"]

        if platform.system() == "Windows":
            # Windows: use keyboard library
            if self.hotkey_registered:
                try:
                    keyboard.remove_hotkey(self.hotkey_registered)
                except:
                    pass
            try:
                self.hotkey_registered = keyboard.add_hotkey(
                    hotkey,
                    self.take_screenshot,
                    suppress=True
                )
                print(f"Hotkey registered: {hotkey}")
            except Exception as e:
                print(f"Error registering hotkey: {e}")
        else:
            # macOS/Linux: use pynput (doesn't require root)
            if self.hotkey_registered:
                try:
                    self.hotkey_registered.stop()
                except:
                    pass

            # Parse hotkey string into pynput format
            hotkey_parts = hotkey.lower().replace(' ', '').split('+')
            hotkey_set = set()

            for part in hotkey_parts:
                if part in ('ctrl', 'control'):
                    hotkey_set.add(pynput_keyboard.Key.ctrl)
                elif part in ('alt', 'option'):
                    hotkey_set.add(pynput_keyboard.Key.alt)
                elif part in ('shift',):
                    hotkey_set.add(pynput_keyboard.Key.shift)
                elif part in ('cmd', 'command', 'super', 'win'):
                    hotkey_set.add(pynput_keyboard.Key.cmd)
                elif len(part) == 1:
                    hotkey_set.add(pynput_keyboard.KeyCode.from_char(part))
                else:
                    # Try to get special key
                    try:
                        hotkey_set.add(getattr(pynput_keyboard.Key, part))
                    except AttributeError:
                        hotkey_set.add(pynput_keyboard.KeyCode.from_char(part[0]))

            current_keys = set()

            def on_press(key):
                current_keys.add(key)
                if hotkey_set.issubset(current_keys):
                    self.take_screenshot()

            def on_release(key):
                try:
                    current_keys.discard(key)
                except:
                    pass

            try:
                self.hotkey_registered = pynput_keyboard.Listener(
                    on_press=on_press,
                    on_release=on_release
                )
                self.hotkey_registered.start()
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
        os.makedirs(folder, exist_ok=True)
        if platform.system() == "Darwin":  # macOS
            subprocess.run(["open", folder])
        elif platform.system() == "Windows":
            os.startfile(folder)
        else:  # Linux
            subprocess.run(["xdg-open", folder])

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

        # Use tkinter's native key binding instead of keyboard library (fixes macOS crash)
        self.recording_keys = set()

        def on_key_press(event):
            # Build modifier string
            modifiers = []
            if event.state & 0x4:  # Control
                modifiers.append("ctrl")
            if event.state & 0x8:  # Alt/Option
                modifiers.append("alt")
            if event.state & 0x1:  # Shift
                modifiers.append("shift")
            if event.state & 0x40 or event.state & 0x80:  # Command (macOS)
                modifiers.append("cmd")

            # Get the key name
            key = event.keysym.lower()

            # Skip if it's just a modifier key
            if key in ('control_l', 'control_r', 'alt_l', 'alt_r', 'shift_l', 'shift_r',
                       'meta_l', 'meta_r', 'super_l', 'super_r'):
                return

            # Map some common key names
            key_map = {
                'return': 'enter',
                'escape': 'esc',
                'prior': 'page up',
                'next': 'page down',
                'print': 'print screen',
            }
            key = key_map.get(key, key)

            # Build the hotkey string
            if modifiers:
                hotkey = '+'.join(modifiers + [key])
            else:
                hotkey = key

            self.finish_recording(hotkey)

        # Bind to the settings window
        self.settings_window.bind('<Key>', on_key_press)
        self.settings_window.focus_force()

    def finish_recording(self, hotkey):
        # Unbind the key handler
        try:
            self.settings_window.unbind('<Key>')
        except:
            pass

        self.hotkey_var.set(hotkey)
        self.record_btn.config(
            text="RECORD NEW HOTKEY",
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
                if platform.system() == "Windows":
                    keyboard.remove_hotkey(self.hotkey_registered)
                else:
                    self.hotkey_registered.stop()
            except:
                pass
        if self.tray_icon:
            self.tray_icon.stop()
        if self.root:
            self.root.quit()
            self.root.destroy()
        # Clean up lock file
        try:
            if LOCK_FILE.exists():
                LOCK_FILE.unlink()
        except:
            pass
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
    # Check if already running to prevent duplicate tray icons
    if is_already_running():
        print("AutoScreen is already running!")
        # Show a message box to inform the user
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("AutoScreen", "AutoScreen is already running in the system tray.")
        root.destroy()
        sys.exit(0)

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
