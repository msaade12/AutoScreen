#!/bin/bash
# Create a macOS app bundle that uses system Python

APP_NAME="AutoScreen"
APP_DIR="dist/${APP_NAME}.app"
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Create app structure
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR/Contents/MacOS"
mkdir -p "$APP_DIR/Contents/Resources"

# Create Info.plist
cat > "$APP_DIR/Contents/Info.plist" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>AutoScreen</string>
    <key>CFBundleIdentifier</key>
    <string>com.autoscreen.app</string>
    <key>CFBundleName</key>
    <string>AutoScreen</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0.0</string>
    <key>CFBundleVersion</key>
    <string>1</string>
    <key>LSMinimumSystemVersion</key>
    <string>10.15</string>
    <key>LSUIElement</key>
    <true/>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

# Create launcher script
cat > "$APP_DIR/Contents/MacOS/AutoScreen" << 'EOF'
#!/bin/bash
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
RESOURCES_DIR="$SCRIPT_DIR/../Resources"

# Use Python from python.org if available, otherwise use system python
if [ -x "/Library/Frameworks/Python.framework/Versions/3.12/bin/python3" ]; then
    PYTHON="/Library/Frameworks/Python.framework/Versions/3.12/bin/python3"
elif [ -x "/Library/Frameworks/Python.framework/Versions/3.11/bin/python3" ]; then
    PYTHON="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
else
    PYTHON="/usr/bin/python3"
fi

# Install dependencies if needed
"$PYTHON" -c "import rumps" 2>/dev/null || "$PYTHON" -m pip install --user rumps pynput Pillow mss

# Run the app (use macOS-specific version without tkinter)
cd "$RESOURCES_DIR"
exec "$PYTHON" autoscreen_macos.py
EOF

chmod +x "$APP_DIR/Contents/MacOS/AutoScreen"

# Copy Python script and resources
cp "$SCRIPT_DIR/autoscreen_macos.py" "$APP_DIR/Contents/Resources/"

# Sign the app
codesign --force --deep --sign "Apple Development: msaade@technosimplified.com (7T8RALXUQR)" "$APP_DIR"

echo "App created at: $APP_DIR"
echo "Note: Requires Python 3.12 from python.org to be installed"
