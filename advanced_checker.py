"""
🔥 UNIFIED VPN CHECKER v2.1 OPTIMAL
3 запуска Xray на ключ:
1. Main session: Latency + Categories
2. Reconnect test #1
3. Reconnect test #2
"""

import os
import re
import html
import socket
import time
import sys
import subprocess
import requests
import base64
import json
import random
import threading
import concurrent.futures
import atexit
import signal
import gc
from datetime import datetime
from urllib.parse import quote, unquote
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean, stdev

# ------------------ КОНФИГУРАЦИЯ ------------------
WORK_DIR = Path(__file__).parent.absolute()
XRAY_FOLDER = WORK_DIR / "xray"
RESULTS_FOLDER = WORK_DIR / "results"
PREMIUM_FOLDER = RESULTS_FOLDER / "premium"

for d in [XRAY_FOLDER, RESULTS_FOLDER, PREMIUM_FOLDER]:
    d.mkdir(parents=True, exist_ok=True)

KEY_SOURCES = {
    "RU": [
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/RU_Best/ru_white_part1.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/RU_Best/ru_white_part2.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/RU_Best/ru_white_part3.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/RU_Best/ru_white_part4.txt",
    ],
    "EU": [
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/My_Euro/my_euro_part1.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/My_Euro/my_euro_part2.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/My_Euro/my_euro_part3.txt",
    ]
}

MY_CHANNEL = "@vlesstrojan"


# ==================== OPTIMAL НАСТРОЙКИ ====================
@dataclass
class Config:
    # TCP
    TCP_WORKERS: int = 40
    TCP_TIMEOUT: int = 8
    TCP_RETRIES: int = 1
    
    # XRAY
    XRAY_WORKERS: int = 12
    XRAY_STARTUP: float = 1.5
    XRAY_STARTUP_QUICK: float = 1.0  # Для reconnect тестов
    XRAY_TIMEOUT: int = 12
    
    # === ПРОВЕРКИ ===
    # Сессия 1: Latency
    LATENCY_SAMPLES: int = 5
    MIN_LATENCY_SUCCESS: int = 3
    
    # Сессия 1: Categories (в той же сессии)
    CATEGORY_URLS: List[Tuple[str, str]] = field(default_factory=lambda: [
        ("https://www.google.com", "google"),
        ("https://web.telegram.org", "telegram"),
        ("https://www.youtube.com", "youtube"),
        ("https://vk.com", "vk"),
        ("https://www.instagram.com", "instagram"),
        ("https://twitter.com", "twitter"),
        ("https://www.tiktok.com", "tiktok"),
    ])
    
    # Сессии 2-3: Reconnect tests
    RECONNECT_TESTS: int = 2  # Сколько раз переподключаемся
    
    # Пороги
    MIN_RECONNECT_SUCCESS: int = 2  # Из 2 reconnect минимум 2 успешных
    
    # URLs для тестов
    CHECK_URLS: List[str] = field(default_factory=lambda: [
        'https://cp.cloudflare.com/generate_204',
        'http://www.gstatic.com/generate_204',
    ])
    
    GC_EVERY: int = 60


CONFIG = Config()


# ==================== КАЧЕСТВО ====================
class Quality(Enum):
    ELITE = "elite"
    PREMIUM = "premium"
    GOOD = "good"


@dataclass
class QualityThreshold:
    latency_max: float
    jitter_max: float
    categories_min: int


QUALITY_THRESHOLDS = {
    Quality.ELITE: QualityThreshold(latency_max=80, jitter_max=30, categories_min=5),
    Quality.PREMIUM: QualityThreshold(latency_max=150, jitter_max=50, categories_min=4),
    Quality.GOOD: QualityThreshold(latency_max=300, jitter_max=80, categories_min=3),
}


@dataclass
class CheckResult:
    key: str
    alive: bool
    latency: float = 0
    jitter: float = 0
    reconnect_success: int = 0
    categories: int = 0
    telegram: bool = False
    quality: Optional[Quality] = None
    protocol: str = ""
    host: str = ""
    port: int = 0
    error: Optional[str] = None


