"""Shared logic for the LifeAdmin Telegram bot and the Streamlit app."""
import base64
import datetime as dt
import json
import os
import time
import uuid

import requests
from dateutil.relativedelta import relativedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # dotenv is optional (Streamlit Cloud uses secrets)
    pass

CATEGORIES = ["electronics", "appliance", "vehicle", "insurance", "subscription", "medical", "other"]
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/models"
ADD_USAGE = "Format: add Name | Store | purchase date (YYYY-MM-DD or DD/MM/YYYY) | warranty months | amount (optional)"


# ------------------------------------------------------------------ config
def cfg(name, default=None):
    v = os.environ.get(name)
    if v:
        return v
    try:
        import streamlit as st
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:  # noqa: BLE001
        pass
    return default


def now():
    return dt.datetime.now(IST)


def today():
    return now().date()


# ------------------------------------------------------------------ dates / text
def parse_date(s):
    if not s:
        return None
    if isinstance(s, dt.date):
        return s
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return dt.datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            continue
    return None


def add_months(d, n):
    return d + relativedelta(months=int(n))  # clamps 31 Jan + 1 month to 28 Feb


def days_left(expiry):
    d = parse_date(expiry)
    return (d - today()).days if d else None


def pick_stage(dl):
    """Reminder bucket: 31+ days none, 8-30 -> 30, 2-7 -> 7, 1 -> 1, 0 -> 0."""
    if dl is None or dl < 0:
        return None
    for s in (0, 1, 7, 30):
        if dl <= s:
            return s
    return None


def fmt_date(s):
    d = parse_date(s)
    return d.strftime("%d %b %Y") if d else "unknown"


def money(n):
    return f"₹{float(n or 0):,.0f}"


def status_icon(dl):
    if dl is None:
        return "-"
    if dl < 0:
        return "❌ expired"
    if dl <= 7:
        return "🚨 ending soon"
    if dl <= 30:
        return "⏰ within 30 days"
    return "✅ covered"


def reminder_text(item, dl):
    when = "TODAY" if dl == 0 else "tomorrow" if dl == 1 else f"in {dl} days"
    icon = "🚨" if dl <= 1 else "⏰"
    store = f" ({item['store']})" if item.get("store") else ""
    if item.get("category") == "subscription":
        return f"{icon} {item['name']}{store} renews/ends {when} ({fmt_date(item['expiry_date'])}).\nNot using it? Cancel before it charges you."
    if item.get("category") == "insurance":
        return f"{icon} {item['name']}{store} expires {when} ({fmt_date(item['expiry_date'])}).\nRenew in time to avoid a coverage gap."
    return (f"{icon} {item['name']}{store} - warranty ends {when} ({fmt_date(item['expiry_date'])}).\n"
            "Any issue with it? Tell me what is wrong and I will draft the claim.")


def saved_text(item):
    dl = item.get("days_left")
    return (f"✅ Saved: {item['name']}" + (f" ({item['store']})" if item.get("store") else "")
            + f"\nCovered until {fmt_date(item['expiry_date'])}" + (f" ({dl} days left)" if dl is not None else "")
            + "\nI will remind you 30, 7 and 1 day before it ends.")


def format_items(items):
    if not items:
        return "You are not tracking anything yet. Send me a photo of a bill or type:\n" + ADD_USAGE
    lines = []
    for n, i in enumerate(items, 1):
        dl = i.get("days_left")
        lines.append(f"{n}. {i['name']}" + (f" ({i['store']})" if i.get("store") else "")
                     + f" - ends {fmt_date(i.get('expiry_date'))} " + (f"({dl}d) " if dl is not None else "") + status_icon(dl)[:2])
    return "\n".join(lines)


