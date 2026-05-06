from __future__ import annotations

try:
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
except ModuleNotFoundError:
    class InlineKeyboardButton:  # type: ignore[no-redef]
        def __init__(self, text: str, callback_data: str) -> None:
            self.text = text
            self.callback_data = callback_data

    class InlineKeyboardMarkup:  # type: ignore[no-redef]
        def __init__(self, inline_keyboard: list[list[InlineKeyboardButton]]) -> None:
            self.inline_keyboard = inline_keyboard

from app.models import PROFILE_FIELDS

CALLBACK_MAIN = "main"
CALLBACK_REGISTER = "register"
CALLBACK_REGISTER_ALL = "register_all"
CALLBACK_SITES = "sites"
CALLBACK_INFO = "info"
CALLBACK_EDIT = "edit"
CALLBACK_ANALYTICS = "analytics"
CALLBACK_SETTINGS = "settings"
CALLBACK_HELP = "help"
CALLBACK_CANCEL = "cancel"


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Register on Site", callback_data=CALLBACK_REGISTER), InlineKeyboardButton("Register on All Sites", callback_data=CALLBACK_REGISTER_ALL)],
        [InlineKeyboardButton("My Saved Info", callback_data=CALLBACK_INFO)],
        [InlineKeyboardButton("Edit My Info", callback_data=CALLBACK_EDIT), InlineKeyboardButton("Supported Sites", callback_data=CALLBACK_SITES)],
        [InlineKeyboardButton("Analytics", callback_data=CALLBACK_ANALYTICS), InlineKeyboardButton("Settings", callback_data=CALLBACK_SETTINGS)],
        [InlineKeyboardButton("Help", callback_data=CALLBACK_HELP), InlineKeyboardButton("Cancel Current Task", callback_data=CALLBACK_CANCEL)],
    ])


def sites_menu(sites: dict) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(site.name, callback_data=f"site:{site.key}")] for site in sites.values() if site.enabled]
    rows.append([InlineKeyboardButton("Back", callback_data=CALLBACK_MAIN)])
    return InlineKeyboardMarkup(rows)


def edit_profile_menu() -> InlineKeyboardMarkup:
    labels = {
        "first_name": "First name", "last_name": "Last name", "address_line1": "Address line 1", "address_line2": "Address line 2",
        "state_region": "State", "city": "City", "postal_code": "ZIP/postal code", "phone_number": "Phone number", "email": "Email",
    }
    rows = [[InlineKeyboardButton(labels[field], callback_data=f"edit:{field}")] for field in PROFILE_FIELDS]
    rows.append([InlineKeyboardButton("Back", callback_data=CALLBACK_MAIN)])
    return InlineKeyboardMarkup(rows)


def approval_menu(token: str | None = None) -> InlineKeyboardMarkup:
    callback = f"approve_submit:{token}" if token else "approve_submit"
    return InlineKeyboardMarkup([[InlineKeyboardButton("Approve final submission", callback_data=callback), InlineKeyboardButton("Cancel", callback_data=CALLBACK_CANCEL)]])


def continue_menu(token: str | None = None) -> InlineKeyboardMarkup:
    callback = f"manual_continue:{token}" if token else "manual_continue"
    return InlineKeyboardMarkup([[InlineKeyboardButton("Continue", callback_data=callback), InlineKeyboardButton("Cancel", callback_data=CALLBACK_CANCEL)]])
