from __future__ import annotations

from nicegui import ui

from auth.service import require_auth_or_redirect
from auth.views import render_login_page
from config import APP_HOST, APP_PORT, APP_TITLE, SIMPLIFIED_EXPORTS_DIR, STORAGE_SECRET
from domain.simplified_schema_migration import run_startup_simplified_migration
from ui.pages.agreement_v5 import render_agreement_page
from ui.pages.analysis_v5 import render_analysis_page
from ui.pages.dashboard_v5 import render_dashboard
from ui.pages.migration_review_v5 import render_migration_review_page


@ui.page("/login")
def login_page() -> None:
    render_login_page()


@ui.page("/")
def dashboard_page() -> None:
    if not require_auth_or_redirect():
        return
    render_dashboard()


@ui.page("/analysis/{analysis_id}")
def analysis_page(analysis_id: str) -> None:
    render_analysis_page(analysis_id)


@ui.page("/agreement")
def agreement_page() -> None:
    render_agreement_page()


@ui.page("/migration-review")
def migration_review_page() -> None:
    render_migration_review_page()


def main() -> None:
    run_startup_simplified_migration()
    SIMPLIFIED_EXPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ui.run(
        title=APP_TITLE,
        host=APP_HOST,
        port=APP_PORT,
        storage_secret=STORAGE_SECRET,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
