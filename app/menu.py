from __future__ import annotations

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models import OPTIONAL_PROFILE_FIELDS, PROFILE_FIELDS

CALLBACK_MAIN = "main"
CALLBACK_BACK = "back"
CALLBACK_REGISTER = "register"
CALLBACK_REGISTER_ALL = "register_all"
CALLBACK_SITES = "sites"
CALLBACK_UPLOAD_SITES = "upload_sites"
CALLBACK_DELETE_SITE = "delete_site"
CALLBACK_INFO = "info"
CALLBACK_EDIT = "edit"
CALLBACK_STATUS = "status"
CALLBACK_ANALYTICS = "analytics"
CALLBACK_EXPORT_LOGS = "export_logs"
CALLBACK_SETTINGS = "settings"
CALLBACK_HELP = "help"
CALLBACK_PAUSE = "pause_tasks"
CALLBACK_RESUME = "resume_tasks"
CALLBACK_CANCEL = "cancel"


def navigation_row(include_cancel: bool = False) -> list[InlineKeyboardButton]:
    row = [
        InlineKeyboardButton("Back", callback_data=CALLBACK_BACK),
        InlineKeyboardButton("Home", callback_data=CALLBACK_MAIN),
    ]
    if include_cancel:
        row.append(InlineKeyboardButton("Cancel", callback_data=CALLBACK_CANCEL))
    return row


def main_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Start Registration", callback_data=CALLBACK_REGISTER)],
        [InlineKeyboardButton("Add Sites", callback_data=CALLBACK_UPLOAD_SITES), InlineKeyboardButton("View Sites", callback_data=CALLBACK_SITES)],
        [InlineKeyboardButton("Delete Site", callback_data=CALLBACK_DELETE_SITE), InlineKeyboardButton("Analytics", callback_data=CALLBACK_ANALYTICS)],
        [InlineKeyboardButton("Settings", callback_data=CALLBACK_SETTINGS), InlineKeyboardButton("Help", callback_data=CALLBACK_HELP)],
        [InlineKeyboardButton("Pause Tasks", callback_data=CALLBACK_PAUSE), InlineKeyboardButton("Resume Tasks", callback_data=CALLBACK_RESUME)],
        [InlineKeyboardButton("Cancel Tasks", callback_data=CALLBACK_CANCEL)],
    ])


def sites_menu(sites: dict) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(site.name, callback_data=f"site:{site.key}")] for site in sites.values() if site.enabled]
    rows.append([InlineKeyboardButton("Register All Sites", callback_data=CALLBACK_REGISTER_ALL)])
    rows.append(navigation_row(include_cancel=True))
    return InlineKeyboardMarkup(rows)


def delete_sites_menu(sites: dict) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(f"Delete {site.name}", callback_data=f"delete_site:{site.key}")] for site in sites.values()]
    if not rows:
        rows = [[InlineKeyboardButton("No saved sites", callback_data=CALLBACK_MAIN)]]
    rows.append(navigation_row(include_cancel=True))
    return InlineKeyboardMarkup(rows)


def edit_profile_menu() -> InlineKeyboardMarkup:
    labels = {
        "first_name": "First name",
        "last_name": "Last name",
        "address_line1": "Address line 1",
        "address_line2": "Address line 2",
        "state_region": "State/Region",
        "city": "City",
        "postal_code": "ZIP/postal code",
        "phone_number": "Phone number",
        "email": "Email",
        "country": "Country",
        "password": "Password/preference",
    }
    rows = [[InlineKeyboardButton(labels[field] + (" (optional)" if field in OPTIONAL_PROFILE_FIELDS else ""), callback_data=f"edit:{field}")] for field in PROFILE_FIELDS]
    rows.append(navigation_row(include_cancel=True))
    return InlineKeyboardMarkup(rows)


def approval_menu(token: str | None = None) -> InlineKeyboardMarkup:
    callback = f"approve_submit:{token}" if token else "approve_submit"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Approve final submission", callback_data=callback)],
        [InlineKeyboardButton("Cancel", callback_data=CALLBACK_CANCEL), InlineKeyboardButton("Home", callback_data=CALLBACK_MAIN)],
    ])


def continue_menu(token: str | None = None) -> InlineKeyboardMarkup:
    callback = f"manual_continue:{token}" if token else "manual_continue"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("Continue", callback_data=callback)],
        [InlineKeyboardButton("Cancel", callback_data=CALLBACK_CANCEL), InlineKeyboardButton("Home", callback_data=CALLBACK_MAIN)],
    ])
