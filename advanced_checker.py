import os
import sys
import json
import time
import random
import requests
import subprocess
import base64
import hashlib
import socket
from datetime import datetime
from urllib.parse import unquote
from collections import defaultdict
import concurrent.futures
from statistics import mean, stdev
import warnings
warnings.filterwarnings('ignore')

# === КОНФИГУРАЦИЯ ===
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FOLDER = os.path.join(WORK_DIR, "results")
XRAY_FOLDER = os.path.join(WORK_DIR, "xray")

# === ОПТИМИЗАЦИЯ ДЛЯ БОЛЬШИХ ОБЪЕМОВ ===
BATCH_SIZE = 50                     # Обрабатываем по 50 ключей параллельно
MAX_WORKERS_KEYS = 10               # 10 ключей параллельно
MAX_WORKERS_PER_KEY = 12            # 12 сайтов параллельно на ключ
CONNECTION_TIMEOUT = 10             # Увеличен для стабильности
SITE_CHECK_TIMEOUT = 8              # Таймаут проверки сайта
XRAY_STARTUP = 1.5                  # Время запуска xray
STABILITY_CHECKS = 3                # Кол-во проверок стабильности
LATENCY_SAMPLES = 5                 # Проб для измерения задержки

# === МОБИЛЬНЫЕ СПЕЦИФИЧНЫЕ НАСТРОЙКИ ===
MOBILE_QUALITY_THRESHOLDS = {
    "excellent": {"latency": 150, "stability": 95, "success_rate": 90},
    "good": {"latency": 300, "stability": 85, "success_rate": 75},
    "acceptable": {"latency": 500, "stability": 70, "success_rate": 60},
    "poor": {"latency": 1000, "stability": 50, "success_rate": 40}
}

# === РАСШИРЕННЫЕ КАТЕГОРИИ САЙТОВ ===
SITE_CATEGORIES = {
    "banks_priority": {
        "label": "🏦 Банки (Приоритет)",
        "weight": 3.0,  # Высокий вес для рейтинга
        "sites": {
            "sberbank": "https://online.sberbank.ru",
            "tbank": "https://www.tbank.ru",
            "vtb": "https://www.vtb.ru",
            "alfabank": "https://alfabank.ru",
            "gazprombank": "https://www.gazprombank.ru",
            "raiffeisen": "https://www.raiffeisen.ru"
        }
    },
    "gov_priority": {
        "label": "🏛️ Госуслуги (Приоритет)",
        "weight": 2.5,
        "sites": {
            "gosuslugi": "https://www.gosuslugi.ru",
            "nalog": "https://www.nalog.gov.ru",
            "esia": "https://esia.gosuslugi.ru",
            "mos_ru": "https://www.mos.ru"
        }
    },
    "social": {
        "label": "📱 Соцсети",
        "weight": 2.0,
        "sites": {
            "vk": "https://vk.com",
            "ok": "https://ok.ru",
            "instagram": "https://www.instagram.com",
            "twitter": "https://x.com",
            "facebook": "https://www.facebook.com",
            "linkedin": "https://www.linkedin.com",
            "tiktok": "https://www.tiktok.com"
        }
    },
    "messengers": {
        "label": "💬 Мессенджеры",
        "weight": 2.0,
        "sites": {
            "telegram_web": "https://web.telegram.org",
            "whatsapp": "https://web.whatsapp.com",
            "viber": "https://www.viber.com"
        }
    },
    "video": {
        "label": "📺 Видео",
        "weight": 1.5,
        "sites": {
            "youtube": "https://www.youtube.com",
            "rutube": "https://rutube.ru",
            "kinopoisk": "https://www.kinopoisk.ru",
            "ivi": "https://www.ivi.ru"
        }
    },
    "news": {
        "label": "📰 Новости",
        "weight": 1.0,
        "sites": {
            "yandex_news": "https://news.yandex.ru",
            "rbc": "https://www.rbc.ru",
            "tass": "https://tass.ru",
            "ria": "https://ria.ru",
            "lenta": "https://lenta.ru"
        }
    },
    "services": {
        "label": "🛍️ Сервисы",
        "weight": 1.5,
        "sites": {
            "yandex": "https://ya.ru",
            "google": "https://www.google.ru",
            "mail_ru": "https://mail.ru",
            "ozon": "https://www.ozon.ru",
            "wildberries": "https://www.wildberries.ru",
            "avito": "https://www.avito.ru"
        }
    },
    "mobile_operators": {
        "label": "📞 Операторы",
        "weight": 1.5,
        "sites": {
            "mts": "https://www.mts.ru",
            "beeline": "https://www.beeline.ru",
            "megafon": "https://www.megafon.ru",
            "tele2": "https://msk.tele2.ru"
        }
    }
}

