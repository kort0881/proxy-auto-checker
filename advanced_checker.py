"""
📱 MOBILE VPN VALIDATOR v2.0
Продвинутая проверка VPN ключей для мобильных сетей РФ

🎯 Ключевые улучшения:
- Измерение задержки (Latency) с jitter
- Проверка стабильности (множественные запросы)
- Реальные мобильные User-Agents (iOS 17, Android 14)
- Взвешенный рейтинг (банки важнее новостей)
- Параллельная обработка (10 ключей одновременно)
- Дедупликация серверов
- Профили качества для мобильных
"""

import os
import sys
import json
import time
import random
import requests
import subprocess
import base64
import hashlib
from datetime import datetime
from urllib.parse import unquote
import concurrent.futures
from collections import defaultdict
from statistics import mean, stdev, median
import urllib3
urllib3.disable_warnings()

# === НАСТРОЙКИ ===
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FOLDER = os.path.join(WORK_DIR, "results")
XRAY_FOLDER = os.path.join(WORK_DIR, "xray")

# === ПАРАМЕТРЫ ПРОИЗВОДИТЕЛЬНОСТИ ===
MAX_PARALLEL_KEYS = 10          # Параллельных ключей
MAX_PARALLEL_SITES = 12         # Параллельных сайтов на ключ
BATCH_SIZE = 50                 # Размер батча
LATENCY_SAMPLES = 5             # Замеров задержки
STABILITY_CHECKS = 3            # Проверок стабильности на сайт
XRAY_STARTUP_DELAY = 1.0        # Пауза на запуск xray
SITE_TIMEOUT = 8                # Таймаут сайта
BETWEEN_BATCHES_DELAY = 2       # Пауза между батчами

# === МОБИЛЬНЫЕ USER-AGENTS (2024) ===
MOBILE_USER_AGENTS = {
    "iphone_safari": [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_7_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1"
    ],
    "android_chrome": [
        "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 13; SM-A546B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Mobile Safari/537.36",
        "Mozilla/5.0 (Linux; Android 14; 2312DRA50G) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36"  # Xiaomi
    ],
    "android_app": [
        # Для эмуляции запросов из VPN-приложений
        "V2RayNG/1.8.19",
        "Hiddify/2.0.5",
        "SagerNet/0.8.1"
    ]
}

