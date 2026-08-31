from pathlib import Path
import subprocess
import sys

from config import CODINGS_JSON, CODINGS_V4_JSON


def test_active_app_does_not_import_legacy_coding_modules() -> None:
    project_root = Path(__file__).resolve().parents[1]
    script = """
import sys
import app
legacy = [
    'models',
    'domain.coding_service',
    'storage.coding_repo',
    'domain.differentiation_migration',
    'domain.analysis_exchange_service',
    'domain.agreement_service',
    'ui.pages.analysis',
    'ui.pages.agreement',
    'ui.pages.dashboard',
    'ui.pages.migration_review',
]
loaded = [name for name in legacy if name in sys.modules]
if loaded:
    raise SystemExit(','.join(loaded))
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_v4_and_legacy_coding_stores_are_distinct_files() -> None:
    assert CODINGS_V4_JSON != CODINGS_JSON
    assert CODINGS_V4_JSON.name == "codings_v4.json"
