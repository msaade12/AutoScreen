# AutoScreen

A simple, lightweight screenshot tool for Windows with multi-monitor support and customizable hotkeys.

## Features

- **Multi-monitor support** - Capture all screens or select a specific monitor
- **Custom hotkeys** - Set any key combination (e.g., `Ctrl+Shift+S`, `Print Screen`, `F12`)
- **System tray** - Runs quietly in the background
- **Monitor identification** - Flash monitor numbers to identify which is which
- **Instant capture** - One keypress to save a screenshot

## Installation

Download the latest `AutoScreen.exe` from [Releases](../../releases) and run it.

## Usage

1. **First launch** - Configure your settings:
   - Choose save folder
   - Select which monitor(s) to capture
   - Record your preferred hotkey
   - Click "Save & Start"

2. **Take screenshots** - Press your hotkey anytime to capture

3. **System tray** - Right-click the tray icon to:
   - Take a screenshot
   - Open settings
   - Open screenshots folder
   - Exit

## Building from Source

```bash
# Install dependencies
pip install -r requirements.txt

# Build executable
pyinstaller --onefile --noconsole --name AutoScreen autoscreen.py
```

The executable will be in the `dist` folder.

## Requirements

- Windows 10/11
- Python 3.8+ (for building from source)

## License

MIT License
