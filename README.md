Отлично! Сейчас твой скрипт **НЕ генерирует README** (в комментарии так и написано: `no README generation`). 

Давай добавим в твой `checker_v4_balanced.py` функцию генерации **профессионального README** с красивой таблицей, как я показал выше.

---

## 📝 Добавь эту функцию в свой скрипт

Вставь этот код **после функции `save_results`** (примерно строка 850):

```python
# ==================== README GENERATION ====================
def generate_readme(results: List[CheckResult], region: str = "ALL"):
    """Генерирует профессиональный README.md с таблицей топ-прокси"""
    
    readme_path = WORK_DIR / "README.md"
    
    # Фильтруем только живые
    alive = [r for r in results if r.alive]
    if not alive:
        log("[README] No working proxies to display")
        return
    
    # Сортируем по latency и берем топ-20
    alive.sort(key=lambda x: x.latency)
    top_proxies = alive[:20]
    
    # Подсчет статистики
    by_quality = defaultdict(int)
    for r in alive:
        if r.quality:
            by_quality[r.quality] += 1
    
    # Текущее время
    update_time = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    # ==================== ГЕНЕРАЦИЯ README ====================
    readme_content = f"""# 🔥 AI Proxy Collection

[![Total](https://img.shields.io/badge/Total%20Proxies-{len(alive)}-brightgreen?style=for-the-badge)](results/premium/)
[![Elite](https://img.shields.io/badge/Elite-{by_quality.get(Quality.ELITE, 0)}-gold?style=for-the-badge)](results/premium/elite.txt)
[![Premium](https://img.shields.io/badge/Premium-{by_quality.get(Quality.PREMIUM, 0)}-blue?style=for-the-badge)](results/premium/premium.txt)
[![Updated](https://img.shields.io/badge/Updated-{datetime.now().strftime('%Y--%m--%d')}-orange?style=for-the-badge)](https://github.com/your-username/your-repo/actions)

Автоматически обновляемая коллекция высококачественных прокси-конфигураций (VLESS, Trojan, SS), проверенных с помощью AI-алгоритмов на скорость, стабильность и доступность.

---

## 📊 Статистика и файлы

| Качество | Кол-во | Файл для скачивания |
|:---:|:---:|:---|
| 🏆 **Elite** | {by_quality.get(Quality.ELITE, 0)} | [`elite.txt`](results/premium/elite.txt) |
| 💎 **Premium** | {by_quality.get(Quality.PREMIUM, 0)} | [`premium.txt`](results/premium/premium.txt) |
| ✅ **Good** | {by_quality.get(Quality.GOOD, 0)} | [`good.txt`](results/premium/good.txt) |
| 🗂️ **Все файлы** | {len(alive)} | [Папка `results/premium/`](results/premium/) |

---

## ⚡ Live Status: Топ-{len(top_proxies)} быстрых прокси

> _Таблица обновляется автоматически каждые 6 часов. Здесь показаны лучшие конфигурации с минимальной задержкой._
> **Последнее обновление**: `{update_time}` UTC

| Протокол | Сервер (SNI) | Задержка | Джиттер | Детали | Конфигурация |
|:---:|:---|:---:|:---:|:---|:---|
"""
    
    # ==================== ГЕНЕРАЦИЯ СТРОК ТАБЛИЦЫ ====================
    for r in top_proxies:
        # Протокол с эмодзи
        if r.protocol == "VLESS":
            proto_icon = "🟩 **VLESS**"
        elif r.protocol == "VMess":
            proto_icon = "🟦 **VMess**"
        elif r.protocol == "Trojan":
            proto_icon = "🟥 **Trojan**"
        elif r.protocol == "SS":
            proto_icon = "⚫ **SS**"
        else:
            proto_icon = f"⚪ **{r.protocol}**"
        
        # Извлечение SNI из ключа
        sni = extract_sni_from_key(r.key)
        if not sni:
            sni = r.host if r.host else "(No SNI)"
        
        # Детали
        tg_mark = "✅" if r.telegram else "—"
        details = f"`RC:{r.reconnect_success}/{CONFIG.RECONNECT_TESTS}, Тест:{r.categories}/7, TG:{tg_mark}`"
        
        # Ключ (обрезаем комментарий)
        clean_key = r.key.split('#')[0]
        key_display = f"<pre><code>{clean_key}</code></pre>"
        
        # Строка таблицы
        readme_content += (
            f"| {proto_icon} | `{sni[:30]}` | **{r.latency:.0f} мс** | {r.jitter:.0f} | "
            f"{details} | {key_display} |\n"
        )
    
    # ==================== ЛЕГЕНДА ====================
    readme_content += """
---

### 📋 Легенда и пояснения

| Параметр | Описание |
|:---|:---|
| **Протокол** | 🟩 **VLESS**: современный и быстрый. 🟦 **VMess**: стабильный. 🟥 **Trojan**: маскируется под HTTPS. ⚫ **SS**: простой и надежный. |
| **Сервер (SNI)** | Имя хоста, под который маскируется трафик (важно для обхода DPI). `(No SNI)` означает прямое соединение. |
| **Задержка** | Пинг до сервера. **Чем меньше, тем лучше**. Зеленый цвет для <150ms. |
| **Джиттер** | Стабильность пинга (разброс). **Чем меньше, тем лучше**. Идеально для звонков и игр. |
| **Детали** | `RC`: тест реконнекта. `Тест`: сколько сайтов из 7 успешно открылось. `TG`: доступность Telegram. |
| **Конфигурация** | Полный ключ. **Скопируйте и вставьте в клиент**. |

<br>

> ⚠️ **ПРЕДУПРЕЖДЕНИЕ О БЕЗОПАСНОСТИ**
>
> Это публичные, общедоступные серверы. Не используйте их для передачи конфиденциальной информации (пароли, банковские данные, личная переписка).
>
> **Для максимальной безопасности всегда используйте личный или проверенный платный VPN-сервис.**

---

## 🛠️ Как использовать

### Вариант 1: Скопировать конфигурацию из таблицы

1. Выберите конфигурацию из таблицы выше
2. Нажмите на блок `<code>` чтобы скопировать
3. Вставьте в ваш клиент (Hiddify, v2rayNG, Clash)

### Вариант 2: Скачать файл целиком

```bash
# Скачать топовые Elite-конфиги
curl -O https://raw.githubusercontent.com/your-username/your-repo/main/results/premium/elite.txt