# === САЙТЫ С ВЕСАМИ И МОБИЛЬНЫМИ URL ===
SITE_CATEGORIES = {
    "banks": {
        "label": "🏦 Банки",
        "weight": 3.0,  # Высший приоритет
        "priority": 1,
        "sites": {
            "sberbank": {
                "url": "https://online.sberbank.ru",
                "mobile_url": "https://online.sberbank.ru/CSAFront/index.do",
                "weight": 1.0,
                "critical": True,
                "check_content": ["Сбер", "сбербанк"]
            },
            "tbank": {
                "url": "https://www.tbank.ru",
                "mobile_url": "https://www.tbank.ru",
                "weight": 1.0,
                "critical": True,
                "check_content": ["Т-Банк", "Tinkoff"]
            },
            "vtb": {
                "url": "https://www.vtb.ru",
                "mobile_url": "https://www.vtb.ru",
                "weight": 0.9,
                "critical": True,
                "check_content": ["ВТБ", "VTB"]
            },
            "alfa": {
                "url": "https://alfabank.ru",
                "mobile_url": "https://alfabank.ru",
                "weight": 0.9,
                "critical": True,
                "check_content": ["Альфа", "Alfa"]
            },
            "gazprom": {
                "url": "https://www.gazprombank.ru",
                "mobile_url": "https://www.gazprombank.ru",
                "weight": 0.7,
                "critical": False,
                "check_content": ["Газпром"]
            },
            "raiffeisen": {
                "url": "https://www.raiffeisen.ru",
                "mobile_url": "https://www.raiffeisen.ru",
                "weight": 0.6,
                "critical": False,
                "check_content": ["Райффайзен"]
            }
        }
    },
    
    "gov": {
        "label": "🏛️ Госуслуги",
        "weight": 2.5,
        "priority": 2,
        "sites": {
            "gosuslugi": {
                "url": "https://www.gosuslugi.ru",
                "mobile_url": "https://www.gosuslugi.ru",
                "weight": 1.0,
                "critical": True,
                "check_content": ["Госуслуги"]
            },
            "nalog": {
                "url": "https://www.nalog.gov.ru",
                "mobile_url": "https://www.nalog.gov.ru",
                "weight": 0.9,
                "critical": True,
                "check_content": ["налог", "ФНС"]
            },
            "mos": {
                "url": "https://www.mos.ru",
                "mobile_url": "https://www.mos.ru",
                "weight": 0.7,
                "critical": False,
                "check_content": ["Москва", "mos.ru"]
            },
            "pfr": {
                "url": "https://sfr.gov.ru",
                "mobile_url": "https://sfr.gov.ru",
                "weight": 0.6,
                "critical": False,
                "check_content": ["Социальный фонд"]
            }
        }
    },
    
    "social": {
        "label": "📱 Соцсети",
        "weight": 2.0,
        "priority": 3,
        "sites": {
            "vk": {
                "url": "https://vk.com",
                "mobile_url": "https://m.vk.com",
                "weight": 1.0,
                "critical": True,
                "check_content": ["ВКонтакте", "VK"]
            },
            "ok": {
                "url": "https://ok.ru",
                "mobile_url": "https://m.ok.ru",
                "weight": 0.8,
                "critical": True,
                "check_content": ["Одноклассники"]
            },
            "instagram": {
                "url": "https://www.instagram.com",
                "mobile_url": "https://www.instagram.com",
                "weight": 1.0,
                "critical": True,
                "blocked_ru": True,
                "check_content": ["Instagram"]
            },
            "twitter": {
                "url": "https://x.com",
                "mobile_url": "https://mobile.twitter.com",
                "weight": 0.8,
                "critical": False,
                "blocked_ru": True,
                "check_content": ["X.com", "Twitter"]
            },
            "facebook": {
                "url": "https://www.facebook.com",
                "mobile_url": "https://m.facebook.com",
                "weight": 0.7,
                "critical": False,
                "blocked_ru": True,
                "check_content": ["Facebook"]
            },
            "linkedin": {
                "url": "https://www.linkedin.com",
                "mobile_url": "https://www.linkedin.com",
                "weight": 0.6,
                "critical": False,
                "blocked_ru": True,
                "check_content": ["LinkedIn"]
            }
        }
    },
    
    "messengers": {
        "label": "💬 Мессенджеры",
        "weight": 2.0,
        "priority": 4,
        "sites": {
            "telegram": {
                "url": "https://web.telegram.org",
                "mobile_url": "https://web.telegram.org/k/",
                "weight": 1.0,
                "critical": True,
                "check_content": ["Telegram"]
            },
            "whatsapp": {
                "url": "https://web.whatsapp.com",
                "mobile_url": "https://web.whatsapp.com",
                "weight": 0.9,
                "critical": True,
                "check_content": ["WhatsApp"]
            },
            "discord": {
                "url": "https://discord.com",
                "mobile_url": "https://discord.com/app",
                "weight": 0.7,
                "critical": False,
                "blocked_ru": True,
                "check_content": ["Discord"]
            }
        }
    },
    
    "video": {
        "label": "📺 Видео",
        "weight": 1.5,
        "priority": 5,
        "sites": {
            "youtube": {
                "url": "https://www.youtube.com",
                "mobile_url": "https://m.youtube.com",
                "weight": 1.0,
                "critical": True,
                "check_content": ["YouTube"]
            },
            "rutube": {
                "url": "https://rutube.ru",
                "mobile_url": "https://rutube.ru",
                "weight": 0.6,
                "critical": False,
                "check_content": ["RUTUBE"]
            },
            "kinopoisk": {
                "url": "https://www.kinopoisk.ru",
                "mobile_url": "https://www.kinopoisk.ru",
                "weight": 0.7,
                "critical": False,
                "check_content": ["Кинопоиск"]
            },
            "ivi": {
                "url": "https://www.ivi.ru",
                "mobile_url": "https://www.ivi.ru",
                "weight": 0.5,
                "critical": False,
                "check_content": ["ivi"]
            }
        }
    },
    
    "news": {
        "label": "📰 Новости",
        "weight": 1.0,
        "priority": 6,
        "sites": {
            "dzen": {
                "url": "https://dzen.ru",
                "mobile_url": "https://dzen.ru",
                "weight": 0.8,
                "critical": False,
                "check_content": ["Дзен"]
            },
            "rbc": {
                "url": "https://www.rbc.ru",
                "mobile_url": "https://www.rbc.ru",
                "weight": 0.7,
                "critical": False,
                "check_content": ["РБК"]
            },
            "tass": {
                "url": "https://tass.ru",
                "mobile_url": "https://tass.ru",
                "weight": 0.6,
                "critical": False,
                "check_content": ["ТАСС"]
            },
            "lenta": {
                "url": "https://lenta.ru",
                "mobile_url": "https://m.lenta.ru",
                "weight": 0.5,
                "critical": False,
                "check_content": ["Лента"]
            }
        }
    },
    
    "services": {
        "label": "🛍️ Сервисы",
        "weight": 1.5,
        "priority": 7,
        "sites": {
            "yandex": {
                "url": "https://ya.ru",
                "mobile_url": "https://ya.ru",
                "weight": 1.0,
                "critical": True,
                "check_content": ["Яндекс"]
            },
            "google": {
                "url": "https://www.google.ru",
                "mobile_url": "https://www.google.ru",
                "weight": 1.0,
                "critical": True,
                "check_content": ["Google"]
            },
            "mailru": {
                "url": "https://mail.ru",
                "mobile_url": "https://mail.ru",
                "weight": 0.7,
                "critical": False,
                "check_content": ["Mail.ru"]
            },
            "ozon": {
                "url": "https://www.ozon.ru",
                "mobile_url": "https://www.ozon.ru",
                "weight": 0.8,
                "critical": False,
                "check_content": ["OZON"]
            },
            "wildberries": {
                "url": "https://www.wildberries.ru",
                "mobile_url": "https://www.wildberries.ru",
                "weight": 0.8,
                "critical": False,
                "check_content": ["Wildberries"]
            },
            "avito": {
                "url": "https://www.avito.ru",
                "mobile_url": "https://m.avito.ru",
                "weight": 0.7,
                "critical": False,
                "check_content": ["Авито"]
            }
        }
    },
    
    "operators": {
        "label": "📞 Операторы",
        "weight": 1.0,
        "priority": 8,
        "sites": {
            "mts": {
                "url": "https://www.mts.ru",
                "mobile_url": "https://www.mts.ru",
                "weight": 0.8,
                "critical": False,
                "check_content": ["МТС"]
            },
            "beeline": {
                "url": "https://www.beeline.ru",
                "mobile_url": "https://www.beeline.ru",
                "weight": 0.8,
                "critical": False,
                "check_content": ["Билайн"]
            },
            "megafon": {
                "url": "https://www.megafon.ru",
                "mobile_url": "https://www.megafon.ru",
                "weight": 0.7,
                "critical": False,
                "check_content": ["МегаФон"]
            },
            "tele2": {
                "url": "https://msk.tele2.ru",
                "mobile_url": "https://msk.tele2.ru",
                "weight": 0.6,
                "critical": False,
                "check_content": ["Tele2"]
            }
        }
    }
}

