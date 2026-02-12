"""
📱 REAL MOBILE VPN VALIDATOR v5.4 (RELAXED)
Мягкие настройки для максимального сохранения ключей
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

urllib3.disable_warnings()
logging.getLogger("urllib3").setLevel(logging.ERROR)
logging.getLogger("requests").setLevel(logging.ERROR)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger(__name__)

Timeout = Union[float, Tuple[float, float]]

CRITICAL_BAD_SNI: Set[str] = {
    "localhost", "127.0.0.1", "0.0.0.0", "::1", "",
    "example.com", "example.org", "test.com", "test.org",
    "fuck.rkn", "invalid.invalid", "none", "null",
}


def is_critical_bad_sni(sni: Optional[str]) -> bool:
    if sni is None:
        return False
    sni = sni.lower().strip()
    if not sni:
        return True
    if sni in CRITICAL_BAD_SNI:
        return True
    if sni.startswith("127.") or sni.startswith("0."):
        return True
    for bad in CRITICAL_BAD_SNI:
        if bad and sni.endswith("." + bad):
            return True
    return False


# ==================== МЯГКИЕ НАСТРОЙКИ ====================
@dataclass
class Config:
    # --- ЭТАП 1: Quick Filter (СМЯГЧЕНО) ---
    QUICK_PARALLEL: int = 20          # Было 50 → 20
    QUICK_TIMEOUT: Timeout = (5.0, 15.0)  # Было (2, 4) → (5, 15)
    QUICK_RETRIES: int = 2            # Было 1 → 2
    
    # --- ЭТАП 2: Full Test (СМЯГЧЕНО) ---
    FULL_PARALLEL: int = 10           # Было 20 → 10
    LATENCY_SAMPLES: int = 5          # Было 8 → 5
    STABILITY_CHECKS: int = 5         # Было 10 → 5
    CATEGORY_SAMPLES: int = 1         # Было 2 → 1
    
    # --- Таймауты (УВЕЛИЧЕНЫ) ---
    TIMEOUT_FAST: Timeout = (5.0, 15.0)     # Было (2, 5)
    TIMEOUT_NORMAL: Timeout = (8.0, 25.0)   # Было (3, 8)
    TIMEOUT_SLOW: Timeout = (10.0, 45.0)    # Было (4, 15)
    
    # --- Rate Limiting ---
    RATE_LIMIT_MIN: float = 0.1       # Было 0.05
    RATE_LIMIT_MAX: float = 0.3       # Было 0.15
    
    # --- Xray (УВЕЛИЧЕНО) ---
    XRAY_STARTUP: float = 2.0         # Было 0.6 → 2.0
    XRAY_STARTUP_STABILITY: float = 1.5  # Было 0.4 → 1.5
    XRAY_CONN_IDLE: int = 300
    
    # --- Пороги (СМЯГЧЕНЫ) ---
    MIN_LATENCY_SAMPLES: int = 2      # Было 4 → 2
    MIN_STABILITY_PERCENT: float = 50.0  # Было 80 → 50
    
    # --- Категории (СМЯГЧЕНЫ) ---
    MIN_CATEGORIES_GOOD: int = 2      # Было 4 → 2
    
    # --- ELITE ---
    ELITE_LATENCY_THRESHOLD: float = 150.0  # Было 100
    ELITE_STABILITY_THRESHOLD: float = 85.0  # Было 95
    
    # --- Retry ---
    MAX_RETRIES: int = 2              # Было 1 → 2
    RETRY_DELAY: float = 1.0          # Было 0.3 → 1.0
    
    # --- GC ---
    GC_EVERY_N_KEYS: int = 100        # Было 500 → 100 (чаще чистим)
    GC_SLEEP: float = 0.5
    
    TELEGRAM_BONUS: int = 5


CONFIG = Config()
# ==========================================================


FAST_SITES: Set[str] = {
    "www.google.com", "google.com",
    "yandex.ru", "www.yandex.ru",
    "vk.com", "www.vk.com",
    "www.gstatic.com",
    "cp.cloudflare.com",
}

SLOW_SITES: Set[str] = {
    "www.sberbank.ru", "sberbank.ru",
    "www.gosuslugi.ru", "gosuslugi.ru",
}

WORK_DIR = Path(__file__).parent.absolute()
RESULTS_FOLDER = WORK_DIR / "results"
XRAY_FOLDER = WORK_DIR / "xray"
OUTPUT_DIR = RESULTS_FOLDER / "premium"

for d in [RESULTS_FOLDER, XRAY_FOLDER, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# Упрощённый список проверок
QUICK_CHECK_URLS: List[str] = [
    "http://www.gstatic.com/generate_204",
    "http://cp.cloudflare.com/generate_204",
    "http://connectivitycheck.android.com/generate_204",
]

# УПРОЩЁННЫЕ КАТЕГОРИИ (меньше сайтов)
CHECK_SITES: Dict[str, List[Tuple[str, str]]] = {
    "telegram": [
        ("https://web.telegram.org", "Telegram Web"),
    ],
    "social": [
        ("https://vk.com", "VK"),
    ],
    "video": [
        ("https://www.youtube.com", "YouTube"),
    ],
    "services": [
        ("https://www.google.com", "Google"),
    ],
}

USER_AGENTS: List[str] = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 Chrome/123.0.0.0",
]


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


# СМЯГЧЁННЫЕ ПОРОГИ КАЧЕСТВА
QUALITY_PROFILES: Dict[QualityProfile, ProfileThresholds] = {
    QualityProfile.ELITE: ProfileThresholds(
        label="ELITE", latency_max=150, jitter_max=50,
        stability_min=80, categories_min=4, priority=1
    ),
    QualityProfile.PREMIUM: ProfileThresholds(
        label="PREM", latency_max=300, jitter_max=100,
        stability_min=65, categories_min=3, priority=2
    ),
    QualityProfile.GOOD: ProfileThresholds(
        label="GOOD", latency_max=1000, jitter_max=300,
        stability_min=50, categories_min=2, priority=3
    )
}


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
    error: Optional[str] = None  # ДОБАВЛЕНО для диагностики


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
    quick_bad_sni: int = 0
    quick_parse_error: int = 0
    quick_xray_fail: int = 0
    quick_timeout: int = 0
    quick_connect_fail: int = 0
    full_passed: int = 0
    full_failed: int = 0
    elite_with_ip: int = 0
    by_profile: Dict[QualityProfile, int] = field(default_factory=lambda: defaultdict(int))
    start_time: float = field(default_factory=time.time)
    quick_time: float = 0
    full_time: float = 0


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


def rate_limit_delay():
    time.sleep(random.uniform(CONFIG.RATE_LIMIT_MIN, CONFIG.RATE_LIMIT_MAX))


def cleanup_memory():
    gc.collect()
    time.sleep(CONFIG.GC_SLEEP)


def create_session(proxies: Dict[str, str]) -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=0, pool_connections=5, pool_maxsize=5)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.proxies.update(proxies)
    return session


def smart_request(
    session: requests.Session,
    url: str,
    timeout: Optional[Timeout] = None,
    retries: int = 2
) -> Tuple[Optional[requests.Response], float, Optional[str]]:
    """Возвращает (response, latency_ms, error_type)"""
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
            return response, latency, None
            
        except requests.exceptions.ConnectTimeout:
            return None, 0, "connect_timeout"
            
        except requests.exceptions.ReadTimeout:
            if attempt < retries:
                time.sleep(CONFIG.RETRY_DELAY)
            else:
                return None, 0, "read_timeout"
                
        except requests.exceptions.ConnectionError as e:
            return None, 0, f"connection_error"
            
        except Exception as e:
            if attempt < retries:
                time.sleep(CONFIG.RETRY_DELAY)
            else:
                return None, 0, f"other: {type(e).__name__}"
    
    return None, 0, "max_retries"


@contextlib.contextmanager
def xray_session(
    xray_exe: Path,
    config: Dict[str, Any],
    startup_delay: float = CONFIG.XRAY_STARTUP
) -> Generator[Optional[Tuple[subprocess.Popen, int, Path]], None, None]:
    
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
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                try:
                    process.wait(timeout=2)
                except:
                    pass
        
        if config_file:
            safe_remove(config_file)


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
            
            response = requests.get(url, stream=True, timeout=120)
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
                    "0": {"connIdle": CONFIG.XRAY_CONN_IDLE}
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


def quick_check_one(key: str, xray_exe: Path) -> QuickResult:
    """Быстрая проверка с диагностикой"""
    
    server = KeyParser.parse(key)
    if not server:
        return QuickResult(key=key, alive=False, error="parse_error")
    
    if is_critical_bad_sni(server.sni):
        return QuickResult(key=key, alive=False, error="bad_sni")
    
    port = get_free_port()
    config = XrayConfigBuilder.build(server, port)
    if not config:
        return QuickResult(key=key, alive=False, error="config_error")
    
    with xray_session(xray_exe, config) as session:
        if not session:
            return QuickResult(key=key, alive=False, error="xray_fail")
        
        _, socks_port, _ = session
        proxies = {
            "http": f"socks5://127.0.0.1:{socks_port}",
            "https": f"socks5://127.0.0.1:{socks_port}"
        }
        
        http = create_session(proxies)
        try:
            # Пробуем несколько URL
            for url in QUICK_CHECK_URLS:
                response, latency, error = smart_request(
                    http, url,
                    timeout=CONFIG.QUICK_TIMEOUT,
                    retries=CONFIG.QUICK_RETRIES
                )
                
                if response and response.status_code in [200, 204]:
                    return QuickResult(key=key, alive=True, latency=latency)
            
            # Все URL провалились
            return QuickResult(key=key, alive=False, error=error or "all_urls_failed")
        finally:
            http.close()
    
    return QuickResult(key=key, alive=False, error="unknown")


def run_quick_filter(keys: List[str], xray_exe: Path, stats: Stats) -> List[str]:
    """ЭТАП 1: Быстрая фильтрация с детальной статистикой ошибок"""
    
    error_counts: Dict[str, int] = defaultdict(int)
    
    logger.info(f"\n{'='*60}")
    logger.info(f"⚡ ЭТАП 1: БЫСТРЫЙ ФИЛЬТР (RELAXED)")
    logger.info(f"{'='*60}")
    logger.info(f"📦 Ключей: {len(keys)} | Параллельно: {CONFIG.QUICK_PARALLEL}")
    logger.info(f"⏱️  Таймаут: connect={CONFIG.QUICK_TIMEOUT[0]}s, read={CONFIG.QUICK_TIMEOUT[1]}s")
    logger.info(f"🔄 Retries: {CONFIG.QUICK_RETRIES} | Xray startup: {CONFIG.XRAY_STARTUP}s")
    
    start_time = time.time()
    alive_keys: List[str] = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.QUICK_PARALLEL) as executor:
        futures = {
            executor.submit(quick_check_one, key, xray_exe): key 
            for key in keys
        }
        
        done = 0
        total = len(keys)
        
        for future in concurrent.futures.as_completed(futures):
            done += 1
            
            try:
                result = future.result(timeout=60)
                
                if result.alive:
                    alive_keys.append(result.key)
                    stats.quick_alive += 1
                else:
                    stats.quick_dead += 1
                    if result.error:
                        error_counts[result.error] += 1
                    
            except Exception as e:
                stats.quick_dead += 1
                error_counts["future_exception"] += 1
            
            if done % CONFIG.GC_EVERY_N_KEYS == 0:
                cleanup_memory()
                elapsed = time.time() - start_time
                speed = done / elapsed if elapsed > 0 else 1
                eta = (total - done) / speed / 60 if speed > 0 else 0
                pct = stats.quick_alive * 100 // done if done > 0 else 0
                
                # Показываем статистику ошибок
                top_errors = sorted(error_counts.items(), key=lambda x: -x[1])[:3]
                errors_str = " | ".join([f"{k}:{v}" for k, v in top_errors])
                
                logger.info(
                    f"[{done}/{total}] ✅ {stats.quick_alive} ({pct}%) | "
                    f"⏱️ {elapsed/60:.1f}м | ETA: {eta:.1f}м"
                )
                if errors_str:
                    logger.info(f"   ❌ Top errors: {errors_str}")
    
    cleanup_memory()
    stats.quick_time = time.time() - start_time
    
    # Итоговая статистика ошибок
    logger.info(f"\n{'='*60}")
    logger.info(f"📊 СТАТИСТИКА ОШИБОК:")
    for error, count in sorted(error_counts.items(), key=lambda x: -x[1]):
        pct = count * 100 // max(stats.quick_dead, 1)
        logger.info(f"   {error}: {count} ({pct}%)")
    
    pct = stats.quick_alive * 100 // max(len(keys), 1)
    logger.info(f"\n✅ ЭТАП 1 ЗАВЕРШЁН за {stats.quick_time/60:.1f} мин")
    logger.info(f"📊 Живых: {stats.quick_alive} ({pct}%) | Мёртвых: {stats.quick_dead}")
    logger.info(f"{'='*60}\n")
    
    return alive_keys


def full_test_one(key: str, xray_exe: Path) -> Optional[FullResult]:
    """Упрощённая полная проверка"""
    
    server = KeyParser.parse(key)
    if not server:
        return None
    
    if is_critical_bad_sni(server.sni):
        return None
    
    # === LATENCY TEST ===
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
                response, latency, _ = smart_request(
                    http, url,
                    timeout=CONFIG.TIMEOUT_FAST,
                    retries=1
                )
                if response and response.status_code in [200, 204]:
                    latencies.append(latency)
        finally:
            http.close()
    
    if len(latencies) < CONFIG.MIN_LATENCY_SAMPLES:
        return None
    
    latency_avg = round(mean(latencies), 1)
    latency_jitter = round(stdev(latencies), 1) if len(latencies) > 1 else 0
    
    # === CATEGORY TEST (УПРОЩЁННЫЙ) ===
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
                    rate_limit_delay()
                    
                    response, _, _ = smart_request(
                        http, url,
                        timeout=CONFIG.TIMEOUT_NORMAL,
                        retries=CONFIG.MAX_RETRIES
                    )
                    
                    if response and response.status_code < 500:
                        passed += 1
                        if category == "telegram":
                            telegram_works = True
                
                categories[category] = passed
        finally:
            http.close()
    
    categories_passed = sum(1 for v in categories.values() if v > 0)
    
    # === STABILITY TEST (УПРОЩЁННЫЙ) ===
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
                response, _, _ = smart_request(
                    http,
                    QUICK_CHECK_URLS[0],
                    timeout=(5, 10),
                    retries=1
                )
                if response and response.status_code in [200, 204]:
                    successes += 1
            finally:
                http.close()
    
    stability = round(successes / CONFIG.STABILITY_CHECKS * 100, 1)
    
    # МЯГКИЙ ПОРОГ
    if stability < CONFIG.MIN_STABILITY_PERCENT:
        return None
    
    # === ОПРЕДЕЛЕНИЕ ПРОФИЛЯ ===
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
        proxy_ip=None,
        telegram_works=telegram_works
    )


def run_full_test(keys: List[str], xray_exe: Path, stats: Stats) -> List[FullResult]:
    """ЭТАП 2: Полная проверка"""
    
    logger.info(f"\n{'='*60}")
    logger.info(f"🔬 ЭТАП 2: ПОЛНАЯ ПРОВЕРКА (RELAXED)")
    logger.info(f"{'='*60}")
    logger.info(f"📦 Ключей: {len(keys)} | Параллельно: {CONFIG.FULL_PARALLEL}")
    logger.info(f"📊 Мин. стабильность: {CONFIG.MIN_STABILITY_PERCENT}%")
    logger.info(f"📊 Мин. категорий: {CONFIG.MIN_CATEGORIES_GOOD}")
    
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
                result = future.result(timeout=300)
                
                if result:
                    results.append(result)
                    stats.full_passed += 1
                    stats.by_profile[result.profile] += 1
                    
                    label = QUALITY_PROFILES[result.profile].label
                    tg = " 📱" if result.telegram_works else ""
                    
                    logger.info(
                        f"[{done}/{total}] ✓ {label} | "
                        f"{result.latency_avg:.0f}ms j:{result.latency_jitter:.0f} | "
                        f"stab:{result.stability_rate:.0f}% | "
                        f"cat:{result.categories_passed}/{len(CHECK_SITES)}{tg}"
                    )
                else:
                    stats.full_failed += 1
                    
            except Exception as e:
                stats.full_failed += 1
            
            if done % 20 == 0:
                elapsed = time.time() - start_time
                logger.info(f"[{done}/{total}] ⏱️ {elapsed/60:.1f}м | ✓ {stats.full_passed}")
    
    cleanup_memory()
    stats.full_time = time.time() - start_time
    
    logger.info(f"\n✅ ЭТАП 2 ЗАВЕРШЁН за {stats.full_time/60:.1f} мин")
    logger.info(f"📊 Прошло: {stats.full_passed} | Отсеяно: {stats.full_failed}")
    
    return results


def save_results(results: List[FullResult], output_dir: Path, stats: Stats):
    """Сохранение результатов"""
    
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


def find_source_file() -> Optional[Path]:
    if not RESULTS_FOLDER.exists():
        return None
    
    files = list(RESULTS_FOLDER.glob("verified_*.txt"))
    if files:
        return max(files, key=lambda f: f.stat().st_mtime)
    
    files = list(RESULTS_FOLDER.glob("*.txt"))
    if files:
        return max(files, key=lambda f: f.stat().st_mtime)
    
    return None


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


def main() -> int:
    print("\n" + "=" * 60)
    print(" " * 10 + "📱 VPN VALIDATOR v5.4 RELAXED")
    print(" " * 5 + "Мягкие настройки для максимума ключей")
    print("=" * 60)
    
    print(f"\n⚙️  НАСТРОЙКИ (RELAXED):")
    print(f"   Quick: {CONFIG.QUICK_PARALLEL} parallel, timeout={CONFIG.QUICK_TIMEOUT}")
    print(f"   Full: {CONFIG.FULL_PARALLEL} parallel")
    print(f"   Xray startup: {CONFIG.XRAY_STARTUP}s")
    print(f"   Min stability: {CONFIG.MIN_STABILITY_PERCENT}%")
    print(f"   Retries: {CONFIG.QUICK_RETRIES} / {CONFIG.MAX_RETRIES}")
    
    xray_exe = XrayInstaller.setup()
    if not xray_exe:
        logger.error("❌ Не удалось установить Xray")
        return 1
    
    source = find_source_file()
    if not source:
        logger.error("❌ Не найден файл с ключами")
        return 1
    
    logger.info(f"\n📁 Источник: {source.name}")
    
    keys = load_keys(source)
    if not keys:
        logger.error("❌ Нет ключей")
        return 1
    
    stats = Stats(total=len(keys))
    logger.info(f"📦 Ключей: {len(keys)}")
    
    # ЭТАП 1
    alive_keys = run_quick_filter(keys, xray_exe, stats)
    
    if not alive_keys:
        logger.warning("⚠️ Не найдено живых ключей!")
        return 0
    
    # ЭТАП 2
    results = run_full_test(alive_keys, xray_exe, stats)
    
    if results:
        save_results(results, OUTPUT_DIR, stats)
    
    # Итоги
    total_time = time.time() - stats.start_time
    print("\n" + "=" * 60)
    print("📊 ИТОГИ")
    print(f"   Всего: {stats.total}")
    print(f"   Quick alive: {stats.quick_alive} ({stats.quick_alive*100//max(stats.total,1)}%)")
    print(f"   Full passed: {stats.full_passed}")
    print(f"   Время: {total_time/60:.1f} мин")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
