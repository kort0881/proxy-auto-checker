"""
📱 REAL MOBILE VPN VALIDATOR v4.2 (XRAY-POWERED)
Полная проверка VPN с реальными HTTP запросами через Xray

Изменения v4.2:
- Повышенные пороги стабильности
- Параллельная проверка категорий
- Retry логика для запросов
- Экспоненциальный backoff
- Улучшенная обработка ошибок
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
import hashlib
import logging
import contextlib
import tempfile
import functools
from datetime import datetime
from urllib.parse import unquote, quote
from pathlib import Path
import concurrent.futures
from collections import defaultdict
from statistics import mean, stdev
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Any, Generator, Callable, TypeVar
from abc import ABC, abstractmethod
from enum import Enum

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3
urllib3.disable_warnings()

# === НАСТРОЙКА ЛОГИРОВАНИЯ ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)


# === КОНФИГУРАЦИЯ ===
@dataclass(frozen=True)
class TestConfig:
    """Конфигурация тестирования"""
    # Параллелизм
    MAX_PARALLEL: int = 15
    CATEGORY_PARALLEL: int = 5  # Параллельные запросы внутри категории
    
    # Количество проверок
    LATENCY_SAMPLES: int = 15
    STABILITY_CHECKS: int = 15
    CATEGORY_SAMPLES: int = 3
    
    # Таймауты
    TIMEOUT: float = 5.0
    XRAY_STARTUP: float = 0.8
    PROCESS_TERMINATE_TIMEOUT: float = 2.0
    
    # Пороги
    MIN_LATENCY_SAMPLES: int = 5
    MIN_STABILITY_PERCENT: float = 70.0  # Повышено с 50%
    
    # Retry настройки
    MAX_RETRIES: int = 2
    RETRY_BACKOFF: float = 0.5  # Начальная задержка
    RETRY_BACKOFF_MAX: float = 2.0  # Максимальная задержка


# Глобальный конфиг
CONFIG = TestConfig()


# === ДИРЕКТОРИИ ===
WORK_DIR = Path(__file__).parent.absolute()
RESULTS_FOLDER = WORK_DIR / "results"
XRAY_FOLDER = WORK_DIR / "xray"
OUTPUT_DIR = RESULTS_FOLDER / "premium"

for dir_path in [RESULTS_FOLDER, XRAY_FOLDER, OUTPUT_DIR]:
    dir_path.mkdir(parents=True, exist_ok=True)


# === САЙТЫ ДЛЯ ПРОВЕРКИ ===
CHECK_SITES: Dict[str, List[Tuple[str, str]]] = {
    "banks": [
        ("https://www.sberbank.ru", "Сбербанк"),
        ("https://www.tbank.ru", "Т-Банк"),
        ("https://www.vtb.ru", "ВТБ"),
        ("https://alfabank.ru", "Альфа-Банк"),
        ("https://www.gazprombank.ru", "Газпромбанк")
    ],
    "gov": [
        ("https://www.gosuslugi.ru", "Госуслуги"),
        ("https://www.nalog.gov.ru", "Налоговая"),
        ("https://esia.gosuslugi.ru", "ЕСИА")
    ],
    "social": [
        ("https://vk.com", "VK"),
        ("https://ok.ru", "OK"),
        ("https://www.instagram.com", "Instagram"),
        ("https://x.com", "Twitter/X"),
        ("https://www.facebook.com", "Facebook"),
        ("https://www.linkedin.com", "LinkedIn")
    ],
    "messengers": [
        ("https://web.telegram.org", "Telegram Web"),
        ("https://web.whatsapp.com", "WhatsApp Web"),
        ("https://www.viber.com", "Viber")
    ],
    "video": [
        ("https://www.youtube.com", "YouTube"),
        ("https://rutube.ru", "Rutube"),
        ("https://www.kinopoisk.ru", "Кинопоиск"),
        ("https://www.ivi.ru", "Ivi")
    ],
    "news": [
        ("https://news.yandex.ru", "Яндекс.Новости"),
        ("https://www.rbc.ru", "РБК"),
        ("https://tass.ru", "ТАСС"),
        ("https://ria.ru", "РИА")
    ],
    "services": [
        ("https://www.google.com", "Google"),
        ("https://yandex.ru", "Яндекс"),
        ("https://mail.ru", "Mail.ru"),
        ("https://www.ozon.ru", "Ozon"),
        ("https://www.wildberries.ru", "Wildberries"),
        ("https://www.avito.ru", "Avito")
    ],
    "telecom": [
        ("https://www.mts.ru", "МТС"),
        ("https://moskva.beeline.ru", "Билайн"),
        ("https://www.megafon.ru", "Мегафон"),
        ("https://msk.tele2.ru", "Tele2")
    ]
}

QUICK_CHECK_SITES: List[str] = [
    "http://www.gstatic.com/generate_204",
    "http://cp.cloudflare.com/generate_204",
    "http://connectivitycheck.android.com/generate_204"
]

MOBILE_USER_AGENTS: List[str] = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "V2RayNG/1.8.19 (Android 14)",
    "Hiddify/2.5.7 (iOS 17.4)"
]


# === ПРОФИЛИ КАЧЕСТВА (УЖЕСТОЧЁННЫЕ) ===
class QualityProfile(Enum):
    ELITE = "elite"
    PREMIUM = "premium"
    GOOD = "good"


@dataclass(frozen=True)
class ProfileThresholds:
    """Пороговые значения для профиля качества"""
    label: str
    latency_max: float
    jitter_max: float
    stability_min: float  # Теперь выше!
    categories_min: int
    priority: int


QUALITY_PROFILES: Dict[QualityProfile, ProfileThresholds] = {
    QualityProfile.ELITE: ProfileThresholds(
        label="ELITE",
        latency_max=80,
        jitter_max=20,
        stability_min=98,  # Очень высокий
        categories_min=7,
        priority=1
    ),
    QualityProfile.PREMIUM: ProfileThresholds(
        label="PREM",
        latency_max=150,
        jitter_max=35,
        stability_min=95,  # Повышено
        categories_min=6,
        priority=2
    ),
    QualityProfile.GOOD: ProfileThresholds(
        label="GOOD",
        latency_max=250,
        jitter_max=60,
        stability_min=85,  # Повышено с 90 → 85 для баланса
        categories_min=5,
        priority=3
    )
}


# === СТРУКТУРЫ ДАННЫХ ===
@dataclass
class ServerInfo:
    """Информация о VPN сервере"""
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
class TestResult:
    """Результат тестирования ключа"""
    key: str
    latency_avg: float
    latency_jitter: float
    stability_rate: float
    categories_passed: int
    category_details: Dict[str, int]
    profile: QualityProfile
    score: int
    retries_used: int = 0  # Сколько retry понадобилось


@dataclass
class XraySession:
    """Сессия Xray с открытым SOCKS5 прокси"""
    process: subprocess.Popen
    socks_port: int
    config_file: Path
    _http_session: Optional[requests.Session] = field(default=None, repr=False)
    
    @property
    def proxies(self) -> Dict[str, str]:
        return {
            "http": f"socks5://127.0.0.1:{self.socks_port}",
            "https": f"socks5://127.0.0.1:{self.socks_port}"
        }
    
    def is_alive(self) -> bool:
        return self.process.poll() is None
    
    def get_http_session(self) -> requests.Session:
        """Получить HTTP сессию с настроенными retry"""
        if self._http_session is None:
            self._http_session = create_retry_session(self.proxies)
        return self._http_session
    
    def close_http_session(self) -> None:
        """Закрыть HTTP сессию"""
        if self._http_session is not None:
            self._http_session.close()
            self._http_session = None


@dataclass
class ValidationStats:
    """Статистика валидации"""
    total: int = 0
    passed: int = 0
    failed: int = 0
    total_retries: int = 0
    by_profile: Dict[QualityProfile, int] = field(default_factory=lambda: defaultdict(int))


# === RETRY ЛОГИКА ===
T = TypeVar('T')


def create_retry_session(
    proxies: Dict[str, str],
    retries: int = CONFIG.MAX_RETRIES,
    backoff_factor: float = CONFIG.RETRY_BACKOFF
) -> requests.Session:
    """Создание сессии requests с настроенными retry"""
    session = requests.Session()
    
    # Настраиваем retry стратегию
    retry_strategy = Retry(
        total=retries,
        backoff_factor=backoff_factor,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],
        raise_on_status=False
    )
    
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    
    # Устанавливаем прокси
    session.proxies.update(proxies)
    
    return session


def retry_with_backoff(
    func: Callable[..., Optional[T]],
    max_retries: int = CONFIG.MAX_RETRIES,
    backoff: float = CONFIG.RETRY_BACKOFF,
    backoff_max: float = CONFIG.RETRY_BACKOFF_MAX,
    exceptions: Tuple = (requests.RequestException, socket.error)
) -> Callable[..., Tuple[Optional[T], int]]:
    """
    Декоратор для retry с экспоненциальным backoff.
    Возвращает (результат, количество_retry).
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs) -> Tuple[Optional[T], int]:
        retries = 0
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                result = func(*args, **kwargs)
                if result is not None:
                    return result, retries
                
                # None результат - пробуем ещё
                retries += 1
                
            except exceptions as e:
                last_exception = e
                retries += 1
                
                if attempt < max_retries:
                    # Экспоненциальный backoff с jitter
                    delay = min(backoff * (2 ** attempt), backoff_max)
                    delay *= (0.5 + random.random())  # Jitter
                    time.sleep(delay)
        
        if last_exception:
            logger.debug(f"All retries failed: {last_exception}")
        
        return None, retries
    
    return wrapper