@dataclass
class Stats:
    total_downloaded: int = 0
    duplicates: int = 0
    unique: int = 0
    tcp_passed: int = 0
    tcp_failed: int = 0
    xray_passed: int = 0
    xray_failed: int = 0
    by_quality: Dict[Quality, int] = field(default_factory=lambda: defaultdict(int))
    errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    start_time: float = field(default_factory=time.time)


stats = Stats()
stats_lock = threading.Lock()


def record_error(error: str):
    with stats_lock:
        stats.errors[error] += 1


_active_processes: List[subprocess.Popen] = []
_processes_lock = threading.Lock()


def register_process(proc):
    with _processes_lock:
        _active_processes.append(proc)


def unregister_process(proc):
    with _processes_lock:
        if proc in _active_processes:
            _active_processes.remove(proc)


def cleanup_all_processes():
    with _processes_lock:
        for p in list(_active_processes):
            try:
                p.kill()
                p.wait(timeout=1)
            except:
                pass
        _active_processes.clear()


atexit.register(cleanup_all_processes)


def signal_handler(signum, frame):
    print("\n\n⚠️  Прерывание!")
    cleanup_all_processes()
    sys.exit(1)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def log(msg):
    print(msg)


def cleanup_memory():
    gc.collect()
    time.sleep(0.2)


# ==================== XRAY ====================
def setup_xray() -> Optional[Path]:
    exe_name = "xray.exe" if os.name == 'nt' else "xray"
    exe_path = XRAY_FOLDER / exe_name
    
    if exe_path.exists():
        return exe_path
    
    log("📥 Скачивание xray-core...")
    
    try:
        import platform
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
        r = requests.get(url, stream=True, timeout=120)
        zip_path = XRAY_FOLDER / "xray.zip"
        
        with open(zip_path, 'wb') as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
        
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(XRAY_FOLDER)
        
        zip_path.unlink()
        
        if system != "windows":
            exe_path.chmod(0o755)
        
        log("✅ Xray установлен")
        return exe_path
        
    except Exception as e:
        log(f"❌ Ошибка: {e}")
        return None


def create_xray_config(proxy_config: Dict, http_port: int) -> Dict:
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": http_port,
            "listen": "127.0.0.1",
            "protocol": "http",
            "settings": {"timeout": 30}
        }],
        "outbounds": [proxy_config]
    }


def wait_for_port(port: int, timeout: float = 5) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except:
            time.sleep(0.1)
    return False


