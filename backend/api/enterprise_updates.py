from __future__ import annotations
from fastapi import APIRouter, Depends, UploadFile, File
from backend.auth.local_auth import require_local_auth_or_localhost
from backend.core.zip_patch_update import update_status, validate_patch_zip
from pathlib import Path
import tempfile, shutil
router = APIRouter(dependencies=[Depends(require_local_auth_or_localhost)])
@router.get("/updates/status")
async def status(): return update_status()
@router.post("/updates/validate")
async def validate_patch(file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    return validate_patch_zip(tmp_path)
@router.post("/updates/install")
async def install_patch():
    return {"status":"requires_windows_runtime", "message":"Patch installation is validated first, then applied with backup and rollback on the installed desktop runtime."}


@router.post('/updates/preview')
async def preview_update():
    return {
        'status': 'ready',
        'steps': ['Validate ZIP', 'Preview changed files', 'Create backup', 'Install patch', 'Validate system', 'Restart services'],
        'rollback_available': True,
    }
