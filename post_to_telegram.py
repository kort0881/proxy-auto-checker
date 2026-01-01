# post_to_telegram.py
import os
import sys
import requests
from datetime import datetime

# ВАШИ СЕКРЕТЫ ИЗ GITHUB
BOT_TOKEN_PUBLIC = os.environ.get('TELEGRAM_BOT_TOKEN_PUBLIC')  # Бот для @vlesstrojan
BOT_TOKEN_PRIVATE = os.environ.get('TELEGRAM_BOT_TOKEN')        # Бот для закрытого
PRIVATE_CHANNEL = os.environ.get('TELEGRAM_PRIVATE_CHANNEL')   # ID закрытого (-100...)

PUBLIC_CHANNEL = "@vlesstrojan"

WORK_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FOLDER = os.path.join(WORK_DIR, "results")

# ДВЕ РАЗНЫЕ КАРТИНКИ
COVER_PUBLIC = os.path.join(WORK_DIR, "cover_public.jpg")   # Для @vlesstrojan
COVER_PRIVATE = os.path.join(WORK_DIR, "cover_private.jpg")  # Для закрытого

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

def split_file_to_chunks(file_path, chunk_size=100):
    """Разделение файла на части по 100 ключей"""
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    # Только ключи, без комментариев
    keys = [l for l in lines if l.strip() and not l.startswith('#')]
    
    chunks = []
    for i in range(0, len(keys), chunk_size):
        chunk = keys[i:i+chunk_size]
        chunks.append(chunk)
    
    return chunks, len(keys)

def create_chunk_file(lines, index, total_keys, prefix="verified"):
    """Создание временного файла с частью ключей"""
    date_str = datetime.now().strftime('%Y%m%d_%H%M')
    filename = f"{prefix}_part{index+1}_{date_str}.txt"
    filepath = os.path.join(RESULTS_FOLDER, filename)
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(f"# Channel: @vlesstrojan\n")
        f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
        f.write(f"# Part: {index+1}\n")
        f.write(f"# Keys in this part: {len(lines)}\n")
        f.write(f"# Total verified: {total_keys}\n\n")
        f.writelines(lines)
    
    return filepath

def main():
    # Проверка секретов
    if not BOT_TOKEN_PUBLIC:
        print("❌ TELEGRAM_BOT_TOKEN_PUBLIC не установлен")
        return 1
    
    if not BOT_TOKEN_PRIVATE:
        print("❌ TELEGRAM_BOT_TOKEN не установлен")
        return 1
    
    print("\n" + "="*70)
    print(" " * 20 + "📤 TELEGRAM POSTER")
    print("="*70 + "\n")
    
    # Проверка картинок
    if not os.path.exists(COVER_PUBLIC):
        print(f"⚠️  Файл {COVER_PUBLIC} не найден")
    
    if not os.path.exists(COVER_PRIVATE):
        print(f"⚠️  Файл {COVER_PRIVATE} не найден")
    
    # Поиск файла с результатами
    verified_files = [f for f in os.listdir(RESULTS_FOLDER) if f.startswith("verified_") and f.endswith(".txt")]
    
    if not verified_files:
        print("❌ Нет файлов с результатами")
        return 1
    
    latest_file = max(verified_files, key=lambda f: os.path.getmtime(os.path.join(RESULTS_FOLDER, f)))
    file_path = os.path.join(RESULTS_FOLDER, latest_file)
    
    print(f"📁 Файл: {latest_file}")
    
    # Разделение на части
    chunks, total_keys = split_file_to_chunks(file_path, chunk_size=100)
    
    print(f"📦 Всего ключей: {total_keys}")
    print(f"📑 Частей по 100: {len(chunks)}\n")
    
    # ========== ПУБЛИЧНЫЙ КАНАЛ @vlesstrojan ==========
    print("="*70)
    print(f"📢 ПУБЛИЧНЫЙ КАНАЛ: {PUBLIC_CHANNEL}")
    print("="*70 + "\n")
    
    for i, chunk in enumerate(chunks):
        chunk_file = create_chunk_file(chunk, i, total_keys, prefix="public")
        
        # Текст поста
        caption = f"🔥 <b>Проверенные прокси-ключи</b>\n\n"
        caption += f"📅 Дата: <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
        caption += f"📦 Часть: <b>{i+1}</b> из {len(chunks)}\n"
        caption += f"✅ Ключей в части: <b>{len(chunk)}</b>\n"
        caption += f"🎯 Всего проверено: <b>{total_keys}</b>\n\n"
        caption += f"🔐 Метод: <i>XRAY-CORE реальная проверка</i>\n"
        caption += f"💬 Канал: {PUBLIC_CHANNEL}"
        
        # Отправка с ПУБЛИЧНОЙ картинкой
        if os.path.exists(COVER_PUBLIC):
            result = send_photo_with_file(
                PUBLIC_CHANNEL, 
                COVER_PUBLIC,  # ← Картинка для публичного
                chunk_file, 
                caption, 
                bot_token=BOT_TOKEN_PUBLIC
            )
        else:
            print(f"  ⚠️  Нет картинки для публичного канала")
            result = {'ok': False, 'description': 'No cover image'}
        
        if result and result.get('ok'):
            print(f"  ✅ Часть {i+1}/{len(chunks)} отправлена в {PUBLIC_CHANNEL}")
        else:
            print(f"  ❌ Ошибка части {i+1}: {result.get('description', 'Unknown error')}")
        
        # Удаляем временный файл
        try:
            os.remove(chunk_file)
        except:
            pass
        
        # Пауза между постами
        if i < len(chunks) - 1:
            import time
            time.sleep(2)
    
    # ========== ПРИВАТНЫЙ КАНАЛ ==========
    if PRIVATE_CHANNEL:
        print("\n" + "="*70)
        print(f"🔒 ПРИВАТНЫЙ КАНАЛ: {PRIVATE_CHANNEL}")
        print("="*70 + "\n")
        
        for i, chunk in enumerate(chunks):
            chunk_file = create_chunk_file(chunk, i, total_keys, prefix="private")
            
            # Текст для VIP
            caption = f"🔐 <b>VIP Проверенные прокси</b>\n\n"
            caption += f"📅 <code>{datetime.now().strftime('%Y-%m-%d %H:%M')}</code>\n"
            caption += f"📦 Часть <b>{i+1}/{len(chunks)}</b>\n"
            caption += f"✅ Ключей: <b>{len(chunk)}</b> из <b>{total_keys}</b>\n\n"
            caption += f"🎯 Только рабочие | Проверено xray-core"
            
            # Отправка с ПРИВАТНОЙ картинкой
            if os.path.exists(COVER_PRIVATE):
                result = send_photo_with_file(
                    PRIVATE_CHANNEL, 
                    COVER_PRIVATE,  # ← Картинка для приватного
                    chunk_file, 
                    caption, 
                    bot_token=BOT_TOKEN_PRIVATE
                )
            else:
                print(f"  ⚠️  Нет картинки для приватного канала")
                result = {'ok': False, 'description': 'No cover image'}
            
            if result and result.get('ok'):
                print(f"  ✅ VIP часть {i+1}/{len(chunks)} отправлена")
            else:
                print(f"  ❌ Ошибка VIP части {i+1}: {result.get('description', 'Unknown error')}")
            
            try:
                os.remove(chunk_file)
            except:
                pass
            
            if i < len(chunks) - 1:
                import time
                time.sleep(2)
    
    print("\n" + "="*70)
    print("✅ ПОСТИНГ ЗАВЕРШЕН!")
    print("="*70 + "\n")
    return 0

if __name__ == "__main__":
    exit(main())

