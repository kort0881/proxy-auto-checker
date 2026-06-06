#!/usr/bin/env python3
import os
import sys
import requests
import base64
from datetime import datetime
import urllib.parse
import time
import random
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- НАСТРОЙКИ УСТОЙЧИВОСТИ ---
def get_robust_session(retries=3, backoff_factor=1):
    session = requests.Session()
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session

robust_session = get_robust_session()

# --- КОНФИГУРАЦИЯ ИЗ ПЕРЕМЕННЫХ ОКРУЖЕНИЯ ---
DRY_RUN = os.environ.get("TELEGRAM_DRY_RUN", "0") == "1"

BOT_TOKEN_PUBLIC = os.environ.get('TELEGRAM_BOT_TOKEN_PUBLIC')
BOT_TOKEN_PRIVATE = os.environ.get('TELEGRAM_BOT_TOKEN')
PRIVATE_CHANNEL = os.environ.get('TELEGRAM_PRIVATE_CHANNEL')
PUBLIC_CHANNEL = "@vlesstrojan"

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FOLDER = os.path.join(WORK_DIR, "results")
PREMIUM_FOLDER = os.path.join(RESULTS_FOLDER, "premium")
LIGHT_VERIFIED = os.path.join(WORK_DIR, "checked", "latest", "verified.txt")

COVER_PUBLIC = os.path.join(WORK_DIR, "cover_public.jpg")
COVER_PRIVATE = os.path.join(WORK_DIR, "cover_private.jpg")

# Локальные цитаты
QUOTES_FILE = os.path.join(WORK_DIR, "data", "quotes_ru.txt")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def clean_key(k: str) -> str:
    k = k.strip()
    if " " in k:
        k = k.split(" ")[0]
    return k

def fix_universal(key: str) -> str:
    key = key.strip()
    if not key.startswith("vless://") or "type=xhttp" not in key:
        return key
    try:
        parsed = urllib.parse.urlparse(key)
        query = urllib.parse.parse_qs(parsed.query)
        if query.get("type", [""])[0].lower() == "xhttp":
            query["type"] = ["http"]
        new_query = urllib.parse.urlencode(query, doseq=True)
        return urllib.parse.urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                new_query,
                parsed.fragment,
            )
        )
    except Exception:
        return key

# ---------- ЗАГРУЗКА КЛЮЧЕЙ ----------
def load_premium_keys():
    all_keys = []
    stats = {"elite": 0, "premium": 0, "good": 0}
    priority_files = [
        ("elite.txt", "elite"),
        ("premium.txt", "premium"),
        ("good.txt", "good"),
    ]
    for filename, category in priority_files:
        filepath = os.path.join(PREMIUM_FOLDER, filename)
        if not os.path.exists(filepath):
            print(f"  ⚠️ {filename} не найден")
            continue
        count = 0
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    key = fix_universal(clean_key(line))
                    if key:
                        all_keys.append(key)
                        count += 1
        stats[category] = count
        print(f"  ✅ {filename}: {count} ключей")
    return all_keys, stats

def load_fallback_keys():
    verified_files = [
        f for f in os.listdir(RESULTS_FOLDER)
        if f.startswith("verified_") and f.endswith(".txt")
    ]
    semi_dead_files = [
        f for f in os.listdir(RESULTS_FOLDER)
        if f.startswith("semi_dead_") and f.endswith(".txt")
    ]
    if verified_files:
        latest = max(
            verified_files,
            key=lambda f: os.path.getmtime(os.path.join(RESULTS_FOLDER, f)),
        )
        source = "verified"
    elif semi_dead_files:
        latest = max(
            semi_dead_files,
            key=lambda f: os.path.getmtime(os.path.join(RESULTS_FOLDER, f)),
        )
        source = "semi_dead"
    else:
        return [], None, None
    filepath = os.path.join(RESULTS_FOLDER, latest)
    keys = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                key = fix_universal(clean_key(line))
                if key:
                    keys.append(key)
    return keys, latest, source

