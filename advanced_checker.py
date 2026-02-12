"""
📱 REAL MOBILE VPN VALIDATOR v5.3 (FINAL)
Двухэтапная проверка с адаптивными таймаутами и всеми оптимизациями

Изменения v5.3:
- SNI blacklist (без apple.com — он рабочий для Reality)
- TIMEOUT_SLOW: (4, 15) — компромисс между скоростью и полнотой
- MIN_STABILITY: 80% — 70% слишком низко для юзабельности
- Rate limiting: 0.05-0.15s между запросами
- GC + очистка каждые 500 ключей
- Xray policy connIdle: 300
- IP-check только для ELITE кандидатов
- Telegram категория + бонус +5
- Итоговая статистика в файл
- Ожидаемое время: 35-45 мин на 2600 ключей
"""

import os
import sys
import json
import time
import random
import socket
import subprocess
import platform
import base64
import logging
import contextlib
import tempfile
import gc
from datetime import datetime
from urllib.parse import unquote, quote, urlparse
from pathlib import Path
import concurrent.futures
from collections import defaultdict
from statistics import mean, stdev
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any, Generator, Union, Set
from enum import Enum

import requests
from requests.adapters import HTTPAdapter
import urllib3

# === ОТКЛЮЧЕНИЕ WARNINGS ===
urllib3.disable_warnings()
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)

# === ЛОГИРОВАНИЕ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)


# === ТИПЫ ===
Timeout = Union[float, Tuple[float, float]]


# === SNI BLACKLIST ===
# Только ЯВНО невалидные SNI
# apple.com НЕ блокируем — он рабочий SNI для Reality серверов
CRITICAL_BAD_SNI: Set[str] = {
    # Невалидные адреса
    "localhost",
    "127.0.0.1",
    "0.0.0.0",
    "::1",
    "",
    # Тестовые домены
    "example.com",
    "example.org",
    "test.com",
    "test.org",
    # Явный мусор
    "fuck.rkn",
    "invalid.invalid",
    "none",
    "null",
}


def is_critical_bad_sni(sni: Optional[str]) -> bool:
    """Проверка только критически плохих SNI"""
    if sni is None:
        return False
    
    sni = sni.lower().strip()
    
    # Пустой SNI
    if not sni:
        return True
    
    # Точное совпадение с blacklist
    if sni in CRITICAL_BAD_SNI:
        return True
    
    # IP-адрес вместо домена (кроме нормальных серверных IP)
    if sni.startswith("127.") or sni.startswith("0."):
        return True
    
    # Поддомены заблокированных
    for bad in CRITICAL_BAD_SNI:
        if bad and sni.endswith("." + bad):
            return True
    
    return False


# === КОНФИГУРАЦИЯ ===
@dataclass
class Config:
    """Конфигурация валидатора"""
    
    # --- ЭТАП 1: Quick Filter ---
    QUICK_PARALLEL: int = 50
    QUICK_TIMEOUT: Timeout = (2.0, 4.0)
    QUICK_RETRIES: int = 1
    
    # --- ЭТАП 2: Full Test ---
    FULL_PARALLEL: int = 20
    LATENCY_SAMPLES: int = 8
    STABILITY_CHECKS: int = 10
    CATEGORY_SAMPLES: int = 2
    
    # --- Адаптивные таймауты (connect, read) ---
    TIMEOUT_FAST: Timeout = (2.0, 5.0)      # Google, Yandex, VK, 204-check
    TIMEOUT_NORMAL: Timeout = (3.0, 8.0)    # YouTube, Instagram, News
    TIMEOUT_SLOW: Timeout = (4.0, 15.0)     # Банки, Госуслуги, Телеком
    
    # --- Rate Limiting ---
    RATE_LIMIT_MIN: float = 0.05
    RATE_LIMIT_MAX: float = 0.15
    
    # --- Очистка памяти ---
    GC_EVERY_N_KEYS: int = 500
    GC_SLEEP: float = 1.0
    
    # --- Xray ---
    XRAY_STARTUP: float = 0.6
    XRAY_STARTUP_STABILITY: float = 0.4
    XRAY_CONN_IDLE: int = 300
    
    # --- Пороги ---
    MIN_LATENCY_SAMPLES: int = 4
    MIN_STABILITY_PERCENT: float = 80.0     # Повышено с 70%
    
    # --- ELITE IP Check пороги ---
    ELITE_LATENCY_THRESHOLD: float = 100.0
    ELITE_STABILITY_THRESHOLD: float = 95.0
    
    # --- Retry ---
    MAX_RETRIES: int = 1
    RETRY_DELAY: float = 0.3
    
    # --- Бонусы ---
    TELEGRAM_BONUS: int = 5


CONFIG = Config()


# === КЛАССИФИКАЦИЯ САЙТОВ ===
FAST_SITES: Set[str] = {
    "www.google.com", "google.com",
    "yandex.ru", "www.yandex.ru",
    "vk.com", "www.vk.com",
    "mail.ru", "www.mail.ru",
    "ok.ru", "www.ok.ru",
    "www.gstatic.com",
    "cp.cloudflare.com",
    "connectivitycheck.android.com",
    "web.telegram.org",
    "t.me",
}

SLOW_SITES: Set[str] = {
    # Банки
    "www.sberbank.ru", "sberbank.ru",
    "www.tbank.ru", "tbank.ru",
    "www.vtb.ru", "vtb.ru",
    "alfabank.ru", "www.alfabank.ru",
    "www.gazprombank.ru",
    # Госуслуги
    "www.gosuslugi.ru", "gosuslugi.ru",
    "www.nalog.gov.ru", "nalog.gov.ru",
    "esia.gosuslugi.ru",
    # Телеком
    "www.mts.ru", "mts.ru",
    "moskva.beeline.ru", "beeline.ru",
    "www.megafon.ru", "megafon.ru",
    "msk.tele2.ru",
}

OPTIONAL_SITES: Set[str] = {
    "moskva.beeline.ru",
    "esia.gosuslugi.ru",
    "www.gazprombank.ru",
}


