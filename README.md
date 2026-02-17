<div align="center">

# 🚀 Proxy Auto Checker

### Автоматическая проверка и классификация прокси с AI-оптимизацией

![Status](https://img.shields.io/badge/Status-Active-success?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.8+-blue?style=for-the-badge&logo=python)
![License](https://img.shields.io/badge/License-MIT-yellow?style=for-the-badge)
![Automation](https://img.shields.io/badge/Automation-GitHub_Actions-orange?style=for-the-badge&logo=github)

</div>

---

## 📊 Live Statistics

<div align="center">

| 🏆 Quality Tier | 📈 Count | 🔗 Download |
|:---------------:|:--------:|:-----------:|
| **Elite** 💎 | 52 | [elite.txt](results/premium/elite.txt) |
| **Premium** ⭐ | 47 | [premium.txt](results/premium/premium.txt) |
| **Total** 📦 | 648 | [All Files](results/premium/) |

![Total](https://img.shields.io/badge/Total_Proxies-648-brightgreen?style=flat-square)
![Elite](https://img.shields.io/badge/Elite-52-gold?style=flat-square)
![Premium](https://img.shields.io/badge/Premium-47-blue?style=flat-square)
![Updated](https://img.shields.io/badge/Updated-2026--02--17-orange?style=flat-square)

</div>

---

## 🎬 Demo

<div align="center">

![Proxy Checker Demo](гифка.gif)

*Автоматическая проверка прокси в реальном времени с анализом скорости и доступности*

</div>

---

## ✨ Features

- 🔄 **Автоматическая проверка** - GitHub Actions запускается по расписанию
- 🎯 **Умная классификация** - Elite, Premium, Standard качество
- ⚡ **Высокая скорость** - Асинхронная проверка множества прокси
- 📊 **Детальная статистика** - Скорость, анонимность, доступность
- 🌍 **Geo-локация** - Определение страны и провайдера
- 📱 **Telegram интеграция** - Автоматическая публикация результатов
- 🔐 **Проверка анонимности** - Elite/Anonymous/Transparent
- 📈 **История изменений** - Отслеживание качества во времени

---

## 🛠️ Installation

### Quick Start

```bash
# Clone repository
git clone https://github.com/kort0881/proxy-auto-checker.git
cd proxy-auto-checker

# Install dependencies
pip install -r requirements.txt

# Run checker
python check_proxies.py
```

### Advanced Checker

```bash
# Для расширенной проверки с geo-локацией
python advanced_checker.py
```

---

## 📋 Usage

### Basic Check

```python
from check_proxies import ProxyChecker

checker = ProxyChecker()
results = checker.check_proxies(proxy_list)
```

### With Quality Filtering

```python
# Получить только Elite прокси
elite_proxies = checker.get_elite_proxies()

# Сортировка по скорости
fastest = checker.sort_by_speed(elite_proxies)
```

---

## 📁 Project Structure

```
proxy-auto-checker/
├── check_proxies.py          # Основной чекер прокси
├── advanced_checker.py        # Расширенный чекер с geo
├── post_to_telegram.py        # Публикация в Telegram
├── run_and_push.sh           # Автоматизация Git
├── results/
│   └── premium/              # Проверенные прокси
│       ├── elite.txt
│       └── premium.txt
└── .github/
    └── workflows/            # GitHub Actions
```

---

## 🎯 Quality Tiers

| Tier | Анонимность | Скорость | Стабильность | Use Case |
|------|-------------|----------|--------------|----------|
| 💎 **Elite** | High | < 2s | 99%+ | Web scraping, API calls |
| ⭐ **Premium** | Medium | < 5s | 95%+ | General browsing |
| 📦 **Standard** | Low | < 10s | 90%+ | Basic tasks |

---

## 🔄 Automation

Проект использует **GitHub Actions** для автоматической проверки:

- ⏰ Запуск каждые 6 часов
- 🔍 Проверка всех прокси из списка
- 📊 Обновление статистики
- 📤 Публикация в Telegram канал
- 💾 Автоматический commit результатов

---

## 📱 Telegram Integration

Автоматическая публикация результатов в Telegram:

```python
# Настройка в post_to_telegram.py
BOT_TOKEN = 'your_bot_token'
CHANNEL_ID = '@your_channel'
```

**Features:**
- ✅ Форматированные сообщения
- 📊 Статистика в виде таблиц
- 🖼️ Кастомные обложки (cover_public.jpg, cover_private.jpg)
- 🔗 Прямые ссылки на файлы

---

## 🧪 Testing

```bash
# Тест одного прокси
python -c "from check_proxies import test_proxy; test_proxy('1.2.3.4:8080')"

# Быстрая проверка списка
python check_proxies.py --quick --limit 100
```

---

## 📊 Statistics & Monitoring

Проект отслеживает:

- ✅ Success rate (% работающих прокси)
- ⚡ Average response time
- 🌍 Geographic distribution
- 📈 Quality trends over time
- 🔄 Daily/Weekly updates

---

## 🤝 Contributing

Приветствуются pull requests!

1. Fork the project
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

---

## 📝 Requirements

- Python 3.8+
- aiohttp
- requests
- beautifulsoup4
- python-telegram-bot

---

## 📜 License

This project is licensed under the MIT License.

---

## 🔗 Links

- 📢 **Telegram Channel**: [@vlesstrojan](https://t.me/vlesstrojan)
- 🐛 **Issues**: [GitHub Issues](https://github.com/kort0881/proxy-auto-checker/issues)
- ⭐ **Star this repo** if you find it useful!

---

<div align="center">

### 💡 Made with ❤️ for the proxy community

**Last Updated**: 2026-02-17 | **Total Checks**: 10,000+ | **Uptime**: 99.9%

[![GitHub stars](https://img.shields.io/github/stars/kort0881/proxy-auto-checker?style=social)](https://github.com/kort0881/proxy-auto-checker/stargazers)
[![GitHub forks](https://img.shields.io/github/forks/kort0881/proxy-auto-checker?style=social)](https://github.com/kort0881/proxy-auto-checker/network/members)

</div>