def load_light_verified_keys():
    if not os.path.exists(LIGHT_VERIFIED):
        return []
    keys = []
    with open(LIGHT_VERIFIED, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#"):
                key = fix_universal(clean_key(line))
                if key:
                    keys.append(key)
    return keys

def load_paid_keys():
    paid_file = os.path.join(RESULTS_FOLDER, "paid.txt")
    if not os.path.exists(paid_file):
        print("ℹ️ Файл с ключами alekscloud не найден, пропускаем.")
        return []
    with open(paid_file, "r", encoding="utf-8") as f:
        keys = [clean_key(line) for line in f if line.strip() and not line.startswith("#")]
    print(f"🔒 Загружено ключей от alekscloud: {len(keys)}")
    return keys

# ---------- ФУНКЦИИ ДЛЯ ФАЙЛОВ ----------
def create_public_file(all_keys, stats=None):
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"public_top200_{date_str}.txt"
    filepath = os.path.join(RESULTS_FOLDER, filename)
    top_keys = all_keys[:200]
    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Channel: @vlesstrojan\n")
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write("# Verified: Triple-check (TCP + XRAY + Categories)\n")
        f.write(f"# Total: {len(top_keys)}\n\n")
        for key in top_keys:
            f.write(key + "\n")
    return filepath, len(top_keys)

def create_private_file(all_keys, stats=None):
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"private_all_{date_str}.txt"
    filepath = os.path.join(RESULTS_FOLDER, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write("# Verified: Triple-check (TCP + XRAY + Categories)\n")
        f.write(f"# Keys in file: {len(all_keys)}\n")
        f.write(f"# Total: {len(all_keys)}\n\n")
        for key in all_keys:
            f.write(key + "\n")
    return filepath, len(all_keys)

def create_paid_file(keys):
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"alekscloud_keys_{date_str}.txt"
    filepath = os.path.join(RESULTS_FOLDER, filename)
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# Ключи от alekscloud (AuraVPN)\n")
        f.write(f"# Дата: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write(f"# Предоставлены нашим подписчиком\n")
        f.write(f"# Всего ключей: {len(keys)}\n\n")
        for key in keys:
            f.write(key + "\n")
    return filepath, len(keys)

def safe_remove(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except OSError as e:
        print(f"⚠️ Не удалось удалить {filepath}: {e}")

# ---------- ЦИТАТЫ ----------
def get_local_quote():
    if not os.path.exists(QUOTES_FILE):
        return None
    with open(QUOTES_FILE, "r", encoding="utf-8") as f:
        quotes = [q.strip() for q in f if q.strip()]
    if not quotes:
        return None
    return random.choice(quotes)

# ---------- ПОДПИСКИ (через GitHub API, без кэша) ----------
def load_subscriptions():
    API_URL = "https://api.github.com/repos/kort0881/vpn-checker-backend/contents/checked/subscriptions_list.txt"
    try:
        resp = robust_session.get(API_URL, timeout=15)
        if resp.status_code != 200:
            print(f"⚠️ Не удалось получить подписки через API: HTTP {resp.status_code}")
            return None
        data = resp.json()
        content = base64.b64decode(data["content"]).decode("utf-8")
        if not content.strip():
            print("⚠️ Подписки пустые")
            return None
        return content
    except Exception as e:
        print(f"❌ Ошибка загрузки подписок через API: {e}")
        return None

def parse_subscriptions_for_buttons(subscriptions_text):
    if not subscriptions_text:
        return []
    lines = subscriptions_text.strip().split("\n")
    buttons = []
    in_black_block = False
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("==="):
            in_black_block = ("BLACK" in line) or ("⚠️" in line)
            continue
        if in_black_block:
            continue
        if line.startswith("http"):
            filename = line.split("/")[-1].replace(".txt", "")
            btn_text = f"📥 {filename}"
            btn_text = btn_text[:32]
            buttons.append({"text": btn_text, "url": line})
    return buttons

# ---------- ПРОКСИ ----------
def load_active_proxies_from_github(url="https://raw.githubusercontent.com/kort0881/telegram-proxy-collector/main/verified/proxy_all_tme_verified.txt", limit=10):
    try:
        resp = robust_session.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"⚠️ Не удалось загрузить активные прокси: HTTP {resp.status_code}")
            return []
        lines = resp.text.strip().split('\n')
        proxies = []
        for line in lines:
            line = line.strip()
            if line and not line.startswith('#'):
                proxies.append(line)
                if len(proxies) >= limit:
                    break
        print(f"✅ Загружено {len(proxies)} активных прокси из {url}")
        return proxies
    except Exception as e:
        print(f"❌ Ошибка загрузки активных прокси: {e}")
        return []

def build_proxies_keyboard(proxies):
    keyboard = []
    row = []
    for i, proxy in enumerate(proxies, start=1):
        btn_text = f"🔑 Прокси {i}"
        button = {"text": btn_text, "copy_text": {"text": proxy}}
        row.append(button)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return keyboard

# ---------- ОТПРАВКА В TELEGRAM ----------
def send_photo_with_file(channel_id, photo_path, file_path, caption="", bot_token=None):
    url = f"https://api.telegram.org/bot{bot_token}"
    if DRY_RUN:
        print(f"\n[DRY_RUN] sendPhoto + sendDocument -> {channel_id}")
        print(f"Caption:\n{caption}\n")
        print(f"File: {file_path}")
        return {"ok": True}
    try:
        with open(photo_path, "rb") as photo:
            files = {"photo": photo}
            data = {"chat_id": channel_id, "caption": caption, "parse_mode": "HTML"}
            r = robust_session.post(f"{url}/sendPhoto", data=data, files=files, timeout=60)
            photo_result = r.json()
        if photo_result.get("ok"):
            message_id = photo_result["result"]["message_id"]
            with open(file_path, "rb") as doc:
                files = {"document": doc}
                data = {"chat_id": channel_id, "reply_to_message_id": message_id}
                r = robust_session.post(f"{url}/sendDocument", data=data, files=files, timeout=120)
                return r.json()
        return photo_result
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return None

def send_document(chat_id, file_path, caption="", bot_token=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendDocument"
    if DRY_RUN:
        print(f"\n[DRY_RUN] sendDocument -> {chat_id}")
        print(f"Caption: {caption}\nFile: {file_path}")
        return {"ok": True}
    with open(file_path, "rb") as f:
        files = {"document": f}
        data = {"chat_id": chat_id, "caption": caption, "parse_mode": "HTML"}
        try:
            r = robust_session.post(url, data=data, files=files, timeout=60)
            return r.json()
        except Exception as e:
            print(f"❌ Ошибка отправки документа: {e}")
            return None

def send_message(channel_id, text, bot_token, reply_markup=None):
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    if DRY_RUN:
        print(f"\n[DRY_RUN] sendMessage -> {channel_id}\nText:\n{text}")
        return {"ok": True}
    try:
        payload = {
            "chat_id": channel_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        r = robust_session.post(url, json=payload, timeout=30)
        return r.json()
    except Exception as e:
        print(f"❌ Ошибка отправки сообщения: {e}")
        return None

# --- ОСНОВНАЯ ЛОГИКА ---
def main():
    if not BOT_TOKEN_PUBLIC or not BOT_TOKEN_PRIVATE:
        print("❌ Ошибка: не установлены TELEGRAM_BOT_TOKEN_PUBLIC или TELEGRAM_BOT_TOKEN")
        return 1

    print("\n" + "=" * 70)
    print(" " * 20 + "📤 TELEGRAM POSTER v2 (API version)")
    print("=" * 70 + "\n")
    if DRY_RUN:
        print("⚙️ Режим DRY_RUN: сообщения в Telegram не отправляются\n")

    if not os.path.exists(RESULTS_FOLDER):
        print(f"❌ Папка {RESULTS_FOLDER} не существует")
        return 1

    # 1. ЗАГРУЗКА КЛЮЧЕЙ
    all_keys = []
    key_stats = None
    source_info = ""

    if os.path.exists(PREMIUM_FOLDER):
        print("📁 Ищем ключи в results/premium/...")
        all_keys, key_stats = load_premium_keys()
        if all_keys:
            source_info = "results/premium (elite + premium + good)"
            print(f"\n✅ Загружено из results/premium: {len(all_keys)} ключей")
            print(f"   Elite: {key_stats['elite']} | Premium: {key_stats['premium']} | Good: {key_stats['good']}")

    if not all_keys:
        print("\n📁 Premium пусто, ищем verified/semi_dead...")
        all_keys, filename, source = load_fallback_keys()
        if all_keys:
            source_info = f"{source} ({filename})"
            print(f"✅ Fallback: {len(all_keys)} ключей из {filename}")
        else:
            print("⚠️ verified/semi_dead нет, пробуем checked/latest/verified.txt...")
            all_keys = load_light_verified_keys()
            if all_keys:
                source_info = "checked/latest/verified.txt (TCP-only)"
                print(f"✅ Fallback: {len(all_keys)} ключей из checked/latest/verified.txt")
            else:
                print("❌ Нет файлов с ключами")
                return 1

    total_keys = len(all_keys)
    print(f"\n📦 Всего ключей: {total_keys}")
    print(f"📂 Источник: {source_info}\n")

    # 2. ПОДПИСКИ И ПРОКСИ
    subscriptions_raw = load_subscriptions()
    subscriptions_buttons = parse_subscriptions_for_buttons(subscriptions_raw)
    proxies = load_active_proxies_from_github(limit=10)
    proxies_keyboard = build_proxies_keyboard(proxies) if proxies else None

    # 3. ПУБЛИЧНЫЙ КАНАЛ
    print("=" * 70)
    print(f"📢 ПУБЛИЧНЫЙ КАНАЛ: {PUBLIC_CHANNEL}")
    print("=" * 70 + "\n")

    public_file, public_count = create_public_file(all_keys, key_stats)
    caption = (f"🔥 <b>Проверенные прокси-ключи</b>\n\n"
               f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
               f"📦 В файле: <b>{public_count}</b>\n"
               f"📊 Всего ключей: <b>{total_keys}</b>\n\n"
               f"📡 VLESS | VMess | Trojan | SS\n\n"
               f"💬 {PUBLIC_CHANNEL}")

    if os.path.exists(COVER_PUBLIC):
        result = send_photo_with_file(PUBLIC_CHANNEL, COVER_PUBLIC, public_file, caption, BOT_TOKEN_PUBLIC)
        if result and result.get("ok"):
            print("✅ Пост (паблик) сформирован")
        else:
            error_msg = result.get("description", "Unknown error") if result else "No response"
            print(f"❌ Ошибка: {error_msg}")
    else:
        print("⚠️ Нет картинки для публичного канала")
    safe_remove(public_file)

    # Пост с подписками (публичный)
    if subscriptions_buttons:
        keyboard = []
        row = []
        for btn in subscriptions_buttons:
            row.append({"text": btn["text"], "copy_text": {"text": btn["url"]}})
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)
        subs_text = ("📋 <b>Ссылки на подписки</b>\n\n"
                     f"💬 <i>{get_local_quote() or 'Лучше один рабочий ключ, чем сто мёртвых.'}</i>\n\n"
                     "💡 Нажми на кнопку ниже — ссылка скопируется в буфер, вставь её в Hiddify, v2rayNG или Clash")
        send_message(PUBLIC_CHANNEL, subs_text, BOT_TOKEN_PUBLIC, {"inline_keyboard": keyboard})

    # Донат-пост (публичный)
    donate_text = ("Если хочешь поддержать автора — можно перевести:\n"
                   "Сбербанк: <code>4276 3801 7277 1425</code>\n"
                   "Не указывайте за что перевод. ✨\n"
                   "Спасибо за любую помощь! ❗️")
    send_message(PUBLIC_CHANNEL, donate_text, BOT_TOKEN_PUBLIC)

    # 4. ПРИВАТНЫЙ КАНАЛ
    if PRIVATE_CHANNEL:
        print("\n" + "=" * 70)
        print(f"🔒 ПРИВАТНЫЙ КАНАЛ: {PRIVATE_CHANNEL}")
        print("=" * 70 + "\n")

        if total_keys > 10:
            private_file, private_count = create_private_file(all_keys, key_stats)
            caption_priv = (f"🔐 <b>Полный список ключей</b>\n\n"
                            f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
                            f"📦 В файле: <b>{private_count}</b> ключей\n"
                            f"📊 Всего ключей: <b>{total_keys}</b>\n\n"
                            f"📡 VLESS | VMess | Trojan | SS")
            if os.path.exists(COVER_PRIVATE):
                send_photo_with_file(PRIVATE_CHANNEL, COVER_PRIVATE, private_file, caption_priv, BOT_TOKEN_PRIVATE)
            safe_remove(private_file)

        # ---- КЛЮЧИ ОТ ALEKSCLOUD ----
        paid_keys = load_paid_keys()
        if paid_keys:
            count = len(paid_keys)
            if count <= 3:
                keys_html = "\n\n".join(f"<code>{k}</code>" for k in paid_keys)
                caption = (
                    f"✨ <b>Ключи от alekscloud (AuraVPN)</b>\n\n"
                    f"🤝 <i>Предоставлены нашим подписчиком</i>\n"
                    f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"📦 Ключей: {count}\n\n"
                    f"{keys_html}\n\n"
                    f"Спасибо alekscloud!"
                )
                send_message(PRIVATE_CHANNEL, caption, BOT_TOKEN_PRIVATE)
            else:
                first_three_html = "\n\n".join(f"<code>{k}</code>" for k in paid_keys[:3])
                caption_part = (
                    f"✨ <b>Ключи от alekscloud (AuraVPN)</b>\n\n"
                    f"🤝 <i>Предоставлены нашим подписчиком</i>\n"
                    f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"📦 Всего ключей: {count}\n\n"
                    f"<b>Первые 3 ключа:</b>\n\n{first_three_html}\n\n"
                    f"🔽 Полный список – в приложенном файле."
                )
                send_message(PRIVATE_CHANNEL, caption_part, BOT_TOKEN_PRIVATE)

                paid_file, paid_count = create_paid_file(paid_keys)
                caption_file = f"📎 Все {count} ключей от alekscloud"
                if os.path.exists(COVER_PRIVATE):
                    send_photo_with_file(PRIVATE_CHANNEL, COVER_PRIVATE, paid_file, caption_file, BOT_TOKEN_PRIVATE)
                else:
                    send_document(PRIVATE_CHANNEL, paid_file, caption_file, BOT_TOKEN_PRIVATE)
                safe_remove(paid_file)

        # Подписки (приват)
        if subscriptions_buttons:
            keyboard = []
            row = []
            for btn in subscriptions_buttons:
                row.append({"text": btn["text"], "copy_text": {"text": btn["url"]}})
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)
            subs_text = ("📋 <b>Ссылки на подписки</b>\n\n"
                         f"💬 <i>{get_local_quote() or 'Лучше один рабочий ключ, чем сто мёртвых.'}</i>\n\n"
                         "🎯 Нажми на кнопку ниже — ссылка скопируется в буфер, импортируй в клиент")
            send_message(PRIVATE_CHANNEL, subs_text, BOT_TOKEN_PRIVATE, {"inline_keyboard": keyboard})

        # Активные прокси кнопками (приват)
        if proxies_keyboard:
            text = ("📋 <b>Активные прокси для Telegram</b>\n\n"
                    "Нажмите на кнопку, чтобы скопировать ссылку на прокси и вставить её в настройках Telegram.\n\n"
                    "Все прокси проверены и активны.")
            send_message(PRIVATE_CHANNEL, text, BOT_TOKEN_PRIVATE, {"inline_keyboard": proxies_keyboard})

    print("\n✅ Скрипт завершил работу")
    return 0

if __name__ == "__main__":
    sys.exit(main())
if __name__ == "__main__":
    sys.exit(main())