# === ДИРЕКТОРИИ ===
WORK_DIR = Path(__file__).parent.absolute()
RESULTS_FOLDER = WORK_DIR / "results"
XRAY_FOLDER = WORK_DIR / "xray"
OUTPUT_DIR = RESULTS_FOLDER / "premium"

for d in [RESULTS_FOLDER, XRAY_FOLDER, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# === САЙТЫ ДЛЯ ПРОВЕРКИ ===
QUICK_CHECK_URLS: List[str] = [
    "http://www.gstatic.com/generate_204",
    "http://cp.cloudflare.com/generate_204",
]

CHECK_SITES: Dict[str, List[Tuple[str, str]]] = {
    "telegram": [
        ("https://web.telegram.org", "Telegram Web"),
        ("https://t.me", "Telegram Links"),
    ],
    "banks": [
        ("https://www.sberbank.ru", "Сбербанк"),
        ("https://www.tbank.ru", "Т-Банк"),
        ("https://www.vtb.ru", "ВТБ"),
    ],
    "gov": [
        ("https://www.gosuslugi.ru", "Госуслуги"),
        ("https://www.nalog.gov.ru", "Налоговая"),
    ],
    "social": [
        ("https://vk.com", "VK"),
        ("https://www.instagram.com", "Instagram"),
        ("https://x.com", "Twitter/X"),
    ],
    "messengers": [
        ("https://web.whatsapp.com", "WhatsApp Web"),
        ("https://www.viber.com", "Viber"),
    ],
    "video": [
        ("https://www.youtube.com", "YouTube"),
        ("https://www.kinopoisk.ru", "Кинопоиск"),
    ],
    "news": [
        ("https://www.rbc.ru", "РБК"),
        ("https://tass.ru", "ТАСС"),
    ],
    "services": [
        ("https://www.google.com", "Google"),
        ("https://yandex.ru", "Яндекс"),
        ("https://www.ozon.ru", "Ozon"),
    ],
    "telecom": [
        ("https://www.mts.ru", "МТС"),
        ("https://www.megafon.ru", "Мегафон"),
    ]
}

USER_AGENTS: List[str] = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 Chrome/123.0.0.0",
]


# === ПРОФИЛИ КАЧЕСТВА ===
class QualityProfile(Enum):
    ELITE = "elite"
    PREMIUM = "premium"
    GOOD = "good"


@dataclass(frozen=True)
class ProfileThresholds:
    label: str
    latency_max: float
    jitter_max: float
    stability_min: float
    categories_min: int
    priority: int


QUALITY_PROFILES: Dict[QualityProfile, ProfileThresholds] = {
    QualityProfile.ELITE: ProfileThresholds(
        label="ELITE", latency_max=80, jitter_max=20,
        stability_min=98, categories_min=7, priority=1
    ),
    QualityProfile.PREMIUM: ProfileThresholds(
        label="PREM", latency_max=150, jitter_max=35,
        stability_min=90, categories_min=6, priority=2
    ),
    QualityProfile.GOOD: ProfileThresholds(
        label="GOOD", latency_max=300, jitter_max=80,
        stability_min=80, categories_min=4, priority=3  # stability_min повышено с 70
    )
}


# === СТРУКТУРЫ ДАННЫХ ===
@dataclass
class ServerInfo:
    protocol: str
    host: str
    port: int
    uuid: Optional[str] = None
    security: str = "none"
    sni: Optional[str] = None
    network_type: str = "tcp"
    flow: str = ""
    pbk: str = ""
    sid: str = ""
    fp: str = ""
    path: str = ""
    service_name: str = ""
    method: Optional[str] = None
    password: Optional[str] = None


@dataclass
class QuickResult:
    key: str
    alive: bool
    latency: Optional[float] = None


@dataclass
class FullResult:
    key: str
    latency_avg: float
    latency_jitter: float
    stability_rate: float
    categories_passed: int
    category_details: Dict[str, int]
    profile: QualityProfile
    score: int
    proxy_ip: Optional[str] = None
    telegram_works: bool = False


@dataclass
class Stats:
    total: int = 0
    quick_alive: int = 0
    quick_dead: int = 0
    quick_bad_sni: int = 0  # Отсеяно по SNI
    full_passed: int = 0
    full_failed: int = 0
    elite_with_ip: int = 0
    by_profile: Dict[QualityProfile, int] = field(default_factory=lambda: defaultdict(int))
    
    start_time: float = field(default_factory=time.time)
    quick_time: float = 0
    full_time: float = 0


# === УТИЛИТЫ ===
def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        return s.getsockname()[1]


def safe_remove(path: Path):
    with contextlib.suppress(OSError):
        path.unlink()


def get_timeout_for_url(url: str) -> Timeout:
    """Адаптивный таймаут по типу сайта"""
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return CONFIG.TIMEOUT_NORMAL
    
    if host in FAST_SITES or "generate_204" in url:
        return CONFIG.TIMEOUT_FAST
    elif host in SLOW_SITES:
        return CONFIG.TIMEOUT_SLOW
    else:
        return CONFIG.TIMEOUT_NORMAL


def is_optional_site(url: str) -> bool:
    """Опциональный сайт — не влияет на оценку при таймауте"""
    try:
        host = urlparse(url).netloc.lower()
        return host in OPTIONAL_SITES
    except Exception:
        return False


def rate_limit_delay():
    """Задержка между запросами для защиты от rate limiting"""
    time.sleep(random.uniform(CONFIG.RATE_LIMIT_MIN, CONFIG.RATE_LIMIT_MAX))


def cleanup_memory():
    """Очистка памяти и освобождение портов"""
    gc.collect()
    time.sleep(CONFIG.GC_SLEEP)


# === HTTP КЛИЕНТ ===
def create_session(proxies: Dict[str, str]) -> requests.Session:
    """Создание HTTP сессии без urllib3 retry (retry делаем сами)"""
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=0, pool_connections=10, pool_maxsize=10)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.proxies.update(proxies)
    return session


