import os
import sys
import requests
from datetime import datetime
import urllib.parse
import random

# Флаг сухого прогона: если TELEGRAM_DRY_RUN=1, то ничего не отправляем в ТГ
DRY_RUN = os.environ.get("TELEGRAM_DRY_RUN", "0") == "1"

# ВАШИ СЕКРЕТЫ ИЗ GITHUB
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

# Локальные фразы
QUOTES_FILE = os.path.join(WORK_DIR, "data", "quotes_ru.txt")
QUOTES_INDEX_FILE = os.path.join(WORK_DIR, "data", "quotes_index.txt")

EMOJIS = ["⚙️", "🔒", "🚀", "✨", "💎", "🔥", "🌐", "🔑"]

WARNING_TEXT = (
    "⚠️ Материал взят из открытых источников сети Интернет.\n"
    "Информация предоставляется в ознакомительных целях.\n"
    "Все данные получены легальными методами.\n\n"
)

CLIENTS = "Клиенты: v2rayNG · Clash · Hiddify · Shadowrocket\n"
TAGS = "#прокси #v2ray #vmess #vless #shadowsocks #vpn"

SUBSCRIPTIONS_URL = (
    "https://raw.githubusercontent.com/"
    "kort0881/vpn-checker-backend/refs/heads/main/checked/subscriptions_list.txt"
)

# ---------- Функции для работы с подписками ----------
def load_subscriptions():
    try:
        resp = requests.get(SUBSCRIPTIONS_URL, timeout=15)
        if resp.status_code != 200:
            print(f"⚠️ Не удалось получить подписки: HTTP {resp.status_code}")
            return None
        content = resp.text.strip()
        if not content:
            print("⚠️ Подписки пустые")
            return None
        return content
    except Exception as e:
        print(f"❌ Ошибка загрузки подписок: {e}")
        return None

def format_subscriptions_for_telegram(subscriptions_text):
    """Текстовые заголовки блоков не показываем — весь текст через цитату."""
    return ""

def parse_subscriptions_for_buttons(subscriptions_text):
    """Делаем кнопки только для неблэк-блоков."""
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

# ---------- Цитаты ----------
def get_remote_quote():
    try:
        resp = requests.get(
            "http://api.forismatic.com/api/1.0/",
            params={"method": "getQuote", "format": "json", "lang": "ru"},
            timeout=5,
        )
        data = resp.json()
        text = (data.get("quoteText") or "").strip()
        if not text:
            return None
        return text
    except Exception as e:
        print(f"⚠️ Forismatic error: {e}")
        return None

def get_local_quote():
    if not os.path.exists(QUOTES_FILE):
        return None

    with open(QUOTES_FILE, "r", encoding="utf-8") as f:
        quotes = [q.strip() for q in f if q.strip()]

    if not quotes:
        return None

    idx = 0
    if os.path.exists(QUOTES_INDEX_FILE):
        try:
            with open(QUOTES_INDEX_FILE, "r", encoding="utf-8") as f:
                idx = int(f.read().strip() or "0")
        except Exception:
            idx = 0

    quote = quotes[idx % len(quotes)]

    try:
        with open(QUOTES_INDEX_FILE, "w", encoding="utf-8") as f:
            f.write(str((idx + 1) % len(quotes)))
    except Exception as e:
        print(f"⚠️ Не удалось сохранить индекс цитаты: {e}")

    return quote

# ---------- Обработка ключей ----------
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

# ---------- Активные прокси из GitHub ----------
def load_active_proxies_from_github(url="https://raw.githubusercontent.com/kort0881/telegram-proxy-collector/main/verified/proxy_all_tme_verified.txt", limit=10):
    """Загружает до `limit` прокси из указанного файла (каждая строка - прокси)."""
    try:
        resp = requests.get(url, timeout=15)
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
    """Строит клавиатуру: 5 строк по 2 кнопки (копирование текста)."""
    keyboard = []
    row = []
    for i, proxy in enumerate(proxies, start=1):
        btn_text = f"🔑 Прокси {i}"
        button = {
            "text": btn_text,
            "copy_text": {"text": proxy}
        }
        row.append(button)
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    return keyboard