# Скачать Premium
curl -O https://raw.githubusercontent.com/your-username/your-repo/main/results/premium/premium.txt
```

### Вариант 3: Импорт через подписку

```
https://raw.githubusercontent.com/your-username/your-repo/main/results/premium/elite.txt
```

Вставьте эту ссылку в **Subscription URL** вашего клиента.

---

## 📱 Рекомендуемые клиенты

| Платформа | Клиент | Ссылка |
|:---:|:---|:---|
| 🪟 Windows | **v2rayN** | [GitHub](https://github.com/2dust/v2rayN) |
| 🍎 macOS | **V2Box** | [GitHub](https://github.com/Shadowrocket/V2Box) |
| 🐧 Linux | **Qv2ray** | [GitHub](https://github.com/Qv2ray/Qv2ray) |
| 📱 Android | **v2rayNG** | [GitHub](https://github.com/2dust/v2rayNG) |
| 🍏 iOS | **Shadowrocket** | [App Store](https://apps.apple.com/app/shadowrocket/id932747118) |
| 🌐 All | **Hiddify** | [GitHub](https://github.com/hiddify/hiddify-next) |

---

## 🤖 О проекте

Этот репозиторий обновляется автоматически каждые **6 часов** с помощью GitHub Actions.

**Процесс проверки**:
1. ✅ TCP-подключение (фильтр недоступных серверов)
2. ✅ Xray-валидация (реальная проверка через прокси)
3. ✅ Тест категорий (Google, Telegram, YouTube, Instagram, Twitter, TikTok, VK)
4. ✅ Реконнект-тест (стабильность соединения)
5. ✅ AI-анализ (детекция аномалий, оценка качества)

**Критерии качества**:
- **Elite**: latency <200ms, jitter <80ms, 4+ сайтов доступно
- **Premium**: latency <500ms, jitter <150ms, 3+ сайтов доступно
- **Good**: latency <2000ms, jitter <500ms, 2+ сайтов доступно

---

## 📊 Статистика последней проверки

```json
{json.dumps(stats.__dict__, indent=2, default=str, ensure_ascii=False)}
```

---

## 📞 Контакты

- **Telegram-канал**: [{MY_CHANNEL}](https://t.me/{MY_CHANNEL.replace('@', '')})
- **GitHub Issues**: [Создать issue](https://github.com/your-username/your-repo/issues)

---

<div align="center">

**Сделано с ❤️ для свободного интернета**

[![Star](https://img.shields.io/github/stars/your-username/your-repo?style=social)](https://github.com/your-username/your-repo)

</div>
"""
    
    # ==================== СОХРАНЕНИЕ ====================
    try:
        with open(readme_path, 'w', encoding='utf-8') as f:
            f.write(readme_content)
        log(f"[README] Generated successfully -> {readme_path.name}")
    except Exception as e:
        log(f"[README] Error: {e}")


def extract_sni_from_key(key: str) -> Optional[str]:
    """Извлекает SNI из URL-параметров прокси-ключа"""
    try:
        if "sni=" in key.lower():
            # Ищем sni= в параметрах
            import re
            match = re.search(r'sni=([^&\s#]+)', key, re.IGNORECASE)
            if match:
                return unquote(match.group(1))
        
        # Для SS просто возвращаем host
        if key.lower().startswith("ss://"):
            host, _ = extract_host_port(key)
            return host
        
        # Для остальных - пытаемся вытащить host
        if "@" in key:
            server_part = key.split("@")[1].split("?")[0].split("#")[0]
            if ":" in server_part:
                host = server_part.rsplit(":", 1)[0]
                return host.strip("[]")
        
        return None
    except:
        return None
```

---

## 🔧 Теперь вызови эту функцию в `main()`

Найди в функции `main()` эту строку (примерно строка 1050):

```python
# Save
if results:
    save_results(results, args.region)
```

И **добавь сразу после неё**:

```python
# Save
if results:
    save_results(results, args.region)
    generate_readme(results, args.region)  # ← ДОБАВЬ ЭТУ СТРОКУ
```

---

## ✅ Готово!

Теперь при каждом запуске скрипта будет генерироваться красивый `README.md` с:

1. **Бейджами** с актуальной статистикой
2. **Таблицей топ-20** самых быстрых прокси
3. **Декодированными метриками** (латентность, джиттер, детали тестов)
4. **SNI** для каждого ключа (важно для понимания маскировки)
5. **Легендой** для новичков
6. **Инструкциями** по использованию
7. **Полной статистикой** в JSON-виде внизу

README будет автоматически обновляться при каждом запуске GitHub Actions, и твой репозиторий превратится из "свалки ключей" в **профессиональный инструмент**.