# === ПРОФИЛИ КАЧЕСТВА ДЛЯ МОБИЛЬНЫХ ===
QUALITY_PROFILES = {
    "premium": {
        "emoji": "💎",
        "label": "ПРЕМИУМ",
        "description": "Идеально для мобильных",
        "requirements": {
            "latency_max": 200,
            "stability_min": 90,
            "categories_min": 7,
            "weighted_score_min": 80,
            "banks_required": True,
            "gov_required": True
        },
        "priority": 1
    },
    "excellent": {
        "emoji": "⭐",
        "label": "ОТЛИЧНЫЙ",
        "description": "Отлично для мобильных",
        "requirements": {
            "latency_max": 300,
            "stability_min": 85,
            "categories_min": 6,
            "weighted_score_min": 65,
            "banks_required": True,
            "gov_required": False
        },
        "priority": 2
    },
    "good": {
        "emoji": "✅",
        "label": "ХОРОШИЙ",
        "description": "Хорошо для мобильных",
        "requirements": {
            "latency_max": 500,
            "stability_min": 75,
            "categories_min": 5,
            "weighted_score_min": 50,
            "banks_required": False,
            "gov_required": False
        },
        "priority": 3
    },
    "acceptable": {
        "emoji": "👌",
        "label": "ПРИЕМЛЕМЫЙ",
        "description": "Нормально для мобильных",
        "requirements": {
            "latency_max": 800,
            "stability_min": 60,
            "categories_min": 4,
            "weighted_score_min": 35,
            "banks_required": False,
            "gov_required": False
        },
        "priority": 4
    },
    "basic": {
        "emoji": "📶",
        "label": "БАЗОВЫЙ",
        "description": "Минимум для мобильных",
        "requirements": {
            "latency_max": 1000,
            "stability_min": 50,
            "categories_min": 2,
            "weighted_score_min": 20,
            "banks_required": False,
            "gov_required": False
        },
        "priority": 5
    },
    "limited": {
        "emoji": "⚠️",
        "label": "ОГРАНИЧЕННЫЙ",
        "description": "Проблемы с мобильными",
        "requirements": {
            "latency_max": 9999,
            "stability_min": 0,
            "categories_min": 1,
            "weighted_score_min": 0,
            "banks_required": False,
            "gov_required": False
        },
        "priority": 6
    }
}

