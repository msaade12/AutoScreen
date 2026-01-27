#!/usr/bin/env python3
"""Debug script to test hotkey detection on macOS"""
from pynput import keyboard

print("Press keys to see what's detected. Press Ctrl+C to quit.")
print("Try pressing Alt+Z and see what happens...\n")

def on_press(key):
    try:
        # Try to get all info about the key
        info = f"Key: {key}"
        if hasattr(key, 'char'):
            info += f" | char: '{key.char}'"
        if hasattr(key, 'vk'):
            info += f" | vk: {key.vk}"
        if hasattr(key, 'name'):
            info += f" | name: {key.name}"
        print(f"PRESS: {info}")
    except Exception as e:
        print(f"PRESS: {key} (error: {e})")

def on_release(key):
    if key == keyboard.Key.esc:
        print("\nESC pressed - exiting")
        return False

with keyboard.Listener(on_press=on_press, on_release=on_release) as listener:
    listener.join()