# ---------- Отправка ----------
def send_photo_with_file(channel_id, photo_path, file_path, caption="", bot_token=None):
    url = f"https://api.telegram.org/bot{bot_token}"

    if DRY_RUN:
        print(f"\n[DRY_RUN] sendPhoto + sendDocument -> {channel_id}")
        print(f"[DRY_RUN] Caption:\n{caption}\n")
        print(f"[DRY_RUN] File: {file_path}")
        return {"ok": True}

    try:
        with open(photo_path, "rb") as photo:
            files = {"photo": photo}
            data = {
                "chat_id": channel_id,
                "caption": caption,
                "parse_mode": "HTML",
            }
            r = requests.post(
                f"{url}/sendPhoto",
                data=data,
                files=files,
                timeout=30,
            )
            photo_result = r.json()

        if photo_result.get("ok"):
            message_id = photo_result["result"]["message_id"]

            with open(file_path, "rb") as doc:
                files = {"document": doc}
                data = {"chat_id": channel_id, "reply_to_message_id": message_id}
                r = requests.post(
                    f"{url}/sendDocument",
                    data=data,
                    files=files,
                    timeout=60,
                )
                return r.json()

        return photo_result

    except requests.Timeout:
        print("❌ Таймаут при отправке")
        return None
    except Exception as e:
        print(f"❌ Ошибка отправки: {e}")
        return None

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