# ------------------------------------------------------------------ validation
def normalize_item(raw):
    name = (raw.get("name") or "").strip()
    if not name:
        raise ValueError("Item name is required.")
    cat = raw.get("category") if raw.get("category") in CATEGORIES else "other"
    purchase, expiry = parse_date(raw.get("purchase_date")), parse_date(raw.get("expiry_date"))
    if raw.get("purchase_date") and purchase is None:
        raise ValueError("Purchase date must look like 2026-03-14 or 14/03/2026.")
    if raw.get("expiry_date") and expiry is None:
        raise ValueError("Expiry date must look like 2027-03-14 or 14/03/2027.")
    months = raw.get("warranty_months")
    try:
        months = int(months) if months not in (None, "") else None
    except (TypeError, ValueError):
        raise ValueError("Warranty months must be a whole number.")
    if months is not None and not 0 <= months <= 600:
        raise ValueError("Warranty months must be between 0 and 600.")
    if expiry is None and purchase and months is not None:
        expiry = add_months(purchase, months)
    if expiry is None:
        raise ValueError("I need purchase date + warranty months, or an expiry date.")
    amount = raw.get("amount")
    try:
        amount = float(amount) if amount not in (None, "") else None
    except (TypeError, ValueError):
        amount = None
    if amount is not None and amount < 0:
        raise ValueError("Amount cannot be negative.")
    store = (raw.get("store") or "").strip() or None
    return {"name": name[:200], "category": cat, "store": store[:200] if store else None,
            "purchase_date": purchase.isoformat() if purchase else None, "warranty_months": months,
            "expiry_date": expiry.isoformat(), "amount": amount, "currency": (raw.get("currency") or "INR")[:3].upper()}


def parse_add_command(text):
    """'add Name | Store | date | months | amount' -> dict (raises ValueError with a helpful message)."""
    parts = [p.strip() for p in text[3:].split("|")] if text.lower().startswith("add") else []
    if len(parts) < 4 or not parts[0]:
        raise ValueError("I need at least name, store, date and warranty months.\n" + ADD_USAGE)
    d = {"name": parts[0], "store": parts[1], "purchase_date": parts[2], "warranty_months": parts[3]}
    if len(parts) > 4 and parts[4]:
        d["amount"] = parts[4].replace(",", "")
    normalize_item(d)  # validate now so the user gets the error immediately
    return d


# ------------------------------------------------------------------ database
_sb = None


def sb():
    global _sb
    if _sb is None:
        from supabase import create_client
        url, key = cfg("SUPABASE_URL"), cfg("SUPABASE_SERVICE_KEY")
        if not url or not key:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_KEY must be set.")
        _sb = create_client(url, key)
    return _sb


def get_user(telegram_id, name=None):
    row = {"telegram_id": int(telegram_id)}
    if name:
        row["name"] = str(name)[:100]
    return sb().table("users").upsert(row, on_conflict="telegram_id").execute().data[0]


def _decorate(r):
    r["days_left"] = days_left(r.get("expiry_date"))
    return r


def list_items(user_id):
    rows = sb().table("items").select("*").eq("user_id", user_id).order("expiry_date").execute().data
    return [_decorate(r) for r in rows]


def add_item(user_id, raw, image=None, mime="image/jpeg", confidence=1.0):
    rec = normalize_item(raw)
    rec.update(user_id=user_id, confidence=round(float(raw.get("confidence") or confidence), 2))
    if image:
        try:
            path = f"{user_id}/{uuid.uuid4()}.jpg"
            sb().storage.from_("bills").upload(path, image, {"content-type": mime})
            rec["image_url"] = path
        except Exception:  # noqa: BLE001  (saving still works without the photo)
            pass
    return _decorate(sb().table("items").insert(rec).execute().data[0])


def delete_item(item_id):
    sb().table("items").delete().eq("id", item_id).execute()


def add_claim(item_id, issue, draft):
    sb().table("claims").insert({"item_id": item_id, "issue": str(issue)[:1000], "draft_text": draft}).execute()
    sb().table("items").update({"status": "claimed"}).eq("id", item_id).execute()


# ------------------------------------------------------------------ AI
class GeminiError(RuntimeError):
    pass