# === ПРОФИЛИ КАЧЕСТВА ДЛЯ МОБИЛЬНЫХ ===
MOBILE_PROFILES = {
    "premium_mobile": {
        "label": "💎 ПРЕМИУМ МОБИЛЬНЫЙ",
        "emoji": "💎",
        "description": "Идеально для мобильных - банки, низкая задержка, стабильность",
        "requirements": {
            "latency_max": 200,
            "stability_min": 90,
            "banks_min": 5,
            "categories_min": 6,
            "required_categories": ["banks_priority", "gov_priority"]
        },
        "priority": 1
    },
    "excellent_mobile": {
        "label": "⭐ ОТЛИЧНЫЙ МОБИЛЬНЫЙ",
        "emoji": "⭐",
        "description": "Отлично для мобильных - стабильный, быстрый",
        "requirements": {
            "latency_max": 300,
            "stability_min": 85,
            "banks_min": 4,
            "categories_min": 5,
            "required_categories": ["banks_priority"]
        },
        "priority": 2
    },
    "good_mobile": {
        "label": "✅ ХОРОШИЙ МОБИЛЬНЫЙ",
        "emoji": "✅",
        "description": "Хорошо для мобильных - работают основные сервисы",
        "requirements": {
            "latency_max": 500,
            "stability_min": 75,
            "banks_min": 3,
            "categories_min": 4
        },
        "priority": 3
    },
    "acceptable_mobile": {
        "label": "👌 ПРИЕМЛЕМЫЙ МОБИЛЬНЫЙ",
        "emoji": "👌",
        "description": "Приемлемо для мобильных - может тормозить",
        "requirements": {
            "latency_max": 800,
            "stability_min": 65,
            "categories_min": 3
        },
        "priority": 4
    },
    "basic_mobile": {
        "label": "⚡ БАЗОВЫЙ МОБИЛЬНЫЙ",
        "emoji": "⚡",
        "description": "Минимальная функциональность",
        "requirements": {
            "latency_max": 1500,
            "stability_min": 50,
            "categories_min": 2
        },
        "priority": 5
    },
    "unstable": {
        "label": "⚠️ НЕСТАБИЛЬНЫЙ",
        "emoji": "⚠️",
        "description": "Работает нестабильно - не рекомендуется",
        "requirements": {
            "categories_min": 1
        },
        "priority": 6
    }
}

# Кеш для дедупликации серверов
server_cache = {}
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
OUTPUT_DIR = os.path.join(RESULTS_FOLDER, f"mobile_quality_{timestamp}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

stats = {
    "source_keys": 0,
    "checked": 0,
    "failed": 0,
    "duplicates_skipped": 0,
    "by_profile": defaultdict(int),
    "by_category": defaultdict(int),
    "total_time": 0,
    "avg_latency": []
}

def log(msg):
    """Потокобезопасный лог"""
    print(msg, flush=True)

# ========== МОБИЛЬНЫЕ USER AGENTS ==========
MOBILE_USER_AGENTS = [
    # iOS (самые популярные в РФ)
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (iPad; CPU OS 17_2 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Mobile/15E148 Safari/604.1',
    
    # Android (популярные в РФ бренды)
    'Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',  # Samsung
    'Mozilla/5.0 (Linux; Android 13; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',  # Google
    'Mozilla/5.0 (Linux; Android 13; Redmi Note 12) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',  # Xiaomi
    'Mozilla/5.0 (Linux; Android 12; M2101K9G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',  # Xiaomi
    
    # Специфичные для мобильных VPN клиентов
    'Dalvik/2.1.0 (Linux; U; Android 13; SM-G998B Build/TP1A.220624.014)',  # V2RayNG user agent
    'okhttp/4.11.0'  # Hiddify/V2Box user agent
]

# ========== ФУНКЦИИ ПАРСИНГА ==========

def parse_vless(key):
    try:
        if not key.startswith("vless://"):
            return None
        key = key[8:]
        if "@" not in key:
            return None
        
        uuid_part, rest = key.split("@", 1)
        
        if "?" in rest:
            server_part, params_part = rest.split("?", 1)
        else:
            server_part = rest
            params_part = ""
        
        if "#" in params_part:
            params_part = params_part.split("#")[0]
        if "#" in server_part:
            server_part = server_part.split("#")[0]
        
        if ":" not in server_part:
            return None
        
        host, port = server_part.rsplit(":", 1)
        port = int(port)
        
        params = {}
        if params_part:
            for param in params_part.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    params[k] = unquote(v)
        
        # КРИТИЧНО: Валидация для мобильных клиентов
        flow = params.get("flow", "")
        
        config = {
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": host,
                    "port": port,
                    "users": [{
                        "id": uuid_part,
                        "encryption": params.get("encryption", "none"),
                        "flow": flow if flow else ""
                    }]
                }]
            },
            "streamSettings": {
                "network": params.get("type", "tcp"),
                "security": params.get("security", "none")
            }
        }
        
        # TLS настройки (важно для мобильных)
        if params.get("security") in ["tls", "reality"]:
            tls_settings = {
                "serverName": params.get("sni", host),
                "allowInsecure": params.get("allowInsecure", "0") == "1",
                "fingerprint": params.get("fp", "chrome")  # Важно для обхода блокировок
            }
            
            if params.get("security") == "reality":
                tls_settings["publicKey"] = params.get("pbk", "")
                tls_settings["shortId"] = params.get("sid", "")
                tls_settings["spiderX"] = params.get("spx", "")
                config["streamSettings"]["realitySettings"] = tls_settings
            else:
                config["streamSettings"]["tlsSettings"] = tls_settings
        
        # WebSocket настройки
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)}
            }
        
        # gRPC настройки
        elif params.get("type") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": params.get("serviceName", ""),
                "multiMode": params.get("mode", "gun") == "multi"
            }
        
        # HTTP/2 настройки
        elif params.get("type") == "h2":
            config["streamSettings"]["httpSettings"] = {
                "host": [params.get("host", host)],
                "path": params.get("path", "/")
            }
        
        return config
    except Exception as e:
        return None

