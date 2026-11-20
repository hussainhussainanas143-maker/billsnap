"""LifeAdmin Telegram bot - long polling, so no public URL / ngrok / n8n is needed."""
import json
import sys
import threading
import time
import traceback

import requests

import core

TOKEN = core.cfg("TELEGRAM_BOT_TOKEN")
API = f"https://api.telegram.org/bot{TOKEN}"
PENDING = {}    # chat_id -> low-confidence extraction waiting for the user to say YES
LAST_LIST = {}  # chat_id -> items shown by the last /items (for /delete N)

HELP = ("🧾 LifeAdmin Autopilot\n\n"
        "• Send a PHOTO of a bill, warranty card or policy and I will file it.\n"
        "• Or type: add Name | Store | date | warranty months | amount\n"
        "  e.g. add Prestige Mixer | Reliance | 2026-03-14 | 24 | 4999\n"
        "• Ask things like: Is my laptop still in warranty? / What did I spend on appliances?\n"
        "• Say what broke (my mixer stopped working) and I will draft the claim email.\n\n"
        "Commands: /items  /expiring  /delete N  /remindnow  /help")


def tg(method, **params):
    return requests.post(f"{API}/{method}", json=params, timeout=40).json()


def send(chat, text):
    for i in range(0, len(text), 4000):
        tg("sendMessage", chat_id=chat, text=text[i:i + 4000])


def download(file_id):
    path = tg("getFile", file_id=file_id)["result"]["file_path"]
    return requests.get(f"https://api.telegram.org/file/bot{TOKEN}/{path}", timeout=60).content


def handle_image(chat, name, file_id, mime):
    send(chat, "🔍 Reading your bill...")
    data = download(file_id)
    try:
        d = core.extract_bill(data, mime)
    except core.GeminiError as e:
        send(chat, f"I could not read that image ({e}).\nTry again in a minute, or type:\n{core.ADD_USAGE}")
        return
    status, missing = core.assess_extraction(d)
    uid = core.get_user(chat, name)["id"]
    if status == "empty":
        send(chat, "That does not look like a bill, warranty card or policy. Please send a clear, well-lit photo of the document.")
    elif status == "missing":
        send(chat, f"I found: {d['name']}" + (f" from {d['store']}" if d.get("store") else "")
             + f". I could not see the {' and '.join(missing)}.\n\nType the details yourself:\n"
             f"add {d['name']} | {d.get('store') or 'Store'} | {d.get('purchase_date') or 'YYYY-MM-DD'} | <months> | {d.get('amount') or ''}")
    elif status == "unsure":
        PENDING[chat] = {"data": d, "image": data, "mime": mime}
        send(chat, f"I read this but I am not fully sure (confidence {float(d.get('confidence') or 0):.0%}):\n"
             f"• {d['name']} ({d.get('store') or '?'})\n• Bought: {core.fmt_date(d.get('purchase_date'))}\n"
             f"• Warranty: {d.get('warranty_months') or '?'} months\n• Amount: {d.get('amount') or '?'}\n\n"
             "Reply YES to save exactly this, or send an 'add ...' line with the right details.")
    else:
        send(chat, core.saved_text(core.add_item(uid, d, image=data, mime=mime, confidence=d.get("confidence") or 0.9)))


