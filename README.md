# AI Proxy Checker v4.0 BALANCED

[![Python 3.8+](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Telegram](https://img.shields.io/badge/Telegram-@vlesstrojan-blue)](https://t.me/vlesstrojan)

**Профессиональная система автоматической проверки и публикации VPN-ключей** с искусственным интеллектом, многоступенчатой валидацией и интеграцией с Telegram.

---

## 🎯 Возможности

### **Основной функционал**
- ✅ **Многопротокольная поддержка**: VLESS, VMess, Trojan, Shadowsocks
- 🔍 **Трёхступенчатая проверка**: TCP → Xray → Категории сайтов
- 🧠 **AI-движок** (опционально): приоритизация ключей, детекция аномалий
- 📊 **Классификация по качеству**: Elite / Premium / Good
- 🔄 **Автоматическая публикация** в Telegram (публичный + приватный каналы)
- 🔐 **Безопасные мутации**: авто-подбор fingerprint при сбое

### **Продвинутые возможности**
- 📈 **Исторический анализ**: хранение и использование данных о проверках
- 🚀 **Оптимизированная производительность**: настройка workers/timeouts
- 🌍 **Поддержка регионов**: EU, RU, ALL
- 📁 **Структурированные результаты**: отдельные файлы по качеству
- 🔄 **Реконнект-тесты**: проверка стабильности соединения

---

## 📦 Установка

### Требования
- **Python 3.8+**
- **Git**
- **2+ GB RAM** (рекомендуется 4 GB для AI-режима)

### Быстрая установка

```bash
# 1. Клонирование репозитория
git clone https://github.com/kort0881/proxy-auto-checker.git
cd proxy-auto-checker

# 2. Установка зависимостей
pip install -r requirements.txt

# 3. (Опционально) AI-функции
pip install scikit-learn numpy

# 4. Запуск
python checker_v4_balanced.py
```

### Зависимости

```txt
requests>=2.31.0
# Опционально для AI:
scikit-learn>=1.3.0
numpy>=1.24.0
```

---

## 🚀 Использование

### Базовая проверка

```bash
# Проверка всех регионов
python checker_v4_balanced.py

# Только RU-серверы
python checker_v4_balanced.py --region RU

# Только EU-серверы
python checker_v4_balanced.py --region EU
```

### Настройка производительности

```bash
# Увеличить параллелизм (мощный сервер)
python checker_v4_balanced.py --workers 20 --tcp-workers 60

# Уменьшить нагрузку (слабый VPS)
python checker_v4_balanced.py --workers 6 --tcp-workers 20

# Отключить AI (экономия памяти)
python checker_v4_balanced.py --no-ai

# Отключить мутации (быстрая проверка)
python checker_v4_balanced.py --no-mutations
```

### Публикация в Telegram

```bash
# Настройка переменных окружения
export TELEGRAM_BOT_TOKEN_PUBLIC="your_public_bot_token"
export TELEGRAM_BOT_TOKEN="your_private_bot_token"
export TELEGRAM_PRIVATE_CHANNEL="@your_private_channel"

# Запуск публикации
python telegram_poster_v2.py
```

---

## 📂 Структура проекта

```
proxy-auto-checker/
├── checker_v4_balanced.py      # Основной скрипт проверки
├── checker_v3_relaxed.py       # Альтернативная версия (мягкие пороги)
├── telegram_poster_v2.py       # Постинг в Telegram
├── xray/                       # Xray-core (скачивается автоматически)
├── results/                    # Результаты проверок
│   ├── premium/                # Категоризированные ключи
│   │   ├── elite.txt           # <200ms, jitter<80, 4+ сайтов
│   │   ├── premium.txt         # <500ms, jitter<150, 3+ сайтов
│   │   └── good.txt            # <2000ms, jitter<500, 2+ сайтов
│   ├── verified_*.txt          # Все рабочие ключи
│   ├── history.jsonl           # История проверок (AI)
│   ├── stats_latest.json       # Статистика последнего запуска
│   └── checker.log             # Логи работы
├── cover_public.jpg            # Обложка для публичного канала
├── cover_private.jpg           # Обложка для приватного канала
└── requirements.txt            # Python-зависимости
```

---

## 🔧 Конфигурация

### Настройка порогов качества

В `checker_v4_balanced.py`:

```python
QUALITY_THRESHOLDS = {
    Quality.ELITE:   QualityThreshold(
        latency_max=200,   # мс
        jitter_max=80,     # мс
        categories_min=4   # доступных сайтов
    ),
    Quality.PREMIUM: QualityThreshold(
        latency_max=500, 
        jitter_max=150, 
        categories_min=3
    ),
    Quality.GOOD:    QualityThreshold(
        latency_max=2000, 
        jitter_max=500, 
        categories_min=2
    ),
}
```

### Настройка производительности

```python
class Config:
    # TCP-проверка
    TCP_WORKERS = 40          # параллельных потоков
    TCP_TIMEOUT = 8           # таймаут (секунды)
    TCP_RETRIES = 1           # повторные попытки
    
    # Xray-проверка
    XRAY_WORKERS = 12         # параллельных процессов
    XRAY_STARTUP = 5.0        # время на запуск (сек)
    XRAY_TIMEOUT = 12         # таймаут запроса (сек)
    
    # Тесты
    LATENCY_SAMPLES = 3       # измерений задержки
    MIN_LATENCY_SUCCESS = 2   # минимум успешных
    RECONNECT_TESTS = 1       # тестов реконнекта
```

### Добавление источников ключей

```python
KEY_SOURCES = {
    "RU": [
        "https://raw.githubusercontent.com/user/repo/main/ru_keys.txt",
    ],
    "EU": [
        "https://raw.githubusercontent.com/user/repo/main/eu_keys.txt",
    ],
    "CUSTOM": [  # новый регион
        "https://example.com/keys.txt",
    ]
}
```

---

## 📊 Алгоритм проверки

### Ступень 1: TCP-валидация (быстрая фильтрация)
```
Ключи (1000+) → TCP Connect → Живые (~30-50%)
├─ Timeout: 8s
├─ Retries: 1
└─ Workers: 40
```

### Ступень 2: Xray Full Check (глубокая проверка)

**Сессия 1 - Базовые метрики:**
- Измерение задержки (3 пробы через Cloudflare/Google)
- Проверка доступности категорий сайтов (7 URL):
  - Google, Telegram, YouTube, VK, Instagram, Twitter, TikTok
- Расчёт jitter (стабильность задержки)

**Сессия 2 - Стабильность:**
- Тест реконнекта (переподключение и повторная проверка)

**Опциональная мутация:**
- При провале: авто-подбор fingerprint (chrome/firefox/safari/edge)

### AI-анализ (если включён)

1. **Приоритизация**:
   - Сортировка по успешности протокола (VLESS > Trojan > VMess > SS)
   - Reality-ключи получают бонус

2. **Детекция аномалий** (IsolationForest):
   - Анализ по 6 признакам: latency, jitter, reconnect, categories, protocol, security
   - Подозрительные ключи помечаются `[ANOMALY]`

3. **Обучение на истории**:
   - Модель тренируется на последних 10,000 проверках
   - Адаптация к изменениям в сети

---

## 📤 Telegram-публикация

### Публичный канал
- **Топ-100 ключей** в TXT-файле
- **Обложка** с метриками
- **Ссылки на подписки** (кнопки копирования)
- **Донат-пост**

### Приватный канал (VIP)
- **10 лучших ключей** в постах (Markdown + код-блоки)
- **Остальные ключи** в TXT-файле
- **Расширенная статистика** (Elite/Premium/Good)
- **VIP-подписки** с инлайн-кнопками

### Формат постов

```markdown
⚠️ Материал из открытых источников

⚙️ *Ключ 1:*
```
vless://uuid@host:port?type=ws&security=tls...
```

🔒 *Ключ 2:*
```
trojan://password@host:port?security=tls...
```

Клиенты: v2rayNG · Clash · Hiddify · Shadowrocket
#прокси #v2ray #vless #trojan
```

---

## 🔬 Технические детали

### Поддерживаемые протоколы

| Протокол | Транспорты | Безопасность | Fingerprint |
|----------|-----------|--------------|-------------|
| **VLESS** | TCP, WS, gRPC, H2, KCP, xHTTP | TLS, Reality, None | ✅ |
| **VMess** | TCP, WS, gRPC, H2 | TLS, None | ⚠️ |
| **Trojan** | TCP, WS, gRPC | TLS | ✅ |
| **Shadowsocks** | TCP | None | ❌ |

### Безопасность

- **Изолированные процессы**: каждый Xray-процесс использует случайный порт
- **Автоочистка**: kill всех процессов при завершении/ошибке
- **Signal handlers**: обработка Ctrl+C / SIGTERM
- **Валидация конфигов**: парсинг с fallback на дефолты

### Оптимизации

- **Adaptive retries**: повторные попытки только для таймаутов
- **Port waiting**: явное ожидание открытия порта (не sleep)
- **Garbage collection**: принудительный сбор мусора каждые 60 ключей
- **Config caching**: JSON-конфиги в /tmp для переиспользования

---

## 📈 Метрики и статистика

### Выходной JSON (`stats_latest.json`)

```json
{
  "timestamp": "2024-01-15T14:30:00",
  "region": "ALL",
  "total_checked": 1247,
  "total_working": 89,
  "by_quality": {
    "elite": 12,
    "premium": 34,
    "good": 43
  },
  "by_protocol": {
    "VLESS": 45,
    "VMess": 21,
    "Trojan": 18,
    "SS": 5
  },
  "mutations": {
    "tried": 15,
    "successful": 7
  },
  "ai": {
    "enabled": true,
    "anomalies": 3
  },
  "processing_time": 1847.3
}
```

### История проверок (`history.jsonl`)

```jsonl
{"timestamp": 1705329600, "alive": true, "protocol": "VLESS", "latency": 143.5, "jitter": 22.1, "reconnect": 1, "categories": 5, "quality": "elite", "security": "reality"}
{"timestamp": 1705329601, "alive": false, "protocol": "VMess", "error": "tcp_timeout"}
```

---

## 🛠️ Расширенные сценарии

### GitHub Actions (CI/CD)

```yaml
name: Daily Proxy Check

on:
  schedule:
    - cron: '0 */6 * * *'  # Каждые 6 часов
  workflow_dispatch:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install scikit-learn numpy
      
      - name: Run checker
        run: python checker_v4_balanced.py --region ALL
      
      - name: Post to Telegram
        env:
          TELEGRAM_BOT_TOKEN_PUBLIC: ${{ secrets.BOT_TOKEN_PUBLIC }}
          TELEGRAM_BOT_TOKEN: ${{ secrets.BOT_TOKEN_PRIVATE }}
          TELEGRAM_PRIVATE_CHANNEL: ${{ secrets.PRIVATE_CHANNEL }}
        run: python telegram_poster_v2.py
      
      - name: Upload results
        uses: actions/upload-artifact@v3
        with:
          name: premium-keys
          path: results/premium/
```

### Docker

```dockerfile
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    wget unzip && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install scikit-learn numpy

COPY . .

CMD ["python", "checker_v4_balanced.py"]
```

```bash
# Сборка
docker build -t proxy-checker .

# Запуск
docker run -v $(pwd)/results:/app/results \
           -e TELEGRAM_BOT_TOKEN_PUBLIC=xxx \
           -e TELEGRAM_BOT_TOKEN=xxx \
           proxy-checker
```

### Systemd Service (автозапуск)

```ini
[Unit]
Description=AI Proxy Checker
After=network.target

[Service]
Type=simple
User=proxycheck
WorkingDirectory=/opt/proxy-checker
ExecStart=/usr/bin/python3 checker_v4_balanced.py
Restart=on-failure
RestartSec=3600

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable proxy-checker
sudo systemctl start proxy-checker
```

---

## 🐛 Troubleshooting

### Проблема: "Xray не запускается"

```bash
# Проверка архитектуры
python3 -c "import platform; print(platform.machine())"

# Ручная установка xray
cd xray/
wget https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip
unzip Xray-linux-64.zip
chmod +x xray
```

### Проблема: "Out of Memory"

```bash
# Уменьшить workers
python checker_v4_balanced.py --workers 4 --tcp-workers 15 --no-ai

# Или увеличить swap
sudo fallocate -l 4G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### Проблема: "Telegram rate limit"

```python
# В telegram_poster_v2.py добавить задержки
import time
for chunk in chunks:
    send_message(chunk)
    time.sleep(3)  # 3 секунды между постами
```

### Проблема: "AI model не тренируется"

```bash
# Проверка зависимостей
pip install --upgrade scikit-learn numpy

# Очистка истории
rm results/history.jsonl

# Запуск без AI
python checker_v4_balanced.py --no-ai
```

---

## 📝 FAQ

**Q: Сколько ключей можно проверить за раз?**  
A: До 5000+ при мощном сервере (8+ cores, 16GB RAM). На VPS (2 cores, 4GB) ~ 500-1000.

**Q: Почему некоторые ключи пропускаются?**  
A: Возможны причины:
- Неверный формат URI
- TCP-порт закрыт
- Xray не смог установить соединение
- Не прошёл категорийные тесты

**Q: Как добавить свой тест?**  
A: В `CONFIG.CATEGORY_URLS` добавьте кортеж `(url, name)`:
```python
("https://example.com", "custom_site")
```

**Q: Можно ли проверять локальные ключи?**  
A: Да, создайте файл `custom_keys.txt` и измените `download_and_deduplicate()`:
```python
with open('custom_keys.txt') as f:
    return f.read().splitlines()
```

**Q: Работает ли на Windows?**  
A: Да, но для WSL рекомендуется Ubuntu 22.04+. Native Windows поддерживается с ограничениями.

---

## 🤝 Вклад в проект

Приветствуются PR с:
- Новыми источниками ключей
- Оптимизациями алгоритмов
- Поддержкой новых протоколов (TUIC, Hysteria2)
- Улучшениями AI-моделей

### Гайдлайны

1. Fork → Branch → Commit → Push → PR
2. Код должен проходить `flake8` / `black`
3. Добавляйте тесты для новых функций
4. Обновляйте README при изменении API

---

## 📜 Лицензия

**MIT License**

```
Copyright (c) 2024 kort0881

Разрешается использование, модификация, распространение
при сохранении копирайта и дисклеймера об ответственности.
```

---

## ⚠️ Дисклеймер

Проект предоставлен **в образовательных целях**. Автор не несёт ответственности за:
- Нарушение ToS провайдеров
- Использование в незаконных целях
- Потерю данных или повреждение систем

**Используйте VPN-сервисы в соответствии с законодательством вашей страны.**

---

## 📞 Контакты

- **Telegram-канал**: [@vlesstrojan](https://t.me/vlesstrojan)
- **GitHub Issues**: [Создать issue](https://github.com/kort0881/proxy-auto-checker/issues)
- **Email**: [Не указан - используйте Issues]

---

## 🌟 Благодарности

- **Xray Project** за отличный прокси-движок
- **scikit-learn** за AI-инструменты
- Сообществу за фидбек и баг-репорты

---

<div align="center">

**Сделано с ❤️ для свободного интернета**

[![Star on GitHub](https://img.shields.io/github/stars/kort0881/proxy-auto-checker?style=social)](https://github.com/kort0881/proxy-auto-checker)

</div>
