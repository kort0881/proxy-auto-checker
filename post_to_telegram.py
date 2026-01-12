# post_to_telegram.py
import os
import sys
import requests
from datetime import datetime
import urllib.parse  # нужен для правки URL

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

CLIENTS = (
    "Клиенты: v2rayNG · Clash · Hiddify · Shadowrocket\n"
)

TAGS = "#прокси #v2ray #vmess #vless #shadowsocks #vpn"


def clean_key(k: str) -> str:
    """Немного укорачиваем ключи и убираем мусор."""
    k = k.strip()
    if " " in k:
        k = k.split(" ")[0]
    return k


def fix_universal(key: str) -> str:
    """
    Универсальная правка VLESS:
    - Hiddify Desktop не понимает type=xhttp, только tcp/udp/grpc/http.[web:39]
    - Мобильные клиенты нормально работают с type=http.[web:37]
    Поэтому просто меняем xhttp -> http, остальное не трогаем.
    """
    key = key.strip()
    if not key.startswith("vless://") or "type=xhttp" not in key:
        return key

    try:
        parsed = urllib.parse.urlparse(key)
        query = urllib.parse.parse_qs(parsed.query)

        if "type" in query and query["type"][0].lower() == "xhttp":
            query["type"] = ["http"]

        new_query = urllib.parse.urlencode(query, doseq=True)
        return urllib.parse.urlunparse((
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            new_query,
            parsed.fragment,
        ))
    except Exception:
        return key


def build_markdown_chunks(keys, per_chunk=5, max_total_keys=30, limit=3900):
    """
    Делает список markdown-сообщений.
    В каждом: дисклеймер + до per_chunk ключей в ```код-блоках``` + хвост.
    Следим за лимитом длины и избегаем бесконечных циклов.
    """
    keys = [clean_key(k) for k in keys[:max_total_keys]]
    chunks = []
    offset = 0

    while offset < len(keys):
        # пробуем от per_chunk до 1 ключа в сообщении
        for current_size in range(per_chunk, 0, -1):
            part = keys[offset:offset + current_size]
            if not part:
                break

            lines = [WARNING_TEXT]
            for i, key in enumerate(part, start=offset + 1):
                emoji = EMOJIS[(i - 1) % len(EMOJIS)]
                safe_key = key.replace("```", "ʼʼʼ")
                lines.append(f"{emoji} *Ключ {i}:*\n```{safe_key}```\n")

            lines.append(CLIENTS)
            lines.append(TAGS)
            lines.append("— Peacedeath Bot")

            text = "\n".join(lines)

            if len(text) <= limit:
                chunks.append(text)
                offset += current_size
                break
        else:
            # даже один ключ не влез — пропускаем его, чтобы не зациклиться
            offset += 1

    return chunks


def send_photo_with_file(channel_id, photo_path, file_path, caption="", bot_token=None):
    """Отправка фото с подписью, затем файла"""
    url = f"https://api.telegram.org/bot{bot_token}"
    
    try:
        with open(photo_path, 'rb') as photo:
            files = {'photo': photo}
            data = {
                'chat_id': channel_id,
                'caption': caption,
                'parse_mode': 'HTML'
            }
            r = requests.post(
                f"{url}/sendPhoto",
                data=data,
                files=files,
                timeout=30
            )
            photo_result = r.json()
        
        if photo_result.get('ok'):
            message_id = photo_result['result']['message_id']
            
            with open(file_path, 'rb') as doc:
                files = {'document': doc}
                data = {
                    'chat_id': channel_id,
                    'reply_to_message_id': message_id
                }
                r = requests.post(
                    f"{url}/sendDocument",
                    data=data,
                    files=files,
                    timeout=60
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
    """Создать файл с первыми 100 ключами для публичного канала"""
    date_str = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f"public_top100_{date_str}.txt"
    filepath = os.path.join(RESULTS_FOLDER, filename)
    
    top_keys = all_keys[:100]
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# Channel: @vlesstrojan\n")
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write(f"# Verified: Dual-check (TCP + XRAY)\n")
        f.write(f"# Total: {len(all_keys)}\n\n")
        f.writelines(top_keys)
    
    return filepath, len(top_keys)


def create_private_file(all_keys):
    """Создать файл со ВСЕМИ остальными ключами для закрытого канала"""
    date_str = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f"private_remaining_{date_str}.txt"
    filepath = os.path.join(RESULTS_FOLDER, filename)
    
    remaining_keys = all_keys[100:]
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}\n")
        f.write(f"# Verified: Dual-check (TCP + XRAY)\n")
        f.write(f"# Keys: {len(remaining_keys)} / {len(all_keys)}\n\n")
        f.writelines(remaining_keys)
    
    return filepath, len(remaining_keys)


