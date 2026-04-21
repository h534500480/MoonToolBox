# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['tool_suite_gui.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'ros_tool_suite.tools.pcd_slam_map_tool',
        'ros_tool_suite.tools.pcd_tile_split_gui',
        'ros_tool_suite.tools.ipdector',
        'ros_tool_suite.tools.costmap_player',
        'ros_tool_suite.shared_ui',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ros_tool_suite_onefile',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