def _loads(text):
    text = text.replace("```json", "").replace("```", "").strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        a, b = text.find("{"), text.rfind("}")
        if a != -1 and b > a:
            return json.loads(text[a:b + 1])
        raise


def gemini_json(system, parts, temperature=0.0):
    """Call Gemini; if a model is overloaded (503), rate-limited (429), unknown (404) or times out, try the next one."""
    key = cfg("GEMINI_KEY")
    if not key:
        raise GeminiError("GEMINI_KEY is not set.")
    body = {"system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": temperature}}
    models = dict.fromkeys([cfg("GEMINI_MODEL", "gemini-flash-latest"), "gemini-flash-latest",
                            "gemini-flash-lite-latest", "gemini-3.8-flash"])
    last = ""
    for model in models:
        r = None
        for attempt in range(2):
            try:
                r = requests.post(f"{GEMINI_BASE}/{model}:generateContent", headers={"x-goog-api-key": key}, json=body, timeout=45)
            except requests.exceptions.RequestException as e:
                last = f"{model}: no answer in time ({type(e).__name__})"
                r = None
                break
            if r.status_code in (429, 500, 503) and attempt == 0:
                time.sleep(3)
                continue
            break
        if r is None:
            continue
        if r.status_code == 200:
            cands = r.json().get("candidates") or []
            if not cands:
                raise GeminiError("Gemini returned no answer (empty or blocked).")
            text = "".join(p.get("text", "") for p in cands[0].get("content", {}).get("parts", []))
            try:
                return _loads(text)
            except (json.JSONDecodeError, ValueError):
                raise GeminiError("Gemini did not return valid JSON.")
        last = f"{model}: error {r.status_code}: {r.text[:160]}"
        if r.status_code not in (404, 429, 500, 503):  # e.g. 400/403 = key problem, other models will not help
            break
    raise GeminiError(last)


def list_models():
    """Model names this Gemini key can call (for debugging)."""
    r = requests.get(f"{GEMINI_BASE}?pageSize=200", headers={"x-goog-api-key": cfg("GEMINI_KEY", "")}, timeout=30)
    r.raise_for_status()
    return [m["name"].split("/")[-1] for m in r.json().get("models", []) if "generateContent" in m.get("supportedGenerationMethods", [])]


EXTRACT_SYSTEM = """You read photos of bills, receipts, invoices, warranty cards and insurance/subscription documents (mostly Indian).
Return ONLY one JSON object - no prose, no markdown fences:
{"name": short product or service name, "category": "electronics|appliance|vehicle|insurance|subscription|medical|other",
 "store": string or null, "purchase_date": "YYYY-MM-DD" or null, "warranty_months": integer or null,
 "expiry_date": "YYYY-MM-DD" or null, "amount": number or null, "currency": "INR", "confidence": number between 0 and 1}
Rules:
- NEVER guess. If a value is not visible in the image, use null.
- Dates are DD/MM/YYYY unless clearly otherwise. Convert "2 years" to 24 months.
- If the image is not a bill, warranty card or policy, return {"name": null, "confidence": 0}.
- confidence = how legible and complete the document is (blurry or cropped means below 0.6)."""


def extract_bill(image, mime="image/jpeg"):
    return gemini_json(EXTRACT_SYSTEM, [
        {"inline_data": {"mime_type": mime, "data": base64.b64encode(image).decode()}},
        {"text": "Extract the details from this document."}])


def assess_extraction(d):
    """-> ('empty'|'missing'|'unsure'|'ok', missing_fields). Nothing doubtful is ever saved silently."""
    if not d or not d.get("name"):
        return "empty", []
    has_expiry = bool(d.get("expiry_date")) or (bool(d.get("purchase_date")) and d.get("warranty_months") not in (None, "", 0))
    if not has_expiry:
        miss = []
        if not d.get("purchase_date"):
            miss.append("purchase date")
        if not d.get("warranty_months") and not d.get("expiry_date"):
            miss.append("warranty period")
        return "missing", miss
    if float(d.get("confidence") or 0) < 0.7:
        return "unsure", []
    return "ok", []


