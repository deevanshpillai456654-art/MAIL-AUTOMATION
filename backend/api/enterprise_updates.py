from __future__ import annotations
import os
import tempfile
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, Request, UploadFile, File
from backend import config
from backend.auth.local_auth import require_local_auth_or_localhost
from backend.core.enterprise_operations import EnterpriseOperationsCenter
from backend.core.zip_patch_update import update_status
router = APIRouter(dependencies=[Depends(require_local_auth_or_localhost)])
@router.get("/updates/status")
async def status(): return update_status()
@router.post("/updates/validate")
async def validate_patch(request: Request, file: UploadFile = File(...)):
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = tmp.name
    try:
        paths = getattr(request.app.state, "enterprise_operations_paths", {}) or {}
        center = EnterpriseOperationsCenter(
            project_root=Path(paths.get("project_root") or config.APP_DIR),
            data_dir=Path(paths.get("data_dir") or config.DATA_DIR),
            log_dir=Path(paths.get("log_dir") or config.LOG_DIR),
            app_state=request.app.state,
        )
        return center.validate_update_package(tmp_path)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
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
