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

# Try Quartz for native hotkey support (no Input Monitoring needed for some key combos)
try:
    from Quartz import (
        CGEventTapCreate, CGEventTapEnable, CFMachPortCreateRunLoopSource,
        CFRunLoopGetCurrent, CFRunLoopAddSource, CFRunLoopRun,
        kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventKeyDown,
        CGEventGetIntegerValueField, kCGKeyboardEventKeycode,
        kCFRunLoopCommonModes
    )
    QUARTZ_AVAILABLE = True
except ImportError:
    QUARTZ_AVAILABLE = False

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

    def create_monitor_menu(self):
        menu = rumps.MenuItem("Capture Screen")
        monitors, sorted_mons, self.monitor_map = self.get_monitor_mapping()

        # "All Monitors" first
        m = monitors[0]
        item = rumps.MenuItem(f"All Monitors ({m['width']}x{m['height']})",
                              callback=lambda sender: self.set_monitor("all"))
        if self.config["monitor"] == "all":
            item.state = 1
        menu.add(item)

        # Individual monitors - display_num is 1, 2, ... (leftmost first)
        for display_num, (mss_idx, m) in enumerate(sorted_mons, start=1):
            label = f"Monitor {display_num} ({m['width']}x{m['height']})"
            value = str(mss_idx)
            item = rumps.MenuItem(label, callback=lambda sender, v=value: self.set_monitor(v))
            if self.config["monitor"] == value:
                item.state = 1
            menu.add(item)

        menu.add(rumps.separator)
        menu.add(rumps.MenuItem("Identify Monitors", callback=self.identify_monitors))
        return menu

    def identify_monitors(self, _):
        """Show monitor number on each screen."""
        monitors, sorted_mons, _ = self.get_monitor_mapping()
        for display_num, (mss_idx, m) in enumerate(sorted_mons, start=1):
            script = f'''
            display dialog "Monitor {display_num}
{m['width']}x{m['height']}" buttons {{"OK"}} default button "OK" giving up after 3 with title "AutoScreen"
            '''
            subprocess.Popen(['osascript', '-e', script])

    def set_monitor(self, value):
        self.config["monitor"] = value
        self.save_config()
        # Update menu checkmarks - find the matching mss index
        for item in self.menu["Capture Screen"].values():
            if hasattr(item, 'state'):
                title = str(item.title) if hasattr(item, 'title') else ""
                if value == "all" and "All Monitors" in title:
                    item.state = 1
                elif value != "all" and value == self._get_mss_idx_for_menu_item(title):
                    item.state = 1
                else:
                    item.state = 0

        # Show friendly name in notification
        if value == "all":
            name = "All Monitors"
        else:
            # Find display number for this mss index
            for disp, idx in getattr(self, 'monitor_map', {}).items():
                if str(idx) == value:
                    name = f"Monitor {disp}"
                    break
            else:
                name = f"Monitor {value}"
        rumps.notification("AutoScreen", "Monitor Changed", f"Now capturing: {name}")

    def _get_mss_idx_for_menu_item(self, title):
        """Get the mss index for a menu item title like 'Monitor 1 (1920x1080)'."""
        import re
        match = re.search(r'Monitor (\d+)', title)
        if match:
            display_num = int(match.group(1))
            return str(getattr(self, 'monitor_map', {}).get(display_num, display_num))
        return None

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

        # Convert our hotkey format to pynput GlobalHotKeys format
        # e.g., "cmd+shift+s" -> "<cmd>+<shift>+s"
        # e.g., "f12" -> "<f12>"
        hotkey_parts = hotkey.lower().replace(' ', '').split('+')
        pynput_parts = []

        for part in hotkey_parts:
            if part in ('ctrl', 'control'):
                pynput_parts.append('<ctrl>')
            elif part in ('alt', 'option'):
                pynput_parts.append('<alt>')
            elif part in ('shift',):
                pynput_parts.append('<shift>')
            elif part in ('cmd', 'command', 'super', 'win'):
                pynput_parts.append('<cmd>')
            elif part.startswith('f') and part[1:].isdigit():
                # F-keys like f1, f12
                pynput_parts.append(f'<{part}>')
            else:
                pynput_parts.append(part)

        pynput_hotkey = '+'.join(pynput_parts)
        print(f"Registering hotkey: {hotkey} -> {pynput_hotkey}")

        def on_activate():
            print(f"Hotkey {pynput_hotkey} activated!")
            # Use thread to avoid blocking
            threading.Thread(target=self.take_screenshot, daemon=True).start()

        try:
            self.hotkey_listener = pynput_keyboard.GlobalHotKeys({
                pynput_hotkey: on_activate
            })
            self.hotkey_listener.start()
            print(f"Hotkey listener started for: {pynput_hotkey}")
        except Exception as e:
            print(f"Error registering hotkey: {e}")
            # Fallback: try with basic Listener
            self._register_hotkey_fallback(hotkey)

    def _register_hotkey_fallback(self, hotkey):
        """Fallback hotkey registration using basic Listener."""
        print("Using fallback hotkey listener...")
        hotkey_parts = hotkey.lower().replace(' ', '').split('+')

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
                target_key = part
            elif len(part) == 1:
                target_key = part
            else:
                target_key = part

        pressed_modifiers = set()

        def on_press(key):
            nonlocal pressed_modifiers

            # Track modifiers
            if hasattr(key, 'name'):
                if 'ctrl' in key.name:
                    pressed_modifiers.add('ctrl')
                    return
                elif 'alt' in key.name:
                    pressed_modifiers.add('alt')
                    return
                elif 'shift' in key.name:
                    pressed_modifiers.add('shift')
                    return
                elif 'cmd' in key.name:
                    pressed_modifiers.add('cmd')
                    return

            # Check for target key
            key_name = None
            if hasattr(key, 'name'):
                key_name = key.name.lower()
            elif hasattr(key, 'char') and key.char:
                key_name = key.char.lower()

            if key_name and target_key and key_name == target_key:
                if required_modifiers == pressed_modifiers:
                    print(f"Fallback: Taking screenshot!")
                    threading.Thread(target=self.take_screenshot, daemon=True).start()

        def on_release(key):
            nonlocal pressed_modifiers
            if hasattr(key, 'name'):
                if 'ctrl' in key.name:
                    pressed_modifiers.discard('ctrl')
                elif 'alt' in key.name:
                    pressed_modifiers.discard('alt')
                elif 'shift' in key.name:
                    pressed_modifiers.discard('shift')
                elif 'cmd' in key.name:
                    pressed_modifiers.discard('cmd')

        self.hotkey_listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
        self.hotkey_listener.start()
        print(f"Fallback hotkey registered: {hotkey}")

    def take_screenshot_clicked(self, _):
        self.take_screenshot()

    def take_screenshot(self):
        try:
            os.makedirs(self.config["save_folder"], exist_ok=True)
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            filename = f"screenshot_{timestamp}.png"
            filepath = os.path.join(self.config["save_folder"], filename)

            with mss.mss() as sct:
                if self.config["monitor"] == "all":
                    # monitors[0] is the combined virtual screen of all monitors
                    monitor = sct.monitors[0]
                else:
                    monitor_num = int(self.config["monitor"])
                    if monitor_num < len(sct.monitors):
                        monitor = sct.monitors[monitor_num]
                    else:
                        monitor = sct.monitors[0]

                sct_img = sct.grab(monitor)
                screenshot = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

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
