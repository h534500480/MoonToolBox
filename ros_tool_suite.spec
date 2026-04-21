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
    [],
    exclude_binaries=True,
    name='ros_tool_suite',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ros_tool_suite',
)
