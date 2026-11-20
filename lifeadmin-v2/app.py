"""LifeAdmin Autopilot - Streamlit web app (same Supabase database as the Telegram bot)."""
import pandas as pd
import requests
import streamlit as st

import core

st.set_page_config(page_title="LifeAdmin Autopilot", page_icon="🧾", layout="wide")

missing = [k for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "GEMINI_KEY") if not core.cfg(k)]
if missing:
    st.error(f"Missing secrets: {', '.join(missing)}. Add them in App > Settings > Secrets.")
    st.stop()

_pw = core.cfg("APP_PASSWORD")
if _pw and not st.session_state.get("authed"):
    st.title("🧾 LifeAdmin Autopilot")
    entered = st.text_input("Password", type="password")
    if entered and entered == _pw:
        st.session_state.authed = True
        st.rerun()
    elif entered:
        st.error("Wrong password.")
    st.stop()

# ---------------------------------------------------------------- sidebar
st.sidebar.title("🧾 LifeAdmin")
st.sidebar.caption("Your bills, warranties and renewals - remembered for you.")
tid_raw = st.sidebar.text_input("Telegram user id", value=str(core.cfg("DEFAULT_TELEGRAM_ID", "111111111")))
if not tid_raw.strip().isdigit():
    st.sidebar.error("Enter your numeric Telegram id (get it from @userinfobot).")
    st.stop()
TID = int(tid_raw)
try:
    UID = core.get_user(TID)["id"]
    ITEMS = core.list_items(UID)
except Exception as e:  # noqa: BLE001
    st.error(f"Could not reach the database: {e}")
    st.stop()
st.sidebar.metric("Tracked items", len(ITEMS))
st.sidebar.caption("Same database as the Telegram bot: items added in either place show up in both.")

st.title("LifeAdmin Autopilot")
tab_add, tab_items, tab_ask, tab_rem = st.tabs(["➕ Add a bill", "📦 My items", "💬 Ask LifeAdmin", "⏰ Reminders"])

# ---------------------------------------------------------------- add
with tab_add:
    st.subheader("Snap a bill, confirm, done")
    st.session_state.setdefault("ver", 0)
    left, right = st.columns([1, 1.2])
    with left:
        up = st.file_uploader("Photo of a bill, receipt or warranty card", type=["jpg", "jpeg", "png"])
        with st.expander("or use the camera"):
            cam = st.camera_input("Take a photo")
        img = up or cam
        if img is not None:
            st.image(img, use_container_width=True)
            if st.button("🔍 Read it with AI", type="primary"):
                with st.spinner("Reading your bill..."):
                    try:
                        raw = img.getvalue()
                        st.session_state.draft = core.extract_bill(raw, img.type or "image/jpeg")
                        st.session_state.draft_img = raw
                        st.session_state.draft_mime = img.type or "image/jpeg"
                        st.session_state.ver += 1
                        st.rerun()
                    except Exception as e:  # noqa: BLE001
                        st.error(f"Could not read the bill: {e}")
    with right:
        d = st.session_state.get("draft") or {}
        if d:
            status, gaps = core.assess_extraction(d)
            conf = float(d.get("confidence") or 0)
            if status == "empty":
                st.error("That doesn't look like a bill or warranty card. Try a clearer photo, or fill the form by hand.")
            elif status in ("missing", "unsure"):
                st.warning(f"I'm not sure about this one (confidence {conf:.0%}" + (f", missing {', '.join(gaps)}" if gaps else "")
                           + "). Please check every field before saving.")
            else:
                st.success(f"Read with confidence {conf:.0%}. Review and save.")
        v = st.session_state.ver
        cat = d.get("category") if d.get("category") in core.CATEGORIES else "other"
        with st.form(f"item_form_{v}"):
            name = st.text_input("Item / service", d.get("name") or "")
            category = st.selectbox("Category", core.CATEGORIES, index=core.CATEGORIES.index(cat))
            store = st.text_input("Store / provider", d.get("store") or "")
            purchase = st.date_input("Purchase date", value=core.parse_date(d.get("purchase_date")) or core.today())
            months = st.number_input("Warranty / validity (months)", 0, 600, int(d.get("warranty_months") or 12))
            amount = st.number_input("Amount (₹)", min_value=0.0, value=float(d.get("amount") or 0.0), step=100.0)
            if st.form_submit_button("💾 Save item", type="primary"):
                try:
                    item = core.add_item(UID, {"name": name, "category": category, "store": store,
                                               "purchase_date": purchase.isoformat(), "warranty_months": int(months),
                                               "amount": float(amount)},
                                         image=st.session_state.get("draft_img"),
                                         mime=st.session_state.get("draft_mime", "image/jpeg"),
                                         confidence=float(d.get("confidence") or 1))
                    for k in ("draft", "draft_img", "draft_mime"):
                        st.session_state.pop(k, None)
                    st.session_state.ver += 1
                    st.success(f"Saved {item['name']}. Covered until {core.fmt_date(item['expiry_date'])}.")
                    st.balloons()
                except Exception as e:  # noqa: BLE001
                    st.error(f"Could not save: {e}")