def answer_question(items, question):
    slim = [{k: i.get(k) for k in ("id", "name", "category", "store", "purchase_date", "warranty_months",
                                   "expiry_date", "days_left", "amount", "currency", "status")} for i in items]
    system = f"""You are LifeAdmin, a friendly assistant that tracks the user's bills, warranties, insurance and subscriptions.
Today is {today().isoformat()}. The user's records (JSON):
{json.dumps(slim)}

Reply with ONLY a JSON object: {{"reply": string, "claim": null or {{"item_id": string, "issue": string, "draft_text": string}}}}
Rules:
- Answer ONLY from the records above. If something is not there, say so and suggest sending a photo of the bill. Never invent items, dates or amounts.
- "reply" is short plain text (no markdown) with dates like 14 Mar 2027. For spending questions add up the amounts and show the total.
- If the user reports a faulty product, find the matching record. If it is still covered (days_left >= 0), set "claim" and write a polite,
  ready-to-send warranty claim email in "draft_text" (subject, product, store, purchase date, amount, the issue, request for repair or
  replacement, placeholders [Your Name] and [Phone]). Put the draft in "reply" too, with one line saying it is in warranty.
- If the warranty has ended, say so, set "claim" to null, and suggest next steps (paid repair, goodwill request to the store).
- If several records match, ask which one. For greetings, explain: send a bill photo, type add Name | Store | date | months | amount, or ask a question."""
    out = gemini_json(system, [{"text": question}], temperature=0.3)
    valid = {i["id"] for i in items}
    claim = out.get("claim")
    if not (isinstance(claim, dict) and claim.get("item_id") in valid):
        claim = None
    return {"reply": out.get("reply") or "Sorry, I could not answer that.", "claim": claim}


# ------------------------------------------------------------------ reminders / digest
def due_reminders():
    rows = (sb().table("items").select("id,name,store,category,expiry_date,users(telegram_id),reminders(stage)")
            .eq("status", "active").gte("expiry_date", today().isoformat()).execute().data)
    out = []
    for i in rows:
        dl = days_left(i["expiry_date"])
        stage = pick_stage(dl)
        if stage is None or not i.get("users"):
            continue
        if any(r["stage"] == stage for r in (i.get("reminders") or [])):
            continue
        out.append({"item_id": i["id"], "telegram_id": i["users"]["telegram_id"], "stage": stage,
                    "days_left": dl, "text": reminder_text(i, dl)})
    return out


def mark_sent(item_id, stage):
    sb().table("reminders").upsert({"item_id": item_id, "stage": stage}, on_conflict="item_id,stage").execute()


def monthly_digests():
    rows = sb().table("items").select("*, users(telegram_id)").neq("status", "archived").execute().data
    by = {}
    for r in rows:
        if r.get("users"):
            by.setdefault(r["users"]["telegram_id"], []).append(_decorate(r))
    out = []
    for tid, items in by.items():
        soon = sorted([i for i in items if i["status"] == "active" and i["days_left"] is not None and 0 <= i["days_left"] <= 30],
                      key=lambda i: i["days_left"])
        spent = sum(float(i.get("amount") or 0) for i in items
                    if i.get("purchase_date") and 0 <= (today() - parse_date(i["purchase_date"])).days <= 30)
        subs = [i["name"] for i in items if i["category"] == "subscription" and i["status"] == "active"]
        t = "📅 Your monthly LifeAdmin digest\n\n"
        t += ("Ending in the next 30 days:\n" + "\n".join(f"• {i['name']} - {fmt_date(i['expiry_date'])} ({i['days_left']}d)" for i in soon)
              if soon else "Nothing expires in the next 30 days. 🎉")
        t += f"\n\n💸 Added in the last 30 days: {money(spent)}"
        if subs:
            t += f"\n🔁 Active subscriptions: {', '.join(subs)}. Still using all of them?"
        out.append({"telegram_id": tid, "text": t})
    return out