def handle_text(chat, name, text):
    low = text.lower().strip()
    uid = core.get_user(chat, name)["id"]
    if low in ("/start", "/help", "help"):
        send(chat, HELP)
    elif low == "/items":
        items = core.list_items(uid)
        LAST_LIST[chat] = items
        send(chat, core.format_items(items) + ("\n\nRemove one with /delete 2" if items else ""))
    elif low == "/expiring":
        soon = [i for i in core.list_items(uid) if i["status"] == "active" and i["days_left"] is not None and 0 <= i["days_left"] <= 30]
        send(chat, core.format_items(soon) if soon else "Nothing ends in the next 30 days. 🎉")
    elif low.startswith("/delete"):
        items = LAST_LIST.get(chat) or core.list_items(uid)
        try:
            target = items[int(low.split()[1]) - 1]
        except (IndexError, ValueError):
            send(chat, "Use /items first, then /delete 2 (the number from the list).")
            return
        core.delete_item(target["id"])
        LAST_LIST.pop(chat, None)
        send(chat, f"🗑️ Deleted {target['name']}.")
    elif low == "/remindnow":
        n = run_reminders()
        send(chat, f"Sent {n} reminder(s)." if n else "No reminders are due right now.")
    elif low in ("yes", "y", "confirm") and chat in PENDING:
        p = PENDING.pop(chat)
        try:
            send(chat, core.saved_text(core.add_item(uid, p["data"], image=p["image"], mime=p["mime"], confidence=p["data"].get("confidence") or 0.6)))
        except ValueError as e:
            send(chat, f"Could not save: {e}")
    elif low.startswith("add ") or low == "add":
        try:
            PENDING.pop(chat, None)
            send(chat, core.saved_text(core.add_item(uid, core.parse_add_command(text))))
        except ValueError as e:
            send(chat, str(e))
    else:
        try:
            ans = core.answer_question(core.list_items(uid), text)
        except core.GeminiError as e:
            send(chat, f"The AI service did not answer ({e}). Try again in a minute. You can still use /items or add ...")
            return
        send(chat, ans["reply"])
        if ans["claim"]:
            c = ans["claim"]
            core.add_claim(c["item_id"], c.get("issue", ""), c.get("draft_text", ""))


def handle(msg):
    chat = msg["chat"]["id"]
    name = (msg.get("from") or {}).get("first_name")
    try:
        doc = msg.get("document") or {}
        if msg.get("photo"):
            handle_image(chat, name, msg["photo"][-1]["file_id"], "image/jpeg")
        elif (doc.get("mime_type") or "").startswith("image/"):
            handle_image(chat, name, doc["file_id"], doc["mime_type"])
        elif (msg.get("text") or "").strip():
            handle_text(chat, name, msg["text"].strip())
        else:
            send(chat, "Send me a photo of a bill, or type a question. /help shows what I can do.")
    except Exception as e:  # noqa: BLE001  - the user always gets a reply, never silence
        traceback.print_exc()
        send(chat, f"Sorry, something went wrong ({type(e).__name__}). Please try again.")


# ------------------------------------------------------------------ scheduled jobs
def run_reminders():
    sent = 0
    for r in core.due_reminders():
        if tg("sendMessage", chat_id=r["telegram_id"], text=r["text"]).get("ok"):
            core.mark_sent(r["item_id"], r["stage"])
            sent += 1
    return sent


def scheduler():
    """Daily reminders after 9am IST and a digest on the 1st (catches up if the bot was off at 9)."""
    last_rem = last_dig = None
    while True:
        try:
            n = core.now()
            if n.hour >= 9:
                if last_rem != n.date():
                    print("reminders sent:", run_reminders())
                    last_rem = n.date()
                if n.day == 1 and last_dig != n.date():
                    for d in core.monthly_digests():
                        tg("sendMessage", chat_id=d["telegram_id"], text=d["text"])
                    last_dig = n.date()
        except Exception:  # noqa: BLE001
            traceback.print_exc()
        time.sleep(300)


def main():
    if not TOKEN:
        sys.exit("TELEGRAM_BOT_TOKEN is not set. Fill in .env first.")
    tg("deleteWebhook")  # a leftover n8n webhook would otherwise block long polling
    me = tg("getMe")
    if not me.get("ok"):
        sys.exit(f"Telegram rejected the token: {me}")
    print(f"Bot @{me['result']['username']} is running. Press Ctrl+C to stop.")
    threading.Thread(target=scheduler, daemon=True).start()
    offset = None
    while True:
        try:
            data = requests.get(f"{API}/getUpdates", params={"timeout": 30, "offset": offset,
                                "allowed_updates": json.dumps(["message"])}, timeout=45).json()
            if not data.get("ok"):
                print("Telegram error:", data)
                time.sleep(5)
                continue
            for u in data["result"]:
                offset = u["update_id"] + 1
                if u.get("message"):
                    handle(u["message"])
        except requests.exceptions.RequestException as e:
            print("network problem, retrying:", e)
            time.sleep(5)
        except KeyboardInterrupt:
            print("Stopped.")
            break


if __name__ == "__main__":
    main()