# === ИНИЦИАЛИЗАЦИЯ ===
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
OUTPUT_DIR = os.path.join(RESULTS_FOLDER, f"mobile_validated_{timestamp}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

# Для дедупликации
seen_servers = set()

stats = {
    "total_keys": 0,
    "unique_servers": 0,
    "duplicates_skipped": 0,
    "checked": 0,
    "passed": 0,
    "failed": 0,
    "by_profile": defaultdict(int),
    "by_category": defaultdict(lambda: {"accessible": 0, "total": 0}),
    "latency_samples": [],
    "start_time": None
}

def log(msg):
    print(msg, flush=True)

# ========== ПАРСЕРЫ КЛЮЧЕЙ ==========

def get_server_hash(key):
    """Получение уникального хеша сервера для дедупликации"""
    try:
        # Извлекаем host:port из ключа
        if "vless://" in key or "trojan://" in key:
            if "@" in key:
                server_part = key.split("@")[1].split("?")[0].split("#")[0]
                return hashlib.md5(server_part.encode()).hexdigest()[:16]
        elif "vmess://" in key:
            encoded = key.replace("vmess://", "").split("#")[0]
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            try:
                data = json.loads(base64.b64decode(encoded))
                server = f"{data.get('add')}:{data.get('port')}"
                return hashlib.md5(server.encode()).hexdigest()[:16]
            except:
                pass
        elif "ss://" in key:
            if "@" in key:
                server_part = key.split("@")[1].split("#")[0]
                return hashlib.md5(server_part.encode()).hexdigest()[:16]
    except:
        pass
    return hashlib.md5(key.encode()).hexdigest()[:16]

def parse_vless(key):
    try:
        if not key.startswith("vless://"):
            return None
        key = key[8:]
        if "@" not in key:
            return None
        
        uuid_part, rest = key.split("@", 1)
        
        params_part = ""
        if "?" in rest:
            server_part, params_part = rest.split("?", 1)
        else:
            server_part = rest
        
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
        
        config = {
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": host,
                    "port": port,
                    "users": [{
                        "id": uuid_part,
                        "encryption": params.get("encryption", "none"),
                        "flow": params.get("flow", "")
                    }]
                }]
            },
            "streamSettings": {
                "network": params.get("type", "tcp"),
                "security": params.get("security", "none")
            }
        }
        
        # TLS
        if params.get("security") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": params.get("sni", host),
                "allowInsecure": params.get("allowInsecure", "0") == "1",
                "fingerprint": params.get("fp", "chrome")
            }
            if params.get("alpn"):
                config["streamSettings"]["tlsSettings"]["alpn"] = params.get("alpn").split(",")
        
        # Reality
        if params.get("security") == "reality":
            config["streamSettings"]["realitySettings"] = {
                "serverName": params.get("sni", ""),
                "fingerprint": params.get("fp", "chrome"),
                "publicKey": params.get("pbk", ""),
                "shortId": params.get("sid", ""),
                "spiderX": params.get("spx", "")
            }
        
        # WebSocket
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)}
            }
        
        # gRPC
        if params.get("type") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": params.get("serviceName", ""),
                "multiMode": params.get("mode", "") == "multi"
            }
        
        # HTTP/2
        if params.get("type") == "h2":
            config["streamSettings"]["httpSettings"] = {
                "path": params.get("path", "/"),
                "host": [params.get("host", host)]
            }
        
        return config
    except:
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
        
        if data.get("net") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": data.get("path", "")
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
        
        params_part = ""
        if "?" in rest:
            server_part, params_part = rest.split("?", 1)
        else:
            server_part = rest
        
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
        if not security:
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
        
        return {
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
    except:
        return None

def parse_key(key):
    key = key.strip()
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

def create_xray_config(proxy_config, socks_port):
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": True, "auth": "noauth"},
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
        }],
        "outbounds": [proxy_config]
    }