# ---------------------------------------------------------------- items
with tab_items:
    st.subheader("Everything you are tracking")
    if not ITEMS:
        st.info("Nothing here yet. Add a bill in the first tab.")
    else:
        active = [i for i in ITEMS if i["status"] == "active"]
        soon = [i for i in active if i["days_left"] is not None and 0 <= i["days_left"] <= 30]
        c1, c2, c3 = st.columns(3)
        c1.metric("Items tracked", len(ITEMS))
        c2.metric("Ending in 30 days", len(soon))
        c3.metric("Total value", core.money(sum(float(i.get("amount") or 0) for i in ITEMS)))
        st.dataframe(pd.DataFrame([{
            "Item": i["name"], "Category": i["category"], "Store": i["store"] or "", "Bought": i["purchase_date"],
            "Ends": i["expiry_date"], "Days left": i["days_left"],
            "Status": core.status_icon(i["days_left"]) if i["status"] == "active" else i["status"],
            "Amount": core.money(i["amount"])} for i in ITEMS]), use_container_width=True, hide_index=True)
        with st.expander("Remove an item"):
            labels = [f'{i["name"]} ({i["expiry_date"]})' for i in ITEMS]
            pick = st.selectbox("Item", labels)
            if st.button("🗑️ Delete"):
                core.delete_item(ITEMS[labels.index(pick)]["id"])
                st.rerun()

# ---------------------------------------------------------------- ask
with tab_ask:
    st.subheader("Ask in plain language")
    st.caption('Try: "Is my laptop still in warranty?", "What did I spend on appliances?", "My mixer stopped working"')
    q = st.text_input("Your question")
    if st.button("Ask", type="primary") and q.strip():
        with st.spinner("Thinking..."):
            try:
                st.session_state.answer = core.answer_question(ITEMS, q)
            except Exception as e:  # noqa: BLE001
                st.error(str(e))
    ans = st.session_state.get("answer")
    if ans:
        st.write(ans["reply"])
        if ans["claim"]:
            st.text_area("Draft claim email (edit before sending)", ans["claim"].get("draft_text", ""), height=280)
            if st.button("📨 Mark as claimed and save draft"):
                try:
                    core.add_claim(ans["claim"]["item_id"], ans["claim"].get("issue", ""), ans["claim"].get("draft_text", ""))
                    st.session_state.pop("answer", None)
                    st.success("Claim saved.")
                except Exception as e:  # noqa: BLE001
                    st.error(str(e))

# ---------------------------------------------------------------- reminders
with tab_rem:
    st.subheader("What would you be warned about?")
    st.caption("The Telegram bot sends these automatically at 30, 7, 1 and 0 days before coverage ends.")
    due = [i for i in ITEMS if i["status"] == "active" and i["days_left"] is not None and 0 <= i["days_left"] <= 30]
    if not due:
        st.success("Nothing expires in the next 30 days. 🎉")
    for i in due:
        st.warning(core.reminder_text(i, i["days_left"]))
    token = core.cfg("TELEGRAM_BOT_TOKEN")
    if due and token and st.button("📲 Send these to my Telegram"):
        body = "\n".join(f'• {i["name"]} - {core.fmt_date(i["expiry_date"])} ({i["days_left"]}d)' for i in due)
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": TID, "text": "Ending soon:\n" + body}, timeout=20)
        st.success("Sent!") if r.ok else st.error(f"Telegram error: {r.text[:200]}")