def smart_request(
    session: requests.Session,
    url: str,
    timeout: Optional[Timeout] = None,
    retries: int = 1
) -> Tuple[Optional[requests.Response], float]:
    """
    HTTP запрос с нашими retry и адаптивным таймаутом.
    
    - ConnectTimeout → сразу отказ (сервер мёртв)
    - ReadTimeout → retry (сервер жив, но медленный)
    - ConnectionError → сразу отказ
    
    Возвращает (response, latency_ms)
    """
    if timeout is None:
        timeout = get_timeout_for_url(url)
    
    for attempt in range(retries + 1):
        try:
            start = time.time()
            response = session.get(
                url,
                timeout=timeout,
                headers={"User-Agent": random.choice(USER_AGENTS)},
                allow_redirects=True
            )
            latency = (time.time() - start) * 1000
            return response, latency
            
        except requests.exceptions.ConnectTimeout:
            # Сервер не доступен — retry бесполезен
            return None, 0
            
        except requests.exceptions.ReadTimeout:
            # Сервер подключился, но не ответил — можно попробовать ещё
            if attempt < retries:
                time.sleep(CONFIG.RETRY_DELAY)
                
        except requests.exceptions.ConnectionError:
            # Соединение отклонено — retry бесполезен
            return None, 0
            
        except requests.exceptions.RequestException:
            # Другие ошибки — попробуем ещё раз
            if attempt < retries:
                time.sleep(CONFIG.RETRY_DELAY)
    
    return None, 0


def check_proxy_ip(session: requests.Session) -> Optional[str]:
    """Проверка IP прокси (только для ELITE кандидатов)"""
    try:
        response, _ = smart_request(
            session,
            "https://api64.ipify.org?format=json",
            timeout=(2, 3),
            retries=0
        )
        if response and response.status_code == 200:
            data = response.json()
            return data.get('ip')
    except Exception:
        pass
    return None