def start_xray(xray_exe, config, config_path):
    try:
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        
        process = subprocess.Popen(
            [xray_exe, "run", "-c", config_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        time.sleep(XRAY_STARTUP_DELAY)
        
        if process.poll() is not None:
            return None
        
        return process
    except:
        return None

def stop_xray(process):
    if not process:
        return
    try:
        process.terminate()
        process.wait(timeout=2)
    except:
        try:
            process.kill()
        except:
            pass

def cleanup_file(filepath):
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except:
        pass

# ========== ИЗМЕРЕНИЕ LATENCY ==========

def measure_latency(proxies, samples=5):
    """Измерение задержки с множественными замерами"""
    latencies = []
    test_url = "https://ya.ru"  # Быстрый российский сайт
    
    headers = {
        "User-Agent": random.choice(MOBILE_USER_AGENTS["iphone_safari"]),
        "Accept-Language": "ru-RU,ru;q=0.9"
    }
    
    for _ in range(samples):
        try:
            start = time.time()
            response = requests.get(
                test_url,
                proxies=proxies,
                headers=headers,
                timeout=5,
                allow_redirects=True,
                verify=False
            )
            if response.status_code < 400:
                latency = (time.time() - start) * 1000  # мс
                latencies.append(latency)
        except:
            pass
        time.sleep(0.1)
    
    if not latencies:
        return None
    
    return {
        "avg": round(mean(latencies), 1),
        "min": round(min(latencies), 1),
        "max": round(max(latencies), 1),
        "jitter": round(stdev(latencies), 1) if len(latencies) > 1 else 0,
        "samples": len(latencies)
    }

# ========== ПРОВЕРКА САЙТОВ ==========

def get_mobile_headers(for_bank=False):
    """Получение мобильных заголовков"""
    if for_bank:
        # Для банков используем Safari (больше доверия)
        ua = random.choice(MOBILE_USER_AGENTS["iphone_safari"])
    else:
        # Для остальных - случайный
        all_uas = MOBILE_USER_AGENTS["iphone_safari"] + MOBILE_USER_AGENTS["android_chrome"]
        ua = random.choice(all_uas)
    
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.5,en;q=0.3",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "none",
        "Cache-Control": "max-age=0"
    }

def check_site_with_stability(site_name, site_info, proxies, category_name):
    """Проверка сайта с замером стабильности"""
    url = site_info.get("mobile_url", site_info["url"])
    is_bank = category_name == "banks"
    
    successes = 0
    total_time = 0
    
    for attempt in range(STABILITY_CHECKS):
        try:
            headers = get_mobile_headers(for_bank=is_bank)
            
            start = time.time()
            response = requests.get(
                url,
                proxies=proxies,
                headers=headers,
                timeout=SITE_TIMEOUT,
                allow_redirects=True,
                verify=False
            )
            elapsed = time.time() - start
            
            if response.status_code < 400:
                # Проверка контента (опционально)
                content_ok = True
                if site_info.get("check_content"):
                    content = response.text.lower()
                    content_ok = any(
                        text.lower() in content 
                        for text in site_info["check_content"]
                    )
                
                if content_ok:
                    successes += 1
                    total_time += elapsed
        except:
            pass
        
        if attempt < STABILITY_CHECKS - 1:
            time.sleep(0.2)
    
    stability = (successes / STABILITY_CHECKS) * 100
    avg_time = (total_time / successes * 1000) if successes > 0 else 0
    
    return {
        "name": site_name,
        "accessible": successes > 0,
        "stability": round(stability, 1),
        "avg_response_ms": round(avg_time, 1),
        "attempts": STABILITY_CHECKS,
        "successes": successes,
        "weight": site_info.get("weight", 1.0),
        "critical": site_info.get("critical", False)
    }

def check_all_sites_parallel(proxies):
    """Параллельная проверка всех сайтов"""
    results = {}
    all_tasks = []
    
    # Собираем все задачи
    for cat_name, cat_data in SITE_CATEGORIES.items():
        results[cat_name] = {
            "label": cat_data["label"],
            "weight": cat_data["weight"],
            "sites": {},
            "accessible_count": 0,
            "total_count": len(cat_data["sites"]),
            "weighted_score": 0,
            "avg_stability": 0
        }
        
        for site_name, site_info in cat_data["sites"].items():
            all_tasks.append((cat_name, site_name, site_info))
    
    # Параллельная проверка
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL_SITES) as executor:
        futures = {}
        for cat_name, site_name, site_info in all_tasks:
            future = executor.submit(
                check_site_with_stability,
                site_name, site_info, proxies, cat_name
            )
            futures[future] = (cat_name, site_name)
        
        for future in concurrent.futures.as_completed(futures, timeout=SITE_TIMEOUT * STABILITY_CHECKS * 2):
            cat_name, site_name = futures[future]
            try:
                site_result = future.result()
                results[cat_name]["sites"][site_name] = site_result
                
                if site_result["accessible"]:
                    results[cat_name]["accessible_count"] += 1
                    results[cat_name]["weighted_score"] += site_result["weight"]
            except:
                results[cat_name]["sites"][site_name] = {
                    "name": site_name,
                    "accessible": False,
                    "stability": 0,
                    "error": "timeout"
                }
    
    # Подсчет средней стабильности по категории
    for cat_name, cat_data in results.items():
        stabilities = [
            s["stability"] for s in cat_data["sites"].values()
            if s.get("accessible")
        ]
        if stabilities:
            cat_data["avg_stability"] = round(mean(stabilities), 1)
    
    return results

# ========== ПРОФИЛИРОВАНИЕ ==========

def calculate_weighted_score(site_results):
    """Расчет взвешенного рейтинга"""
    total_score = 0
    max_score = 0
    
    for cat_name, cat_data in site_results.items():
        cat_weight = SITE_CATEGORIES[cat_name]["weight"]
        
        # Максимальный балл категории
        max_cat_score = sum(
            s.get("weight", 1.0) 
            for s in SITE_CATEGORIES[cat_name]["sites"].values()
        ) * cat_weight
        max_score += max_cat_score
        
        # Набранный балл
        earned = cat_data["weighted_score"] * cat_weight
        total_score += earned
    
    return round((total_score / max_score * 100), 1) if max_score > 0 else 0

def determine_quality_profile(site_results, latency_data):
    """Определение профиля качества"""
    
    # Подсчет метрик
    accessible_categories = [
        cat for cat, data in site_results.items()
        if data["accessible_count"] > 0
    ]
    categories_count = len(accessible_categories)
    
    # Средняя стабильность по всем сайтам
    all_stabilities = []
    for cat_data in site_results.values():
        for site_data in cat_data["sites"].values():
            if site_data.get("accessible"):
                all_stabilities.append(site_data["stability"])
    
    avg_stability = mean(all_stabilities) if all_stabilities else 0
    
    # Взвешенный рейтинг
    weighted_score = calculate_weighted_score(site_results)
    
    # Latency
    avg_latency = latency_data["avg"] if latency_data else 9999
    
    # Проверка банков и госуслуг
    has_banks = site_results.get("banks", {}).get("accessible_count", 0) >= 3
    has_gov = site_results.get("gov", {}).get("accessible_count", 0) >= 2
    
    # Проход по профилям
    for profile_name in sorted(QUALITY_PROFILES.keys(), key=lambda x: QUALITY_PROFILES[x]["priority"]):
        profile = QUALITY_PROFILES[profile_name]
        req = profile["requirements"]
        
        # Проверка требований
        if avg_latency > req["latency_max"]:
            continue
        if avg_stability < req["stability_min"]:
            continue
        if categories_count < req["categories_min"]:
            continue
        if weighted_score < req["weighted_score_min"]:
            continue
        if req["banks_required"] and not has_banks:
            continue
        if req["gov_required"] and not has_gov:
            continue
        
        return profile_name
    
    return "limited"

