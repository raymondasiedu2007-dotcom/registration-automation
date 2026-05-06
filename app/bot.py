from __future__ import annotations

import asyncio
import os
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.ai_mapper import AIFormMapper
from app.analytics import AnalyticsService, format_analytics
from app.config import AppConfig, load_config
from app.database import Database
from app.menu import approval_menu, continue_menu, edit_profile_menu, main_menu, sites_menu
from app.models import AttemptStatus, PROFILE_FIELDS, UserProfile
from app.playwright_runner import PlaywrightRegistrationRunner

FIELD_LABELS = {
    "first_name": "First name", "last_name": "Last name", "address_line1": "Address line 1", "address_line2": "Address line 2",
    "state_region": "State/Region", "city": "City", "postal_code": "ZIP/postal code", "phone_number": "Phone number", "email": "Email address",
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Welcome. Use this bot only for authorized registrations on configured sites.", reply_markup=main_menu())


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    config: AppConfig = context.application.bot_data["config"]
    db: Database = context.application.bot_data["db"]
    analytics: AnalyticsService = context.application.bot_data["analytics"]
    user_id = query.from_user.id
    data = query.data or "main"

    if data == "main":
        await query.edit_message_text("Main Menu", reply_markup=main_menu())
    elif data == "register":
        await query.edit_message_text("Select a configured site:", reply_markup=sites_menu(config.sites))
    elif data.startswith("site:"):
        await begin_registration(query, context, data.split(":", 1)[1])
    elif data == "info":
        profile = await db.get_profile(user_id)
        await query.edit_message_text(format_profile(profile), reply_markup=main_menu())
    elif data == "edit":
        await query.edit_message_text("Choose a field to edit:", reply_markup=edit_profile_menu())
    elif data.startswith("edit:"):
        field = data.split(":", 1)[1]
        if field not in PROFILE_FIELDS:
            await query.edit_message_text("Unknown field.", reply_markup=main_menu())
            return
        context.user_data["editing_field"] = field
        await query.edit_message_text(f"Send the new value for {FIELD_LABELS[field]}.")
    elif data == "sites":
        await query.edit_message_text(format_sites(config.sites), reply_markup=main_menu())
    elif data == "analytics":
        await query.edit_message_text(format_analytics(await analytics.summary()), reply_markup=main_menu())
    elif data == "settings":
        await query.edit_message_text("Settings: AI mapping and site allowlists are managed in config.yaml.", reply_markup=main_menu())
    elif data == "help":
        await query.edit_message_text(help_text(), reply_markup=main_menu())
    elif data == "cancel":
        context.user_data.clear()
        await query.edit_message_text("Current task cancelled.", reply_markup=main_menu())
    elif data == "approve_submit":
        context.user_data["approval_future"].set_result(True)
        await query.edit_message_text("Submission approved. Continuing automation...")
    elif data == "manual_continue":
        future = context.user_data.get("manual_future")
        if future and not future.done():
            future.set_result(True)
        await query.edit_message_text("Continuing after manual action...")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    field = context.user_data.pop("editing_field", None)
    if not field:
        await update.message.reply_text("Use the menu to choose an action.", reply_markup=main_menu())
        return
    db: Database = context.application.bot_data["db"]
    profile = await db.get_profile(update.effective_user.id)
    setattr(profile, field, update.message.text.strip())
    await db.upsert_profile(profile)
    await update.message.reply_text(f"Updated {FIELD_LABELS[field]}.", reply_markup=main_menu())


async def begin_registration(query, context: ContextTypes.DEFAULT_TYPE, site_key: str) -> None:
    config: AppConfig = context.application.bot_data["config"]
    db: Database = context.application.bot_data["db"]
    site = config.require_site(site_key)
    profile = await db.get_profile(query.from_user.id)
    missing = [field for field in site.required_profile_fields if not getattr(profile, field, "").strip()]
    if missing:
        await query.edit_message_text("Missing required profile fields: " + ", ".join(FIELD_LABELS[f] for f in missing), reply_markup=edit_profile_menu())
        return
    await query.edit_message_text(f"Starting authorized registration helper for {site.name}. Final submit requires your approval.")
    attempt_id = await db.start_attempt(query.from_user.id, site.key)
    runner: PlaywrightRegistrationRunner = context.application.bot_data["runner"]

    async def manual_callback(message: str, screenshot: str) -> None:
        future = asyncio.get_running_loop().create_future()
        context.user_data["manual_future"] = future
        if screenshot:
            await context.bot.send_photo(query.message.chat_id, photo=open(screenshot, "rb"), caption=message, reply_markup=continue_menu())
        else:
            await context.bot.send_message(query.message.chat_id, message, reply_markup=continue_menu())
        await future

    async def approval_callback(screenshot: str) -> bool:
        future = asyncio.get_running_loop().create_future()
        context.user_data["approval_future"] = future
        await context.bot.send_photo(query.message.chat_id, photo=open(screenshot, "rb"), caption="Approve final submission?", reply_markup=approval_menu())
        return bool(await future)

    result = await runner.run(site, profile, manual_callback, approval_callback)
    status = result.get("status")
    if status == "success":
        await db.finish_attempt(attempt_id, AttemptStatus.SUCCESS, manual_interventions=int(result.get("manual_interventions", 0)))
        await context.bot.send_message(query.message.chat_id, "Registration submitted after your approval.", reply_markup=main_menu())
    elif status == "cancelled":
        await db.finish_attempt(attempt_id, AttemptStatus.CANCELLED, manual_interventions=int(result.get("manual_interventions", 0)))
        await context.bot.send_message(query.message.chat_id, "Registration cancelled before submission.", reply_markup=main_menu())
    else:
        reason = str(result.get("failure_reason", "unknown"))
        await db.finish_attempt(attempt_id, AttemptStatus.FAILED, failure_reason=reason, failure_category="automation", manual_interventions=int(result.get("manual_interventions", 0)))
        await db.log_error(query.from_user.id, site.key, "automation", reason, screenshot_path=str(result.get("screenshot") or ""))
        await context.bot.send_message(query.message.chat_id, f"Registration failed safely: {reason}", reply_markup=main_menu())


def format_profile(profile: UserProfile) -> str:
    lines = ["My Saved Info"]
    masked = profile.masked_dict()
    for field in PROFILE_FIELDS:
        lines.append(f"{FIELD_LABELS[field]}: {masked[field]}")
    return "\n".join(lines)


def format_sites(sites: dict) -> str:
    lines = ["Supported Sites"]
    for site in sites.values():
        status = "enabled" if site.enabled else "disabled"
        lines.append(f"• {site.name}: {site.domain} — {site.registration_url} ({status})")
    return "\n".join(lines)


def help_text() -> str:
    return (
        "This bot assists with authorized registration only on domains listed in config.yaml. "
        "It will not bypass CAPTCHA, anti-bot checks, email/phone verification, rate limits, or access controls. "
        "You must manually complete verification and approve final submission."
    )


def build_application(config_path: str = "config.yaml") -> Application:
    load_dotenv()
    config = load_config(config_path)
    token = config.telegram_token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    app = Application.builder().token(token).build()
    db = Database(config.database_path)
    ai_mapper = AIFormMapper(config.ai)
    runner = PlaywrightRegistrationRunner(config.screenshots_dir, headless=bool(config.raw.get("playwright", {}).get("headless", False)), ai_mapper=ai_mapper)
    app.bot_data.update({"config": config, "db": db, "analytics": AnalyticsService(config.database_path), "runner": runner})
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    return app


async def post_init(application: Application) -> None:
    await application.bot_data["db"].init()


def main() -> None:
    app = build_application(os.getenv("CONFIG_PATH", "config.yaml"))
    app.post_init = post_init
    app.run_polling()


if __name__ == "__main__":
    main()