def parse_vmess(key):
    try:
        if not key.startswith("vmess://"):
            return None
        
        encoded = key[8:]
        if "#" in encoded:
            encoded = encoded.split("#")[0]
        
        padding = len(encoded) % 4
        if padding:
            encoded += '=' * (4 - padding)
        
        decoded = base64.b64decode(encoded).decode('utf-8')
        data = json.loads(decoded)
        
        config = {
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": data.get("add"),
                    "port": int(data.get("port", 443)),
                    "users": [{
                        "id": data.get("id"),
                        "alterId": int(data.get("aid", 0)),
                        "security": data.get("scy", "auto")
                    }]
                }]
            },
            "streamSettings": {
                "network": data.get("net", "tcp"),
                "security": data.get("tls", "")
            }
        }
        
        if data.get("tls") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": data.get("sni", data.get("add")),
                "allowInsecure": data.get("allowInsecure", False),
                "fingerprint": data.get("fp", "chrome")
            }
        
        if data.get("net") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": data.get("path", "/"),
                "headers": {"Host": data.get("host", data.get("add"))}
            }
        
        return config
    except:
        return None

def parse_trojan(key):
    try:
        if not key.startswith("trojan://"):
            return None
        
        key = key[9:]
        if "@" not in key:
            return None
        
        password, rest = key.split("@", 1)
        
        if "?" in rest:
            server_part, params_part = rest.split("?", 1)
        else:
            server_part = rest
            params_part = ""
        
        if "#" in params_part:
            params_part = params_part.split("#")[0]
        if "#" in server_part:
            server_part = server_part.split("#")[0]
        
        if ":" not in server_part:
            return None
        
        host, port = server_part.rsplit(":", 1)
        port = int(port)
        
        params = {}
        if params_part:
            for param in params_part.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    params[k] = unquote(v)
        
        security = params.get("security", "tls")
        if security == "none" or security == "":
            security = "tls"
        
        config = {
            "protocol": "trojan",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": port,
                    "password": password
                }]
            },
            "streamSettings": {
                "network": params.get("type", "tcp"),
                "security": security
            }
        }
        
        if security == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": params.get("sni", host),
                "allowInsecure": params.get("allowInsecure", "0") == "1",
                "fingerprint": params.get("fp", "chrome")
            }
        
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)}
            }
        
        return config
    except:
        return None

def parse_shadowsocks(key):
    try:
        if not key.startswith("ss://"):
            return None
        
        key = key[5:]
        if "#" in key:
            key = key.split("#")[0]
        
        if "@" in key:
            encoded, server = key.rsplit("@", 1)
            if ":" not in server:
                return None
            
            host, port = server.rsplit(":", 1)
            port = int(port)
            
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            
            decoded = base64.b64decode(encoded).decode('utf-8')
            if ":" in decoded:
                method, password = decoded.split(":", 1)
            else:
                return None
        else:
            return None
        
        config = {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": port,
                    "method": method,
                    "password": password
                }]
            },
            "streamSettings": {
                "network": "tcp"
            }
        }
        
        return config
    except:
        return None

