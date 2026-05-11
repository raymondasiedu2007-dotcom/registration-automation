# Registration Automation Telegram Bot

A Python 3.11+ Telegram bot that assists with **authorized** website registration workflows. The bot only automates domains explicitly listed in `config.yaml`, fills registration forms with user-supplied profile data, pauses for CAPTCHA or manual verification, shows a screenshot before submission, and requires final Telegram approval before clicking Submit/Register.

## Safety limitations

This project is intentionally limited:

- Only configured and enabled sites in `config.yaml` can be automated.
- The runner validates every target URL against the configured domain allowlist.
- It does **not** bypass CAPTCHA, anti-bot systems, email verification, phone verification, rate limits, or access controls.
- If CAPTCHA or verification is detected, automation pauses and asks the Telegram user to complete it manually in the browser.
- It can register one authorized user across multiple distinct configured sites, capped at 10 concurrent headless workers and 40 unique sites per batch.
- It rejects duplicate site registrations in the same task and must not be used to create spam accounts.
- Final Submit/Register is never clicked until the Telegram user approves the final screenshot for each site.
- Address line 2, phone number, and password/preference are optional by default unless a site explicitly requires them.
- Playwright inserts deliberate per-field and pre-submit delays and logs registration milestones.
- Playwright runs in headless mode for safety and deployment consistency.
- Optional proxy rotation is supported only through a configured, authorized proxy provider API; it must not be used to bypass CAPTCHA, rate limits, anti-bot controls, or access restrictions.

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

5. Start the bot. Playwright automation is launched in headless mode:

   ```bash
   python -m app.bot
   ```

   Only one polling process can run for a Telegram bot token. The bot creates a local lock file
   at `/tmp/registration-automation-bot.lock` by default; set `BOT_LOCK_FILE` to override the
   path when needed.

## Telegram bot token setup

1. Open Telegram and chat with `@BotFather`.
2. Create a bot with `/newbot`.
3. Copy the token into `.env`:

   ```env
   TELEGRAM_BOT_TOKEN=123456:your_token
   ```

The bot reads `TELEGRAM_BOT_TOKEN` from the environment first, then from `config.yaml`. Keep
this token secret. If it is exposed in logs, chat, screenshots, or source control, revoke it in
BotFather and generate a replacement token before restarting the bot.

## Troubleshooting polling conflicts

Telegram returns `409 Conflict: terminated by other getUpdates request` when more than one
process, service, container, or host uses long polling with the same bot token. Stop the other
instance before starting this bot again. The application now handles that conflict by logging a
clear message and shutting down instead of repeatedly printing stack traces.

## Config file example

Only add domains where you are authorized to run assisted registration.

```yaml
sites:
  - name: "Example Authorized Site"
    signup_url: "https://example.com/register"
    status: "active"
    notes: "Only use with authorization and according to site terms."
    submit_selector: "button[type='submit']"
    field_mappings:
      first_name: "#firstName"
      last_name: "#lastName"
      email: "input[type='email']"
      password: "input[type='password']"
```

Allowed profile fields are:

- `first_name`
- `last_name`
- `address_line1`
- `address_line2` (optional by default)
- `state_region`
- `city`
- `postal_code`
- `phone_number` (optional by default)
- `email`
- `country`
- `password` (or password-generation preference; optional by default)

## Proxy rotation and 9Proxy API

Proxy rotation is disabled by default. When enabled, the runner fetches one authorized proxy per Playwright browser launch and passes it to Playwright; it still pauses for CAPTCHA/manual verification and still requires final Telegram approval before submission.

Generic provider APIs can return plain-text proxy URLs, `{"proxy":"http://user:pass@host:port"}`, or `{"server":"http://host:port","username":"user","password":"pass"}`. To use 9Proxy's API, set `provider: "9proxy"`; the integration defaults to `https://api.9proxy.com/api/proxy`, sends `num=1&t=2`, uses the `api-key` header with no prefix, and reads the first proxy from `data[0]`. You can pass 9Proxy filters through `request_params`, for example:

```yaml
proxy_rotation:
  enabled: true
  provider: "9proxy"
  api_key: "${PROXY_API_KEY}"
  request_params:
    country: US
    plan: premium
    today: true
```

If your 9Proxy account or environment requires a different API host or proxy protocol, override `api_url` or `proxy_scheme` in `config.yaml`.

## Telegram menu

The main menu uses inline keyboards and supports text/document upload for website lists:

- **Start Registration**: choose a configured site, confirm required profile info, run Playwright, pause for manual verification if needed, approve final submission.
- **Register on All Sites**: registers the same user across enabled, not-yet-successful configured sites, using up to 10 concurrent headless workers and stopping after 40 unique sites. Each site still pauses for CAPTCHA/manual verification and requires final approval before submit.
- **Add/Update Profile**: collects profile fields through a menu-based workflow; optional fields can be skipped by sending `skip` or `/skip`.
- **My Saved Info**: displays stored profile fields with sensitive values masked.
- **Upload/Edit Website List**: accepts an authorized `sites.yaml`/`sites.json` payload at runtime.
- **Registration Status**: shows recent attempts for the Telegram user.
- **Export Logs**: exports the user's attempts and error logs as JSON.
- **Edit My Info**: edit first name, last name, address lines, state/region, city, ZIP/postal code, country, phone number, email, and password/preference individually.
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

The submit button is clicked only after **Approve final submission** is pressed for that site. In a multi-site batch, each site sends its own screenshot and approval button. Cancelling resolves pending approvals as rejected and stops submissions that have not already been approved.


## Optional proxy rotation API

Proxy rotation can be enabled when you have authorization to use a proxy provider for the configured sites. When enabled, the runner calls the configured API once per Playwright browser launch and passes the returned proxy to Chromium. This feature does not bypass CAPTCHA, verification, rate limits, or access controls; those safety pauses and final approval still apply.

```yaml
proxy_rotation:
  enabled: true
  api_url: "${PROXY_API_URL}"
  api_key: "${PROXY_API_KEY}"
  api_key_header: "Authorization"
  api_key_prefix: "Bearer"
  proxy_json_path: "proxy"
  timeout_seconds: 10
```

Supported API responses:

- Plain text proxy URL: `http://user:pass@proxy.example:8080`
- JSON proxy URL: `{ "proxy": "socks5://proxy.example:1080" }`
- JSON Playwright-style fields: `{ "server": "http://proxy.example:8080", "username": "user", "password": "pass" }`

Proxy URLs must include an `http`, `https`, `socks4`, or `socks5` scheme plus host and port. Set `proxy_json_path` to a dotted path such as `data.proxy` for nested JSON responses.

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
