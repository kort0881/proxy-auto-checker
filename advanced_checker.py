#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Proxy Checker v6.2 FINAL
TCP pre-filter + Xray + REAL site checks + quality filters
Output: checked/latest/verified.txt
"""

import os
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
import argparse
import logging
import zipfile
import platform
from datetime import datetime
from urllib.parse import quote, unquote
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from logging.handlers import RotatingFileHandler

# ==================== PATHS ====================
WORK_DIR = Path(__file__).parent.absolute()
XRAY_FOLDER = WORK_DIR / "xray"
RESULTS_FOLDER = WORK_DIR / "results"
CHECKED_FOLDER = WORK_DIR / "checked" / "latest"
VERIFIED_FILE = CHECKED_FOLDER / "verified.txt"
STATS_FILE = RESULTS_FOLDER / "stats_latest.json"
LOG_FILE = RESULTS_FOLDER / "checker.log"

for d in [XRAY_FOLDER, RESULTS_FOLDER, CHECKED_FOLDER]:
    d.mkdir(parents=True, exist_ok=True)

# ==================== SOURCES ====================
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
        "https://raw.githubusercontent.com/mshojaei77/v2rayAuto/main/mix",
    ],
}

MY_CHANNEL = "@vlesstrojan"


# ==================== CONFIG ====================
@dataclass
class Config:
    # --- Stage 1: TCP ---
    TCP_WORKERS: int = 100
    TCP_TIMEOUT: float = 3.0
    TCP_ATTEMPTS: int = 2

    # --- Stage 2: Xray ---
    XRAY_WORKERS: int = 8
    XRAY_STARTUP: float = 4.0
    XRAY_QUICK_TIMEOUT: int = 6
    XRAY_LATENCY_TIMEOUT: int = 8
    LATENCY_SAMPLES: int = 3
    MIN_LATENCY_SUCCESS: int = 2

    # --- Categories: РЕАЛЬНАЯ проверка сайтов ---
    CATEGORY_URLS: List[Tuple[str, str, str]] = field(default_factory=lambda: [
        ("https://www.google.com", "google", "google"),
        ("https://web.telegram.org", "telegram", "telegram"),
        ("https://www.youtube.com", "youtube", "youtube"),
        ("https://vk.com", "vk", "vk"),
        ("https://www.instagram.com", "instagram", "instagram"),
        ("https://twitter.com", "twitter", "twitter"),
        ("https://www.tiktok.com", "tiktok", "tiktok"),
    ])
    CATEGORY_TIMEOUT: int = 10
    CATEGORY_PARALLEL: int = 7
    CATEGORY_AS_COMPLETED_TIMEOUT: int = 15
    MIN_CATEGORIES: int = 5
    REQUIRE_TELEGRAM: bool = True
    VERIFY_CONTENT: bool = False

    # --- Quality filters (НОВОЕ) ---
    MAX_JITTER: float = 500.0      # мс — если больше, дропаем (отсеивает j2573)
    MAX_LATENCY: float = 2000.0    # мс — если больше, дропаем (медленные)

    # --- Защита от таймаута (НОВОЕ) ---
    MAX_KEYS: int = 3000           # макс. ключей на входе

    # --- Reconnect ---
    RECONNECT_TESTS: int = 1
    MIN_RECONNECT_SUCCESS: int = 1

    # --- Mutations ---
    MAX_MUTATIONS: int = 1

    # --- Misc ---
    GC_EVERY: int = 50
    MAX_RUNTIME_MIN: int = 55


CONFIG = Config()


@dataclass
class CheckResult:
    key: str
    alive: bool
    latency: float = 0.0
    jitter: float = 0.0
    reconnect_success: int = 0
    categories: int = 0
    telegram: bool = False
    protocol: str = ""
    host: str = ""
    port: int = 0
    security: str = ""
    error: Optional[str] = None
    mutation_used: str = ""


@dataclass
class Stats:
    total_downloaded: int = 0
    duplicates: int = 0
    unique: int = 0
    tcp_passed: int = 0
    tcp_failed: int = 0
    quick_passed: int = 0
    quick_failed: int = 0
    xray_passed: int = 0
    xray_failed: int = 0
    by_protocol: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    mutations_tried: int = 0
    mutations_success: int = 0
    start_time: float = field(default_factory=time.time)


stats = Stats()
stats_lock = threading.Lock()


def record_error(error: str):
    with stats_lock:
        stats.errors[error] += 1


# ==================== LOGGING ====================
def setup_logging():
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=1)
    handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
    logger = logging.getLogger('ProxyChecker')
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        logger.addHandler(handler)
    return logger


file_logger = setup_logging()


def log(msg: str):
    print(msg, flush=True)
    file_logger.info(msg)


def cleanup_memory():
    gc.collect()


# ==================== PROCESS MANAGEMENT ====================
_active_processes: List[subprocess.Popen] = []
_processes_lock = threading.Lock()
_shutdown = threading.Event()


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
            except Exception:
                pass
        _active_processes.clear()


atexit.register(cleanup_all_processes)


def signal_handler(signum, frame):
    print("\n[STOP] Interrupted", flush=True)
    _shutdown.set()
    cleanup_all_processes()
    sys.exit(1)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def time_exceeded() -> bool:
    return (time.time() - stats.start_time) / 60.0 >= CONFIG.MAX_RUNTIME_MIN


# ==================== XRAY SETUP ====================
def setup_xray() -> Optional[Path]:
    exe_name = "xray.exe" if os.name == 'nt' else "xray"
    exe_path = XRAY_FOLDER / exe_name

    if exe_path.exists():
        log(f"[OK] Local Xray found")
        if os.name != 'nt':
            try:
                exe_path.chmod(0o755)
            except Exception:
                pass
        return exe_path

    log("[DL] Downloading xray-core...")
    try:
        system = platform.system().lower()
        machine = platform.machine().lower()

        if system == "windows":
            arch = "64" if "64" in machine else "32"
            filename = f"Xray-windows-{arch}.zip"
        elif system == "linux":
            arch = "arm64-v8a" if ("aarch64" in machine or "arm64" in machine) else "64"
            filename = f"Xray-linux-{arch}.zip"
        elif system == "darwin":
            arch = "arm64-v8a" if "arm" in machine else "64"
            filename = f"Xray-macos-{arch}.zip"
        else:
            log(f"[ERR] Unsupported platform: {system}")
            return None

        url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{filename}"
        r = requests.get(url, stream=True, timeout=120)
        r.raise_for_status()

        zip_path = XRAY_FOLDER / "xray.zip"
        with open(zip_path, 'wb') as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)

        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(XRAY_FOLDER)
        zip_path.unlink()

        if system != "windows":
            exe_path.chmod(0o755)

        log("[OK] Xray installed")
        return exe_path
    except Exception as e:
        log(f"[ERR] Xray setup: {e}")
        return None


# ==================== PARSERS ====================
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
            key = key.split("?", 1)[0]
        if "#" in key:
            key = key.split("#", 1)[0]

        if ":" in key:
            host, port = key.rsplit(":", 1)
            return host.strip("[]"), int(port)
        return None, None
    except Exception:
        return None, None


def parse_key_to_config(key: str) -> Tuple[Optional[Dict], str, str]:
    key_lower = key.lower()
    security = "none"
    if "security=reality" in key_lower:
        security = "reality"
    elif "security=tls" in key_lower:
        security = "tls"

    try:
        if key_lower.startswith("vless://"):
            return parse_vless(key), "VLESS", security
        elif key_lower.startswith("vmess://"):
            return parse_vmess(key), "VMess", security
        elif key_lower.startswith("trojan://"):
            return parse_trojan(key), "Trojan", security
        elif key_lower.startswith("ss://"):
            return parse_shadowsocks(key), "SS", security
    except Exception:
        pass
    return None, "", security


def parse_vless(key: str) -> Optional[Dict]:
    try:
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
                    "users": [{
                        "id": uuid_part,
                        "encryption": "none",
                        "flow": params.get("flow", "")
                    }]
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
                "fingerprint": params.get("fp", "chrome"),
                "spiderX": params.get("spx", "")
            }

        net = params.get("type", "tcp")
        if net == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)}
            }
        elif net == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": params.get("serviceName", "")
            }
        elif net == "tcp" and params.get("headerType") == "http":
            config["streamSettings"]["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "version": "1.1",
                        "method": "GET",
                        "path": [params.get("path", "/")],
                        "headers": {"Host": [params.get("host", host)]}
                    }
                }
            }
        elif net == "h2":
            config["streamSettings"]["httpSettings"] = {
                "host": [params.get("host", host)],
                "path": params.get("path", "/")
            }
        elif net == "xhttp":
            config["streamSettings"]["xhttpSettings"] = {
                "path": params.get("path", "/")
            }

        return config
    except Exception:
        return None


def parse_vmess(key: str) -> Optional[Dict]:
    try:
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
                    "users": [{
                        "id": data.get("id"),
                        "alterId": int(data.get("aid", 0)),
                        "security": "auto"
                    }]
                }]
            },
            "streamSettings": {
                "network": data.get("net", "tcp"),
                "security": data.get("tls", "none") if data.get("tls") else "none"
            }
        }

        if data.get("tls") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": data.get("sni", host),
                "allowInsecure": True
            }

        net = data.get("net", "tcp")
        if net == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": data.get("path", "/"),
                "headers": {"Host": data.get("host", host)}
            }
        elif net == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": data.get("path", "")
            }

        return config
    except Exception:
        return None


def parse_trojan(key: str) -> Optional[Dict]:
    try:
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
            "settings": {
                "servers": [{
                    "address": host,
                    "port": int(port),
                    "password": password
                }]
            },
            "streamSettings": {
                "network": params.get("type", "tcp"),
                "security": "tls",
                "tlsSettings": {
                    "serverName": params.get("sni", host),
                    "allowInsecure": True,
                    "fingerprint": params.get("fp", "chrome")
                }
            }
        }

        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)}
            }
        return config
    except Exception:
        return None


def parse_shadowsocks(key: str) -> Optional[Dict]:
    try:
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
            except Exception:
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
            "settings": {
                "servers": [{
                    "address": host,
                    "port": int(port),
                    "method": method,
                    "password": password
                }]
            },
            "streamSettings": {"network": "tcp"}
        }
    except Exception:
        return None


# ==================== DOWNLOAD ====================
def download_and_deduplicate(sources: Dict[str, List[str]] = None) -> List[str]:
    if sources is None:
        sources = KEY_SOURCES

    all_keys = []
    seen = set()
    duplicates = 0

    log("[DL] Downloading keys...")

    for region, urls in sources.items():
        log(f"  Region: {region}")
        for url in urls:
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                content = r.text.strip()
            except Exception as e:
                log(f"    FAIL {url.split('/')[-1]}: {e}")
                continue

            count = 0
            for line in content.split('\n'):
                line = html.unescape(line.strip())
                if not line or not line.lower().startswith(("vless://", "vmess://", "trojan://", "ss://")):
                    continue
                normalized = line.split("#")[0].strip()
                if normalized in seen:
                    duplicates += 1
                    continue
                seen.add(normalized)
                all_keys.append(line)
                count += 1

            stats.total_downloaded += count
            log(f"    {url.split('/')[-1]}: {count}")

    stats.duplicates = duplicates

    # ⬇️ НОВОЕ: защита от таймаута
    if len(all_keys) > CONFIG.MAX_KEYS:
        log(f"[WARN] Too many keys ({len(all_keys)}), limiting to {CONFIG.MAX_KEYS}")
        random.shuffle(all_keys)
        all_keys = all_keys[:CONFIG.MAX_KEYS]

    stats.unique = len(all_keys)
    log(f"  Total: {stats.total_downloaded + duplicates} | Dupes: {duplicates} | Unique: {len(all_keys)}")
    return all_keys


# ==================== TCP PRE-FILTER ====================
def tcp_prefilter(key: str) -> Optional[str]:
    host, port = extract_host_port(key)
    if not host or not port:
        record_error("parse_error")
        return None

    for attempt in range(CONFIG.TCP_ATTEMPTS):
        if _shutdown.is_set() or time_exceeded():
            return None
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
        except Exception:
            record_error("tcp_other")
            break
        if attempt < CONFIG.TCP_ATTEMPTS - 1:
            time.sleep(0.2)
    return None


# ==================== XRAY SESSION ====================
def wait_for_port(port: int, timeout: float) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _shutdown.is_set():
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return True
        except Exception:
            time.sleep(0.05)
    return False


def find_free_port() -> int:
    for _ in range(30):
        port = random.randint(20000, 50000)
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    raise RuntimeError("No free port")


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


class XraySession:
    def __init__(self, xray_exe: Path, proxy_config: Dict, startup: float):
        self.xray_exe = xray_exe
        self.proxy_config = proxy_config
        self.startup = startup
        self.process = None
        self.port = find_free_port()
        self.config_file = XRAY_FOLDER / f"cfg_{self.port}_{os.getpid()}_{threading.get_ident()}.json"
        self.http_session = None
        self.ok = False

    def __enter__(self):
        try:
            with open(self.config_file, 'w') as f:
                json.dump(create_xray_config(self.proxy_config, self.port), f)

            self.process = subprocess.Popen(
                [str(self.xray_exe), "run", "-c", str(self.config_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            register_process(self.process)

            if wait_for_port(self.port, self.startup) and self.process.poll() is None:
                self.http_session = requests.Session()
                self.http_session.proxies = {
                    'http': f'http://127.0.0.1:{self.port}',
                    'https': f'http://127.0.0.1:{self.port}'
                }
                self.http_session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=10, pool_maxsize=10, max_retries=0
                )
                self.http_session.mount('http://', adapter)
                self.http_session.mount('https://', adapter)
                self.ok = True
        except Exception:
            pass
        return self

    def get(self, url: str, timeout: int, allow_redirects: bool = True):
        if not self.ok or not self.http_session:
            return None
        try:
            return self.http_session.get(url, timeout=timeout, allow_redirects=allow_redirects)
        except Exception:
            return None

    def __exit__(self, *args):
        if self.http_session:
            try:
                self.http_session.close()
            except Exception:
                pass
        if self.process:
            unregister_process(self.process)
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except Exception:
                try:
                    self.process.kill()
                    self.process.wait(timeout=1)
                except Exception:
                    pass
        for _ in range(3):
            try:
                self.config_file.unlink()
                break
            except FileNotFoundError:
                break
            except Exception:
                time.sleep(0.1)


# ==================== CATEGORIES: РЕАЛЬНАЯ ПРОВЕРКА ====================
def check_one_category(session: XraySession, url: str, name: str, keyword: str) -> Tuple[str, bool]:
    try:
        resp = session.get(url, timeout=CONFIG.CATEGORY_TIMEOUT, allow_redirects=True)
        if not resp:
            return (name, False)

        if not (200 <= resp.status_code < 400):
            return (name, False)

        if CONFIG.VERIFY_CONTENT:
            try:
                content = resp.text[:50000].lower()
                if keyword.lower() not in content:
                    return (name, False)
            except Exception:
                pass

        return (name, True)
    except Exception:
        return (name, False)


def check_categories_parallel(session: XraySession) -> Tuple[int, bool]:
    passed = 0
    telegram_ok = False
    futures_map = {}

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.CATEGORY_PARALLEL)
    try:
        for url, name, keyword in CONFIG.CATEGORY_URLS:
            futures_map[executor.submit(check_one_category, session, url, name, keyword)] = name

        try:
            for future in concurrent.futures.as_completed(
                futures_map, timeout=CONFIG.CATEGORY_AS_COMPLETED_TIMEOUT
            ):
                try:
                    name, success = future.result(timeout=1)
                    if success:
                        passed += 1
                        if name == "telegram":
                            telegram_ok = True
                except Exception:
                    pass
        except concurrent.futures.TimeoutError:
            for f in futures_map:
                f.cancel()
    finally:
        executor.shutdown(wait=False, cancel_futures=True)

    return passed, telegram_ok


# ==================== MUTATIONS ====================
def safe_mutate(proxy_config: Dict) -> Tuple[Dict, str]:
    mutated = json.loads(json.dumps(proxy_config))
    stream = mutated.get('streamSettings', {})
    fps = ['chrome', 'firefox', 'safari', 'edge', 'ios', 'android', 'random']
    for key in ('tlsSettings', 'realitySettings'):
        if key in stream:
            old = stream[key].get('fingerprint', 'chrome')
            new = random.choice([f for f in fps if f != old])
            stream[key]['fingerprint'] = new
            return mutated, f"FP_{new}"
    return mutated, ""


# ==================== TWO-PHASE XRAY CHECK ====================
def xray_full_check(key: str, xray_exe: Path) -> CheckResult:
    proxy_config, protocol, security = parse_key_to_config(key)
    if not proxy_config:
        return CheckResult(key=key, alive=False, error="parse_error")

    host, port = extract_host_port(key)

    result = _two_phase_test(key, proxy_config, protocol, security, xray_exe, host, port)
    if result.alive:
        return result

    if CONFIG.MAX_MUTATIONS >= 1 and result.error != "quick_fail":
        mutated_config, mutation_name = safe_mutate(proxy_config)
        if mutation_name:
            with stats_lock:
                stats.mutations_tried += 1
            mut_result = _two_phase_test(
                key, mutated_config, protocol, security, xray_exe, host, port
            )
            if mut_result.alive:
                mut_result.mutation_used = mutation_name
                with stats_lock:
                    stats.mutations_success += 1
                return mut_result

    return result


def _two_phase_test(
    key: str, proxy_config: Dict, protocol: str, security: str,
    xray_exe: Path, host: str, port: int
) -> CheckResult:
    latencies: List[float] = []
    categories_passed = 0
    telegram_works = False

    with XraySession(xray_exe, proxy_config, CONFIG.XRAY_STARTUP) as session:
        if not session.ok:
            return CheckResult(
                key=key, alive=False, error="xray_startup",
                protocol=protocol, host=host, port=port, security=security
            )

        # PHASE A: quick check
        quick_ok = False
        try:
            t1 = time.time()
            resp = session.get("https://cp.cloudflare.com/generate_204",
                               timeout=CONFIG.XRAY_QUICK_TIMEOUT,
                               allow_redirects=False)
            if resp and resp.status_code in (200, 204):
                latencies.append((time.time() - t1) * 1000)
                quick_ok = True
                with stats_lock:
                    stats.quick_passed += 1
        except Exception:
            pass

        if not quick_ok:
            with stats_lock:
                stats.quick_failed += 1
            return CheckResult(
                key=key, alive=False, error="quick_fail",
                protocol=protocol, host=host, port=port, security=security
            )

        # PHASE B: latency samples
        urls = [
            "https://cp.cloudflare.com/generate_204",
            "http://www.gstatic.com/generate_204",
        ]
        for i in range(CONFIG.LATENCY_SAMPLES - 1):
            if _shutdown.is_set() or time_exceeded():
                break
            url = urls[(i + 1) % len(urls)]
            try:
                t1 = time.time()
                resp = session.get(url, timeout=CONFIG.XRAY_LATENCY_TIMEOUT, allow_redirects=False)
                if resp and resp.status_code in (200, 204):
                    latencies.append((time.time() - t1) * 1000)
            except Exception:
                pass
            time.sleep(0.1)

        if len(latencies) < CONFIG.MIN_LATENCY_SUCCESS:
            return CheckResult(
                key=key, alive=False, error="latency_fail",
                protocol=protocol, host=host, port=port, security=security
            )

        # PHASE C: РЕАЛЬНАЯ проверка категорий
        categories_passed, telegram_works = check_categories_parallel(session)

    avg_latency = sum(latencies) / len(latencies)
    jitter = max(latencies) - min(latencies)

    # ⬇️ НОВОЕ: фильтр по latency и jitter
    if avg_latency > CONFIG.MAX_LATENCY:
        return CheckResult(
            key=key, alive=False, error=f"latency_{avg_latency:.0f}",
            protocol=protocol, host=host, port=port, security=security,
            latency=round(avg_latency, 1), jitter=round(jitter, 1),
            categories=categories_passed, telegram=telegram_works
        )

    if jitter > CONFIG.MAX_JITTER:
        return CheckResult(
            key=key, alive=False, error=f"jitter_{jitter:.0f}",
            protocol=protocol, host=host, port=port, security=security,
            latency=round(avg_latency, 1), jitter=round(jitter, 1),
            categories=categories_passed, telegram=telegram_works
        )

    # PHASE D: reconnect test
    reconnect_success = 0
    with XraySession(xray_exe, proxy_config, CONFIG.XRAY_STARTUP) as rs:
        if rs.ok:
            time.sleep(0.3)
            resp = rs.get(random.choice(urls), timeout=6, allow_redirects=False)
            if resp and resp.status_code in (200, 204):
                reconnect_success = 1

    if reconnect_success < CONFIG.MIN_RECONNECT_SUCCESS:
        return CheckResult(
            key=key, alive=False, error="reconnect_fail",
            protocol=protocol, host=host, port=port, security=security,
            latency=round(avg_latency, 1), jitter=round(jitter, 1),
            reconnect_success=reconnect_success,
            categories=categories_passed, telegram=telegram_works
        )

    if categories_passed < CONFIG.MIN_CATEGORIES:
        return CheckResult(
            key=key, alive=False, error=f"only_{categories_passed}_cats",
            protocol=protocol, host=host, port=port, security=security,
            latency=round(avg_latency, 1), jitter=round(jitter, 1),
            reconnect_success=reconnect_success,
            categories=categories_passed, telegram=telegram_works
        )

    if CONFIG.REQUIRE_TELEGRAM and not telegram_works:
        return CheckResult(
            key=key, alive=False, error="no_telegram",
            protocol=protocol, host=host, port=port, security=security,
            latency=round(avg_latency, 1), jitter=round(jitter, 1),
            reconnect_success=reconnect_success,
            categories=categories_passed, telegram=telegram_works
        )

    with stats_lock:
        stats.xray_passed += 1
        stats.by_protocol[protocol] += 1

    return CheckResult(
        key=key, alive=True,
        latency=round(avg_latency, 1), jitter=round(jitter, 1),
        reconnect_success=reconnect_success,
        categories=categories_passed, telegram=telegram_works,
        protocol=protocol, host=host, port=port, security=security
    )


# ==================== SAVE ====================
def save_results(results: List[CheckResult]):
    alive = [r for r in results if r.alive]
    alive.sort(key=lambda x: x.latency)

    with open(VERIFIED_FILE, 'w', encoding='utf-8') as f:
        f.write(f"# {MY_CHANNEL}\n")
        f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC\n")
        f.write(f"# Passed: TCP + Xray + {CONFIG.MIN_CATEGORIES}/7 sites + Reconnect\n")
        f.write(f"# Quality: latency<={CONFIG.MAX_LATENCY:.0f}ms, jitter<={CONFIG.MAX_JITTER:.0f}ms\n")
        f.write(f"# Total: {len(alive)}\n\n")

        for r in alive:
            tg = "TG+" if r.telegram else ""
            mut = f"|{r.mutation_used}" if r.mutation_used else ""
            comment = (
                f"[{r.latency:.0f}ms|j{r.jitter:.0f}|"
                f"rc{r.reconnect_success}/{CONFIG.RECONNECT_TESTS}|"
                f"{r.categories}cat|{tg}{r.protocol}{mut}|{MY_CHANNEL}]"
            )
            f.write(f"{r.key.split('#')[0]}#{quote(comment)}\n")

    log(f"[SAVE] {len(alive)} keys -> {VERIFIED_FILE}")

    stats_data = {
        "timestamp": datetime.now().isoformat(),
        "total_working": len(alive),
        "by_protocol": dict(stats.by_protocol),
        "by_error": dict(stats.errors),
        "processing_time_min": round((time.time() - stats.start_time) / 60, 1),
    }
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats_data, f, indent=2)

    return len(alive)


# ==================== MAIN ====================
def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=CONFIG.XRAY_WORKERS)
    parser.add_argument('--tcp-workers', type=int, default=CONFIG.TCP_WORKERS)
    parser.add_argument('--min-cats', type=int, default=CONFIG.MIN_CATEGORIES)
    parser.add_argument('--max-jitter', type=float, default=CONFIG.MAX_JITTER)
    parser.add_argument('--max-latency', type=float, default=CONFIG.MAX_LATENCY)
    return parser.parse_args()


def main():
    args = parse_args()
    CONFIG.XRAY_WORKERS = args.workers
    CONFIG.TCP_WORKERS = args.tcp_workers
    CONFIG.MIN_CATEGORIES = args.min_cats
    CONFIG.MAX_JITTER = args.max_jitter
    CONFIG.MAX_LATENCY = args.max_latency

    print("\n" + "=" * 60)
    print("  Proxy Checker v6.2 FINAL (REAL site checks + quality filters)")
    print(f"  Channel: {MY_CHANNEL}")
    print("=" * 60)
    print(f"  Category timeout: {CONFIG.CATEGORY_TIMEOUT}s")
    print(f"  Categories needed: {CONFIG.MIN_CATEGORIES}/7")
    print(f"  Telegram required: {CONFIG.REQUIRE_TELEGRAM}")
    print(f"  Max jitter: {CONFIG.MAX_JITTER}ms")
    print(f"  Max latency: {CONFIG.MAX_LATENCY}ms")
    print(f"  Max keys: {CONFIG.MAX_KEYS}")
    print("=" * 60)

    xray_exe = setup_xray()
    if not xray_exe:
        log("[ERR] Xray setup failed")
        return 1

    all_keys = download_and_deduplicate()
    if not all_keys:
        log("[ERR] No keys")
        return 1

    # STAGE 1: TCP
    print("\n" + "=" * 60)
    log(f"[TCP] Stage 1: {len(all_keys)} keys, {CONFIG.TCP_WORKERS} workers")
    print("=" * 60 + "\n")

    tcp_passed = []
    tcp_start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.TCP_WORKERS) as ex:
        futures = {ex.submit(tcp_prefilter, k): k for k in all_keys}
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            if done % CONFIG.GC_EVERY == 0:
                cleanup_memory()
            try:
                r = fut.result()
                if r:
                    tcp_passed.append(r)
                    stats.tcp_passed += 1
                else:
                    stats.tcp_failed += 1
            except Exception:
                stats.tcp_failed += 1

    tcp_time = time.time() - tcp_start
    log(f"[TCP] Passed: {len(tcp_passed)}/{len(all_keys)} in {tcp_time:.1f}s")

    if not tcp_passed:
        log("[ERR] No TCP-alive keys")
        return 1

    if time_exceeded():
        log("[WARN] Time exceeded after TCP, stopping")
        return 0

    # STAGE 2: XRAY
    print("\n" + "=" * 60)
    log(f"[XRAY] Stage 2: {len(tcp_passed)} keys, {CONFIG.XRAY_WORKERS} workers")
    log(f"[XRAY] Real check: {len(CONFIG.CATEGORY_URLS)} sites, min {CONFIG.MIN_CATEGORIES}")
    print("=" * 60 + "\n")

    results = []
    xray_start = time.time()

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.XRAY_WORKERS) as ex:
        futures = {ex.submit(xray_full_check, k, xray_exe): k for k in tcp_passed}
        done = 0
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            if done % 10 == 0:
                cleanup_memory()

            if time_exceeded():
                log(f"[WARN] Time exceeded at {done}/{len(tcp_passed)}, stopping")
                break

            try:
                result = fut.result(timeout=180)
                results.append(result)
                if result.alive:
                    mut = f" [{result.mutation_used}]" if result.mutation_used else ""
                    log(
                        f"  [{done}/{len(tcp_passed)}] OK "
                        f"{result.latency:>6.0f}ms j{result.jitter:>4.0f} "
                        f"rc{result.reconnect_success} "
                        f"{result.categories}cat "
                        f"{result.protocol}{mut}"
                    )
                else:
                    stats.xray_failed += 1
                    if result.error:
                        record_error(result.error)
            except concurrent.futures.TimeoutError:
                stats.xray_failed += 1
                record_error("future_timeout")
            except Exception:
                stats.xray_failed += 1
                record_error("future_exception")

    xray_time = time.time() - xray_start
    total_time = time.time() - stats.start_time

    if results:
        save_results(results)

    # SUMMARY
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Unique: {stats.unique} (dupes: {stats.duplicates})")
    print(f"  TCP: {stats.tcp_passed}")
    print(f"  Quick: {stats.quick_passed} passed, {stats.quick_failed} killed")
    print(f"  Final: {stats.xray_passed} passed ALL stages")
    print()
    if stats.mutations_tried:
        print(f"  Mutations: {stats.mutations_success}/{stats.mutations_tried}")
    print()
    for proto, cnt in sorted(stats.by_protocol.items(), key=lambda x: -x[1]):
        print(f"    {proto}: {cnt}")
    print()
    print(f"  TCP={tcp_time:.1f}s XRAY={xray_time:.1f}s TOTAL={total_time / 60:.1f}min")

    if stats.errors:
        print("\n  Errors:")
        for err, cnt in sorted(stats.errors.items(), key=lambda x: -x[1])[:10]:
            print(f"    {err}: {cnt}")

    print("=" * 60)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[STOP]")
        cleanup_all_processes()
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERR] {e}")
        import traceback
        traceback.print_exc()
        cleanup_all_processes()
        sys.exit(1)