# === XRAY ===
@contextlib.contextmanager
def xray_session(
    xray_exe: Path,
    config: Dict[str, Any],
    startup_delay: float = CONFIG.XRAY_STARTUP
) -> Generator[Optional[Tuple[subprocess.Popen, int, Path]], None, None]:
    """Context manager для безопасного управления Xray процессом"""
    
    process = None
    config_file = None
    
    try:
        fd, path = tempfile.mkstemp(suffix='.json', prefix='xray_', dir=XRAY_FOLDER)
        config_file = Path(path)
        
        with os.fdopen(fd, 'w') as f:
            json.dump(config, f)
        
        process = subprocess.Popen(
            [str(xray_exe), "run", "-c", str(config_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        time.sleep(startup_delay)
        
        if process.poll() is not None:
            yield None
            return
        
        port = config["inbounds"][0]["port"]
        yield (process, port, config_file)
        
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=1)
                except Exception:
                    pass
        
        if config_file:
            safe_remove(config_file)


# === УСТАНОВКА XRAY ===
class XrayInstaller:
    @staticmethod
    def get_exe_name() -> str:
        return "xray.exe" if os.name == 'nt' else "xray"
    
    @classmethod
    def setup(cls) -> Optional[Path]:
        exe_path = XRAY_FOLDER / cls.get_exe_name()
        
        if exe_path.exists():
            logger.info("✅ Xray найден")
            return exe_path
        
        logger.info("🔽 Скачиваем Xray...")
        
        try:
            system = platform.system().lower()
            machine = platform.machine().lower()
            
            if system == "windows":
                arch = "64" if "64" in machine else "32"
                filename = f"Xray-windows-{arch}.zip"
            elif system == "linux":
                if "aarch64" in machine or "arm64" in machine:
                    arch = "arm64-v8a"
                else:
                    arch = "64"
                filename = f"Xray-linux-{arch}.zip"
            elif system == "darwin":
                arch = "arm64-v8a" if "arm" in machine else "64"
                filename = f"Xray-macos-{arch}.zip"
            else:
                logger.error(f"❌ Неподдерживаемая ОС: {system}")
                return None
            
            url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{filename}"
            
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            zip_path = XRAY_FOLDER / "xray.zip"
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(8192):
                    f.write(chunk)
            
            import zipfile
            with zipfile.ZipFile(zip_path) as zf:
                zf.extractall(XRAY_FOLDER)
            
            zip_path.unlink()
            
            if os.name != 'nt':
                exe_path.chmod(0o755)
            
            logger.info("✅ Xray установлен")
            return exe_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка установки Xray: {e}")
            return None


# === ПАРСЕРЫ ===
class KeyParser:
    @classmethod
    def parse(cls, key: str) -> Optional[ServerInfo]:
        key = key.strip().split('#')[0].strip()
        if not key:
            return None
        
        try:
            if key.startswith("vless://"):
                return cls._parse_vless(key)
            elif key.startswith("ss://"):
                return cls._parse_ss(key)
            elif key.startswith("vmess://"):
                return cls._parse_vmess(key)
            elif key.startswith("trojan://"):
                return cls._parse_trojan(key)
        except Exception:
            pass
        return None
    
    @classmethod
    def _parse_vless(cls, key: str) -> ServerInfo:
        data = key[8:]
        uuid, rest = data.split("@", 1)
        server = rest.split("?")[0].split("#")[0]
        
        if "]:" in server:
            host, port = server.rsplit(":", 1)
            host = host.strip("[]")
        else:
            host, port = server.rsplit(":", 1)
        
        params: Dict[str, str] = {}
        if "?" in rest:
            for p in rest.split("?")[1].split("#")[0].split("&"):
                if "=" in p:
                    k, v = p.split("=", 1)
                    params[k] = unquote(v)
        
        return ServerInfo(
            protocol="vless", host=host, port=int(port), uuid=uuid,
            security=params.get("security", "none"),
            sni=params.get("sni", host),
            network_type=params.get("type", "tcp"),
            flow=params.get("flow", ""),
            pbk=params.get("pbk", ""),
            sid=params.get("sid", ""),
            fp=params.get("fp", "chrome"),
            path=params.get("path", "/"),
            service_name=params.get("serviceName", "")
        )
    
    @classmethod
    def _parse_ss(cls, key: str) -> ServerInfo:
        data = key[5:].split("#")[0]
        
        if "@" not in data:
            padding = len(data) % 4
            if padding:
                data += '=' * (4 - padding)
            data = base64.urlsafe_b64decode(data).decode()
        
        encoded, server = data.rsplit("@", 1)
        
        if "]:" in server:
            host, port = server.rsplit(":", 1)
            host = host.strip("[]")
        else:
            host, port = server.rsplit(":", 1)
        
        padding = len(encoded) % 4
        if padding:
            encoded += '=' * (4 - padding)
        
        try:
            decoded = base64.urlsafe_b64decode(encoded).decode()
        except Exception:
            decoded = base64.b64decode(encoded).decode()
        
        method, password = decoded.split(":", 1)
        
        return ServerInfo(
            protocol="shadowsocks", host=host, port=int(port),
            method=method, password=password
        )
    
    @classmethod
    def _parse_vmess(cls, key: str) -> ServerInfo:
        encoded = key[8:]
        padding = len(encoded) % 4
        if padding:
            encoded += '=' * (4 - padding)
        
        data = json.loads(base64.urlsafe_b64decode(encoded).decode())
        
        return ServerInfo(
            protocol="vmess",
            host=data.get("add", ""),
            port=int(data.get("port", 443)),
            uuid=data.get("id", ""),
            security=data.get("tls", "none"),
            sni=data.get("sni", data.get("add", "")),
            network_type=data.get("net", "tcp"),
            path=data.get("path", "/")
        )
    
    @classmethod
    def _parse_trojan(cls, key: str) -> ServerInfo:
        data = key[9:]
        password, rest = data.split("@", 1)
        server = rest.split("?")[0].split("#")[0]
        
        if "]:" in server:
            host, port = server.rsplit(":", 1)
            host = host.strip("[]")
        else:
            host, port = server.rsplit(":", 1)
        
        params: Dict[str, str] = {}
        if "?" in rest:
            for p in rest.split("?")[1].split("#")[0].split("&"):
                if "=" in p:
                    k, v = p.split("=", 1)
                    params[k] = unquote(v)
        
        return ServerInfo(
            protocol="trojan", host=host, port=int(port), password=password,
            security=params.get("security", "tls"),
            sni=params.get("sni", host),
            network_type=params.get("type", "tcp")
        )


# === XRAY CONFIG ===
class XrayConfigBuilder:
    @classmethod
    def build(cls, server: ServerInfo, port: int) -> Optional[Dict]:
        outbound = cls._outbound(server)
        if not outbound:
            return None
        
        return {
            "log": {"loglevel": "none"},
            "policy": {
                "levels": {
                    "0": {
                        "connIdle": CONFIG.XRAY_CONN_IDLE
                    }
                }
            },
            "inbounds": [{
                "port": port,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"udp": True}
            }],
            "outbounds": [outbound]
        }
    
    @classmethod
    def _outbound(cls, s: ServerInfo) -> Optional[Dict]:
        if s.protocol == "vless":
            user: Dict[str, Any] = {"id": s.uuid, "encryption": "none"}
            if s.flow:
                user["flow"] = s.flow
            return {
                "protocol": "vless",
                "settings": {
                    "vnext": [{
                        "address": s.host,
                        "port": s.port,
                        "users": [user]
                    }]
                },
                "streamSettings": cls._stream(s)
            }
        
        elif s.protocol == "shadowsocks":
            return {
                "protocol": "shadowsocks",
                "settings": {
                    "servers": [{
                        "address": s.host,
                        "port": s.port,
                        "method": s.method,
                        "password": s.password
                    }]
                },
                "streamSettings": {"network": "tcp"}
            }
        
        elif s.protocol == "vmess":
            return {
                "protocol": "vmess",
                "settings": {
                    "vnext": [{
                        "address": s.host,
                        "port": s.port,
                        "users": [{
                            "id": s.uuid,
                            "alterId": 0,
                            "security": "auto"
                        }]
                    }]
                },
                "streamSettings": cls._stream(s)
            }
        
        elif s.protocol == "trojan":
            return {
                "protocol": "trojan",
                "settings": {
                    "servers": [{
                        "address": s.host,
                        "port": s.port,
                        "password": s.password
                    }]
                },
                "streamSettings": cls._stream(s)
            }
        
        return None
    
    @classmethod
    def _stream(cls, s: ServerInfo) -> Dict:
        ss: Dict[str, Any] = {
            "network": s.network_type,
            "security": s.security
        }
        
        if s.security == "reality":
            ss["realitySettings"] = {
                "serverName": s.sni or s.host,
                "publicKey": s.pbk,
                "shortId": s.sid,
                "fingerprint": s.fp or "chrome"
            }
        elif s.security == "tls":
            ss["tlsSettings"] = {
                "serverName": s.sni or s.host,
                "allowInsecure": True,
                "fingerprint": s.fp or "chrome"
            }
        
        if s.network_type == "ws":
            ss["wsSettings"] = {"path": s.path or "/"}
            if s.sni:
                ss["wsSettings"]["headers"] = {"Host": s.sni}
        elif s.network_type == "grpc":
            ss["grpcSettings"] = {"serviceName": s.service_name}
        
        return ss


# ============================================================
# ЭТАП 1: QUICK FILTER
# ============================================================

def quick_check_one(key: str, xray_exe: Path) -> QuickResult:
    """Быстрая проверка одного ключа: жив или нет"""
    
    server = KeyParser.parse(key)
    if not server:
        return QuickResult(key=key, alive=False)
    
    # SNI blacklist check
    if is_critical_bad_sni(server.sni):
        return QuickResult(key=key, alive=False)
    
    port = get_free_port()
    config = XrayConfigBuilder.build(server, port)
    if not config:
        return QuickResult(key=key, alive=False)
    
    with xray_session(xray_exe, config) as session:
        if not session:
            return QuickResult(key=key, alive=False)
        
        _, socks_port, _ = session
        proxies = {
            "http": f"socks5://127.0.0.1:{socks_port}",
            "https": f"socks5://127.0.0.1:{socks_port}"
        }
        
        http = create_session(proxies)
        try:
            url = random.choice(QUICK_CHECK_URLS)
            response, latency = smart_request(
                http, url,
                timeout=CONFIG.QUICK_TIMEOUT,
                retries=CONFIG.QUICK_RETRIES
            )
            
            if response and response.status_code in [200, 204]:
                return QuickResult(key=key, alive=True, latency=latency)
        finally:
            http.close()
    
    return QuickResult(key=key, alive=False)


def run_quick_filter(keys: List[str], xray_exe: Path, stats: Stats) -> List[str]:
    """ЭТАП 1: Быстрая фильтрация всех ключей"""
    
    # Предварительная фильтрация по SNI (мгновенная)
    pre_filtered_keys: List[str] = []
    for key in keys:
        server = KeyParser.parse(key)
        if server and is_critical_bad_sni(server.sni):
            stats.quick_bad_sni += 1
        else:
            pre_filtered_keys.append(key)
    
    if stats.quick_bad_sni > 0:
        logger.info(f"🚫 Отсеяно по SNI blacklist: {stats.quick_bad_sni}")
    
    logger.info(f"\n{'='*60}")
    logger.info(f"⚡ ЭТАП 1: БЫСТРЫЙ ФИЛЬТР")
    logger.info(f"{'='*60}")
    logger.info(f"📦 Ключей: {len(pre_filtered_keys)} | Параллельно: {CONFIG.QUICK_PARALLEL}")
    logger.info(f"⏱️  Таймаут: connect={CONFIG.QUICK_TIMEOUT[0]}s, read={CONFIG.QUICK_TIMEOUT[1]}s")
    
    start_time = time.time()
    alive_keys: List[str] = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.QUICK_PARALLEL) as executor:
        futures = {
            executor.submit(quick_check_one, key, xray_exe): key 
            for key in pre_filtered_keys
        }
        
        done = 0
        total = len(pre_filtered_keys)
        
        for future in concurrent.futures.as_completed(futures):
            done += 1
            
            try:
                result = future.result(timeout=30)
                
                if result.alive:
                    alive_keys.append(result.key)
                    stats.quick_alive += 1
                else:
                    stats.quick_dead += 1
                    
            except Exception:
                stats.quick_dead += 1
            
            # Очистка памяти + прогресс
            if done % CONFIG.GC_EVERY_N_KEYS == 0:
                cleanup_memory()
                elapsed = time.time() - start_time
                speed = done / elapsed if elapsed > 0 else 1
                eta = (total - done) / speed / 60 if speed > 0 else 0
                pct = stats.quick_alive * 100 // done if done > 0 else 0
                logger.info(
                    f"[{done}/{total}] "
                    f"✅ {stats.quick_alive} ({pct}%) | "
                    f"⏱️ {elapsed/60:.1f}м | ETA: {eta:.1f}м | 🧹 GC"
                )
            elif done % 100 == 0:
                elapsed = time.time() - start_time
                speed = done / elapsed if elapsed > 0 else 1
                eta = (total - done) / speed / 60 if speed > 0 else 0
                pct = stats.quick_alive * 100 // done if done > 0 else 0
                logger.info(
                    f"[{done}/{total}] "
                    f"✅ {stats.quick_alive} ({pct}%) | "
                    f"⏱️ {elapsed/60:.1f}м | ETA: {eta:.1f}м"
                )
    
    # Финальная очистка
    cleanup_memory()
    
    stats.quick_time = time.time() - start_time
    
    pct = stats.quick_alive * 100 // max(len(pre_filtered_keys), 1)
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ ЭТАП 1 ЗАВЕРШЁН за {stats.quick_time/60:.1f} мин")
    logger.info(f"📊 Живых: {stats.quick_alive} ({pct}%) | Мёртвых: {stats.quick_dead}")
    if stats.quick_bad_sni > 0:
        logger.info(f"🚫 Плохой SNI: {stats.quick_bad_sni}")
    logger.info(f"{'='*60}\n")
    
    return alive_keys


