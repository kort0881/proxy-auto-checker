#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Poster v3.1
Источник: checked/latest/verified.txt
Каналы: приватный (обязателен) + публичный (опционален)
Cover: cover_private.jpg (fallback → cover_public.jpg)
"""

import os
import sys
import requests
from datetime import datetime, timezone
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ==================== НАСТРОЙКИ ====================
DRY_RUN = os.environ.get("TELEGRAM_DRY_RUN", "0") == "1"

BOT_TOKEN_PRIVATE = os.environ.get("TELEGRAM_BOT_TOKEN")
PRIVATE_CHANNEL = os.environ.get("TELEGRAM_PRIVATE_CHANNEL", "-1002926041814")

BOT_TOKEN_PUBLIC = os.environ.get("TELEGRAM_BOT_TOKEN_PUBLIC")
PUBLIC_CHANNEL = os.environ.get("TELEGRAM_PUBLIC_CHANNEL", "-1002287416438")

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FOLDER = os.path.join(WORK_DIR, "results")
CHECKED_FOLDER = os.path.join(WORK_DIR, "checked", "latest")
VERIFIED_FILE = os.path.join(CHECKED_FOLDER, "verified.txt")

COVER_PRIVATE = os.path.join(WORK_DIR, "cover_private.jpg")
COVER_PUBLIC = os.path.join(WORK_DIR, "cover_public.jpg")
if os.path.exists(COVER_PRIVATE):
    COVER = COVER_PRIVATE
elif os.path.exists(COVER_PUBLIC):
    COVER = COVER_PUBLIC
else:
    COVER = None

SUB_URL = "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/subscriptions_list.txt"


# ==================== HTTP ====================
def make_session():
    s = requests.Session()
    retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("http://", adapter)
    s.mount("https://", adapter)
    return s


session = make_session()


# ==================== LOAD KEYS ====================
def load_verified():
    if not os.path.exists(VERIFIED_FILE):
        print(f"❌ {VERIFIED_FILE} не найден")
        return []
    keys = []
    with open(VERIFIED_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                keys.append(line)
    return keys


# ==================== SUBSCRIPTIONS ====================
def load_subscriptions():
    try:
        r = session.get(SUB_URL, timeout=15)
        if r.status_code != 200:
            print(f"⚠️ Subscriptions: HTTP {r.status_code}")
            return None
        return r.text
    except Exception as e:
        print(f"⚠️ Subscriptions error: {e}")
        return None


def parse_subscription_buttons(text):
    if not text:
        return []
    buttons = []
    in_black = False
    for line in text.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        if line.startswith("==="):
            in_black = ("BLACK" in line) or ("⚠️" in line)
            continue
        if in_black:
            continue
        if line.startswith("http"):
            name = line.split("/")[-1].replace(".txt", "")
            if len(name) > 28:
                name = name[:28] + "..."
            buttons.append({"text": f"📥 {name}", "url": line})
    return buttons[:10]


# ==================== TELEGRAM API ====================
def send_photo_document(channel, photo_path, doc_path, caption, token):
    if DRY_RUN:
        print(f"\n[DRY_RUN] sendPhoto+sendDocument -> {channel}")
        print(f"Cover: {photo_path}")
        print(f"Doc: {doc_path}")
        print(f"Caption:\n{caption}\n")
        return {"ok": True}

    try:
        with open(photo_path, "rb") as photo:
            r = session.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": channel, "caption": caption, "parse_mode": "HTML"},
                files={"photo": photo},
                timeout=60
            )
            photo_res = r.json()
    except Exception as e:
        print(f"❌ sendPhoto: {e}")
        return None

    if not photo_res.get("ok"):
        print(f"❌ sendPhoto failed: {photo_res}")
        return None

    msg_id = photo_res["result"]["message_id"]

    try:
        with open(doc_path, "rb") as doc:
            r = session.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": channel, "reply_to_message_id": msg_id},
                files={"document": doc},
                timeout=120
            )
            return r.json()
    except Exception as e:
        print(f"❌ sendDocument: {e}")
        return None


def send_document_only(channel, doc_path, caption, token):
    if DRY_RUN:
        print(f"\n[DRY_RUN] sendDocument -> {channel}")
        return {"ok": True}
    try:
        with open(doc_path, "rb") as doc:
            r = session.post(
                f"https://api.telegram.org/bot{token}/sendDocument",
                data={"chat_id": channel, "caption": caption, "parse_mode": "HTML"},
                files={"document": doc},
                timeout=120
            )
            return r.json()
    except Exception as e:
        print(f"❌ sendDocument: {e}")
        return None


def send_message(channel, text, token, reply_markup=None):
    if DRY_RUN:
        print(f"\n[DRY_RUN] sendMessage -> {channel}\nText:\n{text}")
        return {"ok": True}
    payload = {
        "chat_id": channel,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        r = session.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json=payload, timeout=30
        )
        return r.json()
    except Exception as e:
        print(f"❌ sendMessage: {e}")
        return None


# ==================== CAPTION ====================
def build_caption(num_keys, is_public=False):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M')
    base = (
        f"🔥 <b>Проверенные прокси-ключи</b>\n\n"
        f"📅 <code>{ts} UTC</code>\n"
        f"📦 В файле: <b>{num_keys}</b>\n"
        f"✅ TCP → Xray → 5/7 категорий → Reconnect\n\n"
        f"📡 VLESS | VMess | Trojan | SS"
    )
    if is_public:
        base += (
            f"\n\n⚠️ Материал собран из открытых источников сети Интернет, "
            f"предоставляется в ознакомительных целях.\n"
            f"Клиенты: v2rayNG · Clash · Hiddify · Shadowrocket"
        )
    return base


# ==================== PUBLISH ====================
def publish_to(channel, token, keys, subs_buttons, label, is_public=False):
    """Публикует пост (фото+файл+кнопки) в указанный канал. True если всё ок."""
    if not token:
        print(f"⚠️ [{label}] токен не задан — пропускаю канал {channel}")
        return False
    if not channel:
        print(f"⚠️ [{label}] chat_id не задан — пропускаю")
        return False

    print(f"\n[{label}] → {channel}")

    caption = build_caption(len(keys), is_public=is_public)

    if COVER:
        result = send_photo_document(channel, COVER, VERIFIED_FILE, caption, token)
    else:
        print(f"⚠️ [{label}] обложка не найдена, шлю только документ")
        result = send_document_only(channel, VERIFIED_FILE, caption, token)

    if not result or not result.get("ok"):
        print(f"❌ [{label}] ошибка публикации файла: {result}")
        return False

    print(f"✅ [{label}] пост с обложкой и файлом отправлен")

    if subs_buttons:
        keyboard = []
        row = []
        for btn in subs_buttons:
            row.append(btn)
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        send_message(
            channel,
            "📋 <b>Ссылки на подписки</b>\n\n💡 Нажми на кнопку — ссылка скопируется в буфер, вставь в Hiddify / v2rayNG / Clash",
            token,
            {"inline_keyboard": keyboard}
        )
        print(f"✅ [{label}] кнопки подписок: {len(subs_buttons)}")

    return True


# ==================== MAIN ====================
def main():
    if not BOT_TOKEN_PRIVATE:
        print("❌ TELEGRAM_BOT_TOKEN (приватный) не задан")
        return 1

    print("\n" + "=" * 60)
    print("  Telegram Poster v3.1")
    print(f"  Private: {PRIVATE_CHANNEL}")
    print(f"  Public : {PUBLIC_CHANNEL if BOT_TOKEN_PUBLIC else '— (нет токена)'}")
    print(f"  Cover  : {COVER or 'NO COVER'}")
    print(f"  Source : {VERIFIED_FILE}")
    print("=" * 60 + "\n")

    if DRY_RUN:
        print("⚙️ DRY_RUN режим — сообщения не отправляются\n")

    keys = load_verified()
    if not keys:
        print("❌ Нет ключей — пропускаем публикацию")
        return 0

    print(f"✅ Ключей: {len(keys)}")

    subs_text = load_subscriptions()
    subs_buttons = parse_subscription_buttons(subs_text)
    print(f"✅ Кнопок подписок: {len(subs_buttons)}")

    # 1. Приватный канал (обязателен)
    ok_private = publish_to(
        PRIVATE_CHANNEL, BOT_TOKEN_PRIVATE,
        keys, subs_buttons, label="PRIVATE", is_public=False
    )
    if not ok_private:
        print("❌ Приватная публикация провалилась")
        return 1

    # 2. Публичный канал (опционален)
    if BOT_TOKEN_PUBLIC:
        ok_public = publish_to(
            PUBLIC_CHANNEL, BOT_TOKEN_PUBLIC,
            keys, subs_buttons, label="PUBLIC", is_public=True
        )
        if not ok_public:
            print("⚠️ Публичная публикация не удалась (приват прошёл)")
    else:
        print("\nℹ️ TELEGRAM_BOT_TOKEN_PUBLIC не задан — публичный канал пропущен")

    print("\n✅ Готово")
    return 0


if __name__ == "__main__":
    sys.exit(main())
