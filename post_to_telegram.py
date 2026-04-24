#!/usr/bin/env python3
import os
import sys
import requests
from datetime import datetime
import urllib.parse
import time
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
PUBLIC_CHANNEL = "@vlesstrojan"  # Убедитесь, что это правильный юзернейм

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FOLDER = os.path.join(WORK_DIR, "results")
PREMIUM_FOLDER = os.path.join(RESULTS_FOLDER, "premium")
LIGHT_VERIFIED = os.path.join(WORK_DIR, "checked", "latest", "verified.txt")

COVER_PUBLIC = os.path.join(WORK_DIR, "cover_public.jpg")
COVER_PRIVATE = os.path.join(WORK_DIR, "cover_private.jpg")

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---
def load_active_proxies_from_github(url="https://raw.githubusercontent.com/kort0881/telegram-proxy-collector/main/verified/proxy_all_tme_verified.txt", limit=10):
    """Загружает до `limit` прокси из указанного файла."""
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
    """Строит клавиатуру для отправки в Telegram с кнопками копирования."""
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

# --- ОСНОВНЫЕ ФУНКЦИИ ЗАГРУЗКИ КЛЮЧЕЙ (ВАША СУЩЕСТВУЮЩАЯ ЛОГИКА) ---
def clean_key(k: str) -> str:
    k = k.strip()
    if " " in k:
        k = k.split(" ")[0]
    return k

def fix_universal(key: str) -> str:
    # ... (ваша существующая функция без изменений) ...
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

def load_premium_keys():
    # ... (ваша существующая функция без изменений) ...
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

# ... (функции load_fallback_keys, load_light_verified_keys, create_public_file, create_private_file у вас уже есть, они не меняются) ...

# --- ОТПРАВКА В TELEGRAM ---
def send_photo_with_file(channel_id, photo_path, file_path, caption="", bot_token=None):
    url = f"https://api.telegram.org/bot{bot_token}"
    if DRY_RUN:
        print(f"\n[DRY_RUN] sendPhoto + sendDocument -> {channel_id}")
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
    print(" " * 20 + "📤 TELEGRAM POSTER v2")
    print("=" * 70 + "\n")
    if DRY_RUN:
        print("⚙️ Режим DRY_RUN: сообщения в Telegram не отправляются\n")

    # 1. ЗАГРУЖАЕМ КЛЮЧИ (ваша существующая логика)
    all_keys = []
    if os.path.exists(PREMIUM_FOLDER):
        print("📁 Загрузка ключей из results/premium/...")
        all_keys, key_stats = load_premium_keys()
    # ... (добавьте сюда вашу логику fallback, если premium пуст) ...

    if not all_keys:
        print("❌ Нет ключей для постинга")
        return 1

    total_keys = len(all_keys)
    print(f"\n✅ Загружено ключей: {total_keys}")

    # 2. ЗАГРУЖАЕМ ПРОКСИ ДЛЯ КНОПОК
    proxies = load_active_proxies_from_github(limit=10)
    proxies_keyboard = None
    if proxies:
        proxies_keyboard = {"inline_keyboard": build_proxies_keyboard(proxies)}

    # 3. ФОРМИРУЕМ И ОТПРАВЛЯЕМ ПОСТЫ
    # --- Публичный канал ---
    print(f"\n📢 ПУБЛИЧНЫЙ КАНАЛ: {PUBLIC_CHANNEL}")
    public_file, public_count = create_public_file(all_keys, key_stats)  # Ваша функция
    caption = f"🔥 <b>Проверенные прокси-ключи</b>\n\n📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n📦 В файле: <b>{public_count}</b>\n📊 Всего: <b>{total_keys}</b>\n\n📡 VLESS | VMess | Trojan | SS\n\n💬 {PUBLIC_CHANNEL}"
    
    if os.path.exists(COVER_PUBLIC):
        send_photo_with_file(PUBLIC_CHANNEL, COVER_PUBLIC, public_file, caption, BOT_TOKEN_PUBLIC)
    os.remove(public_file)

    # --- Приватный канал ---
    if PRIVATE_CHANNEL:
        print(f"\n🔒 ПРИВАТНЫЙ КАНАЛ: {PRIVATE_CHANNEL}")
        if total_keys > 10:
            private_file, private_count = create_private_file(all_keys, key_stats)  # Ваша функция
            caption_priv = f"🔐 <b>Полный список ключей</b>\n\n📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n📦 В файле: <b>{private_count}</b>\n📊 Всего: <b>{total_keys}</b>"
            if os.path.exists(COVER_PRIVATE):
                send_photo_with_file(PRIVATE_CHANNEL, COVER_PRIVATE, private_file, caption_priv, BOT_TOKEN_PRIVATE)
            os.remove(private_file)

        # Отправляем сообщение с кнопками прокси
        if proxies_keyboard:
            text = "📋 <b>Активные прокси для Telegram</b>\n\nНажмите на кнопку, чтобы скопировать ссылку на прокси и вставить её в настройках Telegram."
            send_message(PRIVATE_CHANNEL, text, BOT_TOKEN_PRIVATE, proxies_keyboard)

    print("\n✅ Скрипт завершил работу")
    return 0

if __name__ == "__main__":
    sys.exit(main())
