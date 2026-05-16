from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import tempfile
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update
from telegram.error import BadRequest, Conflict
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.ai_mapper import AIFormMapper
from app.analytics import AnalyticsService, format_analytics
from app.config import AppConfig, ConfigError, load_config, parse_sites_config_text
from app.database import Database
from app.logging_config import configure_logging
from app.menu import (
    CALLBACK_ANALYTICS,
    CALLBACK_BACK,
    CALLBACK_CANCEL,
    CALLBACK_DELETE_SITE,
    CALLBACK_HELP,
    CALLBACK_MAIN,
    CALLBACK_PAUSE,
    CALLBACK_REGISTER,
    CALLBACK_REGISTER_ALL,
    CALLBACK_RESUME,
    CALLBACK_SETTINGS,
    CALLBACK_SITES,
    CALLBACK_UPLOAD_SITES,
    approval_menu,
    continue_menu,
    delete_sites_menu,
    edit_profile_menu,
    main_menu,
    sites_menu,
)
from app.models import AttemptStatus, OPTIONAL_PROFILE_FIELDS, PROFILE_FIELDS, SiteConfig, UserProfile
from app.playwright_runner import PlaywrightRegistrationRunner
from app.proxy import ProxyRotator
from app.safety import MAX_CONCURRENT_REGISTRATIONS, MAX_CONFIGURED_UNIQUE_SITES, validate_registration_batch

FIELD_LABELS = {
    "first_name": "First name", "last_name": "Last name", "address_line1": "Address line 1", "address_line2": "Address line 2",
    "state_region": "State/Region", "city": "City", "postal_code": "ZIP/postal code", "phone_number": "Phone number", "email": "Email address",
    "country": "Country", "password": "Password or password-generation preference",
}


async def safe_edit_or_reply(query, text, reply_markup=None):
    try:
        await query.edit_message_text(
            text=text,
            reply_markup=reply_markup,
        )
    except BadRequest as e:
        if "There is no text in the message to edit" in str(e):
            await query.message.reply_text(
                text=text,
                reply_markup=reply_markup,
            )
        else:
            raise


def field_label(field: str) -> str:
    suffix = " (optional)" if field in OPTIONAL_PROFILE_FIELDS else ""
    return f"{FIELD_LABELS[field]}{suffix}"


PROFILE_EDIT_QUEUE_KEY = "profile_edit_queue"
EDITING_FIELD_KEY = "editing_field"
SITES_UPLOAD_KEY = "awaiting_sites_upload"
PROCESSED_CALLBACK_IDS_KEY = "processed_callback_ids"
TASKS_PAUSED_KEY = "tasks_paused"
LOGGER = logging.getLogger(__name__)
DEFAULT_LOCK_FILE = "/tmp/registration-automation-bot.lock"


