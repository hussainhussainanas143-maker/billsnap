# LifeAdmin Autopilot v2

A Telegram bot + web app that remembers your bills, warranties and renewals.
Send a photo of a bill: AI reads it, you confirm anything doubtful, and it warns you before things expire.

Tools: Telegram Bot API, Google Gemini (vision LLM), Supabase (Postgres + Storage), Streamlit, Python.

```
Telegram  <->  bot.py  --->  Gemini (reads bills, answers questions, drafts claims)
                 |
                 +------->  Supabase  <-------  app.py (Streamlit web app)
```
`core.py` holds all shared logic (validation, dates, reminders, AI calls); `bot.py` and `app.py` are thin front-ends.
No n8n, no ngrok, no separate API server: the bot polls Telegram, so it works from any laptop.

Design points for the viva:
- The AI is never trusted: it must return null for anything not visible; missing dates or low confidence (< 0.7) means the item is NOT saved until the user confirms or types the details.
- Reminders are idempotent (unique item + stage in the database), so nothing is sent twice.
- Photos go to a private storage bucket; tables are locked behind the service key; the web app has a password.
- Date maths clamps month ends (31 Jan + 1 month = 28 Feb).

## 1. Setup (once)
1. Install Python 3.10+ from python.org (tick "Add Python to PATH"). Check: `python --version`.
2. In this folder: `pip install -r requirements.txt`
3. Copy `.env.example` to `.env` and fill it in:
   - SUPABASE_URL, SUPABASE_SERVICE_KEY: Supabase > Settings > API (use the **secret** key, sb_secret_...)
   - GEMINI_KEY: https://aistudio.google.com/app/apikey (free)
   - GEMINI_MODEL: a Gemini flash model your key can use (default gemini-3.8-flash)
   - TELEGRAM_BOT_TOKEN: from @BotFather (`/newbot`)
4. Database: if your Supabase tables already exist, you do not need to redo anything. For a fresh project run `supabase/schema.sql` in the SQL Editor (it includes the permission GRANT lines).
5. **Unpublish the old n8n workflows** that use this bot, so they do not fight over it.

## 2. Self-test
```
python check.py
```
It prints OK/FAIL for Supabase, Gemini and Telegram and tells you what to fix.

## 3. Run the bot
```
python bot.py
```
Leave the window open while you demo. Try in Telegram:
- `add Prestige Mixer | Reliance | 2026-03-14 | 24 | 4999`
- `Is my mixer still in warranty?`
- `My mixer stopped working` (drafts the claim email)
- a photo of a bill; a blurry one makes it ask you instead of guessing
- `/items`, `/expiring`, `/delete 1`, `/remindnow`

For demo reminders, run `supabase/seed.sql` (put your Telegram id in it) then send `/remindnow`.

## 4. Web app (Streamlit)
Local: `streamlit run app.py`

Deploy for a link:
1. Put this folder on GitHub (never upload `.env`).
2. https://share.streamlit.io > Create app > pick the repo, main file `app.py`.
3. Advanced settings > Secrets: paste `.streamlit/secrets.toml.example` with real values.
4. Deploy. Give your sir the link and the APP_PASSWORD.

## Tests
`python -m unittest tests.test_core -v`