def safe_remove(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except OSError as e:
        print(f"⚠️ Не удалось удалить {filepath}: {e}")

# ---------- MAIN ----------
def main():
    if not BOT_TOKEN_PUBLIC:
        print("❌ TELEGRAM_BOT_TOKEN_PUBLIC не установлен")
        return 1
    if not BOT_TOKEN_PRIVATE:
        print("❌ TELEGRAM_BOT_TOKEN не установлен")
        return 1

    print("\n" + "=" * 70)
    print(" " * 20 + "📤 TELEGRAM POSTER v2")
    print("=" * 70 + "\n")
    if DRY_RUN:
        print("⚙️ Режим DRY_RUN: сообщения в Telegram отправляться не будут\n")

    if not os.path.exists(RESULTS_FOLDER):
        print(f"❌ Папка {RESULTS_FOLDER} не существует")
        return 1

    # Подписки (общие для обоих каналов)
    subscriptions_raw = load_subscriptions()
    subscriptions_formatted = format_subscriptions_for_telegram(subscriptions_raw)
    subscriptions_buttons = parse_subscriptions_for_buttons(subscriptions_raw)

    # ============== ЗАГРУЗКА КЛЮЧЕЙ (для файлов и публичного канала) ==============
    all_keys = []
    key_stats = None
    source_info = ""

    # 1) Premium
    if os.path.exists(PREMIUM_FOLDER):
        print("📁 Ищем ключи в results/premium/...")
        all_keys, key_stats = load_premium_keys()
        if all_keys:
            source_info = "results/premium (elite + premium + good)"
            print(f"\n✅ Загружено из results/premium: {len(all_keys)} ключей")
            print(f"   Elite: {key_stats['elite']} | Premium: {key_stats['premium']} | Good: {key_stats['good']}")

    # 2) verified/semi_dead
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

    if total_keys == 0:
        print("❌ Нет ключей для постинга")
        return 1

    # ========== ПУБЛИЧНЫЙ КАНАЛ ==========
    print("=" * 70)
    print(f"📢 ПУБЛИЧНЫЙ КАНАЛ: {PUBLIC_CHANNEL}")
    print("=" * 70 + "\n")

    public_file, public_count = create_public_file(all_keys, key_stats)

    caption = "🔥 <b>Проверенные прокси-ключи</b>\n\n"
    caption += f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
    caption += f"📦 В файле: <b>{public_count}</b>\n"
    caption += f"📊 Всего ключей: <b>{total_keys}</b>\n\n"
    caption += "📡 VLESS | VMess | Trojan | SS\n\n"
    caption += f"💬 {PUBLIC_CHANNEL}\n\n"
    # Раздел реакций УДАЛЁН

    if os.path.exists(COVER_PUBLIC):
        result = send_photo_with_file(
            PUBLIC_CHANNEL,
            COVER_PUBLIC,
            public_file,
            caption,
            bot_token=BOT_TOKEN_PUBLIC,
        )
        if result and result.get("ok"):
            print(f"✅ Пост (паблик) сформирован")
        else:
            error_msg = result.get("description", "Unknown error") if result else "No response"
            print(f"❌ Ошибка: {error_msg}")
    else:
        print("⚠️ Нет картинки для публичного канала")

    safe_remove(public_file)

    # Пост с подписками в публичный канал
    if subscriptions_buttons:
        keyboard = []
        row = []
        for btn in subscriptions_buttons:
            row.append(
                {
                    "text": btn["text"],
                    "copy_text": {"text": btn["url"]},
                }
            )
            if len(row) == 2:
                keyboard.append(row)
                row = []
        if row:
            keyboard.append(row)

        subs_text = "📋 <b>Ссылки на подписки</b>\n\n"
        quote = get_remote_quote() or get_local_quote() or "Лучше один рабочий ключ, чем сто мёртвых."
        subs_text += f"💬 <i>{quote}</i>\n\n"
        subs_text += "💡 Нажми на кнопку ниже — ссылка скопируется в буфер, вставь её в Hiddify, v2rayNG или Clash"

        if DRY_RUN:
            print("\n[DRY_RUN] sendMessage (public subscriptions)")
            print("Text:\n", subs_text)
        else:
            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN_PUBLIC}/sendMessage",
                    json={
                        "chat_id": PUBLIC_CHANNEL,
                        "text": subs_text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                        "reply_markup": {"inline_keyboard": keyboard},
                    },
                    timeout=15,
                )
                if resp.json().get("ok"):
                    print("✅ Пост с подписками (public) отправлен")
                else:
                    print(f"❌ Ошибка поста с подписками (public): {resp.json().get('description')}")
            except Exception as e:
                print(f"❌ Ошибка отправки подписок (public): {e}")

    # Донат-пост
    donate_text = (
        "Если хочешь поддержать автора — можно перевести:\n"
        "Сбербанк: <code>4276 3801 7277 1425</code>\n"
        "Не указывайте за что перевод. ✨\n"
        "Спасибо за любую помощь! ❗️"
    )
    if DRY_RUN:
        print("\n[DRY_RUN] sendMessage (donate)")
        print("Text:\n", donate_text)
    else:
        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN_PUBLIC}/sendMessage",
                json={
                    "chat_id": PUBLIC_CHANNEL,
                    "text": donate_text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if resp.json().get("ok"):
                print("✅ Донат-пост отправлен")
        except Exception as e:
            print(f"❌ Ошибка отправки донат-поста: {e}")

    # ========== ПРИВАТНЫЙ КАНАЛ ==========
    if PRIVATE_CHANNEL:
        print("\n" + "=" * 70)
        print(f"🔒 ПРИВАТНЫЙ КАНАЛ: {PRIVATE_CHANNEL}")
        print("=" * 70 + "\n")

        # ---- Файл со всеми ключами (только если есть больше 10) ----
        if total_keys > 10:
            private_file, private_count = create_private_file(all_keys, key_stats)

            caption_priv = "🔐 <b>Полный список ключей</b>\n\n"
            caption_priv += f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
            caption_priv += f"📦 В файле: <b>{private_count}</b> ключей\n"
            caption_priv += f"📊 Всего ключей: <b>{total_keys}</b>\n\n"
            caption_priv += "📡 VLESS | VMess | Trojan | SS"

            if os.path.exists(COVER_PRIVATE):
                if DRY_RUN:
                    print("\n[DRY_RUN] sendPhoto + sendDocument (private)")
                    print("Caption:\n", caption_priv)
                    print("File:", private_file)
                else:
                    result = send_photo_with_file(
                        PRIVATE_CHANNEL,
                        COVER_PRIVATE,
                        private_file,
                        caption_priv,
                        bot_token=BOT_TOKEN_PRIVATE,
                    )
                    if result and result.get("ok"):
                        print(f"✅ Пост с файлом (приват) сформирован ({private_count} ключей в файле)")
            else:
                print("⚠️ Нет картинки для приватного канала")

            safe_remove(private_file)

        # ---- Пост с подписками (приват) ----
        if subscriptions_buttons:
            keyboard = []
            row = []
            for btn in subscriptions_buttons:
                row.append(
                    {
                        "text": btn["text"],
                        "copy_text": {"text": btn["url"]},
                    }
                )
                if len(row) == 2:
                    keyboard.append(row)
                    row = []
            if row:
                keyboard.append(row)

            subs_text = "📋 <b>Ссылки на подписки</b>\n\n"
            quote = get_remote_quote() or get_local_quote() or "Лучше один рабочий ключ, чем сто мёртвых."
            subs_text += f"💬 <i>{quote}</i>\n\n"
            subs_text += "🎯 Нажми на кнопку ниже — ссылка скопируется в буфер, импортируй в клиент"

            if DRY_RUN:
                print("\n[DRY_RUN] sendMessage (private subscriptions)")
                print("Text:\n", subs_text)
            else:
                try:
                    resp = requests.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN_PRIVATE}/sendMessage",
                        json={
                            "chat_id": PRIVATE_CHANNEL,
                            "text": subs_text,
                            "parse_mode": "HTML",
                            "disable_web_page_preview": True,
                            "reply_markup": {"inline_keyboard": keyboard},
                        },
                        timeout=15,
                    )
                    if resp.json().get("ok"):
                        print("✅ Пост с подписками (приват) отправлен")
                    else:
                        print(f"❌ Ошибка поста с подписками (приват): {resp.json().get('description')}")
                except Exception as e:
                    print(f"❌ Ошибка отправки подписок (приват): {e}")

        # ---- ВМЕСТО 10 КЛЮЧЕЙ: Активные прокси кнопками ----
        proxies = load_active_proxies_from_github(limit=10)
        if proxies:
            keyboard = build_proxies_keyboard(proxies)
            text = (
                "📋 <b>Активные прокси</b>\n\n"
                "Выберите прокси и нажмите на кнопку, чтобы скопировать ссылку для импорта в ваш клиент.\n\n"
                "Все прокси проверены и активны."
            )
            if DRY_RUN:
                print("\n[DRY_RUN] sendMessage (active proxies)")
                print("Text:\n", text)
            else:
                try:
                    resp = requests.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN_PRIVATE}/sendMessage",
                        json={
                            "chat_id": PRIVATE_CHANNEL,
                            "text": text,
                            "parse_mode": "HTML",
                            "reply_markup": {"inline_keyboard": keyboard}
                        },
                        timeout=15
                    )
                    if resp.json().get("ok"):
                        print("✅ Сообщение с активными прокси отправлено")
                    else:
                        print(f"❌ Ошибка отправки активных прокси: {resp.json().get('description')}")
                except Exception as e:
                    print(f"❌ Ошибка отправки активных прокси: {e}")
        else:
            print("⚠️ Нет активных прокси для отправки (файл пуст или недоступен)")

    print("\n" + "=" * 70)
    print("✅ Скрипт завершил работу")
    print("=" * 70 + "\n")
    return 0

if __name__ == "__main__":
    sys.exit(main())