class BotInstanceLock:
    """Non-blocking process lock that keeps duplicate local pollers from starting."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self._handle = None

    def __enter__(self) -> "BotInstanceLock":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("w", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.close()
            self._handle = None
            raise RuntimeError(
                f"Another local bot process is already running (lock file: {self.path}). "
                "Stop the existing process before starting a new polling instance."
            ) from exc
        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(str(os.getpid()))
        self._handle.flush()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._handle is None:
            return
        fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
        self._handle.close()
        self._handle = None


async def on_bot_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    error = context.error
    if isinstance(error, Conflict):
        LOGGER.error(
            "Telegram polling conflict: another process is calling getUpdates for this bot token. "
            "Stop the other bot process, systemd service, container, or host using the same token "
            "before restarting this one."
        )
        context.application.stop_running()
        return

    LOGGER.error(
        "Unhandled Telegram bot error",
        exc_info=(type(error), error, error.__traceback__) if error else None,
    )


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.effective_message.reply_text("Welcome. Use this bot only for authorized registrations on configured sites.", reply_markup=main_menu())


async def on_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    await query.answer()

    processed = context.user_data.setdefault(PROCESSED_CALLBACK_IDS_KEY, set())
    if query.id in processed:
        LOGGER.info("Duplicate Telegram callback ignored", extra={"callback_id": query.id})
        return
    processed.add(query.id)
    if len(processed) > 200:
        processed.clear()
        processed.add(query.id)

    config: AppConfig = context.application.bot_data["config"]
    db: Database = context.application.bot_data["db"]
    analytics: AnalyticsService = context.application.bot_data["analytics"]
    user_id = query.from_user.id
    data = query.data or CALLBACK_MAIN
    LOGGER.info("Menu clicked", extra={"user_id": user_id, "callback_data": data})

    if data in {CALLBACK_MAIN, CALLBACK_BACK}:
        await safe_edit_or_reply(query, "Main Menu", reply_markup=main_menu())
    elif data == CALLBACK_REGISTER:
        await safe_edit_or_reply(query, "Select a configured site:", reply_markup=sites_menu(config.sites))
    elif data == CALLBACK_REGISTER_ALL:
        await begin_batch_registration(query, context)
    elif data.startswith("site:"):
        await begin_registration(query, context, data.split(":", 1)[1])
    elif data == "info":
        profile = await db.get_profile(user_id)
        await safe_edit_or_reply(query, format_profile(profile), reply_markup=main_menu())
    elif data == "edit":
        await start_profile_edit_sequence(query, context)
    elif data.startswith("edit:"):
        field = data.split(":", 1)[1]
        if field not in PROFILE_FIELDS:
            await safe_edit_or_reply(query, "Unknown field.", reply_markup=main_menu())
            return
        context.user_data[PROFILE_EDIT_QUEUE_KEY] = remaining_profile_fields_after(field)
        context.user_data[EDITING_FIELD_KEY] = field
        await safe_edit_or_reply(query, profile_field_prompt(field))
    elif data == CALLBACK_SITES:
        await safe_edit_or_reply(query, format_sites(config.sites), reply_markup=main_menu())
    elif data == CALLBACK_UPLOAD_SITES:
        context.user_data[SITES_UPLOAD_KEY] = True
        await safe_edit_or_reply(query, upload_sites_prompt(), reply_markup=main_menu())
    elif data == CALLBACK_DELETE_SITE:
        await safe_edit_or_reply(query, "Choose a saved site to delete:", reply_markup=delete_sites_menu(config.sites))
    elif data.startswith("delete_site:"):
        site_key = data.split(":", 1)[1]
        site = config.sites.pop(site_key, None)
        message = f"Deleted site: {site.name}." if site else "Site was not found."
        await safe_edit_or_reply(query, message, reply_markup=main_menu())
    elif data == "status":
        await safe_edit_or_reply(query, format_registration_status(await db.recent_attempts_for_user(user_id)), reply_markup=main_menu())
    elif data == CALLBACK_ANALYTICS:
        await safe_edit_or_reply(query, format_analytics(await analytics.summary()), reply_markup=main_menu())
    elif data == "export_logs":
        await export_logs(query, context, user_id)
    elif data == CALLBACK_SETTINGS:
        await safe_edit_or_reply(query, settings_text(context), reply_markup=main_menu())
    elif data == CALLBACK_HELP:
        await safe_edit_or_reply(query, help_text(), reply_markup=main_menu())
    elif data == CALLBACK_PAUSE:
        context.user_data[TASKS_PAUSED_KEY] = True
        await safe_edit_or_reply(query, "New registration tasks are paused. Use Resume Tasks to start new tasks again.", reply_markup=main_menu())
    elif data == CALLBACK_RESUME:
        context.user_data[TASKS_PAUSED_KEY] = False
        await safe_edit_or_reply(query, "Registration tasks resumed.", reply_markup=main_menu())
    elif data == CALLBACK_CANCEL:
        _resolve_all_pending(context, approved=False)
        context.user_data.pop(PROFILE_EDIT_QUEUE_KEY, None)
        context.user_data.pop(EDITING_FIELD_KEY, None)
        context.user_data.pop(SITES_UPLOAD_KEY, None)
        context.user_data[TASKS_PAUSED_KEY] = True
        await safe_edit_or_reply(query, "Current task cancelled and new tasks paused.", reply_markup=main_menu())
    elif data.startswith("approve_submit"):
        token = _callback_token(data)
        _resolve_future(context, "approval_futures", token, True)
        await safe_edit_or_reply(query, "Submission approved. Continuing automation...", reply_markup=main_menu())
    elif data.startswith("manual_continue"):
        token = _callback_token(data)
        _resolve_future(context, "manual_futures", token, True)
        await safe_edit_or_reply(query, "Continuing after manual action...", reply_markup=main_menu())
    else:
        await safe_edit_or_reply(query, "Unknown menu action. Returning to the main menu.", reply_markup=main_menu())


async def on_document(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.user_data.get(SITES_UPLOAD_KEY):
        await update.message.reply_text("Use Upload/Edit Website List before sending a sites file.", reply_markup=main_menu())
        return
    document = update.message.document
    if not document:
        await update.message.reply_text("No document found.", reply_markup=main_menu())
        return
    telegram_file = await document.get_file()
    payload = bytes(await telegram_file.download_as_bytearray()).decode("utf-8")
    await apply_sites_upload(update, context, payload)


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get(SITES_UPLOAD_KEY):
        await apply_sites_upload(update, context, update.message.text)
        return

    await save_profile_field_value(update, context, update.message.text)


async def on_skip_optional(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await save_profile_field_value(update, context, "skip")


async def save_profile_field_value(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_value: str) -> None:
    field = context.user_data.get(EDITING_FIELD_KEY)
    if not field:
        await update.message.reply_text("Use the menu to choose an action.", reply_markup=main_menu())
        return
    db: Database = context.application.bot_data["db"]
    profile = await db.get_profile(update.effective_user.id)
    value = raw_value.strip()
    skipped = field in OPTIONAL_PROFILE_FIELDS and value.lower() in {"/skip", "skip", "omit", "none"}
    if value.lower() in {"/skip", "skip", "omit", "none"} and field not in OPTIONAL_PROFILE_FIELDS:
        await update.message.reply_text(f"{FIELD_LABELS[field]} is required for the default profile. Please send a value.")
        return
    setattr(profile, field, "" if skipped else value)
    await db.upsert_profile(profile)

    next_field = next_profile_edit_field(context)
    action = "Skipped optional" if skipped else "Updated"
    if next_field:
        await update.message.reply_text(f"{action} {FIELD_LABELS[field]}.\n\n{profile_field_prompt(next_field)}")
        return

    await update.message.reply_text(f"{action} {FIELD_LABELS[field]}. Profile update is complete.", reply_markup=main_menu())


async def apply_sites_upload(update: Update, context: ContextTypes.DEFAULT_TYPE, payload: str) -> None:
    config: AppConfig = context.application.bot_data["config"]
    try:
        sites = parse_sites_config_text(payload)
    except (ConfigError, ValueError) as exc:
        await update.message.reply_text(f"Website list was not accepted: {exc}", reply_markup=main_menu())
        return
    config.sites = sites
    context.user_data.pop(SITES_UPLOAD_KEY, None)
    await update.message.reply_text(f"Loaded {len(sites)} website(s). Only enabled, allowlisted sites can be automated.", reply_markup=main_menu())


async def export_logs(query, context: ContextTypes.DEFAULT_TYPE, user_id: int) -> None:
    db: Database = context.application.bot_data["db"]
    payload = await db.export_logs_for_user(user_id)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as handle:
        json.dump(payload, handle, indent=2)
        path = Path(handle.name)
    try:
        with path.open("rb") as document:
            await context.bot.send_document(query.message.chat_id, document=document, filename="registration-logs.json", caption="Registration logs export")
        await safe_edit_or_reply(query, "Exported logs.", reply_markup=main_menu())
    finally:
        path.unlink(missing_ok=True)


async def start_profile_edit_sequence(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data[PROFILE_EDIT_QUEUE_KEY] = list(PROFILE_FIELDS[1:])
    context.user_data[EDITING_FIELD_KEY] = PROFILE_FIELDS[0]
    await safe_edit_or_reply(query, "Let's update your saved info one field at a time.\n\n" + profile_field_prompt(PROFILE_FIELDS[0]))


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
    optional_note = " Send 'skip' or /skip to leave this optional field blank." if field in OPTIONAL_PROFILE_FIELDS else ""
    return f"Send {field_label(field)} ({step_number}/{total_steps}).{optional_note}"


async def begin_registration(query, context: ContextTypes.DEFAULT_TYPE, site_key: str) -> None:
    if context.user_data.get(TASKS_PAUSED_KEY):
        await safe_edit_or_reply(query, "Registration tasks are paused. Use Resume Tasks before starting a new registration.", reply_markup=main_menu())
        return
    config: AppConfig = context.application.bot_data["config"]
    db: Database = context.application.bot_data["db"]
    site = config.require_site(site_key)
    LOGGER.info("Registration started", extra={"user_id": query.from_user.id, "site_key": site.key})
    validate_registration_batch([site], requested_concurrency=1)
    profile = await db.get_profile(query.from_user.id)
    missing = missing_required_fields(profile, [site])
    if missing:
        await safe_edit_or_reply(query, "Missing required profile fields: " + ", ".join(field_label(f) for f in missing), reply_markup=edit_profile_menu())
        return
    await safe_edit_or_reply(query, f"Starting authorized registration helper for {site.name}. Final submit requires your approval.")
    result = await run_site_registration(query, context, site, profile)
    await context.bot.send_message(query.message.chat_id, format_site_result(site, result), reply_markup=main_menu())


async def begin_batch_registration(query, context: ContextTypes.DEFAULT_TYPE) -> None:
    if context.user_data.get(TASKS_PAUSED_KEY):
        await safe_edit_or_reply(query, "Registration tasks are paused. Use Resume Tasks before starting a new registration.", reply_markup=main_menu())
        return
    config: AppConfig = context.application.bot_data["config"]
    db: Database = context.application.bot_data["db"]
    LOGGER.info("Registration started", extra={"user_id": query.from_user.id, "mode": "batch"})
    profile = await db.get_profile(query.from_user.id)
    successful_site_keys = await db.successful_site_keys_for_user(query.from_user.id)
    sites = [site for site in config.enabled_sites.values() if site.key not in successful_site_keys][:MAX_CONFIGURED_UNIQUE_SITES]
    if not sites:
        await safe_edit_or_reply(query, "No enabled configured sites remain to register for this user.", reply_markup=main_menu())
        return
    concurrency = min(MAX_CONCURRENT_REGISTRATIONS, len(sites))
    validate_registration_batch(sites, requested_concurrency=concurrency)
    missing = missing_required_fields(profile, sites)
    if missing:
        await safe_edit_or_reply(query, "Missing required profile fields: " + ", ".join(field_label(f) for f in missing), reply_markup=edit_profile_menu())
        return
    await safe_edit_or_reply(query,
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
        lines.append(f"{field_label(field)}: {masked[field]}")
    return "\n".join(lines)


def format_sites(sites: dict) -> str:
    lines = ["Supported Sites"]
    for site in sites.values():
        enabled = "enabled" if site.enabled else "disabled"
        notes = f" — {site.notes}" if site.notes else ""
        lines.append(f"• {site.name}: {site.domain} — {site.registration_url} ({enabled}; status={site.status}){notes}")
    return "\n".join(lines)


def format_registration_status(attempts: list[dict[str, object]]) -> str:
    if not attempts:
        return "No registration attempts yet."
    lines = ["Recent registration status"]
    for attempt in attempts:
        completed = attempt.get("completed_at") or "in progress"
        failure = f" — {attempt['failure_reason']}" if attempt.get("failure_reason") else ""
        lines.append(f"• {attempt['site_key']}: {attempt['status']} ({completed}){failure}")
    return "\n".join(lines)


def upload_sites_prompt() -> str:
    return (
        "Send or upload a sites.yaml/sites.json payload with a top-level sites list or object. "
        "Each site needs name, signup_url (or registration_url), and optional field_mappings, notes, and status. "
        "Only include sites where you are allowed to create your own account."
    )


def settings_text(context: ContextTypes.DEFAULT_TYPE) -> str:
    paused = "paused" if context.user_data.get(TASKS_PAUSED_KEY) else "active"
    return (
        f"Settings\nTask state: {paused}\n"
        "AI mapping and site allowlists are managed in config.yaml and .env. "
        "Use DASHSCOPE_API_KEY and MOONSHOT_API_KEY for Qwen and Moonshot providers."
    )


def help_text() -> str:
    return (
        "This bot assists with authorized registration only on domains listed in config.yaml. "
        "It can register one user across unique configured sites with up to 10 concurrent headless workers. "
        "It will not bypass CAPTCHA, MFA, anti-bot checks, email/phone verification, rate limits, or access controls. "
        "Automation uses deliberate delays. You must manually complete verification and approve each final submission."
    )


def build_application(config_path: str = "config.yaml") -> Application:
    load_dotenv()
    configure_logging(os.getenv("LOG_LEVEL", "INFO"))
    config = load_config(config_path)
    token = config.telegram_token or os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is required")
    app = Application.builder().token(token).build()
    db = Database(config.database_path)
    ai_mapper = AIFormMapper(config.ai)
    proxy_rotator = ProxyRotator(config.proxy_rotation)
    runner = PlaywrightRegistrationRunner(config.screenshots_dir, headless=config.playwright_headless, ai_mapper=ai_mapper, proxy_rotator=proxy_rotator)
    app.bot_data.update({"config": config, "db": db, "analytics": AnalyticsService(config.database_path), "runner": runner})
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(on_menu))
    app.add_handler(CommandHandler("skip", on_skip_optional))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.add_error_handler(on_bot_error)
    return app


async def post_init(application: Application) -> None:
    await application.bot_data["db"].init()


def main() -> None:
    lock_path = os.getenv("BOT_LOCK_FILE", DEFAULT_LOCK_FILE)
    with BotInstanceLock(lock_path):
        app = build_application(os.getenv("CONFIG_PATH", "config.yaml"))
        app.post_init = post_init
        app.run_polling()


if __name__ == "__main__":
    main()
