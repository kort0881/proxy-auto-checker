# post_to_telegram.py
import os
import sys
import requests
from datetime import datetime
import html

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
    "Материал взят из открытых источников сети Интернет.\n"
    "Информация предоставляется в ознакомительных целях.\n"
    "Все данные получены легальными методами.\n\n"
)

CLIENTS = (
    "Клиенты: v2rayNG · Clash · Hiddify · Shadowrocket\n"
)

TAGS = "#прокси #v2ray #vmess #vless #shadowsocks #vpn"


def build_readable_post_html(keys):
    """Человекочитаемый пост с максимум 15 ключами, HTML <pre>."""
    keys = keys[:15]

    blocks = []
    for i, key in enumerate(keys, start=1):
        emoji = EMOJIS[(i - 1) % len(EMOJIS)]
        safe_key = html.escape(key)
        blocks.append(f"{emoji} Ключ {i}:\n<pre>{safe_key}</pre>")

    safe_warning = html.escape(WARNING_TEXT)
    safe_clients = html.escape(CLIENTS)
    safe_tags = html.escape(TAGS)

    text = (
        f"{safe_warning}"
        + "\n".join(blocks)
        + "\n\n"
        + f"{safe_clients}\n"
        + f"{safe_tags}\n\n"
        + "— Peacedeath Bot"
    )
    return text


def split_message(text, limit=3500):
    """Режем длинный текст на части <= limit, стараясь резать по пустой строке."""
    parts = []
    while len(text) > limit:
        cut_pos = text.rfind("\n\n", 0, limit)
        if cut_pos == -1:
            cut_pos = limit
        parts.append(text[:cut_pos])
        text = text[cut_pos:].lstrip()
    if text:
        parts.append(text)
    return parts


def send_photo_with_file(channel_id, photo_path, file_path, caption="", bot_token=None):
    """Отправка фото с подписью, затем файла"""
    url = f"https://api.telegram.org/bot{bot_token}"
    
    try:
        # 1. Фото с подписью
        with open(photo_path, 'rb') as photo:
            files = {'photo': photo}
            data = {
                'chat_id': channel_id,
                'caption': caption,
                'parse_mode': 'HTML'
            }
            r = requests.post(f"{url}/sendPhoto", data=data, files=files)
            photo_result = r.json()
        
        # 2. Файл как reply к фото
        if photo_result.get('ok'):
            message_id = photo_result['result']['message_id']
            
            with open(file_path, 'rb') as doc:
                files = {'document': doc}
                data = {
                    'chat_id': channel_id,
                    'reply_to_message_id': message_id
                }
                r = requests.post(f"{url}/sendDocument", data=data, files=files)
                return r.json()
        
        return photo_result
        
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
    
    verified_files = [f for f in os.listdir(RESULTS_FOLDER) if f.startswith("verified_") and f.endswith(".txt")]
    
    if not verified_files:
        print("❌ Нет файлов с результатами")
        return 1
    
    latest_file = max(verified_files, key=lambda f: os.path.getmtime(os.path.join(RESULTS_FOLDER, f)))
    file_path = os.path.join(RESULTS_FOLDER, latest_file)
    
    print(f"📁 Файл: {latest_file}")
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    all_keys = [l for l in lines if l.strip() and not l.startswith('#')]
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
        print(f"⚠️  Нет картинки")
    
    try:
        os.remove(public_file)
    except:
        pass
    
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
                print(f"✅ Пост с файлом отправлен в приватный канал")
            else:
                print(f"❌ Ошибка: {result.get('description', 'Unknown error')}")
        else:
            print(f"⚠️  Нет картинки для приватного канала")
        
        # 2) Отдельный пост: до 15 ключей, HTML + разбиение
        readable_text = build_readable_post_html(all_keys)
        parts = split_message(readable_text, limit=3500)
        for idx, part in enumerate(parts, start=1):
            try:
                resp = requests.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN_PRIVATE}/sendMessage",
                    json={
                        "chat_id": PRIVATE_CHANNEL,
                        "text": part,
                        "parse_mode": "HTML",
                        "disable_web_page_preview": True,
                    },
                    timeout=15,
                )
                print(f"✅ Часть {idx}/{len(parts)} форматированного поста: {resp.status_code} {resp.text}")
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