class RetryableRequest:
    """Класс для выполнения HTTP запросов с retry"""
    
    def __init__(
        self,
        session: requests.Session,
        max_retries: int = CONFIG.MAX_RETRIES,
        backoff: float = CONFIG.RETRY_BACKOFF
    ):
        self.session = session
        self.max_retries = max_retries
        self.backoff = backoff
        self.total_retries = 0
    
    def get(
        self,
        url: str,
        timeout: float = CONFIG.TIMEOUT,
        **kwargs
    ) -> Tuple[Optional[requests.Response], int]:
        """GET запрос с retry. Возвращает (response, retries_used)"""
        retries = 0
        
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, timeout=timeout, **kwargs)
                return response, retries
                
            except (requests.RequestException, socket.error) as e:
                retries += 1
                self.total_retries += 1
                
                if attempt < self.max_retries:
                    delay = min(
                        self.backoff * (2 ** attempt),
                        CONFIG.RETRY_BACKOFF_MAX
                    )
                    delay *= (0.5 + random.random())
                    logger.debug(f"Retry {attempt + 1}/{self.max_retries} after {delay:.2f}s: {e}")
                    time.sleep(delay)
        
        return None, retries


# === УТИЛИТЫ ===
def get_free_port() -> int:
    """Получение гарантированно свободного порта"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def get_random_user_agent() -> str:
    return random.choice(MOBILE_USER_AGENTS)


def safe_remove(path: Path) -> None:
    with contextlib.suppress(OSError, FileNotFoundError):
        path.unlink()


# === УПРАВЛЕНИЕ XRAY ПРОЦЕССОМ ===
@contextlib.contextmanager
def xray_session(
    xray_exe: Path, 
    config: Dict[str, Any],
    startup_delay: float = CONFIG.XRAY_STARTUP
) -> Generator[Optional[XraySession], None, None]:
    """Context manager для безопасного управления Xray процессом"""
    process: Optional[subprocess.Popen] = None
    config_file: Optional[Path] = None
    session: Optional[XraySession] = None
    
    try:
        fd, config_path = tempfile.mkstemp(suffix='.json', prefix='xray_', dir=XRAY_FOLDER)
        config_file = Path(config_path)
        
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(config, f)
        
        process = subprocess.Popen(
            [str(xray_exe), "run", "-c", str(config_file)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE
        )
        
        time.sleep(startup_delay)
        
        if process.poll() is not None:
            stderr = process.stderr.read().decode('utf-8', errors='ignore') if process.stderr else ""
            logger.debug(f"Xray failed to start: {stderr[:200]}")
            yield None
            return
        
        socks_port = config["inbounds"][0]["port"]
        
        session = XraySession(
            process=process,
            socks_port=socks_port,
            config_file=config_file
        )
        
        yield session
        
    except Exception as e:
        logger.debug(f"Xray session error: {e}")
        yield None
        
    finally:
        # Закрываем HTTP сессию
        if session is not None:
            session.close_http_session()
        
        # Завершаем процесс
        if process is not None and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=CONFIG.PROCESS_TERMINATE_TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        
        if config_file is not None:
            safe_remove(config_file)


# === УСТАНОВКА XRAY ===
class XrayInstaller:
    """Установщик Xray-core"""
    
    @staticmethod
    def get_platform_info() -> Tuple[str, str]:
        system = platform.system().lower()
        machine = platform.machine().lower()
        
        if system == "windows":
            arch = "64" if "64" in machine or "amd64" in machine else "32"
            return "windows", arch
        elif system == "linux":
            if "aarch64" in machine or "arm64" in machine:
                arch = "arm64-v8a"
            elif "64" in machine or "x86_64" in machine:
                arch = "64"
            else:
                arch = "32"
            return "linux", arch
        elif system == "darwin":
            arch = "arm64-v8a" if "arm" in machine else "64"
            return "macos", arch
        
        raise RuntimeError(f"Unsupported platform: {system} {machine}")
    
    @staticmethod
    def get_exe_name() -> str:
        return "xray.exe" if os.name == 'nt' else "xray"
    
    @classmethod
    def setup(cls) -> Optional[Path]:
        exe_path = XRAY_FOLDER / cls.get_exe_name()
        
        if exe_path.exists():
            logger.info(f"✅ Xray найден: {exe_path}")
            return exe_path
        
        logger.info("🔽 Скачиваем Xray-core...")
        
        try:
            system, arch = cls.get_platform_info()
            
            if system == "macos":
                filename = f"Xray-macos-{arch}.zip"
            else:
                filename = f"Xray-{system}-{arch}.zip"
            
            url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{filename}"
            
            zip_path = XRAY_FOLDER / "xray.zip"
            
            response = requests.get(url, stream=True, timeout=60)
            response.raise_for_status()
            
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            import zipfile
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(XRAY_FOLDER)
            
            zip_path.unlink()
            
            if os.name != 'nt':
                exe_path.chmod(0o755)
            
            logger.info(f"✅ Xray установлен: {exe_path}")
            return exe_path
            
        except Exception as e:
            logger.error(f"❌ Ошибка установки Xray: {e}")
            return None


# === ПАРСИНГ КЛЮЧЕЙ ===
class KeyParser:
    """Парсер VPN ключей"""
    
    @classmethod
    def parse(cls, key: str) -> Optional[ServerInfo]:
        key = key.strip()
        
        if '#' in key:
            key = key.split('#')[0].strip()
        
        if not key:
            return None
        
        parsers = {
            "vless://": cls._parse_vless,
            "ss://": cls._parse_shadowsocks,
            "vmess://": cls._parse_vmess,
            "trojan://": cls._parse_trojan,
        }
        
        for prefix, parser in parsers.items():
            if key.startswith(prefix):
                return parser(key)
        
        return None
    
    @classmethod
    def _parse_vless(cls, key: str) -> Optional[ServerInfo]:
        try:
            key_data = key[8:]
            
            if "@" not in key_data:
                return None
            
            uuid_part, rest = key_data.split("@", 1)
            server_part = rest.split("?")[0].split("#")[0]
            
            if "]:" in server_part:
                host, port = server_part.rsplit(":", 1)
                host = host.strip("[]")
            else:
                host, port = server_part.rsplit(":", 1)
            
            params: Dict[str, str] = {}
            if "?" in rest:
                params_str = rest.split("?")[1].split("#")[0]
                for p in params_str.split("&"):
                    if "=" in p:
                        k, v = p.split("=", 1)
                        params[k] = unquote(v)
            
            return ServerInfo(
                protocol="vless",
                host=host,
                port=int(port),
                uuid=uuid_part,
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
        except Exception as e:
            logger.debug(f"VLESS parse error: {e}")
            return None
    
    @classmethod
    def _parse_shadowsocks(cls, key: str) -> Optional[ServerInfo]:
        try:
            key_data = key[5:].split("#")[0]
            
            if "@" not in key_data:
                padding = len(key_data) % 4
                if padding:
                    key_data += '=' * (4 - padding)
                
                try:
                    decoded = base64.urlsafe_b64decode(key_data).decode('utf-8')
                    if "@" in decoded:
                        key_data = decoded
                    else:
                        return None
                except:
                    return None
            
            encoded, server = key_data.rsplit("@", 1)
            
            if "]:" in server:
                host, port = server.rsplit(":", 1)
                host = host.strip("[]")
            else:
                host, port = server.rsplit(":", 1)
            
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            
            try:
                decoded = base64.urlsafe_b64decode(encoded).decode('utf-8')
            except:
                decoded = base64.b64decode(encoded).decode('utf-8')
            
            method, password = decoded.split(":", 1)
            
            return ServerInfo(
                protocol="shadowsocks",
                host=host,
                port=int(port),
                method=method,
                password=password
            )
        except Exception as e:
            logger.debug(f"Shadowsocks parse error: {e}")
            return None
    
    @classmethod
    def _parse_vmess(cls, key: str) -> Optional[ServerInfo]:
        try:
            encoded = key[8:]
            
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            
            decoded = base64.urlsafe_b64decode(encoded).decode('utf-8')
            data = json.loads(decoded)
            
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
        except Exception as e:
            logger.debug(f"VMess parse error: {e}")
            return None
    
    @classmethod
    def _parse_trojan(cls, key: str) -> Optional[ServerInfo]:
        try:
            key_data = key[9:]
            
            if "@" not in key_data:
                return None
            
            password, rest = key_data.split("@", 1)
            server_part = rest.split("?")[0].split("#")[0]
            
            if "]:" in server_part:
                host, port = server_part.rsplit(":", 1)
                host = host.strip("[]")
            else:
                host, port = server_part.rsplit(":", 1)
            
            params: Dict[str, str] = {}
            if "?" in rest:
                params_str = rest.split("?")[1].split("#")[0]
                for p in params_str.split("&"):
                    if "=" in p:
                        k, v = p.split("=", 1)
                        params[k] = unquote(v)
            
            return ServerInfo(
                protocol="trojan",
                host=host,
                port=int(port),
                password=password,
                security=params.get("security", "tls"),
                sni=params.get("sni", host),
                network_type=params.get("type", "tcp")
            )
        except Exception as e:
            logger.debug(f"Trojan parse error: {e}")
            return None


# === СОЗДАНИЕ КОНФИГА XRAY ===
class XrayConfigBuilder:
    """Построитель конфигурации Xray"""
    
    @classmethod
    def build(cls, server: ServerInfo, socks_port: int) -> Optional[Dict[str, Any]]:
        outbound = cls._build_outbound(server)
        if not outbound:
            return None
        
        return {
            "log": {"loglevel": "none"},
            "inbounds": [{
                "port": socks_port,
                "listen": "127.0.0.1",
                "protocol": "socks",
                "settings": {"udp": True}
            }],
            "outbounds": [outbound]
        }
    
    @classmethod
    def _build_outbound(cls, server: ServerInfo) -> Optional[Dict[str, Any]]:
        builders = {
            "vless": cls._build_vless_outbound,
            "shadowsocks": cls._build_shadowsocks_outbound,
            "vmess": cls._build_vmess_outbound,
            "trojan": cls._build_trojan_outbound,
        }
        
        builder = builders.get(server.protocol)
        if builder:
            return builder(server)
        return None
    
    @classmethod
    def _build_vless_outbound(cls, server: ServerInfo) -> Dict[str, Any]:
        user: Dict[str, Any] = {"id": server.uuid, "encryption": "none"}
        if server.flow:
            user["flow"] = server.flow
        
        return {
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": server.host,
                    "port": server.port,
                    "users": [user]
                }]
            },
            "streamSettings": cls._build_stream_settings(server)
        }
    
    @classmethod
    def _build_shadowsocks_outbound(cls, server: ServerInfo) -> Dict[str, Any]:
        return {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [{
                    "address": server.host,
                    "port": server.port,
                    "method": server.method,
                    "password": server.password
                }]
            },
            "streamSettings": {"network": "tcp"}
        }
    
    @classmethod
    def _build_vmess_outbound(cls, server: ServerInfo) -> Dict[str, Any]:
        return {
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": server.host,
                    "port": server.port,
                    "users": [{
                        "id": server.uuid,
                        "alterId": 0,
                        "security": "auto"
                    }]
                }]
            },
            "streamSettings": cls._build_stream_settings(server)
        }
    
    @classmethod
    def _build_trojan_outbound(cls, server: ServerInfo) -> Dict[str, Any]:
        return {
            "protocol": "trojan",
            "settings": {
                "servers": [{
                    "address": server.host,
                    "port": server.port,
                    "password": server.password
                }]
            },
            "streamSettings": cls._build_stream_settings(server)
        }
    
    @classmethod
    def _build_stream_settings(cls, server: ServerInfo) -> Dict[str, Any]:
        settings: Dict[str, Any] = {
            "network": server.network_type,
            "security": server.security
        }
        
        if server.security == "reality":
            settings["realitySettings"] = {
                "serverName": server.sni or server.host,
                "publicKey": server.pbk,
                "shortId": server.sid,
                "fingerprint": server.fp or "chrome"
            }
        elif server.security == "tls":
            settings["tlsSettings"] = {
                "serverName": server.sni or server.host,
                "allowInsecure": True,
                "fingerprint": server.fp or "chrome"
            }
        
        if server.network_type == "ws":
            settings["wsSettings"] = {"path": server.path or "/"}
            if server.sni:
                settings["wsSettings"]["headers"] = {"Host": server.sni}
        elif server.network_type == "grpc":
            settings["grpcSettings"] = {"serviceName": server.service_name or ""}
        elif server.network_type == "tcp" and server.security != "reality":
            settings["tcpSettings"] = {"header": {"type": "none"}}
        
        return settings


# === ТЕСТЫ ===
class BaseTest(ABC):
    """Базовый класс для тестов"""
    
    def __init__(self, xray_exe: Path):
        self.xray_exe = xray_exe
        self.total_retries = 0
    
    @abstractmethod
    def run(self, session: XraySession) -> Any:
        pass
    
    def execute(self, key: str) -> Optional[Any]:
        server = KeyParser.parse(key)
        if not server:
            return None
        
        port = get_free_port()
        config = XrayConfigBuilder.build(server, port)
        if not config:
            return None
        
        with xray_session(self.xray_exe, config) as session:
            if session is None:
                return None
            return self.run(session)


class LatencyTest(BaseTest):
    """Тест задержки и джиттера с retry"""
    
    def run(self, session: XraySession) -> Optional[Tuple[float, float, int]]:
        """Возвращает (avg, jitter, retries_used)"""
        latencies: List[float] = []
        total_retries = 0
        
        http_session = session.get_http_session()
        requester = RetryableRequest(http_session)
        
        for _ in range(CONFIG.LATENCY_SAMPLES):
            latency, retries = self._measure_request_with_retry(requester)
            total_retries += retries
            
            if latency is not None:
                latencies.append(latency)
        
        self.total_retries = total_retries
        
        if len(latencies) < CONFIG.MIN_LATENCY_SAMPLES:
            return None
        
        avg = round(mean(latencies), 1)
        jitter = round(stdev(latencies), 1) if len(latencies) > 1 else 0.0
        
        return (avg, jitter, total_retries)
    
    def _measure_request_with_retry(
        self, 
        requester: RetryableRequest
    ) -> Tuple[Optional[float], int]:
        """Измерение с retry"""
        url = random.choice(QUICK_CHECK_SITES)
        headers = {"User-Agent": get_random_user_agent()}
        
        start = time.time()
        response, retries = requester.get(
            url,
            headers=headers,
            allow_redirects=False
        )
        
        if response is not None and response.status_code in [200, 204]:
            latency = (time.time() - start) * 1000
            # Корректируем на retry delays
            if retries > 0:
                latency = latency / (retries + 1)  # Примерная корректировка
            return latency, retries
        
        return None, retries


class CategoryTest(BaseTest):
    """Тест доступности категорий сайтов (ПАРАЛЛЕЛЬНЫЙ)"""
    
    def run(self, session: XraySession) -> Tuple[Dict[str, int], int]:
        """Возвращает (results, retries_used)"""
        results: Dict[str, int] = {}
        total_retries = 0
        
        http_session = session.get_http_session()
        
        for category, sites in CHECK_SITES.items():
            passed, retries = self._check_category_parallel(
                http_session, 
                sites[:CONFIG.CATEGORY_SAMPLES]
            )
            results[category] = passed
            total_retries += retries
        
        self.total_retries = total_retries
        return (results, total_retries)
    
    def _check_category_parallel(
        self,
        http_session: requests.Session,
        sites: List[Tuple[str, str]]
    ) -> Tuple[int, int]:
        """Параллельная проверка сайтов в категории"""
        passed = 0
        total_retries = 0
        
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=CONFIG.CATEGORY_PARALLEL
        ) as executor:
            futures = {
                executor.submit(
                    self._check_site_with_retry, 
                    http_session, 
                    url
                ): name
                for url, name in sites
            }
            
            for future in concurrent.futures.as_completed(futures):
                try:
                    success, retries = future.result()
                    total_retries += retries
                    if success:
                        passed += 1
                except Exception as e:
                    logger.debug(f"Category check error: {e}")
        
        return passed, total_retries
    
    def _check_site_with_retry(
        self,
        http_session: requests.Session,
        url: str
    ) -> Tuple[bool, int]:
        """Проверка сайта с retry"""
        requester = RetryableRequest(http_session)
        headers = {"User-Agent": get_random_user_agent()}
        
        response, retries = requester.get(
            url,
            headers=headers,
            allow_redirects=True
        )
        
        success = response is not None and response.status_code < 500
        return success, retries


class StabilityTest:
    """Тест стабильности (множество подключений)"""
    
    def __init__(self, xray_exe: Path):
        self.xray_exe = xray_exe
        self.total_retries = 0
    
    def execute(self, key: str) -> Optional[Tuple[float, int]]:
        """Возвращает (stability_percent, retries_used)"""
        server = KeyParser.parse(key)
        if not server:
            return None
        
        successes = 0
        total_retries = 0
        
        for i in range(CONFIG.STABILITY_CHECKS):
            success, retries = self._single_check_with_retry(server)
            total_retries += retries
            if success:
                successes += 1
        
        self.total_retries = total_retries
        
        if successes == 0:
            return None
        
        return (round(successes / CONFIG.STABILITY_CHECKS * 100, 1), total_retries)
    
    def _single_check_with_retry(self, server: ServerInfo) -> Tuple[bool, int]:
        """Одна проверка с retry"""
        port = get_free_port()
        config = XrayConfigBuilder.build(server, port)
        if not config:
            return False, 0
        
        with xray_session(self.xray_exe, config, startup_delay=0.5) as session:
            if session is None:
                return False, 0
            
            requester = RetryableRequest(
                session.get_http_session(),
                max_retries=1  # Для stability теста меньше retry
            )
            
            response, retries = requester.get(
                "http://www.gstatic.com/generate_204",
                timeout=3,
                allow_redirects=False
            )
            
            success = response is not None and response.status_code in [200, 204]
            return success, retries


# === ВАЛИДАТОР ===
class VPNValidator:
    """Главный валидатор VPN ключей"""
    
    def __init__(self, xray_exe: Path):
        self.xray_exe = xray_exe
        self.latency_test = LatencyTest(xray_exe)
        self.category_test = CategoryTest(xray_exe)
        self.stability_test = StabilityTest(xray_exe)
    
    def validate(self, key: str) -> Optional[TestResult]:
        """Полная валидация одного ключа"""
        total_retries = 0
        
        try:
            # 1. Latency & Jitter
            latency_result = self.latency_test.execute(key)
            if not latency_result:
                return None
            
            latency_avg, jitter, retries = latency_result
            total_retries += retries
            
            # 2. Категории (параллельно!)
            category_result = self.category_test.execute(key)
            if not category_result:
                return None
            
            categories, retries = category_result
            total_retries += retries
            categories_passed = sum(1 for count in categories.values() if count > 0)
            
            # 3. Stability
            stability_result = self.stability_test.execute(key)
            if not stability_result:
                return None
            
            stability, retries = stability_result
            total_retries += retries
            
            if stability < CONFIG.MIN_STABILITY_PERCENT:
                return None
            
            # 4. Определение профиля
            profile, score = self._determine_profile(
                latency_avg, jitter, stability, categories_passed
            )
            
            return TestResult(
                key=key,
                latency_avg=latency_avg,
                latency_jitter=jitter,
                stability_rate=stability,
                categories_passed=categories_passed,
                category_details=categories,
                profile=profile,
                score=score,
                retries_used=total_retries
            )
            
        except Exception as e:
            logger.debug(f"Validation error: {e}")
            return None
    
    def _determine_profile(
        self,
        latency: float,
        jitter: float,
        stability: float,
        categories: int
    ) -> Tuple[QualityProfile, int]:
        """Определение профиля качества"""
        sorted_profiles = sorted(
            QUALITY_PROFILES.items(),
            key=lambda x: x[1].priority
        )
        
        for profile, thresholds in sorted_profiles:
            if (latency <= thresholds.latency_max and
                jitter <= thresholds.jitter_max and
                stability >= thresholds.stability_min and
                categories >= thresholds.categories_min):
                
                score = (
                    100 
                    - int(latency / 10) 
                    + int(stability) 
                    + (categories * 5)
                )
                return profile, max(0, min(score, 200))
        
        return QualityProfile.GOOD, 50


# === ФОРМАТИРОВАНИЕ И СОХРАНЕНИЕ ===
class ResultFormatter:
    @staticmethod
    def format_key(result: TestResult) -> str:
        profile_label = QUALITY_PROFILES[result.profile].label
        
        parts = [
            f"{result.latency_avg:.0f}ms",
            profile_label,
            f"stab{result.stability_rate:.0f}%",
            f"{result.categories_passed}cat",
            "@vlesstrojan"
        ]
        
        comment = "[" + "|".join(parts) + "]"
        comment_encoded = quote(comment, safe='')
        
        base_key = result.key.split('#')[0]
        return f"{base_key}#{comment_encoded}"


class ResultSaver:
    @staticmethod
    def save(results: List[TestResult], output_dir: Path) -> Dict[QualityProfile, int]:
        by_profile: Dict[QualityProfile, List[TestResult]] = defaultdict(list)
        
        for result in results:
            by_profile[result.profile].append(result)
        
        saved_counts = {}
        
        for profile in QualityProfile:
            profile_results = by_profile.get(profile, [])
            if not profile_results:
                continue
            
            profile_results.sort(key=lambda x: x.score, reverse=True)
            
            filename = output_dir / f"{profile.value}.txt"
            
            with open(filename, 'w', encoding='utf-8') as f:
                f.write(f"# {QUALITY_PROFILES[profile].label}\n")
                f.write(f"# Канал: @vlesstrojan\n")
                f.write(f"# Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
                f.write(f"# Ключей: {len(profile_results)}\n\n")
                
                for result in profile_results:
                    f.write(ResultFormatter.format_key(result) + "\n")
            
            saved_counts[profile] = len(profile_results)
            logger.info(f"💾 {QUALITY_PROFILES[profile].label}: {len(profile_results)} → {filename.name}")
        
        return saved_counts


# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def find_latest_verified() -> Optional[Path]:
    if not RESULTS_FOLDER.exists():
        return None
    
    files = list(RESULTS_FOLDER.glob("verified_*.txt"))
    if not files:
        return None
    
    return max(files, key=lambda f: f.stat().st_mtime)


def load_keys(filepath: Path) -> List[str]:
    keys: List[str] = []
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#'):
                key = line.split('#')[0].strip()
                if key:
                    keys.append(key)
    
    return keys


# === MAIN ===
def print_banner():
    print("=" * 100)
    print(" " * 30 + "📱 REAL MOBILE VPN VALIDATOR v4.2")
    print(" " * 35 + "(XRAY-POWERED)")
    print("=" * 100)


def print_config():
    print(f"\n🎯 Проверки:")
    print(f"   ⚡ Latency - {CONFIG.LATENCY_SAMPLES} замеров (retry: {CONFIG.MAX_RETRIES})")
    print(f"   🏦 Категории - {len(CHECK_SITES)} × {CONFIG.CATEGORY_SAMPLES} (parallel: {CONFIG.CATEGORY_PARALLEL})")
    print(f"   📊 Stability - {CONFIG.STABILITY_CHECKS} подключений (min: {CONFIG.MIN_STABILITY_PERCENT}%)")
    
    print(f"\n🔄 Retry: max={CONFIG.MAX_RETRIES}, backoff={CONFIG.RETRY_BACKOFF}s-{CONFIG.RETRY_BACKOFF_MAX}s")
    
    print(f"\n🌐 {sum(len(sites) for sites in CHECK_SITES.values())} сайтов:")
    for category, sites in CHECK_SITES.items():
        names = ', '.join([s[1] for s in sites[:3]])
        if len(sites) > 3:
            names += f" (+{len(sites) - 3})"
        print(f"   {category}: {names}")


def main() -> int:
    print_banner()
    print_config()
    
    # Установка Xray
    xray_exe = XrayInstaller.setup()
    if not xray_exe:
        logger.error("❌ Не удалось установить Xray")
        return 1
    
    # Загрузка ключей
    source_file = find_latest_verified()
    if not source_file:
        logger.error("❌ Не найден verified файл")
        return 1
    
    logger.info(f"\n📁 Источник: {source_file.name}")
    
    keys = load_keys(source_file)
    if not keys:
        logger.error("❌ Нет ключей для проверки")
        return 1
    
    stats = ValidationStats(total=len(keys))
    
    logger.info(f"📦 Ключей: {len(keys)}")
    logger.info(f"⏱️  Оценка: ~{int(len(keys) * 15 / 60)} минут\n")  # Быстрее из-за параллелизма
    
    print("=" * 100)
    logger.info("🔍 Начинаем проверку...")
    print("=" * 100 + "\n")
    
    # Валидация
    validator = VPNValidator(xray_exe)
    all_results: List[TestResult] = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.MAX_PARALLEL) as executor:
        future_to_key = {
            executor.submit(validator.validate, key): key 
            for key in keys
        }
        
        completed = 0
        for future in concurrent.futures.as_completed(future_to_key):
            completed += 1
            
            try:
                result = future.result()
            except Exception as e:
                logger.debug(f"Future exception: {e}")
                result = None
            
            if result:
                all_results.append(result)
                stats.passed += 1
                stats.total_retries += result.retries_used
                stats.by_profile[result.profile] += 1
                
                label = QUALITY_PROFILES[result.profile].label
                retry_info = f" (retry:{result.retries_used})" if result.retries_used > 0 else ""
                logger.info(
                    f"[{completed}/{len(keys)}] {label}: "
                    f"Lat:{result.latency_avg:.0f}ms "
                    f"Stab:{result.stability_rate:.0f}% "
                    f"Cat:{result.categories_passed}/8{retry_info}"
                )
            else:
                stats.failed += 1
                if completed % 10 == 0:
                    logger.info(f"[{completed}/{len(keys)}] ...")
    
    # Сохранение
    print("\n" + "=" * 100)
    logger.info("💾 СОХРАНЕНИЕ")
    print("=" * 100 + "\n")
    
    ResultSaver.save(all_results, OUTPUT_DIR)
    
    # Итоги
    print("\n" + "=" * 100)
    print(f"✅ Готово! Прошло: {stats.passed}/{stats.total}")
    print(f"🔄 Всего retry: {stats.total_retries}")
    
    for profile in QualityProfile:
        count = stats.by_profile.get(profile, 0)
        if count > 0:
            print(f"   {QUALITY_PROFILES[profile].label}: {count}")
    
    print("=" * 100)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