def run_xray_session(xray_exe: Path, proxy_config: Dict, startup: float = 1.5):
    """Context manager для одной сессии Xray"""
    http_port = random.randint(20000, 50000)
    config = create_xray_config(proxy_config, http_port)
    config_file = XRAY_FOLDER / f"config_{http_port}.json"
    
    class XraySession:
        def __init__(self):
            self.process = None
            self.port = http_port
            self.proxies = None
            self.ok = False
        
        def __enter__(self):
            try:
                with open(config_file, 'w') as f:
                    json.dump(config, f)
                
                self.process = subprocess.Popen(
                    [str(xray_exe), "run", "-c", str(config_file)],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                register_process(self.process)
                
                if wait_for_port(http_port, timeout=startup) and self.process.poll() is None:
                    self.proxies = {
                        'http': f'http://127.0.0.1:{http_port}',
                        'https': f'http://127.0.0.1:{http_port}'
                    }
                    self.ok = True
                
            except:
                pass
            
            return self
        
        def __exit__(self, *args):
            if self.process:
                unregister_process(self.process)
                try:
                    self.process.terminate()
                    self.process.wait(timeout=2)
                except:
                    try:
                        self.process.kill()
                        self.process.wait(timeout=1)
                    except:
                        pass
            
            try:
                config_file.unlink()
            except:
                pass
    
    return XraySession()


# ==================== ЗАГРУЗКА ====================
def download_and_deduplicate() -> List[str]:
    all_keys: List[str] = []
    seen: Set[str] = set()
    duplicates = 0
    
    log("📥 Загрузка ключей...")
    
    for region, urls in KEY_SOURCES.items():
        log(f"\n🌍 {region}:")
        for url in urls:
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                lines = r.text.strip().split('\n')
                
                count = 0
                for line in lines:
                    line = html.unescape(line.strip())
                    if not line or not line.lower().startswith(("vless://", "vmess://", "trojan://", "ss://")):
                        continue
                    
                    key_normalized = line.split("#")[0].strip()
                    
                    if key_normalized in seen:
                        duplicates += 1
                        continue
                    
                    seen.add(key_normalized)
                    all_keys.append(line)
                    count += 1
                
                stats.total_downloaded += count
                log(f"  ✅ {url.split('/')[-1]}: {count}")
                
            except Exception as e:
                log(f"  ❌ {url.split('/')[-1]}: {e}")
    
    stats.duplicates = duplicates
    stats.unique = len(all_keys)
    
    log(f"\n📦 Скачано: {stats.total_downloaded + duplicates}, Дубли: {duplicates}, Уникальных: {len(all_keys)}")
    
    return all_keys


# ==================== ПАРСЕРЫ ====================
def extract_host_port(key: str) -> Tuple[Optional[str], Optional[int]]:
    try:
        key = key.strip()
        
        if key.lower().startswith("vmess://"):
            encoded = key[8:]
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            data = json.loads(base64.b64decode(encoded).decode('utf-8'))
            return data.get("add"), int(data.get("port", 443))
        
        for prefix in ["vless://", "trojan://", "ss://"]:
            if key.lower().startswith(prefix):
                key = key[len(prefix):]
                break
        
        if "@" in key:
            key = key.split("@", 1)[1]
        if "?" in key:
            key = key.split("?")[0]
        if "#" in key:
            key = key.split("#")[0]
        
        if ":" in key:
            host, port = key.rsplit(":", 1)
            return host.strip("[]"), int(port)
        
        return None, None
    except:
        return None, None


def parse_key_to_config(key: str) -> Tuple[Optional[Dict], str]:
    key_lower = key.lower()
    
    try:
        if key_lower.startswith("vless://"):
            return parse_vless(key), "VLESS"
        elif key_lower.startswith("vmess://"):
            return parse_vmess(key), "VMess"
        elif key_lower.startswith("trojan://"):
            return parse_trojan(key), "Trojan"
        elif key_lower.startswith("ss://"):
            return parse_shadowsocks(key), "SS"
    except:
        pass
    
    return None, ""


def parse_vless(key: str) -> Optional[Dict]:
    key = key[8:]
    if "@" not in key:
        return None
    
    uuid_part, rest = key.split("@", 1)
    server_part = rest.split("?")[0].split("#")[0]
    
    if ":" not in server_part:
        return None
    
    host, port = server_part.rsplit(":", 1)
    host = host.strip("[]")
    
    params = {}
    if "?" in rest:
        for param in rest.split("?")[1].split("#")[0].split("&"):
            if "=" in param:
                k, v = param.split("=", 1)
                params[k] = unquote(v)
    
    config = {
        "protocol": "vless",
        "settings": {
            "vnext": [{
                "address": host,
                "port": int(port),
                "users": [{"id": uuid_part, "encryption": "none", "flow": params.get("flow", "")}]
            }]
        },
        "streamSettings": {
            "network": params.get("type", "tcp"),
            "security": params.get("security", "none")
        }
    }
    
    if params.get("security") == "tls":
        config["streamSettings"]["tlsSettings"] = {
            "serverName": params.get("sni", host),
            "allowInsecure": True,
            "fingerprint": params.get("fp", "chrome")
        }
    elif params.get("security") == "reality":
        config["streamSettings"]["realitySettings"] = {
            "serverName": params.get("sni", host),
            "publicKey": params.get("pbk", ""),
            "shortId": params.get("sid", ""),
            "fingerprint": params.get("fp", "chrome")
        }
    
    if params.get("type") == "ws":
        config["streamSettings"]["wsSettings"] = {"path": params.get("path", "/"), "headers": {"Host": params.get("host", host)}}
    elif params.get("type") == "grpc":
        config["streamSettings"]["grpcSettings"] = {"serviceName": params.get("serviceName", "")}
    
    return config


def parse_vmess(key: str) -> Optional[Dict]:
    encoded = key[8:]
    padding = len(encoded) % 4
    if padding:
        encoded += '=' * (4 - padding)
    
    data = json.loads(base64.b64decode(encoded).decode('utf-8'))
    host = data.get("add", "")
    port = int(data.get("port", 443))
    
    config = {
        "protocol": "vmess",
        "settings": {
            "vnext": [{
                "address": host,
                "port": port,
                "users": [{"id": data.get("id"), "alterId": int(data.get("aid", 0)), "security": "auto"}]
            }]
        },
        "streamSettings": {
            "network": data.get("net", "tcp"),
            "security": data.get("tls", "none") if data.get("tls") else "none"
        }
    }
    
    if data.get("tls") == "tls":
        config["streamSettings"]["tlsSettings"] = {"serverName": data.get("sni", host), "allowInsecure": True}
    
    if data.get("net") == "ws":
        config["streamSettings"]["wsSettings"] = {"path": data.get("path", "/"), "headers": {"Host": data.get("host", host)}}
    
    return config


def parse_trojan(key: str) -> Optional[Dict]:
    key = key[9:]
    if "@" not in key:
        return None
    
    password, rest = key.split("@", 1)
    password = unquote(password)
    server_part = rest.split("?")[0].split("#")[0]
    
    if ":" not in server_part:
        return None
    
    host, port = server_part.rsplit(":", 1)
    host = host.strip("[]")
    
    params = {}
    if "?" in rest:
        for param in rest.split("?")[1].split("#")[0].split("&"):
            if "=" in param:
                k, v = param.split("=", 1)
                params[k] = unquote(v)
    
    config = {
        "protocol": "trojan",
        "settings": {"servers": [{"address": host, "port": int(port), "password": password}]},
        "streamSettings": {"network": params.get("type", "tcp"), "security": "tls"}
    }
    
    config["streamSettings"]["tlsSettings"] = {
        "serverName": params.get("sni", host),
        "allowInsecure": True,
        "fingerprint": params.get("fp", "chrome")
    }
    
    if params.get("type") == "ws":
        config["streamSettings"]["wsSettings"] = {"path": params.get("path", "/"), "headers": {"Host": params.get("host", host)}}
    
    return config


def parse_shadowsocks(key: str) -> Optional[Dict]:
    key = key[5:].split("#")[0]
    
    if "@" in key:
        encoded, server = key.split("@", 1)
        host, port = server.rsplit(":", 1)
        host = host.strip("[]")
        
        padding = len(encoded) % 4
        if padding:
            encoded += '=' * (4 - padding)
        
        try:
            decoded = base64.b64decode(encoded).decode('utf-8')
            method, password = decoded.split(":", 1)
        except:
            method, password = encoded.split(":", 1)
    else:
        padding = len(key) % 4
        if padding:
            key += '=' * (4 - padding)
        decoded = base64.b64decode(key).decode('utf-8')
        creds, server = decoded.rsplit("@", 1)
        method, password = creds.split(":", 1)
        host, port = server.rsplit(":", 1)
        host = host.strip("[]")
    
    return {
        "protocol": "shadowsocks",
        "settings": {"servers": [{"address": host, "port": int(port), "method": method, "password": password}]},
        "streamSettings": {"network": "tcp"}
    }


# ==================== TCP ====================
def tcp_check(key: str) -> Optional[str]:
    host, port = extract_host_port(key)
    if not host or not port:
        record_error("parse_error")
        return None
    
    for attempt in range(CONFIG.TCP_RETRIES + 1):
        try:
            with socket.create_connection((host, port), timeout=CONFIG.TCP_TIMEOUT):
                return key
        except socket.timeout:
            record_error("tcp_timeout")
        except ConnectionRefusedError:
            record_error("tcp_refused")
            break
        except socket.gaierror:
            record_error("dns_error")
            break
        except:
            record_error("tcp_other")
            break
        
        if attempt < CONFIG.TCP_RETRIES:
            time.sleep(0.3)
    
    return None


# ==================== XRAY FULL CHECK (3 СЕССИИ) ====================
def xray_full_check(key: str, xray_exe: Path) -> CheckResult:
    """
    3 запуска Xray:
    1. Main session: Latency (5 замеров) + Categories (7 сайтов)
    2. Reconnect test #1
    3. Reconnect test #2
    """
    
    proxy_config, protocol = parse_key_to_config(key)
    if not proxy_config:
        return CheckResult(key=key, alive=False, error="parse_error")
    
    # Host/port для логов
    if protocol in ["VLESS", "VMess"]:
        host = proxy_config["settings"]["vnext"][0]["address"]
        port = proxy_config["settings"]["vnext"][0]["port"]
    else:
        host = proxy_config["settings"]["servers"][0]["address"]
        port = proxy_config["settings"]["servers"][0]["port"]
    
    # ============================================
    # СЕССИЯ 1: Latency + Categories
    # ============================================
    latencies: List[float] = []
    categories_passed = 0
    telegram_works = False
    
    with run_xray_session(xray_exe, proxy_config, CONFIG.XRAY_STARTUP) as session:
        if not session.ok:
            return CheckResult(key=key, alive=False, error="xray_startup_1",
                             protocol=protocol, host=host, port=port)
        
        # Latency test
        for i in range(CONFIG.LATENCY_SAMPLES):
            url = CONFIG.CHECK_URLS[i % len(CONFIG.CHECK_URLS)]
            try:
                t1 = time.time()
                resp = requests.get(url, proxies=session.proxies, timeout=CONFIG.XRAY_TIMEOUT, allow_redirects=False)
                if resp.status_code in [200, 204]:
                    latencies.append((time.time() - t1) * 1000)
            except:
                pass
            time.sleep(0.1)
        
        if len(latencies) < CONFIG.MIN_LATENCY_SUCCESS:
            return CheckResult(key=key, alive=False, error="latency_fail",
                             protocol=protocol, host=host, port=port)
        
        # Categories test
        for url, name in CONFIG.CATEGORY_URLS:
            try:
                resp = requests.get(url, proxies=session.proxies, timeout=10, allow_redirects=True)
                if resp.status_code < 500:
                    categories_passed += 1
                    if name == "telegram":
                        telegram_works = True
            except:
                pass
    
    avg_latency = mean(latencies)
    jitter = stdev(latencies) if len(latencies) > 1 else 0
    
    # ============================================
    # СЕССИИ 2-3: Reconnect tests
    # ============================================
    reconnect_success = 0
    
    for i in range(CONFIG.RECONNECT_TESTS):
        # Пауза между reconnect (имитация реального использования)
        time.sleep(0.5)
        
        with run_xray_session(xray_exe, proxy_config, CONFIG.XRAY_STARTUP_QUICK) as session:
            if not session.ok:
                continue
            
            # Быстрая проверка connectivity
            try:
                url = random.choice(CONFIG.CHECK_URLS)
                resp = requests.get(url, proxies=session.proxies, timeout=8, allow_redirects=False)
                if resp.status_code in [200, 204]:
                    reconnect_success += 1
            except:
                pass
    
    # Проверяем reconnect stability
    if reconnect_success < CONFIG.MIN_RECONNECT_SUCCESS:
        return CheckResult(
            key=key, alive=False, error="reconnect_fail",
            protocol=protocol, host=host, port=port,
            latency=round(avg_latency, 1), jitter=round(jitter, 1),
            reconnect_success=reconnect_success, categories=categories_passed
        )
    
    # ============================================
    # Определение качества
    # ============================================
    quality = None
    
    for q in [Quality.ELITE, Quality.PREMIUM, Quality.GOOD]:
        thresh = QUALITY_THRESHOLDS[q]
        if (avg_latency <= thresh.latency_max and
            jitter <= thresh.jitter_max and
            categories_passed >= thresh.categories_min):
            quality = q
            break
    
    if quality is None:
        return CheckResult(
            key=key, alive=False, error="below_threshold",
            protocol=protocol, host=host, port=port,
            latency=round(avg_latency, 1), jitter=round(jitter, 1),
            reconnect_success=reconnect_success, categories=categories_passed
        )
    
    return CheckResult(
        key=key,
        alive=True,
        latency=round(avg_latency, 1),
        jitter=round(jitter, 1),
        reconnect_success=reconnect_success,
        categories=categories_passed,
        telegram=telegram_works,
        quality=quality,
        protocol=protocol,
        host=host,
        port=port
    )


# ==================== СОХРАНЕНИЕ ====================
def save_results(results: List[CheckResult]):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    
    by_quality: Dict[Quality, List[CheckResult]] = defaultdict(list)
    for r in results:
        if r.alive and r.quality:
            by_quality[r.quality].append(r)
    
    for quality in Quality:
        items = by_quality.get(quality, [])
        if not items:
            continue
        
        items.sort(key=lambda x: x.latency)
        filename = PREMIUM_FOLDER / f"{quality.value}.txt"
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {quality.value.upper()}\n")
            f.write(f"# {MY_CHANNEL}\n")
            f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# Ключей: {len(items)}\n\n")
            
            for r in items:
                tg = "TG+" if r.telegram else ""
                comment = f"[{r.latency:.0f}ms|j{r.jitter:.0f}|rc{r.reconnect_success}/{CONFIG.RECONNECT_TESTS}|{r.categories}cat|{tg}{r.protocol}|{MY_CHANNEL}]"
                base_key = r.key.split('#')[0]
                f.write(f"{base_key}#{quote(comment)}\n")
        
        log(f"💾 {quality.value.upper()}: {len(items)} → {filename.name}")
    
    # Общий файл
    all_results = [r for r in results if r.alive]
    all_results.sort(key=lambda x: x.latency)
    
    verified_file = RESULTS_FOLDER / f"verified_{timestamp}.txt"
    
    with open(verified_file, 'w', encoding='utf-8') as f:
        f.write(f"# {MY_CHANNEL}\n")
        f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Рабочих: {len(all_results)}\n")
        f.write(f"# Метод: TCP + XRAY×3 (Latency+Jitter+Reconnect+Categories)\n\n")
        
        for r in all_results:
            comment = f"{r.quality.value.upper()} {r.latency:.0f}ms {r.protocol} {MY_CHANNEL}"
            f.write(f"{r.key.split('#')[0]}#{quote(comment)}\n")
    
    log(f"💾 Общий: {len(all_results)} → {verified_file.name}")


# ==================== MAIN ====================
def main():
    print("\n" + "=" * 70)
    print(" " * 10 + "🔥 UNIFIED VPN CHECKER v2.1 OPTIMAL 🔥")
    print(" " * 5 + "3 сессии: Latency+Categories → Reconnect×2")
    print(" " * 20 + f"Канал: {MY_CHANNEL}")
    print("=" * 70)
    
    print(f"\n⚙️  Настройки:")
    print(f"   TCP: {CONFIG.TCP_WORKERS} workers")
    print(f"   XRAY: {CONFIG.XRAY_WORKERS} workers")
    print(f"   Latency samples: {CONFIG.LATENCY_SAMPLES}")
    print(f"   Reconnect tests: {CONFIG.RECONNECT_TESTS}")
    print(f"   Categories: {len(CONFIG.CATEGORY_URLS)}")
    print()
    print(f"📊 Качество:")
    for q in Quality:
        t = QUALITY_THRESHOLDS[q]
        print(f"   {q.value.upper()}: lat≤{t.latency_max}ms, jit≤{t.jitter_max}ms, cat≥{t.categories_min}")
    print()
    
    xray_exe = setup_xray()
    if not xray_exe:
        return 1
    
    all_keys = download_and_deduplicate()
    if not all_keys:
        return 1
    
    # TCP
    print("\n" + "=" * 70)
    log(f"⚡ ЭТАП 1: TCP ({CONFIG.TCP_WORKERS} workers)")
    print("=" * 70 + "\n")
    
    tcp_start = time.time()
    tcp_passed: List[str] = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.TCP_WORKERS) as executor:
        futures = {executor.submit(tcp_check, key): key for key in all_keys}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            if done % CONFIG.GC_EVERY == 0:
                cleanup_memory()
                log(f"[{done}/{len(all_keys)}] TCP alive: {len(tcp_passed)}")
            try:
                result = future.result(timeout=30)
                if result:
                    tcp_passed.append(result)
                    stats.tcp_passed += 1
                else:
                    stats.tcp_failed += 1
            except:
                stats.tcp_failed += 1
    
    tcp_time = time.time() - tcp_start
    log(f"\n✅ TCP: {len(tcp_passed)}/{len(all_keys)} за {tcp_time:.1f}с")
    
    if not tcp_passed:
        return 1
    
    # XRAY
    print("\n" + "=" * 70)
    log(f"⚡ ЭТАП 2: XRAY×3 ({CONFIG.XRAY_WORKERS} workers)")
    log(f"   Session 1: Latency({CONFIG.LATENCY_SAMPLES}) + Categories({len(CONFIG.CATEGORY_URLS)})")
    log(f"   Sessions 2-3: Reconnect tests")
    print("=" * 70 + "\n")
    
    xray_start = time.time()
    results: List[CheckResult] = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.XRAY_WORKERS) as executor:
        futures = {executor.submit(xray_full_check, key, xray_exe): key for key in tcp_passed}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            if done % 10 == 0:
                cleanup_memory()
            try:
                result = future.result(timeout=120)
                if result.alive:
                    results.append(result)
                    stats.xray_passed += 1
                    stats.by_quality[result.quality] += 1
                    
                    tg = " 📱" if result.telegram else ""
                    log(f"[{done}/{len(tcp_passed)}] ✓ {result.quality.value.upper():>7} | "
                        f"{result.latency:>5.0f}ms j{result.jitter:>3.0f} | "
                        f"rc:{result.reconnect_success}/{CONFIG.RECONNECT_TESTS} | "
                        f"{result.categories}cat{tg}")
                else:
                    stats.xray_failed += 1
                    if result.error:
                        record_error(result.error)
            except:
                stats.xray_failed += 1
                record_error("future_exception")
    
    xray_time = time.time() - xray_start
    total_time = time.time() - stats.start_time
    
    if results:
        save_results(results)
    
    # Статистика
    print("\n" + "=" * 70)
    print("📊 ИТОГИ")
    print("=" * 70)
    print(f"   Уникальных: {stats.unique} (дубли: {stats.duplicates})")
    print(f"   TCP: {stats.tcp_passed} ({stats.tcp_passed*100//stats.unique}%)")
    print(f"   XRAY: {stats.xray_passed} ({stats.xray_passed*100//max(stats.tcp_passed,1)}%)")
    print()
    print(f"🏆 Качество:")
    for q in Quality:
        count = stats.by_quality.get(q, 0)
        if count > 0:
            print(f"   {q.value.upper()}: {count}")
    print()
    print(f"⏱️  TCP={tcp_time:.1f}с, XRAY={xray_time:.1f}с, ВСЕГО={total_time/60:.1f}мин")
    
    if stats.errors:
        print("\n📊 Причины отсева:")
        for error, count in sorted(stats.errors.items(), key=lambda x: -x[1])[:5]:
            print(f"   {error}: {count}")
    
    print("=" * 70)
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\n⚠️ Прервано")
        cleanup_all_processes()
        exit_code = 1
    except Exception as e:
        print(f"\n❌ {e}")
        import traceback
        traceback.print_exc()
        cleanup_all_processes()
        exit_code = 1
    
    sys.exit(exit_code)
