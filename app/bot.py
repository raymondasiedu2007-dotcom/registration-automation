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
from app.models import AttemptStatus, PROFILE_FIELDS, SiteConfig, UserProfile
from app.playwright_runner import PlaywrightRegistrationRunner
from app.safety import MAX_CONCURRENT_REGISTRATIONS, MAX_CONFIGURED_UNIQUE_SITES, validate_registration_batch

FIELD_LABELS = {
    "first_name": "First name", "last_name": "Last name", "address_line1": "Address line 1", "address_line2": "Address line 2",
    "state_region": "State/Region", "city": "City", "postal_code": "ZIP/postal code", "phone_number": "Phone number", "email": "Email address",
}

PROFILE_EDIT_QUEUE_KEY = "profile_edit_queue"
EDITING_FIELD_KEY = "editing_field"


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
    elif data == "register_all":
        await begin_batch_registration(query, context)
    elif data.startswith("site:"):
        await begin_registration(query, context, data.split(":", 1)[1])
    elif data == "info":
        profile = await db.get_profile(user_id)
        await query.edit_message_text(format_profile(profile), reply_markup=main_menu())
    elif data == "edit":
        await start_profile_edit_sequence(query, context)
    elif data.startswith("edit:"):
        field = data.split(":", 1)[1]
        if field not in PROFILE_FIELDS:
            await query.edit_message_text("Unknown field.", reply_markup=main_menu())
            return
        context.user_data[PROFILE_EDIT_QUEUE_KEY] = remaining_profile_fields_after(field)
        context.user_data[EDITING_FIELD_KEY] = field
        await query.edit_message_text(profile_field_prompt(field))
    elif data == "sites":
        await query.edit_message_text(format_sites(config.sites), reply_markup=main_menu())
    elif data == "analytics":
        await query.edit_message_text(format_analytics(await analytics.summary()), reply_markup=main_menu())
    elif data == "settings":
        await query.edit_message_text("Settings: AI mapping and site allowlists are managed in config.yaml.", reply_markup=main_menu())
    elif data == "help":
        await query.edit_message_text(help_text(), reply_markup=main_menu())
    elif data == "cancel":
        _resolve_all_pending(context, approved=False)
        context.user_data.clear()
        await query.edit_message_text("Current task cancelled.", reply_markup=main_menu())
    elif data.startswith("approve_submit"):
        token = _callback_token(data)
        _resolve_future(context, "approval_futures", token, True)
        await query.edit_message_text("Submission approved. Continuing automation...")
    elif data.startswith("manual_continue"):
        token = _callback_token(data)
        _resolve_future(context, "manual_futures", token, True)
        await query.edit_message_text("Continuing after manual action...")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    field = context.user_data.get(EDITING_FIELD_KEY)
    if not field:
        await update.message.reply_text("Use the menu to choose an action.", reply_markup=main_menu())
        return
    db: Database = context.application.bot_data["db"]
    profile = await db.get_profile(update.effective_user.id)
    setattr(profile, field, update.message.text.strip())
    await db.upsert_profile(profile)

    next_field = next_profile_edit_field(context)
    if next_field:
        await update.message.reply_text(f"Updated {FIELD_LABELS[field]}.\n\n{profile_field_prompt(next_field)}")
        return

    await update.message.reply_text(f"Updated {FIELD_LABELS[field]}. All profile fields are complete.", reply_markup=main_menu())