def parse_proxy_key(key):
    """Парсинг прокси ключа с определением протокола"""
    key_lower = key.lower()
    
    if key_lower.startswith("vless://"):
        config = parse_vless(key)
        return (config, "VLESS") if config else (None, None)
    elif key_lower.startswith("vmess://"):
        config = parse_vmess(key)
        return (config, "VMess") if config else (None, None)
    elif key_lower.startswith("trojan://"):
        config = parse_trojan(key)
        return (config, "Trojan") if config else (None, None)
    elif key_lower.startswith("ss://"):
        config = parse_shadowsocks(key)
        return (config, "SS") if config else (None, None)
    
    return None, None

# ========== XRAY УПРАВЛЕНИЕ ==========

def create_xray_config(proxy_config, socks_port=10808):
    """Создание конфига Xray с оптимизациями для мобильных"""
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {
                "udp": True,
                "auth": "noauth"
            },
            "sniffing": {
                "enabled": True,
                "destOverride": ["http", "tls"]
            }
        }],
        "outbounds": [
            proxy_config,
            {
                "protocol": "freedom",
                "tag": "direct"
            }
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": []
        }
    }

def kill_process(process):
    """Безопасное завершение процесса"""
    if not process:
        return
    try:
        process.terminate()
        process.wait(timeout=2)
    except:
        try:
            process.kill()
            process.wait(timeout=1)
        except:
            pass

def safe_remove_file(filepath):
    """Безопасное удаление файла"""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except:
        pass

# ========== ПРОВЕРКА КАЧЕСТВА СОЕДИНЕНИЯ ==========

def measure_latency(proxies, test_url="https://www.google.com", samples=LATENCY_SAMPLES):
    """Измерение задержки соединения (критично для мобильных!)"""
    latencies = []
    
    for _ in range(samples):
        try:
            start = time.time()
            requests.head(
                test_url,
                proxies=proxies,
                timeout=3,
                allow_redirects=False,
                verify=False
            )
            latency = (time.time() - start) * 1000  # в миллисекундах
            latencies.append(latency)
        except:
            latencies.append(9999)  # Очень высокая задержка при ошибке
        
        time.sleep(0.1)  # Небольшая пауза между замерами
    
    # Убираем экстремальные значения
    if len(latencies) > 2:
        latencies.sort()
        latencies = latencies[1:-1]
    
    return {
        "avg": round(mean(latencies), 1) if latencies else 9999,
        "min": round(min(latencies), 1) if latencies else 9999,
        "max": round(max(latencies), 1) if latencies else 9999,
        "jitter": round(stdev(latencies), 1) if len(latencies) > 1 else 0
    }

def check_stability(proxies, test_urls, checks=STABILITY_CHECKS):
    """Проверка стабильности соединения (множественные запросы)"""
    success_count = 0
    total_checks = len(test_urls) * checks
    
    for url in test_urls:
        for _ in range(checks):
            try:
                r = requests.get(
                    url,
                    proxies=proxies,
                    timeout=SITE_CHECK_TIMEOUT,
                    allow_redirects=True,
                    verify=False,
                    headers={'User-Agent': random.choice(MOBILE_USER_AGENTS)}
                )
                if r.status_code < 400:
                    success_count += 1
            except:
                pass
            time.sleep(0.05)  # Минимальная пауза
    
    stability = (success_count / total_checks * 100) if total_checks > 0 else 0
    return round(stability, 1)

def check_site_mobile(site_name, site_url, proxies):
    """Проверка сайта с имитацией мобильного клиента"""
    headers = {
        'User-Agent': random.choice(MOBILE_USER_AGENTS),
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'ru-RU,ru;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'DNT': '1'
    }
    
    try:
        start = time.time()
        r = requests.get(
            site_url,
            proxies=proxies,
            timeout=SITE_CHECK_TIMEOUT,
            allow_redirects=True,
            headers=headers,
            verify=False
        )
        response_time = (time.time() - start) * 1000
        
        # Успех: статус < 400 или редирект на рабочую страницу
        if r.status_code < 400 or (r.status_code in [301, 302, 307, 308] and len(r.history) > 0):
            return {
                "site": site_name,
                "success": True,
                "status": r.status_code,
                "response_time": round(response_time, 0)
            }
    except requests.exceptions.Timeout:
        return {"site": site_name, "success": False, "status": "timeout"}
    except requests.exceptions.ConnectionError:
        return {"site": site_name, "success": False, "status": "connection_error"}
    except:
        pass
    
    return {"site": site_name, "success": False, "status": "failed"}

# ========== КОМПЛЕКСНАЯ ПРОВЕРКА КЛЮЧА ==========