# ============================================================
# ЭТАП 2: FULL TEST
# ============================================================

def full_test_one(key: str, xray_exe: Path) -> Optional[FullResult]:
    """Полная проверка одного ключа: latency, categories, stability, IP"""
    
    server = KeyParser.parse(key)
    if not server:
        return None
    
    # Двойная проверка SNI (на случай если прошёл quick filter)
    if is_critical_bad_sni(server.sni):
        return None
    
    # === 1. LATENCY TEST ===
    latencies: List[float] = []
    port = get_free_port()
    config = XrayConfigBuilder.build(server, port)
    if not config:
        return None
    
    with xray_session(xray_exe, config) as session:
        if not session:
            return None
        
        _, socks_port, _ = session
        proxies = {
            "http": f"socks5://127.0.0.1:{socks_port}",
            "https": f"socks5://127.0.0.1:{socks_port}"
        }
        
        http = create_session(proxies)
        try:
            for _ in range(CONFIG.LATENCY_SAMPLES):
                url = random.choice(QUICK_CHECK_URLS)
                response, latency = smart_request(
                    http, url,
                    timeout=CONFIG.TIMEOUT_FAST,
                    retries=0
                )
                if response and response.status_code in [200, 204]:
                    latencies.append(latency)
        finally:
            http.close()
    
    if len(latencies) < CONFIG.MIN_LATENCY_SAMPLES:
        return None
    
    latency_avg = round(mean(latencies), 1)
    latency_jitter = round(stdev(latencies), 1) if len(latencies) > 1 else 0
    
    # === 2. CATEGORY TEST ===
    categories: Dict[str, int] = {}
    telegram_works = False
    
    port = get_free_port()
    config = XrayConfigBuilder.build(server, port)
    
    with xray_session(xray_exe, config) as session:
        if not session:
            return None
        
        _, socks_port, _ = session
        proxies = {
            "http": f"socks5://127.0.0.1:{socks_port}",
            "https": f"socks5://127.0.0.1:{socks_port}"
        }
        
        http = create_session(proxies)
        try:
            for category, sites in CHECK_SITES.items():
                passed = 0
                
                for url, name in sites[:CONFIG.CATEGORY_SAMPLES]:
                    # Rate limiting между запросами
                    rate_limit_delay()
                    
                    timeout = get_timeout_for_url(url)
                    optional = is_optional_site(url)
                    
                    response, _ = smart_request(
                        http, url,
                        timeout=timeout,
                        retries=CONFIG.MAX_RETRIES
                    )
                    
                    if response and response.status_code < 500:
                        passed += 1
                        if category == "telegram":
                            telegram_works = True
                    elif not optional:
                        # Обязательный сайт не ответил — ещё одна попытка
                        rate_limit_delay()
                        response, _ = smart_request(
                            http, url,
                            timeout=timeout,
                            retries=1
                        )
                        if response and response.status_code < 500:
                            passed += 1
                            if category == "telegram":
                                telegram_works = True
                
                categories[category] = passed
        finally:
            http.close()
    
    categories_passed = sum(1 for v in categories.values() if v > 0)
    
    # === 3. STABILITY TEST ===
    successes = 0
    
    for _ in range(CONFIG.STABILITY_CHECKS):
        port = get_free_port()
        config = XrayConfigBuilder.build(server, port)
        
        with xray_session(
            xray_exe, config, 
            startup_delay=CONFIG.XRAY_STARTUP_STABILITY
        ) as session:
            if not session:
                continue
            
            _, socks_port, _ = session
            proxies = {"http": f"socks5://127.0.0.1:{socks_port}"}
            
            http = create_session(proxies)
            try:
                response, _ = smart_request(
                    http,
                    QUICK_CHECK_URLS[0],
                    timeout=(2, 3),
                    retries=0
                )
                if response and response.status_code in [200, 204]:
                    successes += 1
            finally:
                http.close()
    
    stability = round(successes / CONFIG.STABILITY_CHECKS * 100, 1)
    
    if stability < CONFIG.MIN_STABILITY_PERCENT:
        return None
    
    # === 4. IP CHECK (только для ELITE кандидатов) ===
    proxy_ip: Optional[str] = None
    is_elite_candidate = (
        latency_avg < CONFIG.ELITE_LATENCY_THRESHOLD and 
        stability > CONFIG.ELITE_STABILITY_THRESHOLD
    )
    
    if is_elite_candidate:
        port = get_free_port()
        config = XrayConfigBuilder.build(server, port)
        
        with xray_session(xray_exe, config) as session:
            if session:
                _, socks_port, _ = session
                proxies = {
                    "http": f"socks5://127.0.0.1:{socks_port}",
                    "https": f"socks5://127.0.0.1:{socks_port}"
                }
                
                http = create_session(proxies)
                try:
                    proxy_ip = check_proxy_ip(http)
                finally:
                    http.close()
    
    # === 5. ОПРЕДЕЛЕНИЕ ПРОФИЛЯ ===
    profile = QualityProfile.GOOD
    score = 50
    
    for p, t in sorted(QUALITY_PROFILES.items(), key=lambda x: x[1].priority):
        if (latency_avg <= t.latency_max and
            latency_jitter <= t.jitter_max and
            stability >= t.stability_min and
            categories_passed >= t.categories_min):
            
            profile = p
            score = 100 - int(latency_avg / 10) + int(stability) + categories_passed * 5
            break
    
    # Бонус за Telegram
    if telegram_works:
        score += CONFIG.TELEGRAM_BONUS
    
    return FullResult(
        key=key,
        latency_avg=latency_avg,
        latency_jitter=latency_jitter,
        stability_rate=stability,
        categories_passed=categories_passed,
        category_details=categories,
        profile=profile,
        score=max(0, min(score, 200)),
        proxy_ip=proxy_ip,
        telegram_works=telegram_works
    )


