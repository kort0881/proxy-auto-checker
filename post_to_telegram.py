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

COVER_PUBLIC = os.path.join(WORK_DIR, "cover_public.jpg")
COVER_PRIVATE = os.path.join(WORK_DIR, "cover_private.jpg")

EMOJIS = ["⚙️", "🔒", "🚀", "✨", "💎", "🔥", "🌐", "🔑"]

WARNING_TEXT = (
    "⚠️ Материал взят из открытых источников сети Интернет.\n"
    "Информация предоставляется в ознакомительных целях.\n"
    "Все данные получены легальными методами.\n\n"
)

CLIENTS = "Клиенты: v2rayNG · Clash · Hiddify · Shadowrocket\n"
TAGS = "#прокси #v2ray #vmess #vless #shadowsocks #vpn"

REACTIONS_TEXT = (
    "Если формат зашел — жми 👍\n"
    "Не согласен — выбери 😡\n"
    "Хочешь продолжение — поставь 🔥\n"
    "Конфиг рабочий? жми 🟢, лагает — тыкай 🔴\n"
    "Протокол топ? ставь 🚀, если фейл — жми 💥\n"
    "Юзаешь? отмечай 😎, если нет — выбирай 🤔"
)

# URL с подписками из первого репозитория
SUBSCRIPTIONS_URL = (
    "https://raw.githubusercontent.com/"
    "kort0881/vpn-checker-backend/refs/heads/main/checked/subscriptions_list.txt"
)


def load_subscriptions():
    """Загрузить ссылки на подписки по HTTP из первого репозитория."""
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
    """Форматировать подписки для Telegram (HTML)."""
    if not subscriptions_text:
        return ""

    lines = subscriptions_text.strip().split("\n")
    formatted_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Заголовки разделов
        if line.startswith("==="):
            formatted_lines.append(f"\n<b>{line}</b>")
        # Ссылки
        elif line.startswith("http"):
            filename = line.split("/")[-1]
            formatted_lines.append(f"📥 <a href='{line}'>{filename}</a>")

    return "\n".join(formatted_lines)


def clean_key(k: str) -> str:
    """Убираем мусор из ключа."""
    k = k.strip()
    if " " in k:
        k = k.split(" ")[0]
    return k


def fix_universal(key: str) -> str:
    """
    Делает VLESS-ключ универсальным:
    - Меняет type=xhttp на type=http для совместимости с Hiddify Desktop.
    """
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


def build_markdown_chunks(keys, per_chunk=5, max_total_keys=10, limit=3900):
    """
    Создаёт список markdown-сообщений.
    В каждом: дисклеймер + до per_chunk ключей в код-блоках + хвост.
    Каждый ключ в отдельном код-блоке.
    """
    keys = [clean_key(k) for k in keys[:max_total_keys]]
    chunks = []
    offset = 0

    while offset < len(keys):
        added = False
        for current_size in range(per_chunk, 0, -1):
            part = keys[offset : offset + current_size]
            if not part:
                break

            lines = [WARNING_TEXT]
            for i, key in enumerate(part, start=offset + 1):
                emoji = EMOJIS[(i - 1) % len(EMOJIS)]
                safe_key = key.replace("```", "'''")
                lines.append(f"{emoji} *Ключ {i}:*")
                lines.append("```")
                lines.append(f"{safe_key}")
                lines.append("```")
                lines.append("")

            lines.append(CLIENTS)
            lines.append(TAGS)
            lines.append("— Peacedeath Bot")

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
    """Отправка фото с подписью, затем файла как ответ."""
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


def create_public_file(all_keys):
    """Создать файл с первыми 100 ключами для публичного канала."""
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"public_top100_{date_str}.txt"
    filepath = os.path.join(RESULTS_FOLDER, filename)

    top_keys = all_keys[:100]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write("# Channel: @vlesstrojan\n")
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write("# Verified: Dual-check (TCP + XRAY)\n")
        f.write(f"# Total: {len(top_keys)}\n\n")
        for key in top_keys:
            f.write(key + "\n")

    return filepath, len(top_keys)