def get_server_hash(config):
    """Получение хеша сервера для дедупликации"""
    try:
        if config["protocol"] in ["vless", "vmess"]:
            server_data = config["settings"]["vnext"][0]
        else:  # trojan, shadowsocks
            server_data = config["settings"]["servers"][0]
        
        hash_str = f"{server_data['address']}:{server_data['port']}:{config['protocol']}"
        return hashlib.md5(hash_str.encode()).hexdigest()
    except:
        return None

def check_key_mobile_quality(key, xray_exe):
    """
    ГЛАВНАЯ ФУНКЦИЯ: Комплексная проверка ключа для мобильных клиентов
    
    Этапы проверки:
    1. Парсинг и валидация конфига
    2. Дедупликация (пропуск уже проверенных серверов)
    3. Запуск Xray
    4. Измерение задержки (latency)
    5. Проверка стабильности
    6. Массовая проверка сайтов
    7. Расчет рейтинга и определение профиля
    """
    try:
        # 1. Парсинг
        proxy_config, protocol = parse_proxy_key(key)
        if not proxy_config:
            return None
        
        # 2. Дедупликация
        server_hash = get_server_hash(proxy_config)
        if server_hash and server_hash in server_cache:
            stats["duplicates_skipped"] += 1
            return None
        
        # 3. Запуск Xray
        socks_port = random.randint(30000, 50000)
        config = create_xray_config(proxy_config, socks_port)
        config_file = os.path.join(XRAY_FOLDER, f"check_{socks_port}.json")
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        
        process = subprocess.Popen(
            [xray_exe, "run", "-c", config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(XRAY_STARTUP)
        
        if process.poll() is not None:
            safe_remove_file(config_file)
            return None
        
        proxies = {
            'http': f'socks5://127.0.0.1:{socks_port}',
            'https': f'socks5://127.0.0.1:{socks_port}'
        }
        
        # 4. Измерение задержки (КРИТИЧНО!)
        latency_data = measure_latency(proxies)
        
        # Если задержка слишком высокая - сразу отбрасываем
        if latency_data["avg"] > 2000:
            kill_process(process)
            safe_remove_file(config_file)
            return None
        
        # 5. Проверка стабильности на приоритетных сайтах
        stability_test_urls = [
            "https://www.google.com",
            "https://ya.ru",
            "https://vk.com"
        ]
        stability = check_stability(proxies, stability_test_urls)
        
        # Если нестабильный - отбрасываем
        if stability < 40:
            kill_process(process)
            safe_remove_file(config_file)
            return None
        
        # 6. Проверка всех сайтов параллельно
        results_by_category = {}
        all_site_results = []
        
        for category_name, category_data in SITE_CATEGORIES.items():
            accessible_sites = []
            site_details = []
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_PER_KEY) as executor:
                futures = {
                    executor.submit(check_site_mobile, site_name, site_url, proxies): site_name
                    for site_name, site_url in category_data['sites'].items()
                }
                
                for future in concurrent.futures.as_completed(futures, timeout=SITE_CHECK_TIMEOUT*2):
                    try:
                        result = future.result()
                        site_details.append(result)
                        if result["success"]:
                            accessible_sites.append(result["site"])
                    except:
                        pass
            
            results_by_category[category_name] = {
                'accessible': accessible_sites,
                'total': len(category_data['sites']),
                'count': len(accessible_sites),
                'percentage': round(len(accessible_sites) / len(category_data['sites']) * 100, 1),
                'weight': category_data['weight'],
                'details': site_details
            }
            
            all_site_results.extend(site_details)
        
        kill_process(process)
        safe_remove_file(config_file)
        
        # 7. Определение профиля и качества
        profile = determine_mobile_profile(results_by_category, latency_data, stability)
        
        if not profile:
            return None
        
        # Сохраняем в кеш
        if server_hash:
            server_cache[server_hash] = True
        
        # Расчет взвешенного рейтинга
        weighted_score = calculate_weighted_score(results_by_category)
        
        result = {
            'key': key,
            'protocol': protocol,
            'profile': profile,
            'latency': latency_data,
            'stability': stability,
            'weighted_score': weighted_score,
            'categories': results_by_category,
            'total_sites_accessible': sum(cat['count'] for cat in results_by_category.values()),
            'total_sites_checked': sum(cat['total'] for cat in results_by_category.values()),
            'all_site_results': all_site_results
        }
        
        stats["avg_latency"].append(latency_data["avg"])
        
        return result
        
    except Exception as e:
        return None

def calculate_weighted_score(results_by_category):
    """Расчет взвешенного рейтинга (приоритет банкам и госуслугам)"""
    total_score = 0
    total_weight = 0
    
    for cat_name, cat_data in results_by_category.items():
        weight = cat_data['weight']
        percentage = cat_data['percentage']
        total_score += percentage * weight
        total_weight += weight * 100  # 100% = максимум
    
    return round(total_score / total_weight * 100, 1) if total_weight > 0 else 0

def determine_mobile_profile(results_by_category, latency_data, stability):
    """Определение профиля ключа для мобильных клиентов"""
    
    accessible_categories = [
        cat_name for cat_name, cat_data in results_by_category.items()
        if cat_data['count'] > 0
    ]
    
    categories_count = len(accessible_categories)
    avg_latency = latency_data["avg"]
    
    # Количество доступных банков
    banks_count = results_by_category.get('banks_priority', {}).get('count', 0)
    
    # Проверяем профили в порядке приоритета
    for profile_name, profile_data in sorted(MOBILE_PROFILES.items(), key=lambda x: x[1]['priority']):
        reqs = profile_data['requirements']
        
        # Проверка всех требований
        if avg_latency > reqs.get('latency_max', 9999):
            continue
        
        if stability < reqs.get('stability_min', 0):
            continue
        
        if categories_count < reqs.get('categories_min', 0):
            continue
        
        if banks_count < reqs.get('banks_min', 0):
            continue
        
        # Проверка обязательных категорий
        required_cats = reqs.get('required_categories', [])
        if required_cats and not all(cat in accessible_categories for cat in required_cats):
            continue
        
        return profile_name
    
    return None

# ========== ФОРМАТИРОВАНИЕ ВЫВОДА ==========

def format_key_result(key, result):
    """Форматирование ключа с детальной информацией для мобильных"""
    profile_data = MOBILE_PROFILES[result['profile']]
    
    # Краткие теги категорий
    category_tags = []
    for cat_name, cat_data in result['categories'].items():
        if cat_data['count'] > 0:
            cat_emoji = SITE_CATEGORIES[cat_name]['label'].split()[0]
            category_tags.append(f"{cat_emoji}{cat_data['count']}/{cat_data['total']}")
    
    # Качество соединения
    latency_tag = f"⚡{result['latency']['avg']}ms"
    stability_tag = f"📊{result['stability']}%"
    score_tag = f"💯{result['weighted_score']}"
    
    comment = f"#{profile_data['emoji']} {latency_tag} {stability_tag} {score_tag} [{', '.join(category_tags)}]"
    
    return f"{key} {comment}"

# ========== БАТЧ-ОБРАБОТКА ==========

def process_keys_batch(keys_batch, xray_exe, batch_num, total_batches):
    """Обработка батча ключей параллельно"""
    log(f"\n{'='*100}")
    log(f"📦 БАТЧ {batch_num}/{total_batches} | Ключей в батче: {len(keys_batch)}")
    log(f"{'='*100}\n")
    
    batch_results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS_KEYS) as executor:
        future_to_key = {
            executor.submit(check_key_mobile_quality, key, xray_exe): (idx, key)
            for idx, key in enumerate(keys_batch, 1)
        }
        
        for future in concurrent.futures.as_completed(future_to_key):
            idx, key = future_to_key[future]
            stats["checked"] += 1
            
            try:
                result = future.result()
                
                if result:
                    batch_results.append((key, result))
                    profile_data = MOBILE_PROFILES[result['profile']]
                    
                    log(f"[{idx}/{len(keys_batch)}] {profile_data['emoji']} "
                        f"Latency:{result['latency']['avg']}ms | "
                        f"Stability:{result['stability']}% | "
                        f"Score:{result['weighted_score']} | "
                        f"Sites:{result['total_sites_accessible']}/{result['total_sites_checked']}")
                    
                    stats["by_profile"][result['profile']] += 1
                else:
                    stats["failed"] += 1
                    if stats["checked"] % 20 == 0:
                        log(f"[{idx}/{len(keys_batch)}] ❌ Failed")
                        
            except Exception as e:
                stats["failed"] += 1
    
    return batch_results