def run_full_test(keys: List[str], xray_exe: Path, stats: Stats) -> List[FullResult]:
    """ЭТАП 2: Полная проверка живых ключей"""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🔬 ЭТАП 2: ПОЛНАЯ ПРОВЕРКА")
    logger.info(f"{'='*60}")
    logger.info(f"📦 Ключей: {len(keys)} | Параллельно: {CONFIG.FULL_PARALLEL}")
    logger.info(f"⏱️  Таймауты: fast={CONFIG.TIMEOUT_FAST}, normal={CONFIG.TIMEOUT_NORMAL}, slow={CONFIG.TIMEOUT_SLOW}")
    logger.info(f"📊 Мин. стабильность: {CONFIG.MIN_STABILITY_PERCENT}%")
    
    start_time = time.time()
    results: List[FullResult] = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.FULL_PARALLEL) as executor:
        futures = {
            executor.submit(full_test_one, key, xray_exe): key 
            for key in keys
        }
        
        done = 0
        total = len(keys)
        
        for future in concurrent.futures.as_completed(futures):
            done += 1
            
            try:
                result = future.result(timeout=180)
                
                if result:
                    results.append(result)
                    stats.full_passed += 1
                    stats.by_profile[result.profile] += 1
                    
                    if result.proxy_ip:
                        stats.elite_with_ip += 1
                    
                    label = QUALITY_PROFILES[result.profile].label
                    tg = " 📱" if result.telegram_works else ""
                    ip = f" 🌐{result.proxy_ip}" if result.proxy_ip else ""
                    
                    logger.info(
                        f"[{done}/{total}] ✓ {label} | "
                        f"{result.latency_avg:.0f}ms j:{result.latency_jitter:.0f} | "
                        f"stab:{result.stability_rate:.0f}% | "
                        f"cat:{result.categories_passed}/9{tg}{ip}"
                    )
                else:
                    stats.full_failed += 1
                    
            except concurrent.futures.TimeoutError:
                stats.full_failed += 1
                logger.debug("Key validation timeout (180s)")
            except Exception as e:
                stats.full_failed += 1
                logger.debug(f"Error: {e}")
            
            # Очистка памяти + прогресс
            if done % CONFIG.GC_EVERY_N_KEYS == 0:
                cleanup_memory()
                elapsed = time.time() - start_time
                logger.info(f"[{done}/{total}] 🧹 GC | ⏱️ {elapsed/60:.1f}м | ✓ {stats.full_passed}")
            elif done % 50 == 0:
                elapsed = time.time() - start_time
                speed = done / elapsed if elapsed > 0 else 1
                eta = (total - done) / speed / 60 if speed > 0 else 0
                logger.info(
                    f"[{done}/{total}] ⏱️ {elapsed/60:.1f}м | "
                    f"ETA: {eta:.1f}м | ✓ {stats.full_passed}"
                )
    
    # Финальная очистка
    cleanup_memory()
    
    stats.full_time = time.time() - start_time
    
    logger.info(f"\n{'='*60}")
    logger.info(f"✅ ЭТАП 2 ЗАВЕРШЁН за {stats.full_time/60:.1f} мин")
    logger.info(f"📊 Прошло: {stats.full_passed} | Отсеяно: {stats.full_failed}")
    if stats.elite_with_ip > 0:
        logger.info(f"🌐 ELITE с IP: {stats.elite_with_ip}")
    logger.info(f"{'='*60}\n")
    
    return results