def main():
    if not BOT_TOKEN_PUBLIC:
        print("❌ TELEGRAM_BOT_TOKEN_PUBLIC не установлен")
        return 1
    
    if not BOT_TOKEN_PRIVATE:
        print("❌ TELEGRAM_BOT_TOKEN не установлен")
        return 1
    
    print("\n" + "="*70)
    print(" " * 20 + "📤 TELEGRAM POSTER")
    print("="*70 + "\n")
    
    if not os.path.exists(COVER_PUBLIC):
        print(f"⚠️  Файл {COVER_PUBLIC} не найден")
    
    if not os.path.exists(COVER_PRIVATE):
        print(f"⚠️  Файл {COVER_PRIVATE} не найден")
    
    verified_files = [
        f for f in os.listdir(RESULTS_FOLDER)
        if f.startswith("verified_") and f.endswith(".txt")
    ]
    
    if not verified_files:
        print("❌ Нет файлов с результатами")
        return 1
    
    latest_file = max(
        verified_files,
        key=lambda f: os.path.getmtime(os.path.join(RESULTS_FOLDER, f))
    )
    file_path = os.path.join(RESULTS_FOLDER, latest_file)
    
    print(f"📁 Файл: {latest_file}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # универсальная правка только для vless type=xhttp
    all_keys = [fix_universal(l) for l in lines if l.strip() and not l.startswith('#')]
    total_keys = len(all_keys)
    
    print(f"📦 Всего ключей: {total_keys}\n")
    
    if total_keys == 0:
        print("❌ Нет ключей для постинга")
        return 1
    
    # ========== ПУБЛИЧНЫЙ КАНАЛ ==========
    print("="*70)
    print(f"📢 ПУБЛИЧНЫЙ КАНАЛ: {PUBLIC_CHANNEL}")
    print("="*70 + "\n")
    
    public_file, public_count = create_public_file(all_keys)
    
    caption = f"🔥 <b>Проверенные прокси-ключи</b>\n\n"
    caption += f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
    caption += f"✅ Лучших: <b>{public_count}</b>\n"
    caption += f"📊 Всего проверено: <b>{total_keys}</b>\n\n"
    caption += f"🔍 Двойная проверка: TCP + XRAY\n"
    caption += f"📡 VLESS | VMess | Trojan | SS\n\n"
    caption += f"💬 {PUBLIC_CHANNEL}"
    
    if os.path.exists(COVER_PUBLIC):
        result = send_photo_with_file(
            PUBLIC_CHANNEL, 
            COVER_PUBLIC,
            public_file, 
            caption, 
            bot_token=BOT_TOKEN_PUBLIC
        )
        
        if result and result.get('ok'):
            print(f"✅ Пост отправлен в {PUBLIC_CHANNEL}")
        else:
            print(f"❌ Ошибка: {result.get('description', 'Unknown error')}")
    else:
        print("⚠️  Нет картинки")
    
    try:
        os.remove(public_file)
    except:
        pass

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
        print(f"✅ Донат-пост отправлен: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"❌ Ошибка отправки донат-поста: {e}")
    
    # ========== ПРИВАТНЫЙ КАНАЛ ==========
    if PRIVATE_CHANNEL and total_keys > 100:
        print("\n" + "="*70)
        print(f"🔒 ПРИВАТНЫЙ КАНАЛ: {PRIVATE_CHANNEL}")
        print("="*70 + "\n")
        
        private_file, private_count = create_private_file(all_keys)
        
        caption = f"🔐 <b>Полный список ключей</b>\n\n"
        caption += f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
        caption += f"📦 Ключей: <b>{private_count}</b> из {total_keys}\n\n"
        caption += f"🔍 Двойная проверка: TCP + XRAY\n"
        caption += f"📡 VLESS | VMess | Trojan | SS"
        
        # 1) Пост: картинка + файл
        if os.path.exists(COVER_PRIVATE):
            result = send_photo_with_file(
                PRIVATE_CHANNEL, 
                COVER_PRIVATE,
                private_file, 
                caption, 
                bot_token=BOT_TOKEN_PRIVATE
            )
            
            if result and result.get('ok'):
                print("✅ Пост с файлом отправлен в приватный канал")
            else:
                print(f"❌ Ошибка: {result.get('description', 'Unknown error')}")
        else:
            print("⚠️  Нет картинки для приватного канала")
        
        # 2) Отдельные посты с код-блоками
        chunks = build_markdown_chunks(all_keys, per_chunk=5, max_total_keys=30, limit=3900)
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
                print(f"✅ Часть {idx}/{len(chunks)} форматированного поста: {resp.status_code} {resp.text}")
            except Exception as e:
                print(f"❌ Ошибка отправки части {idx}: {e}")
        
        try:
            os.remove(private_file)
        except:
            pass
    elif total_keys <= 100:
        print("\n⚠️  Меньше 100 ключей - только публичный пост")
    
    print("\n" + "="*70)
    print("✅ ГОТОВО")
    print("="*70 + "\n")
    return 0


if __name__ == "__main__":
    exit(main())





