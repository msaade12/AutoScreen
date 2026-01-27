"""
AutoScreen for macOS - Screenshot tool with hotkey support
Uses rumps instead of tkinter to avoid Tcl/Tk compatibility issues on macOS Sequoia
"""
import os
import sys
import json
import subprocess
import tempfile
import threading
from datetime import datetime
from pathlib import Path

import rumps
from PIL import Image, ImageGrab
import mss
from pynput import keyboard as pynput_keyboard

# Config file path
CONFIG_FILE = Path.home() / ".autoscreen_config.json"

DEFAULT_CONFIG = {
    "save_folder": str(Path.home() / "Screenshots"),
    "monitor": "all",
    "hotkey": "cmd+shift+s",
}

# Lock file for single instance
LOCK_FILE = Path(tempfile.gettempdir()) / ".autoscreen.lock"


def is_already_running():
    """Check if another instance is already running using a lock file."""
    import fcntl
    global lock_file_handle
    try:
        lock_file_handle = open(LOCK_FILE, 'w')
        fcntl.flock(lock_file_handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_file_handle.write(str(os.getpid()))
        lock_file_handle.flush()
        return False
    except (IOError, OSError):
        return True


def copy_image_to_clipboard(image):
    """Copy a PIL Image to the macOS clipboard."""
    try:
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
            image.save(tmp.name, 'PNG')
            tmp_path = tmp.name

        script = f'''
        set the clipboard to (read (POSIX file "{tmp_path}") as «class PNGf»)
        '''
        subprocess.run(['osascript', '-e', script], check=True, capture_output=True)
        os.unlink(tmp_path)
        return True
    except Exception as e:
        print(f"Failed to copy to clipboard: {e}")
        return False


class AutoScreenApp(rumps.App):
    def __init__(self):
        super().__init__("AutoScreen", icon=None, quit_button=None)
        self.config = self.load_config()
        self.hotkey_listener = None

        # Build menu
        self.menu = [
            rumps.MenuItem("Take Screenshot", callback=self.take_screenshot_clicked),
            None,  # Separator
            rumps.MenuItem("Open Screenshots Folder", callback=self.open_folder),
            None,  # Separator
            self.create_monitor_menu(),
            self.create_hotkey_menu(),
            self.create_folder_menu(),
            None,  # Separator
            rumps.MenuItem("Quit", callback=self.quit_app),
        ]

        # Register hotkey
        self.register_hotkey()

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

    def create_monitor_menu(self):
        menu = rumps.MenuItem("Capture Screen")
        with mss.mss() as sct:
            for i, m in enumerate(sct.monitors):
                if i == 0:
                    label = f"All Monitors ({m['width']}x{m['height']})"
                    value = "all"
                else:
                    label = f"Monitor {i} ({m['width']}x{m['height']})"
                    value = str(i)

                item = rumps.MenuItem(label, callback=lambda sender, v=value: self.set_monitor(v))
                if self.config["monitor"] == value:
                    item.state = 1
                menu.add(item)
        return menu

    def set_monitor(self, value):
        self.config["monitor"] = value
        self.save_config()
        # Update menu checkmarks
        for item in self.menu["Capture Screen"].values():
            if hasattr(item, 'state'):
                item.state = 0
        rumps.notification("AutoScreen", "Monitor Changed", f"Now capturing: {value}")

    def create_hotkey_menu(self):
        menu = rumps.MenuItem("Hotkey")
        hotkeys = ["cmd+shift+s", "cmd+shift+4", "ctrl+shift+s", "f12"]
        for hk in hotkeys:
            item = rumps.MenuItem(hk, callback=lambda sender, h=hk: self.set_hotkey(h))
            if self.config["hotkey"] == hk:
                item.state = 1
            menu.add(item)

        # Add separator and custom option
        menu.add(None)
        current_item = rumps.MenuItem(f"Current: {self.config['hotkey']}")
        current_item.set_callback(None)
        menu.add(current_item)
        menu.add(rumps.MenuItem("Set Custom Hotkey...", callback=self.set_custom_hotkey))
        return menu

    def set_custom_hotkey(self, _):
        """Show dialog to enter custom hotkey."""
        script = f'''
        set currentHotkey to "{self.config['hotkey']}"
        set dialogResult to display dialog "Enter hotkey combination:" & return & return & "Examples: cmd+shift+s, ctrl+alt+p, f12" & return & "Use: cmd, ctrl, alt, shift + letter/number/f-key" default answer currentHotkey with title "AutoScreen - Custom Hotkey"
        return text returned of dialogResult
        '''
        try:
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                new_hotkey = result.stdout.strip().lower().replace(' ', '')
                if new_hotkey:
                    self.set_hotkey(new_hotkey)
        except Exception as e:
            print(f"Error setting custom hotkey: {e}")

    def set_hotkey(self, hotkey):
        self.config["hotkey"] = hotkey
        self.save_config()
        self.register_hotkey()
        # Update menu
        for item in self.menu["Hotkey"].values():
            if hasattr(item, 'state'):
                item.state = 0
        rumps.notification("AutoScreen", "Hotkey Changed", f"New hotkey: {hotkey}")

    def create_folder_menu(self):
        menu = rumps.MenuItem("Save Location")

        # Add current folder
        current = rumps.MenuItem(f"Current: {self.config['save_folder'][:30]}...")
        current.set_callback(None)
        menu.add(current)

        # Add option to change
        change = rumps.MenuItem("Change Folder...", callback=self.change_folder)
        menu.add(change)

        return menu

    def change_folder(self, _):
        # Use AppleScript to show folder picker
        script = '''
        tell application "System Events"
            activate
            set selectedFolder to choose folder with prompt "Select Screenshots Folder"
            return POSIX path of selectedFolder
        end tell
        '''
        try:
            result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                new_folder = result.stdout.strip()
                self.config["save_folder"] = new_folder
                self.save_config()
                rumps.notification("AutoScreen", "Folder Changed", f"Saving to: {new_folder}")
        except Exception as e:
            print(f"Error changing folder: {e}")

    def register_hotkey(self):
        if self.hotkey_listener:
            try:
                self.hotkey_listener.stop()
            except:
                pass

        hotkey = self.config["hotkey"]
        hotkey_parts = hotkey.lower().replace(' ', '').split('+')

        # Separate modifiers from the main key
        required_modifiers = set()
        target_key = None

        for part in hotkey_parts:
            if part in ('ctrl', 'control'):
                required_modifiers.add('ctrl')
            elif part in ('alt', 'option'):
                required_modifiers.add('alt')
            elif part in ('shift',):
                required_modifiers.add('shift')
            elif part in ('cmd', 'command', 'super', 'win'):
                required_modifiers.add('cmd')
            elif part.startswith('f') and part[1:].isdigit():
                # F-keys like f1, f12
                target_key = part
            elif len(part) == 1:
                target_key = part
            else:
                target_key = part

        # Track currently pressed modifiers
        pressed_modifiers = set()

        def normalize_key(key):
            """Get the base key character, ignoring Option modifier effects."""
            # Handle F-keys (they come as Key.f1, Key.f2, etc.)
            if isinstance(key, pynput_keyboard.Key):
                key_name = key.name if hasattr(key, 'name') else str(key)
                if key_name.startswith('f') and key_name[1:].isdigit():
                    return key_name.lower()
                return None

            if hasattr(key, 'vk') and key.vk is not None:
                # Map virtual key codes to characters (US keyboard layout)
                vk_to_char = {
                    0: 'a', 1: 's', 2: 'd', 3: 'f', 4: 'h', 5: 'g', 6: 'z', 7: 'x', 8: 'c', 9: 'v',
                    11: 'b', 12: 'q', 13: 'w', 14: 'e', 15: 'r', 16: 'y', 17: 't', 18: '1', 19: '2',
                    20: '3', 21: '4', 22: '6', 23: '5', 24: '=', 25: '9', 26: '7', 27: '-', 28: '8',
                    29: '0', 31: 'o', 32: 'u', 34: 'i', 35: 'p', 37: 'l', 38: 'j', 40: 'k', 41: ';',
                    43: ',', 45: 'n', 46: 'm', 47: '.', 50: '`',
                }
                return vk_to_char.get(key.vk)
            if hasattr(key, 'char') and key.char:
                return key.char.lower()
            return None

        def on_press(key):
            # Track modifier keys
            if key == pynput_keyboard.Key.ctrl or key == pynput_keyboard.Key.ctrl_l or key == pynput_keyboard.Key.ctrl_r:
                pressed_modifiers.add('ctrl')
            elif key == pynput_keyboard.Key.alt or key == pynput_keyboard.Key.alt_l or key == pynput_keyboard.Key.alt_r:
                pressed_modifiers.add('alt')
            elif key == pynput_keyboard.Key.shift or key == pynput_keyboard.Key.shift_l or key == pynput_keyboard.Key.shift_r:
                pressed_modifiers.add('shift')
            elif key == pynput_keyboard.Key.cmd or key == pynput_keyboard.Key.cmd_l or key == pynput_keyboard.Key.cmd_r:
                pressed_modifiers.add('cmd')
            else:
                # Check if this is the target key and all modifiers are pressed
                if required_modifiers == pressed_modifiers:
                    key_char = normalize_key(key)
                    if key_char and target_key and key_char == target_key.lower():
                        self.take_screenshot()

        def on_release(key):
            # Remove modifier from tracking
            if key == pynput_keyboard.Key.ctrl or key == pynput_keyboard.Key.ctrl_l or key == pynput_keyboard.Key.ctrl_r:
                pressed_modifiers.discard('ctrl')
            elif key == pynput_keyboard.Key.alt or key == pynput_keyboard.Key.alt_l or key == pynput_keyboard.Key.alt_r:
                pressed_modifiers.discard('alt')
            elif key == pynput_keyboard.Key.shift or key == pynput_keyboard.Key.shift_l or key == pynput_keyboard.Key.shift_r:
                pressed_modifiers.discard('shift')
            elif key == pynput_keyboard.Key.cmd or key == pynput_keyboard.Key.cmd_l or key == pynput_keyboard.Key.cmd_r:
                pressed_modifiers.discard('cmd')

        self.hotkey_listener = pynput_keyboard.Listener(
            on_press=on_press,
            on_release=on_release
        )
        self.hotkey_listener.start()
        print(f"Hotkey registered: {hotkey}")

    def take_screenshot_clicked(self, _):
        self.take_screenshot()

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

            # Copy to clipboard
            copy_image_to_clipboard(screenshot)

            rumps.notification("AutoScreen", "Screenshot Saved", f"{filename} (copied to clipboard)")

        except Exception as e:
            print(f"Error taking screenshot: {e}")
            rumps.notification("AutoScreen", "Error", str(e))

    def open_folder(self, _):
        folder = self.config["save_folder"]
        os.makedirs(folder, exist_ok=True)
        subprocess.run(["open", folder])

    def quit_app(self, _):
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        try:
            if LOCK_FILE.exists():
                LOCK_FILE.unlink()
        except:
            pass
        rumps.quit_application()


def main():
    if is_already_running():
        rumps.notification("AutoScreen", "Already Running", "AutoScreen is already running in the menu bar.")
        sys.exit(0)

    app = AutoScreenApp()
    app.run()


if __name__ == "__main__":
    main()