# ============================================================
# СОХРАНЕНИЕ
# ============================================================

def save_results(results: List[FullResult], output_dir: Path, stats: Stats):
    """Сохранение результатов по профилям"""
    
    by_profile: Dict[QualityProfile, List[FullResult]] = defaultdict(list)
    for r in results:
        by_profile[r.profile].append(r)
    
    for profile in QualityProfile:
        items = by_profile.get(profile, [])
        if not items:
            continue
        
        items.sort(key=lambda x: x.score, reverse=True)
        
        filename = output_dir / f"{profile.value}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {QUALITY_PROFILES[profile].label}\n")
            f.write(f"# @vlesstrojan\n")
            f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# Ключей: {len(items)}\n\n")
            
            for r in items:
                label = QUALITY_PROFILES[r.profile].label
                tg = "TG+" if r.telegram_works else ""
                comment = (
                    f"[{r.latency_avg:.0f}ms|{label}|"
                    f"stab{r.stability_rate:.0f}%|"
                    f"{r.categories_passed}cat|{tg}@vlesstrojan]"
                )
                base_key = r.key.split('#')[0]
                f.write(f"{base_key}#{quote(comment)}\n")
        
        logger.info(f"💾 {QUALITY_PROFILES[profile].label}: {len(items)} → {filename.name}")
    
    # Статистика
    save_statistics(output_dir, stats, results)


def save_statistics(output_dir: Path, stats: Stats, results: List[FullResult]):
    """Сохранение итоговой статистики в файл"""
    
    stats_file = output_dir / "statistics.txt"
    total_time = time.time() - stats.start_time
    
    telegram_count = sum(1 for r in results if r.telegram_works)
    with_ip_count = sum(1 for r in results if r.proxy_ip)
    
    if results:
        avg_latency = mean([r.latency_avg for r in results])
        avg_stability = mean([r.stability_rate for r in results])
        avg_categories = mean([r.categories_passed for r in results])
    else:
        avg_latency = 0
        avg_stability = 0
        avg_categories = 0
    
    with open(stats_file, 'w', encoding='utf-8') as f:
        f.write(f"# VPN Validator v5.3 - Statistics\n")
        f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*50}\n\n")
        
        f.write(f"⏱️  ВРЕМЯ\n")
        f.write(f"   Общее: {total_time/60:.1f} мин\n")
        f.write(f"   Этап 1 (фильтр): {stats.quick_time/60:.1f} мин\n")
        f.write(f"   Этап 2 (полный): {stats.full_time/60:.1f} мин\n\n")
        
        f.write(f"📦 СТАТИСТИКА КЛЮЧЕЙ\n")
        f.write(f"   Всего: {stats.total}\n")
        f.write(f"   Отсеяно SNI: {stats.quick_bad_sni}\n")
        f.write(f"   Quick Filter живых: {stats.quick_alive} ({stats.quick_alive*100//max(stats.total,1)}%)\n")
        f.write(f"   Quick Filter мёртвых: {stats.quick_dead}\n")
        f.write(f"   Full Test прошло: {stats.full_passed}\n")
        f.write(f"   Full Test отсеяно: {stats.full_failed}\n\n")
        
        f.write(f"🏆 ПО ПРОФИЛЯМ\n")
        for profile in QualityProfile:
            count = stats.by_profile.get(profile, 0)
            f.write(f"   {QUALITY_PROFILES[profile].label}: {count}\n")
        f.write(f"\n")
        
        f.write(f"📊 СРЕДНИЕ ПОКАЗАТЕЛИ\n")
        f.write(f"   Latency: {avg_latency:.1f} ms\n")
        f.write(f"   Stability: {avg_stability:.1f}%\n")
        f.write(f"   Categories: {avg_categories:.1f}/9\n")
        f.write(f"   С Telegram: {telegram_count}\n")
        f.write(f"   С IP-check: {with_ip_count}\n\n")
        
        f.write(f"⚙️  КОНФИГУРАЦИЯ\n")
        f.write(f"   Quick Parallel: {CONFIG.QUICK_PARALLEL}\n")
        f.write(f"   Full Parallel: {CONFIG.FULL_PARALLEL}\n")
        f.write(f"   Timeout Fast: {CONFIG.TIMEOUT_FAST}\n")
        f.write(f"   Timeout Normal: {CONFIG.TIMEOUT_NORMAL}\n")
        f.write(f"   Timeout Slow: {CONFIG.TIMEOUT_SLOW}\n")
        f.write(f"   Min Stability: {CONFIG.MIN_STABILITY_PERCENT}%\n")
        f.write(f"   Latency Samples: {CONFIG.LATENCY_SAMPLES}\n")
        f.write(f"   Stability Checks: {CONFIG.STABILITY_CHECKS}\n")
        f.write(f"   Categories: {len(CHECK_SITES)}\n")
        f.write(f"   SNI Blacklist: {len(CRITICAL_BAD_SNI)} entries\n")
    
    logger.info(f"📊 Статистика → {stats_file.name}")


