import os
import sys
import requests
from datetime import datetime
import urllib.parse

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

EMOJIS = ["⚙️", "🔒", "🚀", "✨", "💎", "🔥", "🌐", "🔑"]

WARNING_TEXT = (
    "⚠️ Материал взят из открытых источников сети Интернет.\n"
    "Информация предоставляется в ознакомительных целях.\n"
    "Все данные получены легальными методами.\n\n"
)

CLIENTS = "Клиенты: v2rayNG · Clash · Hiddify · Shadowrocket\n"
TAGS = "#прокси #v2ray #vmess #vless #shadowsocks #vpn #all"

REACTIONS_TEXT = (
    "Если формат зашел — жми 👍\n"
    "Не согласен — выбери ⚡️\n"
    "Хочешь продолжение — поставь 🔥\n"
    "Конфиг рабочий? жми 🟢, лагает — тыкай 🧨\n"
    "Протокол топ? ставь 🚀, если фейл — жми 💥\n"
    "Юзаешь? отмечай 😎, если нет — выбирай 🤔"
)

SUBSCRIPTIONS_URL = (
    "https://raw.githubusercontent.com/"
    "kort0881/vpn-checker-backend/refs/heads/main/checked/subscriptions_list.txt"
)


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
    if not subscriptions_text:
        return ""
    lines = subscriptions_text.strip().split("\n")
    formatted_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("==="):
            formatted_lines.append(f"\n<b>{line}</b>")
    return "\n".join(formatted_lines)


def parse_subscriptions_for_buttons(subscriptions_text):
    if not subscriptions_text:
        return []
    lines = subscriptions_text.strip().split("\n")
    buttons = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("==="):
            continue
        if line.startswith("http"):
            filename = line.split("/")[-1].replace(".txt", "")
            btn_text = f"📥 {filename}"
            btn_text = btn_text[:32]
            buttons.append({"text": btn_text, "url": line})
    return buttons


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
    """
    Вариант для ALL: читаем файлы, которые пишет ai_checker_all.py:
    all_elite.txt / all_premium.txt / all_good.txt
    """
    all_keys = []
    stats = {"elite": 0, "premium": 0, "good": 0}

    priority_files = [
        ("all_elite.txt", "elite"),
        ("all_premium.txt", "premium"),
        ("all_good.txt", "good"),
    ]

    for filename, category in priority_files:
        filepath = os.path.join(PREMIUM_FOLDER, filename)
        if not os.path.exists(filepath):
            print(f"  ⚠️ {filename} не найден (ALL)")
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
        print(f"  ✅ {filename}: {count} ключей (ALL)")

    return all_keys, stats


def load_fallback_keys():
    verified_files = [
        f for f in os.listdir(RESULTS_FOLDER)
        if f.startswith("verified_all_") and f.endswith(".txt")
    ]
    if not verified_files:
        return [], None, None

    latest = max(
        verified_files,
        key=lambda f: os.path.getmtime(os.path.join(RESULTS_FOLDER, f)),
    )
    source = "verified_all"
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


def build_markdown_chunks(keys, per_chunk=5, max_total_keys=10, limit=3900):
    keys = [clean_key(k) for k in keys[:max_total_keys]]
    chunks = []
    offset = 0

    while offset < len(keys):
        added = False
        for current_size in range(per_chunk, 0, -1):
            part = keys[offset: offset + current_size]
            if not part:
                break

            lines = [WARNING_TEXT]
            for i, key in enumerate(part, start=offset + 1):
                emoji = EMOJIS[(i - 1) % len(EMOJIS)]
                safe_key = key.replace("```", "'''")
                lines.append(f"{emoji} *ALL ключ {i}:*")
                lines.append("```")
                lines.append(f"{safe_key}")
                lines.append("```")
                lines.append("")

            lines.append(CLIENTS)
            lines.append(TAGS)
            lines.append("— Peacedeath Bot (ALL)")

            text = "\n".join(lines)

            if len(text) <= limit:
                chunks.append(text)
                offset += current_size
                added = True
                break

        if not added:
            offset += 1

    return chunks