def create_private_file(all_keys):
    """Создать файл со всеми ключами (кроме первых 10) для закрытого канала."""
    date_str = datetime.now().strftime("%Y%m%d_%H%M")
    filename = f"private_remaining_{date_str}.txt"
    filepath = os.path.join(RESULTS_FOLDER, filename)

    remaining_keys = all_keys[10:]

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write("# Verified: Dual-check (TCP + XRAY)\n")
        f.write(f"# Keys in file: {len(remaining_keys)}\n")
        f.write("# Keys in posts: 10\n")
        f.write(f"# Total: {len(all_keys)}\n\n")
        for key in remaining_keys:
            f.write(key + "\n")

    return filepath, len(remaining_keys)


def safe_remove(filepath: str):
    """Безопасное удаление файла."""
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
    print(" " * 20 + "📤 TELEGRAM POSTER")
    print("=" * 70 + "\n")

    if not os.path.exists(RESULTS_FOLDER):
        print(f"❌ Папка {RESULTS_FOLDER} не существует")
        return 1

    if not os.path.exists(COVER_PUBLIC):
        print(f"⚠️ Файл {COVER_PUBLIC} не найден")

    if not os.path.exists(COVER_PRIVATE):
        print(f"⚠️ Файл {COVER_PRIVATE} не найден")

    # Загружаем подписки с GitHub (из первого репозитория)
    subscriptions_raw = load_subscriptions()
    subscriptions_formatted = format_subscriptions_for_telegram(subscriptions_raw)

    verified_files = [
        f
        for f in os.listdir(RESULTS_FOLDER)
        if f.startswith("verified_") and f.endswith(".txt")
    ]

    semi_dead_files = [
        f
        for f in os.listdir(RESULTS_FOLDER)
        if f.startswith("semi_dead_") and f.endswith(".txt")
    ]

    if verified_files:
        latest_file = max(
            verified_files,
            key=lambda f: os.path.getmtime(os.path.join(RESULTS_FOLDER, f)),
        )
        print("📄 Используем verified-файл (идеальные ключи)")
    elif semi_dead_files:
        latest_file = max(
            semi_dead_files,
            key=lambda f: os.path.getmtime(os.path.join(RESULTS_FOLDER, f)),
        )
        print("📄 Verified нет, используем semi_dead (частично рабочие)")
    else:
        print("❌ Нет файлов с результатами")
        return 1

    file_path = os.path.join(RESULTS_FOLDER, latest_file)
    print(f"📁 Файл: {latest_file}")

    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    all_keys = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith("#"):
            key = fix_universal(clean_key(line))
            all_keys.append(key)

    total_keys = len(all_keys)
    print(f"📦 Всего ключей: {total_keys}\n")

    if total_keys == 0:
        print("❌ Нет ключей для постинга")
        return 1

    # ========== ПУБЛИЧНЫЙ КАНАЛ ==========
    print("=" * 70)
    print(f"📢 ПУБЛИЧНЫЙ КАНАЛ: {PUBLIC_CHANNEL}")
    print("=" * 70 + "\n")

    public_file, public_count = create_public_file(all_keys)

    caption = "🔥 <b>Проверенные прокси-ключи</b>\n\n"
    caption += f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
    caption += f"✅ Лучших: <b>{public_count}</b>\n"
    caption += f"📊 Всего проверено: <b>{total_keys}</b>\n\n"
    caption += "🔍 Двойная проверка: TCP + XRAY\n"
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
            print(f"✅ Пост отправлен в {PUBLIC_CHANNEL}")
        else:
            error_msg = result.get("description", "Unknown error") if result else "No response"
            print(f"❌ Ошибка: {error_msg}")
    else:
        print("⚠️ Нет картинки для публичного канала")

    safe_remove(public_file)

    # Пост с подписками в публичный канал
    if subscriptions_formatted:
        subs_text = "📋 <b>Ссылки на подписки</b>\n\n"
        subs_text += subscriptions_formatted
        subs_text += "\n\n💡 Импортируй любую ссылку в Hiddify, v2rayNG или Clash"

        try:
            resp = requests.post(
                f"https://api.telegram.org/bot{BOT_TOKEN_PUBLIC}/sendMessage",
                json={
                    "chat_id": PUBLIC_CHANNEL,
                    "text": subs_text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=15,
            )
            if resp.json().get("ok"):
                print("✅ Пост с подписками отправлен")
            else:
                print(
                    f"❌ Ошибка поста с подписками: {resp.json().get('description')}"
                )
        except Exception as e:
            print(f"❌ Ошибка отправки подписок: {e}")
    else:
        print("⚠️ Подписки не найдены / не отправлены")

    # Донат-пост в публичный канал
    donate_text = (
        "Если хочешь поддержать автора — можно перевести:\n"
        "Сбербанк: <code>4276 3801 7277 1425</code>\n"
        "Не указывайте за что перевод. ✨\n"
        "Спасибо за любую помощь! ❗️"
    )
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
        else:
            print(
                f"❌ Ошибка донат-поста: {resp.json().get('description')}"
            )
    except Exception as e:
        print(f"❌ Ошибка отправки донат-поста: {e}")

    # ========== ПРИВАТНЫЙ КАНАЛ ==========
    if PRIVATE_CHANNEL and total_keys > 10:
        print("\n" + "=" * 70)
        print(f"🔒 ПРИВАТНЫЙ КАНАЛ: {PRIVATE_CHANNEL}")
        print("=" * 70 + "\n")

        private_file, private_count = create_private_file(all_keys)

        caption = "🔐 <b>Полный список ключей</b>\n\n"
        caption += f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
        caption += f"📦 В файле: <b>{private_count}</b> ключей\n"
        caption += "📝 В постах: <b>10</b> ключей\n"
        caption += f"📊 Всего: <b>{total_keys}</b>\n\n"
        caption += "🔍 Двойная проверка: TCP + XRAY\n"
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
                    f"✅ Пост с файлом отправлен ({private_count} ключей в файле)"
                )
            else:
                error_msg = (
                    result.get("description", "Unknown error")
                    if result
                    else "No response"
                )
                print(f"❌ Ошибка: {error_msg}")
        else:
            print("⚠️ Нет картинки для приватного канала")

        # Пост с подписками в приватный канал
        if subscriptions_formatted:
            subs_text = "📋 <b>Ссылки на подписки (VIP)</b>\n\n"
            subs_text += subscriptions_formatted
            subs_text += "\n\n🎯 Импортируй в клиент для автообновления"

            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN_PRIVATE}/sendMessage",
                    json={
                        "chat_id": PRIVATE_CHANNEL,
                        "text": subs_text,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                )
                if resp.json().get("ok"):
                    print("✅ Пост с подписками (приват) отправлен")
                else:
                    print(
                        f"❌ Ошибка поста с подписками (приват): {resp.json().get('description')}"
                    )
            except Exception as e:
                print(f"❌ Ошибка отправки подписок (приват): {e}")
        else:
            print("⚠️ Подписки (приват) не найдены / не отправлены")

        chunks = build_markdown_chunks(
            all_keys, per_chunk=5, max_total_keys=10, limit=3900
        )
        print(f"📝 Отправка {len(chunks)} постов с ключами...")

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
                    print(f"✅ Пост {idx}/{len(chunks)} отправлен")
                else:
                    print(
                        f"❌ Пост {idx} ошибка: {resp.json().get('description')}"
                    )
            except Exception as e:
                print(f"❌ Ошибка отправки поста {idx}: {e}")

        safe_remove(private_file)

    elif total_keys <= 10:
        print("\n⚠️ Меньше 10 ключей — только публичный пост")

    print("\n" + "=" * 70)
    print("✅ ГОТОВО")
    print("=" * 70 + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())