# ============================================================
# MAIN
# ============================================================

def find_source_file() -> Optional[Path]:
    """Поиск файла с ключами"""
    if not RESULTS_FOLDER.exists():
        return None
    
    # Сначала verified
    files = list(RESULTS_FOLDER.glob("verified_*.txt"))
    if files:
        return max(files, key=lambda f: f.stat().st_mtime)
    
    # Потом любой .txt
    files = list(RESULTS_FOLDER.glob("*.txt"))
    if files:
        return max(files, key=lambda f: f.stat().st_mtime)
    
    return None


def load_keys(filepath: Path) -> List[str]:
    """Загрузка ключей из файла"""
    keys: List[str] = []
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key = line.split('#')[0].strip()
                if key:
                    keys.append(key)
    return keys


def print_banner():
    print("\n" + "=" * 60)
    print(" " * 10 + "📱 VPN VALIDATOR v5.3 FINAL")
    print(" " * 5 + "Adaptive Timeouts | SNI Filter | Rate Limiting")
    print("=" * 60)


def print_config():
    total_sites = sum(len(sites) for sites in CHECK_SITES.values())
    
    print(f"\n⚙️  Конфигурация:")
    print(f"   Quick Filter: {CONFIG.QUICK_PARALLEL} parallel, timeout={CONFIG.QUICK_TIMEOUT}")
    print(f"   Full Test: {CONFIG.FULL_PARALLEL} parallel")
    print(f"   Таймауты: fast={CONFIG.TIMEOUT_FAST}, normal={CONFIG.TIMEOUT_NORMAL}, slow={CONFIG.TIMEOUT_SLOW}")
    print(f"   Min Stability: {CONFIG.MIN_STABILITY_PERCENT}%")
    print(f"   Rate Limit: {CONFIG.RATE_LIMIT_MIN}-{CONFIG.RATE_LIMIT_MAX}s")
    print(f"   GC каждые: {CONFIG.GC_EVERY_N_KEYS} ключей")
    print(f"   Категорий: {len(CHECK_SITES)} ({total_sites} сайтов)")
    print(f"   SNI Blacklist: {len(CRITICAL_BAD_SNI)} записей")
    print(f"   ELITE IP-check: lat<{CONFIG.ELITE_LATENCY_THRESHOLD}ms, stab>{CONFIG.ELITE_STABILITY_THRESHOLD}%")


def print_summary(stats: Stats):
    total_time = time.time() - stats.start_time
    
    print("\n" + "=" * 60)
    print("📊 ИТОГИ")
    print("=" * 60)
    print(f"⏱️  Общее время: {total_time/60:.1f} мин")
    print(f"   ├─ Этап 1 (фильтр): {stats.quick_time/60:.1f} мин")
    print(f"   └─ Этап 2 (полный): {stats.full_time/60:.1f} мин")
    print()
    print(f"📦 Статистика:")
    print(f"   ├─ Всего ключей: {stats.total}")
    if stats.quick_bad_sni > 0:
        print(f"   ├─ Отсеяно SNI: {stats.quick_bad_sni}")
    print(f"   ├─ После фильтра: {stats.quick_alive} ({stats.quick_alive*100//max(stats.total,1)}%)")
    print(f"   └─ Прошло тест: {stats.full_passed}")
    print()
    
    if stats.full_passed > 0:
        print("🏆 По профилям:")
        for profile in QualityProfile:
            count = stats.by_profile.get(profile, 0)
            if count > 0:
                print(f"   {QUALITY_PROFILES[profile].label}: {count}")
        
        if stats.elite_with_ip > 0:
            print(f"\n🌐 ELITE с IP-check: {stats.elite_with_ip}")
    else:
        print("⚠️  Ни один ключ не прошёл полную проверку")
    
    print("=" * 60)


def main() -> int:
    print_banner()
    print_config()
    
    # Xray
    xray_exe = XrayInstaller.setup()
    if not xray_exe:
        logger.error("❌ Не удалось установить Xray")
        return 1
    
    # Файл с ключами
    source = find_source_file()
    if not source:
        logger.error("❌ Не найден файл с ключами в папке results/")
        return 1
    
    logger.info(f"\n📁 Источник: {source.name}")
    
    keys = load_keys(source)
    if not keys:
        logger.error("❌ Нет ключей")
        return 1
    
    stats = Stats(total=len(keys))
    
    # Оценка времени
    est_quick = len(keys) * 5 / CONFIG.QUICK_PARALLEL / 60
    alive_estimate = int(len(keys) * 0.25)
    est_full = alive_estimate * 40 / CONFIG.FULL_PARALLEL / 60
    
    logger.info(f"📦 Ключей: {len(keys)}")
    logger.info(f"⏱️  Оценка: ~{est_quick:.0f} + ~{est_full:.0f} = ~{est_quick + est_full:.0f} мин")
    
    # ЭТАП 1: Быстрый фильтр
    alive_keys = run_quick_filter(keys, xray_exe, stats)
    
    if not alive_keys:
        logger.warning("⚠️ Не найдено живых ключей!")
        print_summary(stats)
        return 0
    
    # ЭТАП 2: Полная проверка
    results = run_full_test(alive_keys, xray_exe, stats)
    
    # Сохранение
    if results:
        logger.info("\n💾 Сохранение результатов...")
        save_results(results, OUTPUT_DIR, stats)
    else:
        logger.warning("⚠️ Нет результатов для сохранения")
    
    print_summary(stats)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