def send_photo_with_file(channel_id, photo_path, file_path, caption="", bot_token=None):
    url = f"https://api.telegram.org/bot{bot_token}"

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
    filename = f"public_top100_all_{date_str}.txt"
    filepath = os.path.join(RESULTS_FOLDER, filename)

    top_keys = all_keys[:100]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Channel: @vlesstrojan\n")
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write("# Verified: ALL (TCP + HTTP + Categories)\n")
        if stats:
            f.write(
                f"# Elite: {stats.get('elite', 0)} | Premium: {stats.get('premium', 0)} | Good: {stats.get('good', 0)}\n"
            )
        f.write(f"# Total: {len(top_keys)}\n\n")
        for key in top_keys:
            f.write(key + "\n")

    return filepath, len(top_keys)


def create_private_file(all_keys, stats=None):
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"private_remaining_all_{date_str}.txt"
    filepath = os.path.join(RESULTS_FOLDER, filename)

    remaining_keys = all_keys[10:]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write("# Verified: ALL (TCP + HTTP + Categories)\n")
        if stats:
            f.write(
                f"# Elite: {stats.get('elite', 0)} | Premium: {stats.get('premium', 0)} | Good: {stats.get('good', 0)}\n"
            )
        f.write(f"# Keys in file: {len(remaining_keys)}\n")
        f.write("# Keys in posts: 10\n")
        f.write(f"# Total: {len(all_keys)}\n\n")
        for key in remaining_keys:
            f.write(key + "\n")

    return filepath, len(remaining_keys)


def safe_remove(filepath: str):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except OSError as e:
        print(f"⚠️ Не удалось удалить {filepath}: {e}")


