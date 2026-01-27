"""
py2app setup script for AutoScreen macOS app
"""
from setuptools import setup

APP = ['autoscreen_macos.py']
DATA_FILES = []
OPTIONS = {
    'argv_emulation': False,
    'iconfile': None,
    'plist': {
        'CFBundleName': 'AutoScreen',
        'CFBundleDisplayName': 'AutoScreen',
        'CFBundleIdentifier': 'com.autoscreen.app',
        'CFBundleVersion': '1.0.0',
        'CFBundleShortVersionString': '1.0.0',
        'LSMinimumSystemVersion': '10.15',
        'LSUIElement': True,  # Hide from dock
        'NSHighResolutionCapable': True,
    },
    'packages': ['rumps', 'pynput', 'PIL', 'mss'],
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
