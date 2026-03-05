#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Proxy Checker v5.2 LITE
Облегчённая версия без XRAY/DPI/AI
- Только TCP проверки с измерением латентности
- Классификация ELITE/PREMIUM/GOOD по TCP метрикам
- Сохранение результатов в том же формате
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
from datetime import datetime
from urllib.parse import quote, unquote, urlparse
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean, stdev
from logging.handlers import RotatingFileHandler

# ==================== PATHS ====================
WORK_DIR = Path(__file__).parent.absolute()
RESULTS_FOLDER = WORK_DIR / "results"
PREMIUM_FOLDER = RESULTS_FOLDER / "premium"
RF_FOLDER = RESULTS_FOLDER / "rf_ready"
HISTORY_FILE = RESULTS_FOLDER / "history.jsonl"
STATS_FILE = RESULTS_FOLDER / "stats_latest.json"
LOG_FILE = RESULTS_FOLDER / "checker.log"

for d in [RESULTS_FOLDER, PREMIUM_FOLDER, RF_FOLDER]:
    d.mkdir(parents=True, exist_ok=True)

# ==================== UNIVERSAL SOURCE READER ====================
def read_source_text(url: str) -> str:
    """Universal source reader: http/https/file:// or local path"""
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
KEYSOURCES = {
    "RU": [
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/RU_Best/ru_white_part1.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/RU_Best/ru_white_part2.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/RU_Best/ru_white_part3.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/RU_Best/ru_white_part4.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/RU_Best/ru_white_all_part1.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/RU_Best/ru_white_all_part2.txt",
        "https://raw.githubusercontent.com/sakha1370/OpenRay/main/output/country/RU.txt",
    ],
    "EU": [
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/My_Euro/my_euro_part1.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/My_Euro/my_euro_part2.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/My_Euro/my_euro_part3.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/My_Euro/my_euro_all_part1.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/My_Euro/my_euro_all_part2.txt",
        "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/My_Euro/my_euro_all_part3.txt",
        "https://raw.githubusercontent.com/sakha1370/OpenRay/main/output/country/DE.txt",
    ],
    "Prefiltered": [],
}

MY_CHANNEL = "@vlesstrojan"

# ==================== CONFIG ====================
@dataclass
class Config:
    # Workers
    TCP_WORKERS: int = 100

    # Timeouts
    TCP_TIMEOUT: float = 5.0
    TCP_ATTEMPTS: int = 5

    # Quality thresholds (TCP-based)
    ELITE_MAX_LATENCY: float = 300.0
    ELITE_MAX_JITTER: float = 120.0
    ELITE_MIN_SUCCESS: float = 0.90

    PREMIUM_MAX_LATENCY: float = 600.0
    PREMIUM_MAX_JITTER: float = 250.0
    PREMIUM_MIN_SUCCESS: float = 0.70

    GOOD_MAX_LATENCY: float = 2000.0
    GOOD_MIN_SUCCESS: float = 0.50

    # Memory
    GC_EVERY: int = 100

CONFIG = Config()

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
    handler = RotatingFileHandler(
        LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=2
    )
    handler.setFormatter(logging.Formatter('%(asctime)s | %(message)s'))
    logger = logging.getLogger('ProxyChecker')
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
    """Extract host and port from proxy key"""
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

def detect_protocol(key: str) -> Tuple[str, str]:
    """Detect protocol and security from key"""
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

# ==================== DOWNLOAD ====================
def download_and_deduplicate(sources: Dict[str, List[str]] = None) -> List[str]:
    if sources is None:
        sources = KEYSOURCES

    all_keys = []
    seen = set()
    duplicates = 0

    log("[DL] Downloading keys...")

    for region, urls in sources.items():
        log(f"  Region: {region}")
        for url in urls:
            try:
                content = read_source_text(url).strip()
            except Exception as e:
                log(f"    FAIL {url.split('/')[-1]}: {e}")
                continue

            if 'base64' in url:
                try:
                    content = base64.b64decode(content).decode('utf-8')
                except:
                    pass

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
    stats.unique = len(all_keys)
    log(f"  Total: {stats.total_downloaded + duplicates} | Dupes: {duplicates} | Unique: {len(all_keys)}")

    return all_keys