# ========== ГЛАВНАЯ ФУНКЦИЯ ==========

def find_latest_verified():
    """Поиск последнего verified файла"""
    if not os.path.exists(RESULTS_FOLDER):
        return None
    
    verified_files = [
        f for f in os.listdir(RESULTS_FOLDER)
        if f.startswith("verified_") and f.endswith(".txt")
    ]
    
    if not verified_files:
        return None
    
    latest = max(
        verified_files,
        key=lambda f: os.path.getmtime(os.path.join(RESULTS_FOLDER, f))
    )
    
    return os.path.join(RESULTS_FOLDER, latest)

def main():
    start_time = time.time()
    
    print("\n" + "="*100)
    print(" "*25 + "📱 MOBILE VPN KEY QUALITY CHECKER")
    print(" "*20 + "Оптимизировано для Hiddify, V2RayNG, V2Box")
    print("="*100 + "\n")
    
    # Проверка Xray
    xray_exe = os.path.join(XRAY_FOLDER, "xray.exe" if os.name == 'nt' else "xray")
    if not os.path.exists(xray_exe):
        log("❌ XRAY не найден в папке xray/")
        return 1
    
    # Поиск исходного файла
    source_file = find_latest_verified()
    if not source_file:
        log("❌ Не найден verified файл в results/")
        log("💡 Создайте файл verified_YYYY-MM-DD.txt с ключами")
        return 1
    
    log(f"📁 Источник: {os.path.basename(source_file)}\n")
    
    # Загрузка ключей
    with open(source_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    keys = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            if '#' in line:
                key = line.split('#')[0].strip()
            else:
                key = line
            keys.append(key)
    
    stats["source_keys"] = len(keys)
    
    log(f"📦 Загружено ключей: {len(keys)}")
    log(f"🔧 Конфигурация:")
    log(f"   - Батчей параллельно: {MAX_WORKERS_KEYS}")
    log(f"   - Сайтов параллельно на ключ: {MAX_WORKERS_PER_KEY}")
    log(f"   - Размер батча: {BATCH_SIZE}")
    log(f"   - Проверок стабильности: {STABILITY_CHECKS}")
    log(f"   - Замеров задержки: {LATENCY_SAMPLES}\n")
    
    log("🎯 Категории проверки:")
    total_sites = 0
    for cat_name, cat_data in SITE_CATEGORIES.items():
        sites_count = len(cat_data['sites'])
        total_sites += sites_count
        log(f"   {cat_data['label']} (вес {cat_data['weight']}): {sites_count} сайтов")
    log(f"\n📊 Всего: {total_sites} сайтов на ключ\n")
    
    # Разбивка на батчи
    batches = [keys[i:i + BATCH_SIZE] for i in range(0, len(keys), BATCH_SIZE)]
    total_batches = len(batches)
    
    log(f"🔄 Обработка разбита на {total_batches} батч(ей)\n")
    
    all_results = []
    
    # Обработка батчами
    for batch_num, batch in enumerate(batches, 1):
        batch_results = process_keys_batch(batch, xray_exe, batch_num, total_batches)
        all_results.extend(batch_results)
        
        # Промежуточная статистика
        if batch_num < total_batches:
            passed = len(all_results)
            elapsed = int(time.time() - start_time)
            remaining = int((elapsed / stats["checked"]) * (stats["source_keys"] - stats["checked"]))
            log(f"\n📊 Промежуточная статистика:")
            log(f"   Проверено: {stats['checked']}/{stats['source_keys']}")
            log(f"   Пройдено: {passed}")
            log(f"   Не прошло: {stats['failed']}")
            log(f"   Дубликатов пропущено: {stats['duplicates_skipped']}")
            log(f"   Время: {elapsed//60}мин {elapsed%60}сек")
            log(f"   Осталось: ~{remaining//60}мин {remaining%60}сек\n")
    
    # ========== СОХРАНЕНИЕ РЕЗУЛЬТАТОВ ==========
    
    log("\n" + "="*100)
    log("💾 СОХРАНЕНИЕ РЕЗУЛЬТАТОВ")
    log("="*100 + "\n")
    
    # Группировка по профилям
    results_by_profile = defaultdict(list)
    for key, result in all_results:
        results_by_profile[result['profile']].append((key, result))
    
    # Сохранение по профилям
    for profile_name, profile_data in MOBILE_PROFILES.items():
        keys_in_profile = results_by_profile.get(profile_name, [])
        if not keys_in_profile:
            continue
        
        # Сортировка: сначала лучшие по задержке
        keys_in_profile.sort(key=lambda x: x[1]['latency']['avg'])
        
        filename = os.path.join(OUTPUT_DIR, f"{profile_name}_{timestamp}.txt")
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {profile_data['label']} - {profile_data['description']}\n")
            f.write(f"# Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# Всего: {len(keys_in_profile)} ключей\n")
            f.write(f"# Отсортировано по задержке (лучшие сверху)\n\n")
            
            for key, result in keys_in_profile:
                f.write(format_key_result(key, result) + "\n")
        
        log(f"{profile_data['emoji']} {profile_data['label']}: {len(keys_in_profile)} ключей → {os.path.basename(filename)}")
    
    # Детальный JSON
    detailed_file = os.path.join(OUTPUT_DIR, f"detailed_{timestamp}.json")
    with open(detailed_file, 'w', encoding='utf-8') as f:
        json.dump([result for _, result in all_results], f, indent=2, ensure_ascii=False)
    log(f"📄 Детальный отчет → {os.path.basename(detailed_file)}")
    
    # Сводка
    stats["total_time"] = int(time.time() - start_time)
    stats["avg_time_per_key"] = round(stats["total_time"] / max(stats["checked"], 1), 2)
    stats["avg_latency_all"] = round(mean(stats["avg_latency"]), 1) if stats["avg_latency"] else 0
    
    summary_file = os.path.join(OUTPUT_DIR, f"summary_{timestamp}.txt")
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write(f"МОБИЛЬНАЯ ПРОВЕРКА VPN КЛЮЧЕЙ\n")
        f.write(f"{'='*80}\n\n")
        f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Исходных ключей: {stats['source_keys']}\n")
        f.write(f"Проверено: {stats['checked']}\n")
        f.write(f"Пройдено: {len(all_results)}\n")
        f.write(f"Не прошло: {stats['failed']}\n")
        f.write(f"Дубликатов пропущено: {stats['duplicates_skipped']}\n")
        f.write(f"Процент успеха: {round(len(all_results)/stats['checked']*100, 1)}%\n")
        f.write(f"Средняя задержка: {stats['avg_latency_all']}ms\n")
        f.write(f"Время работы: {stats['total_time']}с ({stats['total_time']//60}мин)\n")
        f.write(f"Среднее время на ключ: {stats['avg_time_per_key']}с\n\n")
        f.write(f"ПО ПРОФИЛЯМ КАЧЕСТВА:\n")
        for profile_name in sorted(stats["by_profile"].keys(), key=lambda x: MOBILE_PROFILES[x]['priority']):
            count = stats["by_profile"][profile_name]
            profile_data = MOBILE_PROFILES[profile_name]
            percentage = round(count / len(all_results) * 100, 1) if all_results else 0
            f.write(f"  {profile_data['emoji']} {profile_data['label']}: {count} ({percentage}%)\n")
    
    log(f"📊 Сводка → {os.path.basename(summary_file)}")
    
    # ========== ФИНАЛЬНАЯ СТАТИСТИКА ==========
    
    print("\n" + "="*100)
    print("🏆 ИТОГОВАЯ СТАТИСТИКА")
    print("="*100)
    print(f"📦 Исходных ключей:     {stats['source_keys']}")
    print(f"✅ Проверено:           {stats['checked']}")
    print(f"🎯 Пройдено:            {len(all_results)} ({round(len(all_results)/stats['checked']*100, 1)}%)")
    print(f"❌ Не прошло:           {stats['failed']}")
    print(f"🔄 Дубликатов:          {stats['duplicates_skipped']}")
    print(f"⚡ Средняя задержка:    {stats['avg_latency_all']}ms")
    print(f"\n💎 ПО ПРОФИЛЯМ КАЧЕСТВА:")
    
    for profile_name in sorted(stats["by_profile"].keys(), key=lambda x: MOBILE_PROFILES[x]['priority']):
        count = stats["by_profile"][profile_name]
        profile_data = MOBILE_PROFILES[profile_name]
        percentage = round(count / len(all_results) * 100, 1) if all_results else 0
        avg_latency_profile = round(mean([
            r[1]['latency']['avg'] for r in all_results if r[1]['profile'] == profile_name
        ]), 1) if count > 0 else 0
        
        print(f"  {profile_data['emoji']} {profile_data['label']}: {count} ({percentage}%) | avg {avg_latency_profile}ms")
    
    print(f"\n⏱️  Время работы:        {stats['total_time']}с ({stats['total_time']//60}мин {stats['total_time']%60}сек)")
    print(f"⚡ Среднее на ключ:     {stats['avg_time_per_key']}с")
    print(f"📂 Результаты:          {OUTPUT_DIR}")
    print("="*100 + "\n")
    
    # Топ-10 лучших ключей
    if all_results:
        print("🥇 ТОП-10 ЛУЧШИХ КЛЮЧЕЙ (по задержке):")
        print("="*100)
        top_keys = sorted(all_results, key=lambda x: x[1]['latency']['avg'])[:10]
        for idx, (key, result) in enumerate(top_keys, 1):
            profile_emoji = MOBILE_PROFILES[result['profile']]['emoji']
            print(f"{idx}. {profile_emoji} {result['latency']['avg']}ms | "
                  f"Stability:{result['stability']}% | "
                  f"Score:{result['weighted_score']} | "
                  f"Sites:{result['total_sites_accessible']}/{result['total_sites_checked']}")
        print("="*100 + "\n")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
