"""Run `python check.py` to test Supabase, Gemini and Telegram one by one."""
import requests
import core

ok_all = True


def report(name, fn):
    global ok_all
    try:
        print(f"[ OK ] {name}: {fn()}")
    except Exception as e:  # noqa: BLE001
        ok_all = False
        print(f"[FAIL] {name}: {e}")
        msg = str(e)
        if "42501" in msg or "permission denied" in msg:
            print("       -> Run the GRANT lines at the bottom of supabase/schema.sql in the Supabase SQL Editor.")
        if "does not exist" in msg or "PGRST205" in msg:
            print("       -> Run supabase/schema.sql in the Supabase SQL Editor first.")
        if "Invalid API key" in msg or "JWT" in msg:
            print("       -> Use the SECRET key (sb_secret_...) as SUPABASE_SERVICE_KEY, not the publishable key.")


report("Supabase", lambda: f"connected, users table readable ({len(core.sb().table('users').select('id').limit(1).execute().data)} row(s) sampled)")
gem_ok_before = ok_all
report("Gemini", lambda: f"answered {core.gemini_json('Reply with JSON {\"ok\": true}', [{'text': 'ping'}])}")


if gem_ok_before and not ok_all:
    try:
        flash = [m for m in core.list_models() if "flash" in m]
        print("       Models your key can use:", ", ".join(flash[:15]) or "(none listed)")
        print("       -> If Gemini is overloaded, set GEMINI_MODEL in .env to one of these (try a 'flash-lite' one) and run again.")
    except Exception as e:  # noqa: BLE001
        print("       (could not list models:", e, ")")


def telegram():
    t = core.cfg("TELEGRAM_BOT_TOKEN")
    if not t:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")
    r = requests.get(f"https://api.telegram.org/bot{t}/getMe", timeout=20).json()
    if not r.get("ok"):
        raise RuntimeError(r)
    return f"bot @{r['result']['username']}"


report("Telegram", telegram)
print("\nAll good - run:  python bot.py" if ok_all else "\nFix the FAIL lines above, then run this again.")
