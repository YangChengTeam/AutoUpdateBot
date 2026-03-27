# -*- mode: python ; coding: utf-8 -*-
import os
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_all

u2_datas, u2_binaries, u2_hiddenimports = collect_all('uiautomator2')
adb_datas, adb_binaries, adb_hiddenimports = collect_all('adbutils')
axml_datas, axml_binaries, axml_hiddenimports = collect_all('pyaxmlparser')


block_cipher = None

# 收集 bin 目录及其所有子目录和文件
def collect_bin_files():
    """收集 bin 目录下的所有文件"""
    bin_files = []
    bin_path = Path('bin')
    
    if bin_path.exists():
        for root, dirs, files in os.walk(bin_path):
            for file in files:
                src = os.path.join(root, file)
                # 保持原有目录结构
                dst = os.path.dirname(src)
                bin_files.append((src, dst))
    
    return bin_files

a = Analysis(
    ['cmd/hykb/gui_main.py'],  # HYKB GUI 主程序
    pathex=['cmd/hykb'],
    binaries=u2_binaries + adb_binaries + axml_binaries,
    datas=[
        # 打包 bin 目录及其所有子目录
        ('bin', 'bin'),
        # 如果有其他配置文件，添加到这里
    ] + collect_bin_files() + u2_datas + adb_datas + axml_datas,
    hiddenimports=[
        'tkinter',
        'queue',
        'threading',
        'datetime',
        'yaml',
        'bothykb_main',  # HYKB 核心逻辑文件
        'core.env_loader',
        'core.device.device',
        'services.reporter',
        'utils.utils',
    ] + u2_hiddenimports + adb_hiddenimports + axml_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

splash = Splash(
    '.\\splash.png',
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
    text_size=12,
    minify_script=True,
    always_on_top=True,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='好游快爆采集助手',  # EXE 文件名
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
    icon='icon.ico',
)
