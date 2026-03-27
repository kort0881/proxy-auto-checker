#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Proxy Checker v5.3 LITE (TCP+HTTP-deep) — ALL pipeline

Этот вариант берёт ключи из префильтра ALL:
results/verified_all_*.txt в отдельном репозитории.
"""

import os
import html
import socket
import time
import sys
import requests
import base64
import json
import random
import threading
import concurrent.futures
import gc
import argparse
import logging
import ssl
from datetime import datetime
from urllib.parse import quote, urlparse
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean
from logging.handlers import RotatingFileHandler

# ==================== PATHS ====================
WORK_DIR = Path(__file__).parent.absolute()
RESULTS_FOLDER = WORK_DIR / "results"
PREMIUM_FOLDER = RESULTS_FOLDER / "premium"
RF_FOLDER = RESULTS_FOLDER / "rf_ready"
HISTORY_FILE = RESULTS_FOLDER / "history_all.jsonl"
STATS_FILE = RESULTS_FOLDER / "stats_all_latest.json"
LOG_FILE = RESULTS_FOLDER / "checker_all.log"

for d in [RESULTS_FOLDER, PREMIUM_FOLDER, RF_FOLDER]:
    d.mkdir(parents=True, exist_ok=True)

# ==================== HOST CACHE ====================
host_port_cache: Dict[Tuple[str, int], dict] = {}
host_cache_lock = threading.Lock()

# ==================== GEO CACHE ====================
geo_cache: Dict[str, str] = {}
geo_cache_lock = threading.Lock()

# ==================== UNIVERSAL SOURCE READER ====================
def read_source_text(url: str) -> str:
    if url.startswith("file://"):
        p = Path(urlparse(url).path)
        return p.read_text(encoding="utf-8", errors="ignore")

    p = Path(url)
    if p.exists():
        return p.read_text(encoding="utf-8", errors="ignore")

    for attempt in range(3):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)

# ==================== SOURCES ====================
# ВХОД ДЛЯ ALL-ПАЙПЛАЙНА:
# сюда укажи репо с префильтром ALL (verified_all_*).
KEYSOURCES = {
    "VerifiedALL": [
        # пример: "latest" файл, который ты делаешь в репо префильтра
        "https://raw.githubusercontent.com/kort0881/proxy-prefilter-all/main/results/verified_all_latest.txt",
        # или можно добавить несколько временных файлов:
        # "https://raw.githubusercontent.com/kort0881/proxy-prefilter-all/main/results/verified_all_2026-03-27_12-00-00.txt",
    ],
}

MY_CHANNEL = "@vlesstrojan"

# ==================== CONFIG ====================
@dataclass
class Config:

    TCP_WORKERS: int = 100

    TCP_TIMEOUT: float = 5.0
    TCP_ATTEMPTS: int = 5

    ELITE_MAX_LATENCY: float = 300.0
    ELITE_MAX_JITTER: float = 120.0
    ELITE_MIN_SUCCESS: float = 0.90

    PREMIUM_MAX_LATENCY: float = 600.0
    PREMIUM_MAX_JITTER: float = 250.0
    PREMIUM_MIN_SUCCESS: float = 0.70

    GOOD_MAX_LATENCY: float = 2000.0
    GOOD_MIN_SUCCESS: float = 0.50

    GC_EVERY: int = 100

    SECOND_STAGE_TOP_N: int = 200
    SECOND_STAGE_WORKERS: int = 40
    HTTP_TEST_TIMEOUT: float = 4.0
    HTTP_TEST_URLS: Tuple[str, ...] = (
        "/",                 # просто корень
        "/generate_204",
    )

CONFIG = Config()

# ==================== SMART SERVER SCORING ====================

def compute_server_score(latency: float, jitter: float, success_rate: float, packet_loss: float) -> float:
    latency_score = max(0, 100 - latency * 0.2)
    jitter_penalty = jitter * 0.1
    reliability_score = success_rate * 100
    loss_penalty = packet_loss * 120
    score = latency_score + reliability_score - jitter_penalty - loss_penalty
    return max(0, score)

# ==================== QUALITY ====================
class Quality(Enum):
    ELITE = "elite"
    PREMIUM = "premium"
    GOOD = "good"

@dataclass
class CheckResult:
    key: str
    alive: bool
    latency: float = 0.0
    jitter: float = 0.0
    tcp_success_rate: float = 0.0
    tcp_attempts: int = 0
    tcp_successes: int = 0
    quality: Optional[Quality] = None
    protocol: str = ""
    host: str = ""
    port: int = 0
    security: str = ""
    error: Optional[str] = None

    p50: float = 0.0
    p90: float = 0.0
    packet_loss: float = 0.0
    country: str = ""

@dataclass
class Stats:
    total_downloaded: int = 0
    duplicates: int = 0
    unique: int = 0
    tcp_checked: int = 0
    tcp_alive: int = 0
    tcp_dead: int = 0
    by_quality: Dict[Quality, int] = field(default_factory=lambda: defaultdict(int))
    by_protocol: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    start_time: float = field(default_factory=time.time)

stats = Stats()
stats_lock = threading.Lock()

def record_error(error: str):
    with stats_lock:
        stats.errors[error] += 1

# ==================== LOGGING ====================

def setup_logging():
    handler = RotatingFileHandler(LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2)
    handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
    logger = logging.getLogger('ProxyCheckerALL')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger

file_logger = setup_logging()

def log(msg: str):
    print(msg)
    file_logger.info(msg)

def cleanup_memory():
    gc.collect()

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


def detect_protocol(key: str) -> Tuple[str, str]:
    key_lower = key.lower()
    security = "none"

    if "security=reality" in key_lower:
        security = "reality"
    elif "security=tls" in key_lower:
        security = "tls"

    if key_lower.startswith("vless://"):
        return "VLESS", security
    elif key_lower.startswith("vmess://"):
        return "VMess", security
    elif key_lower.startswith("trojan://"):
        return "Trojan", "tls"
    elif key_lower.startswith("ss://"):
        return "SS", security

    return "Unknown", security

# ==================== EXTRA NETWORK TESTS ====================

def dns_lookup(host: str) -> Optional[float]:
    try:
        start = time.time()
        socket.getaddrinfo(host, None)
        return (time.time() - start) * 1000
    except Exception:
        return None


def tls_handshake(host: str, port: int, timeout: float) -> bool:
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                names = []
                subject = cert.get("subject", [])
                for tup in subject:
                    for k, v in tup:
                        if k.lower() == "commonname":
                            names.append(v.lower())
                for san in cert.get("subjectAltName", []):
                    if san[0].lower() in ("dns",):
                        names.append(san[1].lower())
                host_l = host.lower()
                if names and not any(host_l in n or n in host_l for n in names):
                    return False
                return True
    except Exception:
        return False


def geo_lookup(host: str) -> str:
    with geo_cache_lock:
        if host in geo_cache:
            return geo_cache[host]

    try:
        r = requests.get(f"http://ip-api.com/json/{host}", timeout=3)
        country = r.json().get("countryCode", "??")
    except Exception:
        country = "??"

    with geo_cache_lock:
        geo_cache[host] = country

    return country

# ==================== DOWNLOAD ====================

def download_and_deduplicate(sources: Dict[str, List[str]] = None) -> List[str]:
    if sources is None:
        sources = KEYSOURCES

    all_keys = []
    seen = set()
    duplicates = 0

    log("[DL] Downloading keys (ALL)...")

    for region, urls in sources.items():
        log(f"  Region: {region}")
        for url in urls:
            try:
                content = read_source_text(url).strip()
            except Exception as e:
                log(f"    FAIL {url}: {e}")
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
            log(f"    {url}: {count}")

    stats.duplicates = duplicates
    stats.unique = len(all_keys)

    log(f"  Total: {stats.total_downloaded + duplicates} | Dupes: {duplicates} | Unique: {len(all_keys)}")

    return all_keys

# ==================== QUALITY ====================

def classify_quality(latency: float, jitter: float, success_rate: float) -> Optional[Quality]:
    score = compute_server_score(latency, jitter, success_rate, 1 - success_rate)

    if (latency <= CONFIG.ELITE_MAX_LATENCY and
            jitter <= CONFIG.ELITE_MAX_JITTER and
            success_rate >= CONFIG.ELITE_MIN_SUCCESS and
            score > 120):
        return Quality.ELITE

    if (latency <= CONFIG.PREMIUM_MAX_LATENCY and
            jitter <= CONFIG.PREMIUM_MAX_JITTER and
            success_rate >= CONFIG.PREMIUM_MIN_SUCCESS and
            score > 80):
        return Quality.PREMIUM

    if (latency <= CONFIG.GOOD_MAX_LATENCY and
            success_rate >= CONFIG.GOOD_MIN_SUCCESS):
        return Quality.GOOD

    return None

# ==================== TCP CHECK ====================

def check_key_simple(key: str) -> CheckResult:
    host, port = extract_host_port(key)
    protocol, security = detect_protocol(key)

    if not host or not port:
        record_error("parse_error")
        return CheckResult(
            key=key,
            alive=False,
            error="parse_error",
            protocol=protocol,
            security=security
        )

    cache_key = (host, port)

    with host_cache_lock:
        if cache_key in host_port_cache:
            cached = host_port_cache[cache_key]
            return CheckResult(
                key=key,
                alive=cached["alive"],
                latency=cached["latency"],
                jitter=cached["jitter"],
                tcp_success_rate=cached["tcp_success_rate"],
                tcp_attempts=CONFIG.TCP_ATTEMPTS,
                tcp_successes=cached["tcp_successes"],
                quality=cached["quality"],
                protocol=protocol,
                host=host,
                port=port,
                security=security
            )

    if security == "tls":
        if not tls_handshake(host, port, CONFIG.TCP_TIMEOUT):
            record_error("tls_fail")
            with host_cache_lock:
                host_port_cache[cache_key] = {
                    "alive": False, "latency": 0, "jitter": 0,
                    "tcp_success_rate": 0, "tcp_successes": 0, "quality": None
                }
            return CheckResult(
                key=key,
                alive=False,
                error="tls_fail",
                protocol=protocol,
                host=host,
                port=port,
                security=security
            )

    latencies: List[float] = []
    successes = 0

    dns_latency = dns_lookup(host)

    for attempt in range(CONFIG.TCP_ATTEMPTS):
        try:
            start = time.time()
            with socket.create_connection((host, port), timeout=CONFIG.TCP_TIMEOUT):
                latency_ms = (time.time() - start) * 1000

                if attempt == 0 and dns_latency is not None:
                    latency_ms = max(1.0, latency_ms - dns_latency)

                latencies.append(latency_ms)
                successes += 1

        except socket.timeout:
            record_error("tcp_timeout")
        except ConnectionRefusedError:
            record_error("tcp_refused")
        except socket.gaierror:
            record_error("dns_error")
        except Exception:
            record_error("tcp_other")

        if attempt < CONFIG.TCP_ATTEMPTS - 1:
            time.sleep(random.uniform(0.05, 0.25))

    tcp_success_rate = successes / CONFIG.TCP_ATTEMPTS
    packet_loss = (CONFIG.TCP_ATTEMPTS - successes) / CONFIG.TCP_ATTEMPTS

    if not latencies:
        result = CheckResult(
            key=key,
            alive=False,
            error="tcp_fail",
            protocol=protocol,
            host=host,
            port=port,
            security=security,
            tcp_attempts=CONFIG.TCP_ATTEMPTS,
            tcp_successes=0,
            tcp_success_rate=0.0
        )
        with host_cache_lock:
            host_port_cache[cache_key] = {
                "alive": False, "latency": 0, "jitter": 0,
                "tcp_success_rate": 0, "tcp_successes": 0, "quality": None
            }
        return result

    latencies.sort()

    avg_latency = mean(latencies)
    jitter = max(latencies) - min(latencies)

    n = len(latencies)
    p50 = latencies[min(int(n * 0.50), n - 1)]
    p90 = latencies[min(int(n * 0.90), n - 1)]

    quality = classify_quality(avg_latency, jitter, tcp_success_rate)

    country = geo_lookup(host)

    result = CheckResult(
        key=key,
        alive=quality is not None,
        latency=round(avg_latency, 1),
        jitter=round(jitter, 1),
        tcp_success_rate=round(tcp_success_rate, 2),
        tcp_attempts=CONFIG.TCP_ATTEMPTS,
        tcp_successes=successes,
        quality=quality,
        protocol=protocol,
        host=host,
        port=port,
        security=security,
        p50=round(p50, 1),
        p90=round(p90, 1),
        packet_loss=round(packet_loss, 2),
        country=country
    )

    with host_cache_lock:
        host_port_cache[cache_key] = {
            "alive": result.alive,
            "latency": result.latency,
            "jitter": result.jitter,
            "tcp_success_rate": result.tcp_success_rate,
            "tcp_successes": successes,
            "quality": quality
        }

    return result

# ==================== SECOND STAGE: SIMPLE HTTP(S) TEST ====================

def deep_http_test_one(r: CheckResult) -> bool:
    if not r.host or not r.port:
        return False

    scheme = "https" if r.security in ("tls", "reality") else "http"
    base = f"{scheme}://{r.host}:{r.port}"

    for path in CONFIG.HTTP_TEST_URLS:
        url = base + path
        try:
            resp = requests.get(
                url,
                timeout=CONFIG.HTTP_TEST_TIMEOUT,
                allow_redirects=False,
                verify=(scheme == "https"),
            )
            if resp.status_code in (200, 204, 301, 302):
                return True
        except Exception:
            continue

    return False

def second_stage_filter(results: List[CheckResult]) -> None:
    alive_results = [r for r in results if r.alive and r.host and r.port]
    if not alive_results:
        return

    alive_results.sort(key=lambda x: x.latency)
    top_n = alive_results[:CONFIG.SECOND_STAGE_TOP_N]

    log(f"[DEEP] Second stage HTTP-check for top {len(top_n)} of {len(alive_results)} alive")

    lock = threading.Lock()

    def worker(r: CheckResult):
        ok = deep_http_test_one(r)
        if not ok:
            with lock:
                r.alive = False
                r.error = (r.error or "") + "|deep_http_fail"

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.SECOND_STAGE_WORKERS) as ex:
        futures = [ex.submit(worker, r) for r in top_n]
        for f in concurrent.futures.as_completed(futures):
            try:
                f.result()
            except Exception:
                record_error("deep_http_exception")

# ==================== SAVE RESULTS ====================

def save_results(results: List[CheckResult], region: str = "VerifiedALL"):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    by_quality = defaultdict(list)

    for r in results:
        if r.alive and r.quality:
            by_quality[r.quality].append(r)

    for quality in Quality:
        items = by_quality.get(quality, [])
        if not items:
            continue

        items.sort(key=lambda x: x.latency)
        filename = PREMIUM_FOLDER / f"all_{quality.value}.txt"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {quality.value.upper()}\n")
            f.write(f"# {MY_CHANNEL}\n")
            f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# Mode: ALL TCP+HTTP-LITE\n")
            f.write(f"# Keys: {len(items)}\n\n")

            for r in items:
                is_ru = any(x in (r.host or "").lower() for x in ['.ru', 'russia', 'moscow', 'm9', 'msk'])
                reg = "RU" if is_ru else "EU"

                comment = (
                    f"[{r.latency:.0f}ms|{reg}|j{r.jitter:.0f}|"
                    f"tcp{r.tcp_success_rate:.0%}|{r.protocol}|{MY_CHANNEL}]"
                )
                base_key = r.key.split('#')[0]
                f.write(f"{base_key}#{quote(comment)}\n")

        log(f"[SAVE] ALL {quality.value.upper()}: {len(items)} -> {filename.name}")

    all_results = [r for r in results if r.alive]
    all_results.sort(key=lambda x: x.latency)

    verified_file = RESULTS_FOLDER / f"verified_all_{timestamp}.txt"
    with open(verified_file, 'w', encoding='utf-8') as f:
        f.write(f"# {MY_CHANNEL}\n")
        f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Mode: ALL TCP+HTTP-LITE\n")
        f.write(f"# Working: {len(all_results)}\n\n")

        for r in all_results:
            is_ru = any(x in (r.host or "").lower() for x in ['.ru', 'russia', 'moscow', 'm9', 'msk'])
            reg = "RU" if is_ru else "EU"
            q = r.quality.value.upper() if r.quality else "UNK"
            comment = f"{reg} {q} {r.latency:.0f}ms {r.protocol} {MY_CHANNEL}"
            f.write(f"{r.key.split('#')[0]}#{quote(comment)}\n")

    log(f"[SAVE] ALL working: {len(all_results)} -> {verified_file.name}")

    stats_data = {
        "timestamp": datetime.now().isoformat(),
        "region": region,
        "mode": "ALL TCP+HTTP-LITE",
        "total_checked": stats.tcp_checked,
        "total_working": len(all_results),
        "by_quality": {q.value: len(by_quality.get(q, [])) for q in Quality},
        "by_protocol": dict(stats.by_protocol),
        "errors": dict(stats.errors),
        "processing_time": time.time() - stats.start_time
    }

    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats_data, f, indent=2)

    log(f"[SAVE] Stats -> {STATS_FILE.name}")

    try:
        with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
            for r in results:
                record = {
                    'timestamp': time.time(),
                    'alive': r.alive,
                    'protocol': r.protocol,
                    'latency': r.latency,
                    'jitter': r.jitter,
                    'tcp_success_rate': r.tcp_success_rate,
                    'quality': r.quality.value if r.quality else None,
                    'host': r.host,
                    'port': r.port,
                    'country': r.country,
                    'p50': r.p50,
                    'p90': r.p90,
                    'packet_loss': r.packet_loss,
                    'error': r.error
                }
                f.write(json.dumps(record) + '\n')
    except Exception as e:
        log(f"[WARN] Failed to save history: {e}")

    return stats_data

# ==================== MAIN ====================

def parse_arguments():
    parser = argparse.ArgumentParser(description="AI Proxy Checker v5.3 LITE (ALL, TCP+HTTP)")
    parser.add_argument('--workers', type=int, default=CONFIG.TCP_WORKERS)
    parser.add_argument('--tcp-workers', type=int, default=CONFIG.TCP_WORKERS)
    parser.add_argument('--timeout', type=float, default=CONFIG.TCP_TIMEOUT)
    parser.add_argument('--attempts', type=int, default=CONFIG.TCP_ATTEMPTS)
    parser.add_argument('--second-top', type=int, default=CONFIG.SECOND_STAGE_TOP_N)
    return parser.parse_args()


def main():
    args = parse_arguments()

    CONFIG.TCP_WORKERS = args.tcp_workers
    CONFIG.TCP_TIMEOUT = args.timeout
    CONFIG.TCP_ATTEMPTS = args.attempts
    CONFIG.SECOND_STAGE_TOP_N = args.second_top

    print("\n" + "=" * 60)
    print(" AI Proxy Checker v5.3 LITE (ALL, TCP+HTTP)")
    print(" Two-stage: TCP first, HTTP deep on top-N")
    print(f" Channel: {MY_CHANNEL}")
    print("=" * 60)

    all_keys = download_and_deduplicate(KEYSOURCES)

    if not all_keys:
        log("[ERR] No keys found")
        return 1

    log(f"[TCP] Checking {len(all_keys)} keys with {CONFIG.TCP_WORKERS} workers")

    results: List[CheckResult] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.TCP_WORKERS) as executor:
        futures = {executor.submit(check_key_simple, key): key for key in all_keys}

        done = 0

        for future in concurrent.futures.as_completed(futures):
            done += 1

            if done % CONFIG.GC_EVERY == 0:
                cleanup_memory()

            try:
                result = future.result(timeout=60)
                results.append(result)

                with stats_lock:
                    stats.tcp_checked += 1
                    if result.alive:
                        stats.tcp_alive += 1
                        if result.quality:
                            stats.by_quality[result.quality] += 1
                        stats.by_protocol[result.protocol] += 1
                    else:
                        stats.tcp_dead += 1

            except Exception:
                stats.tcp_dead += 1
                record_error("future_exception")

    second_stage_filter(results)

    save_results(results, region="VerifiedALL")

    print("Finished ALL check")
    return 0


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\n[STOP] Interrupted")
        exit_code = 1
    except Exception as e:
        print(f"\n[ERR] {e}")
        import traceback
        traceback.print_exc()
        exit_code = 1

    sys.exit(exit_code)
