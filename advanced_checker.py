"""
📱 VPN VALIDATOR v6.0 LITE
- Дедупликация ключей
- Один запуск Xray на ключ
- Минимальные проверки
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


# ==================== КОНФИГУРАЦИЯ ====================
@dataclass
class Config:
    # Параллельность
    PARALLEL_WORKERS: int = 15
    
    # Таймауты
    TIMEOUT: Timeout = (5.0, 15.0)
    XRAY_STARTUP: float = 1.5
    
    # Проверки
    LATENCY_SAMPLES: int = 3       # Сколько замеров latency
    QUICK_CATEGORIES: int = 2      # Сколько категорий проверить
    
    # Retry
    RETRIES: int = 2
    RETRY_DELAY: float = 0.5
    
    # GC
    GC_EVERY_N_KEYS: int = 50


CONFIG = Config()


# Директории
WORK_DIR = Path(__file__).parent.absolute()
RESULTS_FOLDER = WORK_DIR / "results"
XRAY_FOLDER = WORK_DIR / "xray"
OUTPUT_DIR = RESULTS_FOLDER / "premium"

for d in [RESULTS_FOLDER, XRAY_FOLDER, OUTPUT_DIR]:
    d.mkdir(parents=True, exist_ok=True)


# URL для проверки
CHECK_URLS: List[str] = [
    "http://www.gstatic.com/generate_204",
    "http://cp.cloudflare.com/generate_204",
]

# Категории (минимум)
CATEGORY_URLS: List[Tuple[str, str]] = [
    ("https://www.google.com", "Google"),
    ("https://web.telegram.org", "Telegram"),
    ("https://www.youtube.com", "YouTube"),
    ("https://vk.com", "VK"),
]

USER_AGENTS: List[str] = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15",
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 Chrome/123.0.0.0",
]


# Качество
class Quality(Enum):
    ELITE = "elite"
    PREMIUM = "premium"
    GOOD = "good"


QUALITY_THRESHOLDS = {
    Quality.ELITE: {"latency": 100, "categories": 4},
    Quality.PREMIUM: {"latency": 200, "categories": 3},
    Quality.GOOD: {"latency": 500, "categories": 2},
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
class CheckResult:
    key: str
    alive: bool
    latency: float = 0
    categories: int = 0
    telegram: bool = False
    quality: Optional[Quality] = None
    error: Optional[str] = None


@dataclass
class Stats:
    total: int = 0
    duplicates: int = 0
    checked: int = 0
    passed: int = 0
    failed: int = 0
    by_quality: Dict[Quality, int] = field(default_factory=lambda: defaultdict(int))
    errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    start_time: float = field(default_factory=time.time)


def get_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        return s.getsockname()[1]


def safe_remove(path: Path):
    with contextlib.suppress(OSError):
        path.unlink()


def cleanup_memory():
    gc.collect()
    time.sleep(0.3)


# ==================== HTTP ====================
def create_session(proxies: Dict[str, str]) -> requests.Session:
    session = requests.Session()
    adapter = HTTPAdapter(max_retries=0, pool_connections=5, pool_maxsize=5)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    session.proxies.update(proxies)
    return session


def do_request(
    session: requests.Session,
    url: str,
    timeout: Timeout = CONFIG.TIMEOUT,
    retries: int = CONFIG.RETRIES
) -> Tuple[bool, float]:
    """Возвращает (success, latency_ms)"""
    
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
            
            if response.status_code < 500:
                return True, latency
                
        except requests.exceptions.Timeout:
            pass
        except requests.exceptions.ConnectionError:
            break  # Retry бесполезен
        except Exception:
            pass
        
        if attempt < retries:
            time.sleep(CONFIG.RETRY_DELAY)
    
    return False, 0


# ==================== XRAY ====================
@contextlib.contextmanager
def xray_session(
    xray_exe: Path,
    config: Dict[str, Any]
) -> Generator[Optional[Tuple[subprocess.Popen, int]], None, None]:
    
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
        
        time.sleep(CONFIG.XRAY_STARTUP)
        
        if process.poll() is not None:
            yield None
            return
        
        port = config["inbounds"][0]["port"]
        yield (process, port)
        
    finally:
        if process and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=1)
        
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
            logger.error(f"❌ Ошибка: {e}")
            return None


# ==================== ПАРСЕРЫ ====================
class KeyParser:
    @classmethod
    def parse(cls, key: str) -> Optional[ServerInfo]:
        key = key.strip()
        if '#' in key:
            key = key.split('#')[0].strip()
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


# ==================== XRAY CONFIG ====================
class XrayConfigBuilder:
    @classmethod
    def build(cls, server: ServerInfo, port: int) -> Optional[Dict]:
        outbound = cls._outbound(server)
        if not outbound:
            return None
        
        return {
            "log": {"loglevel": "none"},
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
                "settings": {"vnext": [{"address": s.host, "port": s.port, "users": [user]}]},
                "streamSettings": cls._stream(s)
            }
        
        elif s.protocol == "shadowsocks":
            return {
                "protocol": "shadowsocks",
                "settings": {"servers": [{"address": s.host, "port": s.port, "method": s.method, "password": s.password}]},
                "streamSettings": {"network": "tcp"}
            }
        
        elif s.protocol == "vmess":
            return {
                "protocol": "vmess",
                "settings": {"vnext": [{"address": s.host, "port": s.port, "users": [{"id": s.uuid, "alterId": 0, "security": "auto"}]}]},
                "streamSettings": cls._stream(s)
            }
        
        elif s.protocol == "trojan":
            return {
                "protocol": "trojan",
                "settings": {"servers": [{"address": s.host, "port": s.port, "password": s.password}]},
                "streamSettings": cls._stream(s)
            }
        
        return None
    
    @classmethod
    def _stream(cls, s: ServerInfo) -> Dict:
        ss: Dict[str, Any] = {"network": s.network_type, "security": s.security}
        
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


# ==================== ПРОВЕРКА (ОДИН ЗАПУСК XRAY!) ====================
def check_key(key: str, xray_exe: Path) -> CheckResult:
    """
    ОДИН запуск Xray на ключ:
    1. Проверка connectivity (несколько замеров latency)
    2. Проверка категорий
    """
    
    server = KeyParser.parse(key)
    if not server:
        return CheckResult(key=key, alive=False, error="parse_error")
    
    port = get_free_port()
    config = XrayConfigBuilder.build(server, port)
    if not config:
        return CheckResult(key=key, alive=False, error="config_error")
    
    with xray_session(xray_exe, config) as session:
        if not session:
            return CheckResult(key=key, alive=False, error="xray_fail")
        
        _, socks_port = session
        proxies = {
            "http": f"socks5://127.0.0.1:{socks_port}",
            "https": f"socks5://127.0.0.1:{socks_port}"
        }
        
        http = create_session(proxies)
        
        try:
            # === 1. LATENCY TEST ===
            latencies: List[float] = []
            
            for _ in range(CONFIG.LATENCY_SAMPLES):
                url = random.choice(CHECK_URLS)
                success, latency = do_request(http, url, retries=1)
                if success:
                    latencies.append(latency)
            
            if not latencies:
                return CheckResult(key=key, alive=False, error="connectivity_fail")
            
            avg_latency = mean(latencies)
            
            # === 2. CATEGORY TEST ===
            categories_passed = 0
            telegram_works = False
            
            for url, name in CATEGORY_URLS[:CONFIG.QUICK_CATEGORIES + 2]:
                success, _ = do_request(http, url, timeout=(5, 20), retries=1)
                if success:
                    categories_passed += 1
                    if "telegram" in name.lower():
                        telegram_works = True
            
            # === 3. ОПРЕДЕЛЕНИЕ КАЧЕСТВА ===
            quality = Quality.GOOD
            
            for q in [Quality.ELITE, Quality.PREMIUM, Quality.GOOD]:
                thresh = QUALITY_THRESHOLDS[q]
                if avg_latency <= thresh["latency"] and categories_passed >= thresh["categories"]:
                    quality = q
                    break
            
            return CheckResult(
                key=key,
                alive=True,
                latency=round(avg_latency, 1),
                categories=categories_passed,
                telegram=telegram_works,
                quality=quality
            )
            
        except Exception as e:
            return CheckResult(key=key, alive=False, error=f"exception: {type(e).__name__}")
        finally:
            http.close()


# ==================== ЗАГРУЗКА И ДЕДУПЛИКАЦИЯ ====================
def load_and_deduplicate(filepath: Path) -> Tuple[List[str], int]:
    """
    Загрузка ключей С ДЕДУПЛИКАЦИЕЙ
    Возвращает: (уникальные ключи, количество дублей)
    """
    seen: Set[str] = set()
    unique_keys: List[str] = []
    duplicates = 0
    
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            
            # Убираем тег для нормализации
            if '#' in line:
                key_normalized = line.split('#')[0].strip()
            else:
                key_normalized = line.strip()
            
            if not key_normalized:
                continue
            
            # Проверка на дубль
            if key_normalized in seen:
                duplicates += 1
                continue
            
            seen.add(key_normalized)
            unique_keys.append(line)  # Сохраняем оригинальный ключ (с тегом)
    
    return unique_keys, duplicates


def find_source_file() -> Optional[Path]:
    if not RESULTS_FOLDER.exists():
        return None
    
    # Приоритет: verified_*.txt
    files = list(RESULTS_FOLDER.glob("verified_*.txt"))
    if files:
        return max(files, key=lambda f: f.stat().st_mtime)
    
    # Fallback: любой .txt
    files = list(RESULTS_FOLDER.glob("*.txt"))
    if files:
        return max(files, key=lambda f: f.stat().st_mtime)
    
    return None


# ==================== СОХРАНЕНИЕ ====================
def save_results(results: List[CheckResult], output_dir: Path):
    """Сохранение по категориям качества"""
    
    by_quality: Dict[Quality, List[CheckResult]] = defaultdict(list)
    for r in results:
        if r.alive and r.quality:
            by_quality[r.quality].append(r)
    
    for quality in Quality:
        items = by_quality.get(quality, [])
        if not items:
            continue
        
        # Сортируем по latency (лучшие первые)
        items.sort(key=lambda x: x.latency)
        
        filename = output_dir / f"{quality.value}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {quality.value.upper()}\n")
            f.write(f"# @vlesstrojan\n")
            f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# Ключей: {len(items)}\n\n")
            
            for r in items:
                tg = "TG+" if r.telegram else ""
                comment = f"[{r.latency:.0f}ms|{r.quality.value}|{r.categories}cat|{tg}@vlesstrojan]"
                base_key = r.key.split('#')[0]
                f.write(f"{base_key}#{quote(comment)}\n")
        
        logger.info(f"💾 {quality.value.upper()}: {len(items)} → {filename.name}")


# ==================== MAIN ====================
def main() -> int:
    print("\n" + "=" * 60)
    print(" " * 10 + "📱 VPN VALIDATOR v6.0 LITE")
    print(" " * 5 + "Дедупликация + Один запуск Xray на ключ")
    print("=" * 60)
    
    print(f"\n⚙️  Настройки:")
    print(f"   Workers: {CONFIG.PARALLEL_WORKERS}")
    print(f"   Timeout: {CONFIG.TIMEOUT}")
    print(f"   Xray startup: {CONFIG.XRAY_STARTUP}s")
    print(f"   Latency samples: {CONFIG.LATENCY_SAMPLES}")
    
    # Xray
    xray_exe = XrayInstaller.setup()
    if not xray_exe:
        logger.error("❌ Не удалось установить Xray")
        return 1
    
    # Файл
    source = find_source_file()
    if not source:
        logger.error("❌ Не найден файл с ключами")
        return 1
    
    logger.info(f"\n📁 Источник: {source.name}")
    
    # Загрузка С ДЕДУПЛИКАЦИЕЙ
    keys, duplicates = load_and_deduplicate(source)
    
    if not keys:
        logger.error("❌ Нет ключей")
        return 1
    
    stats = Stats(total=len(keys) + duplicates, duplicates=duplicates)
    
    logger.info(f"📦 Всего строк: {stats.total}")
    if duplicates > 0:
        logger.info(f"🔄 Дубликатов удалено: {duplicates}")
    logger.info(f"✅ Уникальных ключей: {len(keys)}")
    
    # Проверка
    logger.info(f"\n{'='*60}")
    logger.info(f"🔬 ПРОВЕРКА ({CONFIG.PARALLEL_WORKERS} workers)")
    logger.info(f"{'='*60}\n")
    
    start_time = time.time()
    results: List[CheckResult] = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.PARALLEL_WORKERS) as executor:
        futures = {executor.submit(check_key, key, xray_exe): key for key in keys}
        
        done = 0
        total = len(keys)
        
        for future in concurrent.futures.as_completed(futures):
            done += 1
            stats.checked += 1
            
            try:
                result = future.result(timeout=120)
                
                if result.alive:
                    results.append(result)
                    stats.passed += 1
                    stats.by_quality[result.quality] += 1
                    
                    tg = " 📱" if result.telegram else ""
                    logger.info(
                        f"[{done}/{total}] ✓ {result.quality.value.upper()} | "
                        f"{result.latency:.0f}ms | {result.categories}cat{tg}"
                    )
                else:
                    stats.failed += 1
                    if result.error:
                        stats.errors[result.error] += 1
                    
            except Exception as e:
                stats.failed += 1
                stats.errors["future_exception"] += 1
            
            # Прогресс и GC
            if done % CONFIG.GC_EVERY_N_KEYS == 0:
                cleanup_memory()
                elapsed = time.time() - start_time
                speed = done / elapsed if elapsed > 0 else 1
                eta = (total - done) / speed / 60 if speed > 0 else 0
                pct = stats.passed * 100 // done if done > 0 else 0
                
                logger.info(
                    f"[{done}/{total}] ✅ {stats.passed} ({pct}%) | "
                    f"⏱️ {elapsed/60:.1f}м | ETA: {eta:.1f}м"
                )
    
    total_time = time.time() - start_time
    
    # Сохранение
    if results:
        logger.info(f"\n💾 Сохранение результатов...")
        save_results(results, OUTPUT_DIR)
    
    # Статистика ошибок
    if stats.errors:
        logger.info(f"\n📊 Ошибки:")
        for error, count in sorted(stats.errors.items(), key=lambda x: -x[1])[:5]:
            pct = count * 100 // max(stats.failed, 1)
            logger.info(f"   {error}: {count} ({pct}%)")
    
    # Итоги
    print("\n" + "=" * 60)
    print("📊 ИТОГИ")
    print("=" * 60)
    print(f"   Всего строк: {stats.total}")
    print(f"   Дубликатов: {stats.duplicates}")
    print(f"   Уникальных: {len(keys)}")
    print(f"   Прошло: {stats.passed} ({stats.passed*100//max(len(keys),1)}%)")
    print(f"   Время: {total_time/60:.1f} мин")
    print()
    print("🏆 По качеству:")
    for q in Quality:
        count = stats.by_quality.get(q, 0)
        if count > 0:
            print(f"   {q.value.upper()}: {count}")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
