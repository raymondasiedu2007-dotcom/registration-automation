# Registration Automation Telegram Bot

A Python 3.11+ Telegram bot that assists with **authorized** website registration workflows. The bot only automates domains explicitly listed in `config.yaml`, fills registration forms with user-supplied profile data, pauses for CAPTCHA or manual verification, shows a screenshot before submission, and requires final Telegram approval before clicking Submit/Register.

## Safety limitations

This project is intentionally limited:

- Only configured and enabled sites in `config.yaml` can be automated.
- The runner validates every target URL against the configured domain allowlist.
- It does **not** bypass CAPTCHA, anti-bot systems, email verification, phone verification, rate limits, or access controls.
- If CAPTCHA or verification is detected, automation pauses and asks the Telegram user to complete it manually in the browser.
- It supports one authorized registration at a time and must not be used to create spam or bulk accounts.
- Final Submit/Register is never clicked until the Telegram user approves the final screenshot.

## Project structure

```text
app/
  bot.py
  config.py
  database.py
  menu.py
  playwright_runner.py
  form_extractor.py
  ai_mapper.py
  captcha_handler.py
  analytics.py
  models.py
  safety.py
  logging_config.py
config.example.yaml
requirements.txt
.env.example
README.md
```

## Setup

1. Create a virtual environment and install dependencies:

   ```bash
   python3.11 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

2. Install Playwright browsers:

   ```bash
   playwright install chromium
   ```

3. Copy environment and config examples:

   ```bash
   cp .env.example .env
   cp config.example.yaml config.yaml
   ```

4. Edit `.env` and `config.yaml` for your Telegram bot token and authorized sites.

5. Start the bot:

   ```bash
   python -m app.bot
   ```

## Telegram bot token setup

1. Open Telegram and chat with `@BotFather`.
2. Create a bot with `/newbot`.
3. Copy the token into `.env`:

   ```env
   TELEGRAM_BOT_TOKEN=123456:your_token
   ```

The bot reads `TELEGRAM_BOT_TOKEN` from the environment first, then from `config.yaml`.

## Config file example

Only add domains where you are authorized to run assisted registration.

```yaml
sites:
  example_site:
    name: "Example Authorized Site"
    domain: "example.com"
    registration_url: "https://example.com/register"
    enabled: true
    submit_selector: "button[type='submit']"
    field_mappings:
      "#firstName": "first_name"
      "#lastName": "last_name"
      "#email": "email"
```

Allowed profile fields are:

- `first_name`
- `last_name`
- `address_line1`
- `address_line2`
- `state_region`
- `city`
- `postal_code`
- `phone_number`
- `email`

## Telegram menu

The main menu uses inline keyboards:

- **Register on Site**: choose a configured site, confirm required profile info, run Playwright, pause for manual verification if needed, approve final submission.
- **My Saved Info**: displays stored profile fields with sensitive values masked.
- **Edit My Info**: edit first name, last name, address lines, state/region, city, ZIP/postal code, phone number, and email individually.
- **Supported Sites**: lists configured sites with domain, registration URL, and enabled/disabled status.
- **Analytics**: shows attempts, successes, failures, manual interventions, most-used site, last attempt, average duration, and failure reasons.
- **Settings**: explains config-managed settings.
- **Help**: displays safety boundaries and workflow notes.
- **Cancel Current Task**: clears current Telegram task state.

## CAPTCHA and manual verification flow

When the runner detects CAPTCHA or verification text/selectors, it sends:

> Manual action required. Please complete the CAPTCHA/verification in the browser, then press Continue.

The browser remains open. The Telegram user completes the challenge manually and presses **Continue**. The bot checks again and proceeds only when the challenge is no longer detected.

## Final submission approval

Before any submit/register click, the bot sends a screenshot with:

> Approve final submission?

The submit button is clicked only after **Approve final submission** is pressed. Cancelling stops the workflow before submission.

## Optional Kimi/Qwen AI mapping

AI mapping uses an OpenAI-compatible `/chat/completions` endpoint. The bot sends structured form metadata only, asks for strict JSON, validates the JSON, rejects unknown selectors/profile fields, and never allows AI to invent user data.

Example Kimi configuration:

```yaml
ai:
  enabled: true
  provider: "kimi"
  base_url: "https://api.moonshot.ai/v1"
  api_key: "${AI_API_KEY}"
  model: "kimi-k2"
  confidence_threshold: 0.8
```

Example Qwen-compatible configuration:

```yaml
ai:
  enabled: true
  provider: "qwen"
  base_url: "https://dashscope-intl.aliyuncs.com/compatible-mode/v1"
  api_key: "${AI_API_KEY}"
  model: "qwen-plus"
```

If confidence is low, the automation pauses and asks the Telegram user to confirm mappings before continuing.

## Analytics database

SQLite tables are created automatically:

- `users`
- `user_profiles`
- `registration_attempts`
- `site_analytics`
- `error_logs`

## Running tests

```bash
pytest
```