async def start_profile_edit_sequence(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[PROFILE_EDIT_QUEUE_KEY] = list(PROFILE_FIELDS[1:])
    context.user_data[EDITING_FIELD_KEY] = PROFILE_FIELDS[0]
    await query.edit_message_text("Let's update your saved info one field at a time.\n\n" + profile_field_prompt(PROFILE_FIELDS[0]))


def remaining_profile_fields_after(field: str) -> list[str]:
    try:
        start_index = PROFILE_FIELDS.index(field) + 1
    except ValueError:
        return []
    return list(PROFILE_FIELDS[start_index:])


def next_profile_edit_field(context: ContextTypes.DEFAULT_TYPE) -> str | None:
    queue = context.user_data.get(PROFILE_EDIT_QUEUE_KEY) or []
    if not queue:
        context.user_data.pop(EDITING_FIELD_KEY, None)
        context.user_data.pop(PROFILE_EDIT_QUEUE_KEY, None)
        return None
    next_field = queue.pop(0)
    context.user_data[EDITING_FIELD_KEY] = next_field
    context.user_data[PROFILE_EDIT_QUEUE_KEY] = queue
    return next_field


def profile_field_prompt(field: str) -> str:
    step_number = PROFILE_FIELDS.index(field) + 1
    total_steps = len(PROFILE_FIELDS)
    return f"Send {FIELD_LABELS[field]} ({step_number}/{total_steps})."


async def begin_registration(query, context: ContextTypes.DEFAULT_TYPE, site_key: str) -> None:
    config: AppConfig = context.application.bot_data["config"]
    db: Database = context.application.bot_data["db"]
    site = config.require_site(site_key)
    validate_registration_batch([site], requested_concurrency=1)
    profile = await db.get_profile(query.from_user.id)
    missing = missing_required_fields(profile, [site])
    if missing:
        await query.edit_message_text("Missing required profile fields: " + ", ".join(FIELD_LABELS[f] for f in missing), reply_markup=edit_profile_menu())
        return
    await query.edit_message_text(f"Starting authorized registration helper for {site.name}. Final submit requires your approval.")
    result = await run_site_registration(query, context, site, profile)
    await context.bot.send_message(query.message.chat_id, format_site_result(site, result), reply_markup=main_menu())


async def begin_batch_registration(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    config: AppConfig = context.application.bot_data["config"]
    db: Database = context.application.bot_data["db"]
    profile = await db.get_profile(query.from_user.id)
    successful_site_keys = await db.successful_site_keys_for_user(query.from_user.id)
    sites = [site for site in config.enabled_sites.values() if site.key not in successful_site_keys][:MAX_CONFIGURED_UNIQUE_SITES]
    if not sites:
        await query.edit_message_text("No enabled configured sites remain to register for this user.", reply_markup=main_menu())
        return
    concurrency = min(MAX_CONCURRENT_REGISTRATIONS, len(sites))
    validate_registration_batch(sites, requested_concurrency=concurrency)
    missing = missing_required_fields(profile, sites)
    if missing:
        await query.edit_message_text("Missing required profile fields: " + ", ".join(FIELD_LABELS[f] for f in missing), reply_markup=edit_profile_menu())
        return
    await query.edit_message_text(
        f"Starting registrations for {len(sites)} unique configured site(s), up to {concurrency} at a time. "
        "Each site still requires final approval before submit."
    )
    semaphore = asyncio.Semaphore(concurrency)

    async def worker(site: SiteConfig) -> tuple[SiteConfig, dict[str, object]]:
        async with semaphore:
            return site, await run_site_registration(query, context, site, profile)

    results = await asyncio.gather(*(worker(site) for site in sites))
    summary_lines = ["Batch registration complete:"]
    for site, result in results:
        summary_lines.append(format_site_result(site, result))
    await context.bot.send_message(query.message.chat_id, "\n".join(summary_lines), reply_markup=main_menu())


async def run_site_registration(query, context: ContextTypes.DEFAULT_TYPE, site: SiteConfig, profile: UserProfile) -> dict[str, object]:
    db: Database = context.application.bot_data["db"]
    runner: PlaywrightRegistrationRunner = context.application.bot_data["runner"]
    attempt_id = await db.start_attempt(query.from_user.id, site.key)
    token = str(attempt_id)

    async def manual_callback(message: str, screenshot: str) -> None:
        future = asyncio.get_running_loop().create_future()
        _future_map(context, "manual_futures")[token] = future
        caption = f"{site.name}: {message}"
        if screenshot:
            with open(screenshot, "rb") as photo:
                await context.bot.send_photo(query.message.chat_id, photo=photo, caption=caption, reply_markup=continue_menu(token))
        else:
            await context.bot.send_message(query.message.chat_id, caption, reply_markup=continue_menu(token))
        await future

    async def approval_callback(screenshot: str) -> bool:
        future = asyncio.get_running_loop().create_future()
        _future_map(context, "approval_futures")[token] = future
        with open(screenshot, "rb") as photo:
            await context.bot.send_photo(query.message.chat_id, photo=photo, caption=f"{site.name}: Approve final submission?", reply_markup=approval_menu(token))
        return bool(await future)

    result = await runner.run(site, profile, manual_callback, approval_callback)
    status = result.get("status")
    if status == "success":
        await db.finish_attempt(attempt_id, AttemptStatus.SUCCESS, manual_interventions=int(result.get("manual_interventions", 0)))
    elif status == "cancelled":
        await db.finish_attempt(attempt_id, AttemptStatus.CANCELLED, manual_interventions=int(result.get("manual_interventions", 0)))
    else:
        reason = str(result.get("failure_reason", "unknown"))
        await db.finish_attempt(attempt_id, AttemptStatus.FAILED, failure_reason=reason, failure_category="automation", manual_interventions=int(result.get("manual_interventions", 0)))
        await db.log_error(query.from_user.id, site.key, "automation", reason, screenshot_path=str(result.get("screenshot") or ""))
    _future_map(context, "manual_futures").pop(token, None)
    _future_map(context, "approval_futures").pop(token, None)
    return result


def _callback_token(data: str) -> str:
    return data.split(":", 1)[1] if ":" in data else "default"


def _future_map(context: ContextTypes.DEFAULT_TYPE, key: str) -> dict[str, asyncio.Future]:
    return context.user_data.setdefault(key, {})


def _resolve_future(context: ContextTypes.DEFAULT_TYPE, key: str, token: str, value: bool) -> None:
    future = _future_map(context, key).get(token)
    if future and not future.done():
        future.set_result(value)


def _resolve_all_pending(context: ContextTypes.DEFAULT_TYPE, approved: bool) -> None:
    for key, value in (("approval_futures", approved), ("manual_futures", True)):
        for future in list(_future_map(context, key).values()):
            if future and not future.done():
                future.set_result(value)


def missing_required_fields(profile: UserProfile, sites: list[SiteConfig]) -> list[str]:
    required = sorted({field for site in sites for field in site.required_profile_fields})
    return [field for field in required if not getattr(profile, field, "").strip()]


def format_site_result(site: SiteConfig, result: dict[str, object]) -> str:
    status = result.get("status")
    if status == "success":
        return f"✅ {site.name}: submitted after approval"
    if status == "cancelled":
        return f"⚠️ {site.name}: cancelled before submission"
    return f"❌ {site.name}: failed safely ({result.get('failure_reason', 'unknown')})"


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
        "It can register one user across unique configured sites with up to 10 concurrent headless workers. "
        "It will not bypass CAPTCHA, anti-bot checks, email/phone verification, rate limits, or access controls. "
        "You must manually complete verification and approve each final submission."
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
    runner = PlaywrightRegistrationRunner(config.screenshots_dir, headless=config.playwright_headless, ai_mapper=ai_mapper)
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