def main():
    if not BOT_TOKEN_PUBLIC:
        print("❌ TELEGRAM_BOT_TOKEN_PUBLIC не установлен")
        return 1
    if not BOT_TOKEN_PRIVATE:
        print("❌ TELEGRAM_BOT_TOKEN не установлен")
        return 1

    print("\n" + "=" * 70)
    print(" " * 20 + "📤 TELEGRAM POSTER v2 (ALL)")
    print(" " * 10 + "(результаты ai_checker_all.py)")
    print("=" * 70 + "\n")

    if not os.path.exists(RESULTS_FOLDER):
        print(f"❌ Папка {RESULTS_FOLDER} не существует")
        return 1

    subscriptions_raw = load_subscriptions()
    subscriptions_formatted = format_subscriptions_for_telegram(subscriptions_raw)
    subscriptions_buttons = parse_subscriptions_for_buttons(subscriptions_raw)

    # ============== ЗАГРУЗКА КЛЮЧЕЙ ==============
    all_keys = []
    key_stats = None
    source_info = ""

    # 1) ALL premium
    if os.path.exists(PREMIUM_FOLDER):
        print("📁 Ищем ALL-ключи в results/premium/...")
        all_keys, key_stats = load_premium_keys()
        if all_keys:
            source_info = "ALL premium (all_elite + all_premium + all_good)"
            print(f"\n✅ Загружено из ALL premium: {len(all_keys)} ключей")
            print(
                f"   Elite: {key_stats['elite']} | Premium: {key_stats['premium']} | Good: {key_stats['good']}"
            )

    # 2) fallback: verified_all_*.txt
    if not all_keys:
        print("\n📁 ALL premium пусто, ищем verified_all_...")  
        all_keys, filename, source = load_fallback_keys()
        if all_keys:
            source_info = f"{source} ({filename})"
            print(f"✅ Fallback: {len(all_keys)} ключей из {filename}")
        else:
            print("❌ Нет ALL-файлов с ключами")
            return 1

    total_keys = len(all_keys)
    print(f"\n📦 Всего ALL-ключей: {total_keys}")
    print(f"📂 Источник: {source_info}\n")

    if total_keys == 0:
        print("❌ Нет ключей для постинга (ALL)")
        return 1

    # ========== ПУБЛИЧНЫЙ КАНАЛ ==========
    print("=" * 70)
    print(f"📢 ПУБЛИЧНЫЙ КАНАЛ (ALL): {PUBLIC_CHANNEL}")
    print("=" * 70 + "\n")

    public_file, public_count = create_public_file(all_keys, key_stats)

    caption = "🔥 <b>Проверенные прокси-ключи (ALL)</b>\n\n"
    caption += f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
    caption += f"✅ Лучших (ALL): <b>{public_count}</b>\n"
    caption += f"📊 Всего проверено (ALL): <b>{total_keys}</b>\n\n"

    if key_stats and any(key_stats.values()):
        caption += (
            f"🏆 Elite: {key_stats['elite']} | Premium: {key_stats['premium']} | Good: {key_stats['good']}\n\n"
        )

    caption += "🔍 Проверка: ALL TCP + HTTP + Categories\n"
    caption += "📡 VLESS | VMess | Trojan | SS\n\n"
    caption += f"💬 {PUBLIC_CHANNEL}\n\n"
    caption += REACTIONS_TEXT

    if os.path.exists(COVER_PUBLIC):
        result = send_photo_with_file(
            PUBLIC_CHANNEL,
            COVER_PUBLIC,
            public_file,
            caption,
            bot_token=BOT_TOKEN_PUBLIC,
        )
        if result and result.get("ok"):
            print(f"✅ ALL-пост отправлен в {PUBLIC_CHANNEL}")
        else:
            error_msg = result.get("description", "Unknown error") if result else "No response"
            print(f"❌ Ошибка: {error_msg}")
    else:
        print("⚠️ Нет картинки для публичного канала")

    safe_remove(public_file)

    # ========== ПРИВАТНЫЙ КАНАЛ ==========
    if PRIVATE_CHANNEL and total_keys > 10:
        print("\n" + "=" * 70)
        print(f"🔒 ПРИВАТНЫЙ КАНАЛ (ALL): {PRIVATE_CHANNEL}")
        print("=" * 70 + "\n")

        private_file, private_count = create_private_file(all_keys, key_stats)

        caption = "🔐 <b>Полный список ключей (ALL)</b>\n\n"
        caption += f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
        caption += f"📦 В файле: <b>{private_count}</b> ключей\n"
        caption += "📝 В постах: <b>10</b> ключей\n"
        caption += f"📊 Всего (ALL): <b>{total_keys}</b>\n\n"

        if key_stats and any(key_stats.values()):
            caption += (
                f"🏆 Elite: {key_stats['elite']} | Premium: {key_stats['premium']} | Good: {key_stats['good']}\n\n"
            )

        caption += "🔍 Проверка: ALL TCP + HTTP + Categories\n"
        caption += "📡 VLESS | VMess | Trojan | SS"

        if os.path.exists(COVER_PRIVATE):
            result = send_photo_with_file(
                PRIVATE_CHANNEL,
                COVER_PRIVATE,
                private_file,
                caption,
                bot_token=BOT_TOKEN_PRIVATE,
            )
            if result and result.get("ok"):
                print(
                    f"✅ ALL-пост с файлом отправлен ({private_count} ключей в файле)"
                )
            else:
                error_msg = result.get("description", "Unknown error") if result else "No response"
                print(f"❌ Ошибка: {error_msg}")
        else:
            print("⚠️ Нет картинки для приватного канала")

        chunks = build_markdown_chunks(all_keys, per_chunk=5, max_total_keys=10, limit=3900)
        print(f"📝 Отправка {len(chunks)} ALL-постов с ключами...")

        for idx, text in enumerate(chunks, start=1):
            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN_PRIVATE}/sendMessage",
                    json={
                        "chat_id": PRIVATE_CHANNEL,
                        "text": text,
                        "parse_mode": "Markdown",
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                )
                if resp.json().get("ok"):
                    print(f"✅ Пост {idx}/{len(chunks)} отправлен (ALL)")
                else:
                    print(
                        f"❌ Пост {idx} ошибка: {resp.json().get('description')}"
                    )
            except Exception as e:
                print(f"❌ Ошибка отправки поста {idx}: {e}")

        safe_remove(private_file)
    elif total_keys <= 10:
        print("\n⚠️ Меньше 10 ALL-ключей — только публичный пост")

    print("\n" + "=" * 70)
    print("✅ ГОТОВО (ALL)")
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
