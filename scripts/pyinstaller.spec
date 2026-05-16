# -*- mode: python ; coding: utf-8 -*-
"""
AI Email Organizer - PyInstaller Specification
Builds standalone Windows executable
"""

import os
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

project_root = Path(SPECPATH).parent.parent

hidden_imports = [
    'uvicorn',
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',
    'fastapi',
    'fastapi.middleware.cors',
    'fastapi.staticfiles',
    'starlette',
    'starlette.middleware.cors',
    'starlette.staticfiles',
    'starlette.responses',
    'starlette.routing',
    'pydantic',
    'pydantic.main',
    'pydantic.fields',
    'jinja2',
    'jinja2.ext',
    'anyio',
    'anyio._backends',
    'anyio._backends._asyncio',
    'httpx',
    'email_validator',
    'itsdangerous',
    'python_multipart',
    'sqlalchemy',
    'sqlite3',
    'asyncio',
    'logging',
    'logging.handlers',
    'json',
    'datetime',
    'pathlib',
    'secrets',
    'hashlib',
    'base64',
]

excludes = [
    'matplotlib',
    'numpy',
    'scipy',
    'pandas',
    'pytest',
    'IPython',
    'jupyter',
    'notebook',
    'tkinter',
    'test',
]

a = Analysis(
    ['../local-service/main.py'],
    pathex=[str(project_root / 'local-service')],
    binaries=[],
    datas=[
        (str(project_root / 'local-service' / 'dashboard'), 'dashboard'),
    ],
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(
    a.pure,
    a.zipped_data,
    cipher=block_cipher
)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='AIEmailOrganizer',
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
    icon=None,
)