# ==================== TCP CHECK WITH METRICS ====================
def classify_quality(latency: float, jitter: float, success_rate: float) -> Optional[Quality]:
    """Классификация качества по TCP метрикам"""

    # ELITE: быстрый и стабильный
    if (latency <= CONFIG.ELITE_MAX_LATENCY and
        jitter <= CONFIG.ELITE_MAX_JITTER and
        success_rate >= CONFIG.ELITE_MIN_SUCCESS):
        return Quality.ELITE

    # PREMIUM: средняя скорость, приемлемая стабильность
    if (latency <= CONFIG.PREMIUM_MAX_LATENCY and
        jitter <= CONFIG.PREMIUM_MAX_JITTER and
        success_rate >= CONFIG.PREMIUM_MIN_SUCCESS):
        return Quality.PREMIUM

    # GOOD: работает, но медленнее
    if (latency <= CONFIG.GOOD_MAX_LATENCY and
        success_rate >= CONFIG.GOOD_MIN_SUCCESS):
        return Quality.GOOD

    return None

def check_key_simple(key: str) -> CheckResult:
    """
    Простая TCP-проверка ключа с измерением латентности.
    Делает N попыток TCP-коннекта, собирает метрики.
    """
    host, port = extract_host_port(key)
    protocol, security = detect_protocol(key)

    if not host or not port:
        record_error("parse_error")
        return CheckResult(
            key=key, alive=False, error="parse_error",
            protocol=protocol, security=security
        )

    latencies: List[float] = []
    successes = 0
    timeouts = 0

    for attempt in range(CONFIG.TCP_ATTEMPTS):
        try:
            t_start = time.time()
            with socket.create_connection((host, port), timeout=CONFIG.TCP_TIMEOUT):
                latency_ms = (time.time() - t_start) * 1000
                latencies.append(latency_ms)
                successes += 1
        except socket.timeout:
            timeouts += 1
            record_error("tcp_timeout")
        except ConnectionRefusedError:
            record_error("tcp_refused")
        except socket.gaierror:
            record_error("dns_error")
        except Exception:
            record_error("tcp_other")

        if attempt < CONFIG.TCP_ATTEMPTS - 1:
            time.sleep(0.1)

    tcp_success_rate = successes / CONFIG.TCP_ATTEMPTS

    if not latencies:
        return CheckResult(
            key=key, alive=False, error="tcp_fail",
            protocol=protocol, host=host, port=port, security=security,
            tcp_attempts=CONFIG.TCP_ATTEMPTS, tcp_successes=0, tcp_success_rate=0.0
        )

    avg_latency = mean(latencies)
    jitter = stdev(latencies) if len(latencies) > 1 else 0.0

    quality = classify_quality(avg_latency, jitter, tcp_success_rate)

    if quality is None:
        return CheckResult(
            key=key, alive=False, error="below_threshold",
            protocol=protocol, host=host, port=port, security=security,
            latency=round(avg_latency, 1), jitter=round(jitter, 1),
            tcp_attempts=CONFIG.TCP_ATTEMPTS, tcp_successes=successes,
            tcp_success_rate=round(tcp_success_rate, 2)
        )

    return CheckResult(
        key=key, alive=True,
        latency=round(avg_latency, 1),
        jitter=round(jitter, 1),
        tcp_success_rate=round(tcp_success_rate, 2),
        tcp_attempts=CONFIG.TCP_ATTEMPTS,
        tcp_successes=successes,
        quality=quality,
        protocol=protocol,
        host=host,
        port=port,
        security=security
    )

# ==================== SAVE RESULTS ====================
def save_results(results: List[CheckResult], region: str = "ALL"):
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
        filename = PREMIUM_FOLDER / f"{quality.value}.txt"

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {quality.value.upper()}\n")
            f.write(f"# {MY_CHANNEL}\n")
            f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# Mode: TCP-LITE\n")
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

        log(f"[SAVE] {quality.value.upper()}: {len(items)} -> {filename.name}")

    all_results = [r for r in results if r.alive]
    all_results.sort(key=lambda x: x.latency)

    verified_file = RESULTS_FOLDER / f"verified_{timestamp}.txt"
    with open(verified_file, 'w', encoding='utf-8') as f:
        f.write(f"# {MY_CHANNEL}\n")
        f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Mode: TCP-LITE\n")
        f.write(f"# Working: {len(all_results)}\n\n")

        for r in all_results:
            is_ru = any(x in (r.host or "").lower() for x in ['.ru', 'russia', 'moscow', 'm9', 'msk'])
            reg = "RU" if is_ru else "EU"
            q = r.quality.value.upper() if r.quality else "UNK"
            comment = f"{reg} {q} {r.latency:.0f}ms {r.protocol} {MY_CHANNEL}"
            f.write(f"{r.key.split('#')[0]}#{quote(comment)}\n")

    log(f"[SAVE] All: {len(all_results)} -> {verified_file.name}")

    stats_data = {
        "timestamp": datetime.now().isoformat(),
        "region": region,
        "mode": "TCP-LITE",
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
                    'error': r.error
                }
                f.write(json.dumps(record) + '\n')
    except Exception as e:
        log(f"[WARN] Failed to save history: {e}")

    return stats_data

