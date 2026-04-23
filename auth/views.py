from __future__ import annotations

from nicegui import ui

from auth.service import authenticate, current_username, login, logout


def top_nav() -> None:
    with ui.row().classes("w-full items-center justify-between bg-slate-100 p-3 rounded"):
        ui.label("SRT Coder").classes("text-lg font-semibold")
        with ui.row().classes("items-center gap-3"):
            username = current_username()
            if username:
                ui.label(f"Signed in as: {username}")
                ui.button("Logout", on_click=lambda: _logout_and_redirect())


def render_login_page() -> None:
    if current_username():
        ui.navigate.to("/")
        return

    with ui.column().classes("w-full max-w-md mx-auto mt-20 gap-4"):
        ui.label("Login").classes("text-2xl font-semibold")
        username = ui.input("Username").props("outlined")
        password = ui.input("Password", password=True, password_toggle_button=True).props("outlined")
        error = ui.label("").classes("text-red-600")

        def handle_login() -> None:
            user = authenticate(username.value or "", password.value or "")
            if user is None or not user.username:
                error.set_text("Invalid username or password")
                return
            login(user.username)
            ui.navigate.to("/")

        ui.button("Sign in", on_click=handle_login).classes("w-full")


def _logout_and_redirect() -> None:
    logout()
    ui.navigate.to("/login")

