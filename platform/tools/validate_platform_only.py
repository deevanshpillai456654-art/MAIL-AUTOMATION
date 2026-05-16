from __future__ import annotations
from pathlib import Path
import sys

FORBIDDEN_EXTS = {'.ts', '.tsx', '.txs'}
FORBIDDEN_OLD_PATHS = ['plugins/india_erp','plugins/india_crm','plugins/india_tracking','plugins/india_air_cargo','backend/connectors','backend/plugins']

def validate(root: Path) -> int:
    bad_exts = [p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in FORBIDDEN_EXTS]
    old_paths = [rel for rel in FORBIDDEN_OLD_PATHS if (root / rel).exists()]
    outside_platform_new = []
    print({'bad_native_files': len(bad_exts), 'old_build_paths': old_paths, 'platform_exists': (root/'platform').exists()})
    return 1 if bad_exts or old_paths or not (root/'platform').exists() else 0

if __name__ == '__main__':
    raise SystemExit(validate(Path(sys.argv[1] if len(sys.argv) > 1 else '.')))
