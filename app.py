from __future__ import annotations

from nicegui import ui

from auth.service import require_auth_or_redirect
from auth.views import render_login_page
from config import APP_HOST, APP_PORT, APP_TITLE, STORAGE_SECRET
from ui.pages.analysis import render_analysis_page
from ui.pages.dashboard import render_dashboard


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


def main() -> None:
    ui.run(
        title=APP_TITLE,
        host=APP_HOST,
        port=APP_PORT,
        storage_secret=STORAGE_SECRET,
    )


if __name__ in {"__main__", "__mp_main__"}:
    main()
