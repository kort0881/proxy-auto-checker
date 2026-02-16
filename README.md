
Вот профессиональный, детальный и визуально оформленный `README.md` специально для твоего скрипта **AI Proxy Checker v4.0 BALANCED**.

Я добавил ASCII-схемы, бейджи и подробное описание логики работы (AI, мутации, проверка категорий), чтобы проект выглядел максимально серьезно.

***

# 🌐 AI Proxy Checker v4.0 [BALANCED]

![Version](https://img.shields.io/badge/Version-4.0%20Balanced-blue?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.8%2B-yellow?style=for-the-badge)
![AI Powered](https://img.shields.io/badge/AI-Enabled-violet?style=for-the-badge)
![Xray Core](https://img.shields.io/badge/Core-Xray-green?style=for-the-badge)

**Профессиональный инструмент для проверки и сортировки VLESS / VMess / Trojan / Shadowsocks прокси.**
Скрипт использует **Xray-core** для глубокой проверки, **AI (Isolation Forest)** для выявления аномалий и систему **умных мутаций** для восстановления проблемных ключей.

---

## 🚀 Основные возможности

### 🧠 Интеллектуальный движок
*   **AI Anomaly Detection**: Использует `scikit-learn` (IsolationForest) для выявления подозрительных прокси, которые технически работают, но ведут себя аномально (на основе истории проверок).
*   **Smart Prioritization**: Сортирует очередь проверки, отдавая приоритет протоколам с высшим шансом успеха (VLESS Reality > Trojan > VMess).
*   **History Learning**: Ведет базу знаний (`history.jsonl`) для обучения модели на ваших данных.

### 🧬 Система мутаций (Safe Mutation)
Если прокси не проходит проверку, скрипт пытается его "вылечить":
*   Автоматически подменяет `fingerprint` (Chrome / Firefox / iOS / Random).
*   Повторно проверяет ключ с новыми параметрами.

### 🛡️ Глубокая проверка (Deep Check)
1.  **TCP Handshake**: Отсеивание мертвых хостов (до 40 потоков).
2.  **Latency & Jitter**: Измерение задержки и её стабильности (3 замера).
3.  **Category Test**: Проверка доступа к 7 сервисам: Google, Telegram, YouTube, VK, Instagram, Twitter, TikTok.
4.  **Reconnect**: Тест на устойчивость соединения (повторное подключение).

---

## 📊 Алгоритм работы

```mermaid
graph TD;
  A[📥 Источники ключей] --> B{⚡ TCP Connect};
  B -- Timeout --> X[🗑️ Trash];
  B -- Success --> C[🔍 Xray Full Check];
  C -- Success --> D[🧠 AI Analysis];
  C -- Fail --> E{🧬 Mutation?};
  E -- Yes --> C;
  E -- No --> X;
  D --> F[🏆 Классификация];
  F --> G[📂 Сохранение (Elite/Premium/Good)];
```

---

## ⚙️ Установка и запуск

### 1. Требования
*   Python 3.8+
*   ОС: Windows, Linux или macOS.

### 2. Установка зависимостей
```bash
pip install requests scikit-learn numpy
```
*(Библиотеки `scikit-learn` и `numpy` нужны для работы AI. Если их нет, скрипт запустится в упрощенном режиме).*

### 3. Запуск
Скрипт автоматически скачает нужную версию `xray-core` при первом запуске.

```bash
# Обычный запуск (все регионы)
python checker_v4_balanced.py

# Только RU сегмент
python checker_v4_balanced.py --region RU

# Настройка потоков (для мощных серверов)
python checker_v4_balanced.py --workers 20 --tcp-workers 100

# Отключить AI и мутации (максимальная скорость)
python checker_v4_balanced.py --no-ai --no-mutations
```

---

## 🏆 Критерии качества (Thresholds)

Скрипт сортирует рабочие прокси по папкам на основе жестких метрик:

| Класс | Папка | Latency | Jitter | Доступность сервисов |
|:---|:---|:---:|:---:|:---:|
| **🥇 ELITE** | `results/premium/elite.txt` | < 200 ms | < 80 | **4+** (из 7) |
| **🥈 PREMIUM** | `results/premium/premium.txt` | < 500 ms | < 150 | **3+** (из 7) |
| **🥉 GOOD** | `results/premium/good.txt` | < 2000 ms | < 500 | **2+** (из 7) |

---

## 📂 Структура файлов

После работы скрипт создает следующую структуру:

```text
├── xray/                  # Исполняемые файлы Xray
├── results/
│   ├── premium/           # Отсортированные ключи
│   │   ├── elite.txt      # Лучшие из лучших
│   │   ├── premium.txt    # Очень хорошие
│   │   └── good.txt       # Рабочие, но медленные
│   ├── verified_X.txt     # Общий список всех рабочих
│   ├── history.jsonl      # База данных для AI (не удалять!)
│   ├── stats_latest.json  # Статистика последнего запуска
│   └── checker.log        # Логи работы
└── checker_v4_balanced.py
```

### Формат вывода ключей
Скрипт добавляет метаданные к каждому ключу для удобства:

```text
vless://uuid@ip:port...#%5B158ms%7Cj19%7Crc1/1%7C7cat%7CTG%2BVLESS%7CFP_safari%7C%5BANOMALY%5D%5D
```
**Расшифровка тега:**
*   `158ms`: Средняя задержка.
*   `j19`: Джиттер (разброс пинга, чем меньше — тем стабильнее).
*   `rc1/1`: Успешный реконнект (1 из 1).
*   `7cat`: Доступно 7 категорий сайтов (Google, YT, etc).
*   `TG`: Работает с Telegram.
*   `FP_safari`: Применена мутация (подмена отпечатка на Safari).
*   `[ANOMALY]`: Пометка AI (если ключ подозрительный).

---

## 🔧 Настройка (Config)

Вы можете изменить параметры внутри скрипта (класс `Config`):

```python
@dataclass
class Config:
    TCP_WORKERS: int = 40       # Потоки для быстрой TCP проверки
    XRAY_WORKERS: int = 12      # Потоки для Xray (тяжелая проверка)
    TCP_TIMEOUT: int = 8        # Таймаут коннекта
    LATENCY_SAMPLES: int = 3    # Количество замеров пинга
    MAX_SAFE_MUTATIONS: int = 1 # Количество попыток "лечения" ключа
```

---

## 📝 Лицензия и Отказ от ответственности

Этот инструмент разработан исключительно в **образовательных и исследовательских целях**.
Автор не несет ответственности за использование полученных прокси-серверов.
Пожалуйста, соблюдайте законы вашей страны при использовании VPN-технологий.

---
<div align="center">
    <b>Channel:</b> <a href="https://t.me/vlesstrojan">@vlesstrojan</a>
    <br>
    <sub>2024 AI Proxy Checker Project</sub>
</div>
