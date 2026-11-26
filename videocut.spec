# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置

使用方法（在 Windows 上运行）：
    pyinstaller videocut.spec
"""

import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# 收集 FunASR / ModelScope 的数据与动态导入子模块
# FunASR 通过注册表机制动态 import 模型实现（如 funasr.auto.auto_model），
# 静态分析扫不到，必须显式收集全部子模块，否则打包后报 No module named 'funasr.auto'。
funasr_datas = collect_data_files('funasr')
modelscope_datas = collect_data_files('modelscope')

# cif_predictor.py 等模块在导入时执行 @torch.jit.script，需要读取自身 .py 源码。
# PyInstaller 默认不把 .py 当数据文件，这里显式放进 _MEIPASS 供 inspect/linecache 读取。
import funasr as _funasr
_funasr_root = os.path.dirname(_funasr.__file__)
_funasr_parent = os.path.dirname(_funasr_root)
funasr_src_datas = []
for _root, _dirs, _files in os.walk(_funasr_root):
    for _name in _files:
        if _name.endswith('.py'):
            funasr_src_datas.append(
                (os.path.join(_root, _name), os.path.relpath(_root, _funasr_parent))
            )

funasr_hidden = collect_submodules('funasr')
modelscope_hidden = collect_submodules('modelscope')
torch_hidden = collect_submodules('torch')
torchaudio_hidden = collect_submodules('torchaudio')
videocut_hidden = collect_submodules('videocut')

a = Analysis(
    ['videocut_entry.py'],
    pathex=[],
    binaries=[],
    datas=funasr_datas + modelscope_datas + funasr_src_datas + [
        (os.path.join(SPECPATH, 'videocut', 'template_defaults.json'), 'videocut'),
        (os.path.join(SPECPATH, 'videocut', 'webui'), 'videocut/webui'),
    ],
    hiddenimports=[
        'videocut',
        *videocut_hidden,
        'click',
        'rich',
        'rich.console',
        'rich.table',
        'rich.panel',
        'rich.prompt',
        'rich.progress',
        'httpx',
        'cryptography',
        'cryptography.fernet',
        'openai',
        'anthropic',
        'funasr',
        *funasr_hidden,
        'modelscope',
        *modelscope_hidden,
        'torch',
        'torchaudio',
        'pyJianYingDraft',
        *torch_hidden,
        *torchaudio_hidden,
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
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='videocut',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # 可以添加图标: icon='assets/icon.ico'
)
