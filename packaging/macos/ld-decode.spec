"""
PyInstaller spec file for creating macOS application bundle of ld-decode
"""
# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None

# Resolve project root relative to this spec file so paths work when invoked
# from any working directory (CI or locally).
# SPECPATH is provided by PyInstaller and contains the spec file's directory
ROOT = Path(SPECPATH).resolve().parents[1]

a = Analysis(
    [str(ROOT / 'lddecode' / 'main.py')],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / 'pyproject.toml'), '.'),
    ],
    hiddenimports=[
        'numpy',
        'scipy',
        'matplotlib',
        'numba',
        'lddecode.commpy_filters',
        'lddecode.core',
        'lddecode.efm_pll',
        'lddecode.fdls',
        'lddecode.fft8',
        'lddecode.utils',
        'lddecode.utils_logging',
        'lddecode.utils_plotting',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ld-decode',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ld-decode',
)

app = BUNDLE(
    coll,
    name='ld-decode.app',
    icon=None,
    bundle_identifier='com.github.happycube.ld-decode',
    version='7.0.0',
    info_plist={
        'NSPrincipalClass': 'NSApplication',
        'NSHighResolutionCapable': 'True',
        'CFBundleShortVersionString': '7.0.0',
        'CFBundleVersion': '7.0.0',
        'CFBundleIdentifier': 'com.github.happycube.ld-decode',
        'CFBundleName': 'ld-decode',
        'CFBundleDisplayName': 'ld-decode',
        'CFBundlePackageType': 'APPL',
        'CFBundleSignature': '????',
        'NSHumanReadableCopyright': 'Copyright © 2026 ld-decode contributors',
        'LSMinimumSystemVersion': '10.13.0',
    },
)
