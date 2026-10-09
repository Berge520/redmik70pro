# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置：生成免安装、免 Python 环境的单文件 exe。

用法（在 code/ 目录下执行）：
    python -m PyInstaller --noconfirm --clean packaging\\RootTool.spec

产出的 exe 位于 dist/RootTool.exe，已内嵌 adb / fastboot / ksud 等二进制，
可在未安装 Python 的电脑上直接双击运行。
"""

import os

# spec 由 PyInstaller 从 packaging/ 下加载，SPECPATH 即该目录。
# 仓库的 code/ 目录是它的上一级。
ROOT = os.path.dirname(SPECPATH)

# adb / fastboot 运行所需的全部二进制与脚本，打入 exe 内的 tools/ 子目录。
# 运行时 core._bundle_dir() 指向 PyInstaller 解包目录，
# core._TOOL_DIRS 会在 <MEIPASS>/tools/ 下找到它们。
_TOOL_FILES = [
    'adb.exe',
    'fastboot.exe',
    'AdbWinApi.dll',
    'AdbWinUsbApi.dll',
    'libwinpthread-1.dll',
    'ksud',
    'fix_lspd.sh',
]
datas = [
    (os.path.join(ROOT, 'tools', name), 'tools')
    for name in _TOOL_FILES
]


a = Analysis(
    [os.path.join(ROOT, 'gui', 'roottool.pyw')],
    pathex=[os.path.join(ROOT, 'gui')],
    binaries=[],
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 减小体积：明确排除用不到的重型标准库/第三方模块。
        'numpy', 'pandas', 'matplotlib', 'PIL', 'scipy',
        'test', 'unittest', 'pydoc', 'doctest',
    ],
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
    name='RootTool',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # 无控制台窗口（GUI 程序）
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    # icon=None,            # 如有 .ico 图标，取消注释并填入路径
)