# ==================== ARGS & MAIN ====================
def parse_arguments():
    parser = argparse.ArgumentParser(description="AI Proxy Checker v5.2 LITE (TCP-only)")
    parser.add_argument('--region', choices=['ALL', 'RU', 'EU', 'Prefiltered'], default='ALL')
    parser.add_argument('--workers', type=int, default=CONFIG.TCP_WORKERS)
    parser.add_argument('--tcp-workers', type=int, default=CONFIG.TCP_WORKERS)
    parser.add_argument('--timeout', type=float, default=CONFIG.TCP_TIMEOUT)
    parser.add_argument('--attempts', type=int, default=CONFIG.TCP_ATTEMPTS)
    return parser.parse_args()

def main():
    args = parse_arguments()

    # workers из workflow: --tcp-workers 50
    CONFIG.TCP_WORKERS = args.tcp_workers
    CONFIG.TCP_TIMEOUT = args.timeout
    CONFIG.TCP_ATTEMPTS = args.attempts

    print("\n" + "=" * 60)
    print(" AI Proxy Checker v5.2 LITE")
    print(" TCP-only mode (no XRAY/DPI/AI)")
    print(f" Channel: {MY_CHANNEL}")
    print("=" * 60)
    print(f"\n Settings:")
    print(f"   Region: {args.region}")
    print(f"   TCP workers: {CONFIG.TCP_WORKERS}")
    print(f"   Timeout: {CONFIG.TCP_TIMEOUT}s")
    print(f"   Attempts per key: {CONFIG.TCP_ATTEMPTS}")
    print()
    print(f" Quality thresholds:")
    print(f"   ELITE:   lat<={CONFIG.ELITE_MAX_LATENCY}ms, jit<={CONFIG.ELITE_MAX_JITTER}ms, success>={CONFIG.ELITE_MIN_SUCCESS:.0%}")
    print(f"   PREMIUM: lat<={CONFIG.PREMIUM_MAX_LATENCY}ms, jit<={CONFIG.PREMIUM_MAX_JITTER}ms, success>={CONFIG.PREMIUM_MIN_SUCCESS:.0%}")
    print(f"   GOOD:    lat<={CONFIG.GOOD_MAX_LATENCY}ms, success>={CONFIG.GOOD_MIN_SUCCESS:.0%}")
    print()

    if args.region != 'ALL':
        sources = {args.region: KEYSOURCES.get(args.region, [])}
    else:
        sources = KEYSOURCES

    all_keys = download_and_deduplicate(sources)
    if not all_keys:
        log("[ERR] No keys found")
        return 1

    print("\n" + "=" * 60)
    log(f"[TCP] Checking {len(all_keys)} keys with {CONFIG.TCP_WORKERS} workers")
    print("=" * 60 + "\n")

    tcp_start = time.time()
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

                        if done % 50 == 0 or (result.quality == Quality.ELITE):
                            log(
                                f"  [{done}/{len(all_keys)}] OK "
                                f"{(result.quality.value if result.quality else 'UNK').upper():>7} | "
                                f"{result.latency:>6.0f}ms j{result.jitter:>4.0f} | "
                                f"tcp:{result.tcp_success_rate:.0%} | "
                                f"{result.protocol}"
                            )
                    else:
                        stats.tcp_dead += 1

            except Exception:
                stats.tcp_dead += 1
                record_error("future_exception")

            if done % 500 == 0:
                log(f"  Progress: {done}/{len(all_keys)} | Alive: {stats.tcp_alive}")

    tcp_time = time.time() - tcp_start
    total_time = time.time() - stats.start_time

    save_results(results, args.region)

    print("\n" + "=" * 60)
    print(" RESULTS")
    print("=" * 60)
    print(f"  Unique: {stats.unique} (dupes: {stats.duplicates})")
    print(f"  Checked: {stats.tcp_checked}")
    print(f"  Alive: {stats.tcp_alive} ({stats.tcp_alive * 100 // max(stats.tcp_checked, 1)}%)")
    print(f"  Dead: {stats.tcp_dead}")
    print()

    for q in Quality:
        count = stats.by_quality.get(q, 0)
        if count > 0:
            print(f"  {q.value.upper()}: {count}")
    print()

    for proto, count in sorted(stats.by_protocol.items(), key=lambda x: -x[1]):
        print(f"  {proto}: {count}")
    print()

    print(f"  Time: {tcp_time:.1f}s ({total_time / 60:.1f} min total)")

    if stats.errors:
        print("\n  Error breakdown:")
        for error, count in sorted(stats.errors.items(), key=lambda x: -x[1])[:5]:
            print(f"    {error}: {count}")

    print("=" * 60)

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