# ========== ОСНОВНАЯ ПРОВЕРКА КЛЮЧА ==========

def check_single_key(key, xray_exe, key_index, total_keys):
    """Полная проверка одного ключа"""
    try:
        # Дедупликация
        server_hash = get_server_hash(key)
        if server_hash in seen_servers:
            return {"status": "duplicate", "key": key}
        seen_servers.add(server_hash)
        
        # Парсинг
        proxy_config, protocol = parse_key(key)
        if not proxy_config:
            return {"status": "parse_error", "key": key}
        
        # Запуск Xray
        socks_port = random.randint(20000, 50000)
        config = create_xray_config(proxy_config, socks_port)
        config_path = os.path.join(XRAY_FOLDER, f"mobile_{socks_port}.json")
        
        process = start_xray(xray_exe, config, config_path)
        if not process:
            cleanup_file(config_path)
            return {"status": "xray_error", "key": key}
        
        try:
            proxies = {
                'http': f'socks5h://127.0.0.1:{socks_port}',
                'https': f'socks5h://127.0.0.1:{socks_port}'
            }
            
            # 1. Измерение latency
            latency_data = measure_latency(proxies, LATENCY_SAMPLES)
            if not latency_data:
                return {"status": "latency_fail", "key": key}
            
            # 2. Проверка всех сайтов
            site_results = check_all_sites_parallel(proxies)
            
            # 3. Определение профиля
            profile = determine_quality_profile(site_results, latency_data)
            
            # 4. Подсчет статистики
            total_accessible = sum(
                cat["accessible_count"] for cat in site_results.values()
            )
            total_sites = sum(
                cat["total_count"] for cat in site_results.values()
            )
            weighted_score = calculate_weighted_score(site_results)
            
            # Средняя стабильность
            all_stabilities = []
            for cat_data in site_results.values():
                for site_data in cat_data["sites"].values():
                    if site_data.get("accessible"):
                        all_stabilities.append(site_data["stability"])
            avg_stability = mean(all_stabilities) if all_stabilities else 0
            
            return {
                "status": "success",
                "key": key,
                "protocol": protocol,
                "profile": profile,
                "latency": latency_data,
                "stability": round(avg_stability, 1),
                "weighted_score": weighted_score,
                "categories": site_results,
                "accessible_categories": [
                    cat for cat, data in site_results.items()
                    if data["accessible_count"] > 0
                ],
                "total_accessible": total_accessible,
                "total_sites": total_sites
            }
            
        finally:
            stop_xray(process)
            cleanup_file(config_path)
            
    except Exception as e:
        return {"status": "error", "key": key, "error": str(e)}

# ========== БАТЧЕВАЯ ОБРАБОТКА ==========

def process_batch(batch, xray_exe, batch_num, total_batches, start_idx):
    """Обработка батча ключей параллельно"""
    results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_PARALLEL_KEYS) as executor:
        futures = {}
        for i, key in enumerate(batch):
            key_idx = start_idx + i + 1
            future = executor.submit(
                check_single_key, key, xray_exe, key_idx, stats["total_keys"]
            )
            futures[future] = (key, key_idx)
        
        for future in concurrent.futures.as_completed(futures):
            key, key_idx = futures[future]
            try:
                result = future.result()
                results.append(result)
                
                # Логирование
                if result["status"] == "success":
                    profile_info = QUALITY_PROFILES[result["profile"]]
                    log(f"  [{key_idx}] {profile_info['emoji']} {result['profile'].upper()}: "
                        f"Lat:{result['latency']['avg']:.0f}ms Stab:{result['stability']:.0f}% "
                        f"Score:{result['weighted_score']:.0f} Sites:{result['total_accessible']}/{result['total_sites']}")
                elif result["status"] == "duplicate":
                    log(f"  [{key_idx}] 🔄 Дубликат - пропущен")
                else:
                    log(f"  [{key_idx}] ❌ {result['status']}")
                    
            except Exception as e:
                log(f"  [{key_idx}] ❌ Ошибка: {e}")
                results.append({"status": "error", "key": key})
    
    return results

# ========== ФОРМАТИРОВАНИЕ ==========

def format_result_line(result):
    """Форматирование строки результата"""
    key = result["key"]
    profile = result["profile"]
    profile_info = QUALITY_PROFILES[profile]
    
    # Категории
    cats = []
    for cat_name in result["accessible_categories"]:
        cat_label = SITE_CATEGORIES[cat_name]["label"].split()[0]
        count = result["categories"][cat_name]["accessible_count"]
        total = result["categories"][cat_name]["total_count"]
        cats.append(f"{cat_label}{count}/{total}")
    
    cats_str = " ".join(cats[:6])
    
    # Метрики
    lat = result["latency"]["avg"]
    stab = result["stability"]
    score = result["weighted_score"]
    
    comment = (f"#{profile_info['emoji']} Lat:{lat:.0f}ms Stab:{stab:.0f}% "
               f"Score:{score:.0f} [{cats_str}]")
    
    return f"{key} {comment}"

# ========== MAIN ==========

def find_latest_verified():
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
    stats["start_time"] = time.time()
    
    print("\n" + "="*100)
    print(" "*20 + "📱 MOBILE VPN VALIDATOR v2.0")
    print(" "*15 + "Продвинутая проверка для мобильных сетей РФ")
    print("="*100)
    
    print("""
🎯 Что проверяем:
   ⚡ Latency (задержка) - {samples} замеров с jitter
   📊 Стабильность - {stability} попыток на сайт
   🌐 {sites} сайтов в {cats} категориях
   📱 Mobile User-Agent (iOS 17, Android 14)
   🇷🇺 Accept-Language: ru-RU
   ⚖️ Взвешенный рейтинг (банки важнее новостей)
""".format(
        samples=LATENCY_SAMPLES,
        stability=STABILITY_CHECKS,
        sites=sum(len(c["sites"]) for c in SITE_CATEGORIES.values()),
        cats=len(SITE_CATEGORIES)
    ))
    
    # Xray
    xray_exe = os.path.join(XRAY_FOLDER, "xray.exe" if os.name == 'nt' else "xray")
    if not os.path.exists(xray_exe):
        log(f"❌ Xray не найден: {xray_exe}")
        return 1
    
    # Источник
    source_file = find_latest_verified()
    if not source_file:
        log("❌ Не найден verified файл в results/")
        return 1
    
    log(f"📁 Источник: {os.path.basename(source_file)}")
    
    # Загрузка
    with open(source_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    keys = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            key = line.split('#')[0].strip()
            if key:
                keys.append(key)
    
    stats["total_keys"] = len(keys)
    
    log(f"📦 Загружено ключей: {len(keys)}")
    
    # Оценка времени
    # ~4 сек на ключ при параллельной обработке
    est_seconds = (len(keys) / MAX_PARALLEL_KEYS) * 6
    log(f"⏱️  Оценка времени: ~{int(est_seconds//60)} мин")
    log(f"🔧 Параллельность: {MAX_PARALLEL_KEYS} ключей × {MAX_PARALLEL_SITES} сайтов")
    
    print("\n" + "="*100)
    log("🚀 Начинаем проверку...")
    print("="*100 + "\n")
    
    # Батчевая обработка
    all_results = []
    batches = [keys[i:i+BATCH_SIZE] for i in range(0, len(keys), BATCH_SIZE)]
    
    for batch_num, batch in enumerate(batches, 1):
        start_idx = (batch_num - 1) * BATCH_SIZE
        
        elapsed = time.time() - stats["start_time"]
        if batch_num > 1:
            avg_per_key = elapsed / start_idx
            remaining = avg_per_key * (len(keys) - start_idx)
            log(f"\n📦 Батч {batch_num}/{len(batches)} | "
                f"Прогресс: {start_idx}/{len(keys)} | "
                f"Осталось: ~{int(remaining//60)}мин")
        else:
            log(f"\n📦 Батч {batch_num}/{len(batches)}")
        
        batch_results = process_batch(batch, xray_exe, batch_num, len(batches), start_idx)
        all_results.extend(batch_results)
        
        if batch_num < len(batches):
            time.sleep(BETWEEN_BATCHES_DELAY)
    
    # Фильтрация успешных
    successful = [r for r in all_results if r["status"] == "success"]
    duplicates = [r for r in all_results if r["status"] == "duplicate"]
    failed = [r for r in all_results if r["status"] not in ["success", "duplicate"]]
    
    stats["passed"] = len(successful)
    stats["failed"] = len(failed)
    stats["duplicates_skipped"] = len(duplicates)
    stats["unique_servers"] = len(seen_servers)
    
    # Группировка по профилям
    by_profile = defaultdict(list)
    for r in successful:
        by_profile[r["profile"]].append(r)
        stats["by_profile"][r["profile"]] += 1
    
    # === СОХРАНЕНИЕ ===
    log("\n" + "="*100)
    log("💾 СОХРАНЕНИЕ РЕЗУЛЬТАТОВ")
    log("="*100 + "\n")
    
    # По профилям
    for profile_name in sorted(QUALITY_PROFILES.keys(), key=lambda x: QUALITY_PROFILES[x]["priority"]):
        results = by_profile.get(profile_name, [])
        if not results:
            continue
        
        profile_info = QUALITY_PROFILES[profile_name]
        filename = os.path.join(OUTPUT_DIR, f"{profile_name}_{timestamp}.txt")
        
        # Сортировка по weighted_score
        results.sort(key=lambda x: x["weighted_score"], reverse=True)
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {profile_info['emoji']} {profile_info['label']}\n")
            f.write(f"# {profile_info['description']}\n")
            f.write(f"# Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# Количество: {len(results)}\n")
            f.write(f"# Метрики: Latency, Stability, Weighted Score\n\n")
            
            for r in results:
                f.write(format_result_line(r) + "\n")
        
        log(f"{profile_info['emoji']} {profile_info['label']}: {len(results)} → {os.path.basename(filename)}")
    
    # Детальный JSON
    detailed_file = os.path.join(OUTPUT_DIR, f"detailed_{timestamp}.json")
    with open(detailed_file, 'w', encoding='utf-8') as f:
        json.dump(successful, f, indent=2, ensure_ascii=False, default=str)
    log(f"📄 Детальный JSON → {os.path.basename(detailed_file)}")
    
    # Сводка
    total_time = int(time.time() - stats["start_time"])
    
    summary_file = os.path.join(OUTPUT_DIR, f"summary_{timestamp}.txt")
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("MOBILE VPN VALIDATOR v2.0 - СВОДКА\n")
        f.write("="*80 + "\n\n")
        
        f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Всего ключей: {stats['total_keys']}\n")
        f.write(f"Уникальных серверов: {stats['unique_servers']}\n")
        f.write(f"Дубликатов пропущено: {stats['duplicates_skipped']}\n")
        f.write(f"Прошли проверку: {stats['passed']}\n")
        f.write(f"Не прошли: {stats['failed']}\n")
        f.write(f"Время: {total_time}с ({total_time//60}мин)\n")
        f.write(f"Среднее на ключ: {total_time/max(len(keys),1):.1f}с\n\n")
        
        f.write("ПАРАМЕТРЫ ПРОВЕРКИ:\n")
        f.write(f"  Замеров latency: {LATENCY_SAMPLES}\n")
        f.write(f"  Проверок стабильности: {STABILITY_CHECKS}\n")
        f.write(f"  Параллельных ключей: {MAX_PARALLEL_KEYS}\n")
        f.write(f"  Параллельных сайтов: {MAX_PARALLEL_SITES}\n\n")
        
        f.write("ПО ПРОФИЛЯМ КАЧЕСТВА:\n")
        for profile_name in sorted(QUALITY_PROFILES.keys(), key=lambda x: QUALITY_PROFILES[x]["priority"]):
            count = stats["by_profile"].get(profile_name, 0)
            if count > 0:
                info = QUALITY_PROFILES[profile_name]
                pct = count / stats["passed"] * 100 if stats["passed"] > 0 else 0
                f.write(f"  {info['emoji']} {info['label']}: {count} ({pct:.1f}%)\n")
        
        # Статистика latency
        if successful:
            latencies = [r["latency"]["avg"] for r in successful]
            f.write(f"\nСТАТИСТИКА LATENCY:\n")
            f.write(f"  Минимум: {min(latencies):.0f}ms\n")
            f.write(f"  Среднее: {mean(latencies):.0f}ms\n")
            f.write(f"  Медиана: {median(latencies):.0f}ms\n")
            f.write(f"  Максимум: {max(latencies):.0f}ms\n")
    
    log(f"📊 Сводка → {os.path.basename(summary_file)}")
    
    # === ФИНАЛЬНАЯ СТАТИСТИКА ===
    print("\n" + "="*100)
    print("📊 ИТОГОВАЯ СТАТИСТИКА")
    print("="*100)
    print(f"Всего ключей:         {stats['total_keys']}")
    print(f"Уникальных серверов:  {stats['unique_servers']}")
    print(f"Дубликатов пропущено: {stats['duplicates_skipped']}")
    print(f"✅ Прошли:            {stats['passed']}")
    print(f"❌ Не прошли:         {stats['failed']}")
    
    print(f"\n🏆 ПО ПРОФИЛЯМ КАЧЕСТВА:")
    for profile_name in sorted(QUALITY_PROFILES.keys(), key=lambda x: QUALITY_PROFILES[x]["priority"]):
        count = stats["by_profile"].get(profile_name, 0)
        if count > 0:
            info = QUALITY_PROFILES[profile_name]
            pct = count / stats["passed"] * 100 if stats["passed"] > 0 else 0
            print(f"  {info['emoji']} {info['label']}: {count} ({pct:.1f}%)")
    
    if successful:
        latencies = [r["latency"]["avg"] for r in successful]
        print(f"\n⚡ LATENCY:")
        print(f"  Min: {min(latencies):.0f}ms | Avg: {mean(latencies):.0f}ms | Max: {max(latencies):.0f}ms")
    
    print(f"\n⏱️  Время: {total_time}с ({total_time//60}мин)")
    print(f"🚀 Скорость: {len(keys)/max(total_time,1)*60:.1f} ключей/мин")
    print(f"📂 Результаты: {OUTPUT_DIR}")
    print("="*100 + "\n")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
