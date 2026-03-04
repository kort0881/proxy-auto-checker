#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PRIMARY PREFILTER v2 (TCP ONLY)
Быстрая фильтрация мусора перед тяжёлым RF-чекером
Задача: TCP alive? → сохранить для второго прогона
"""

import os
import sys
import html
import time
import json
import base64
import socket
import signal
import atexit
import threading
import requests
import concurrent.futures

from pathlib import Path
from datetime import datetime
from urllib.parse import quote
from collections import defaultdict

# ==================== CONFIG ====================
WORK_DIR = Path(__file__).resolve().parent
RESULTS_FOLDER = WORK_DIR / "results"
RESULTS_FOLDER.mkdir(parents=True, exist_ok=True)

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

class Config:
    # Лимиты
    MAX_RUNTIME_MINUTES = 90
    MAX_KEYS_TO_CHECK = 5000

    # TCP
    TCP_WORKERS = 60
    TCP_TIMEOUT = 3
    TCP_RETRIES = 0  # для первички без retry = быстрее

    # Минимум результатов для сохранения
    MIN_RESULTS_TO_SAVE = 5

CONFIG = Config()

# ==================== GLOBALS ====================
_start_time = time.time()
_stop_flag = threading.Event()

def is_time_exceeded():
    return (time.time() - _start_time) / 60.0 >= CONFIG.MAX_RUNTIME_MINUTES

def log(msg):
    print(msg, flush=True)

# Errors
error_stats = defaultdict(int)
error_lock = threading.Lock()

def record_error(name):
    with error_lock:
        error_stats[name] += 1

# Process cleanup (оставляем каркас, но процессов больше не создаём)
_active_processes = []
_proc_lock = threading.Lock()

def register_process(p):
    with _proc_lock:
        _active_processes.append(p)

def unregister_process(p):
    with _proc_lock:
        try:
            _active_processes.remove(p)
        except:
            pass

def cleanup_all_processes():
    with _proc_lock:
        for p in list(_active_processes):
            try:
                p.kill()
                p.wait(timeout=1)
            except:
                pass
        _active_processes.clear()

atexit.register(cleanup_all_processes)

def signal_handler(signum, frame):
    log("\n⚠️  Interrupted! Cleaning up...")
    _stop_flag.set()
    cleanup_all_processes()
    sys.exit(1)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# ==================== UTILS ====================
def normalize_key(line):
    line = html.unescape(line.strip())
    if not line:
        return ""
    if not line.lower().startswith(("vless://", "vmess://", "trojan://", "ss://")):
        return ""
    return line.split("#", 1)[0].strip()

def extract_host_port(key):
    try:
        k = key.strip()

        # vmess base64
        if k.lower().startswith("vmess://"):
            encoded = k[8:]
            pad = len(encoded) % 4
            if pad:
                encoded += "=" * (4 - pad)
            data = json.loads(base64.b64decode(encoded).decode("utf-8", errors="ignore"))
            return data.get("add"), int(data.get("port", 443))

        # strip scheme
        for prefix in ("vless://", "trojan://", "ss://"):
            if k.lower().startswith(prefix):
                k = k[len(prefix):]
                break

        # some ss without @
        if "@" not in k:
            try:
                pad = len(k) % 4
                k2 = k + ("=" * (4 - pad)) if pad else k
                dec = base64.b64decode(k2).decode("utf-8", errors="ignore")
                if "@" in dec:
                    k = dec
            except:
                pass

        if "@" in k:
            k = k.split("@", 1)[1]
        if "?" in k:
            k = k.split("?", 1)[0]
        if "#" in k:
            k = k.split("#", 1)[0]

        if ":" in k:
            host, port = k.rsplit(":", 1)
            return host.strip("[]"), int(port)

        return None, None
    except:
        return None, None

# ==================== DOWNLOAD ====================
def download_keys():
    all_keys = []
    seen = set()

    log("[DL] Downloading keys...")
    for region, urls in KEY_SOURCES.items():
        log(f"  🌍 {region}:")
        for url in urls:
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                count = 0
                for line in r.text.splitlines():
                    n = normalize_key(line)
                    if not n:
                        continue
                    if n in seen:
                        continue
                    seen.add(n)
                    all_keys.append(line.strip())
                    count += 1
                log(f"    ✅ {url.split('/')[-1]}: {count}")
            except Exception as e:
                log(f"    ❌ {url.split('/')[-1]}: {e}")

    if len(all_keys) > CONFIG.MAX_KEYS_TO_CHECK:
        log(f"⚠️  Limited to {CONFIG.MAX_KEYS_TO_CHECK} keys (was {len(all_keys)})")
        all_keys = all_keys[:CONFIG.MAX_KEYS_TO_CHECK]

    log(f"\n📦 Unique keys: {len(all_keys)}")
    return all_keys

# ==================== TCP CHECK ====================
def tcp_check_one(key):
    host, port = extract_host_port(key)
    if not host or not port:
        record_error("parse_error")
        return None

    for _ in range(CONFIG.TCP_RETRIES + 1):
        if _stop_flag.is_set() or is_time_exceeded():
            return None
        try:
            with socket.create_connection((host, port), timeout=CONFIG.TCP_TIMEOUT):
                return key
        except socket.timeout:
            record_error("tcp_timeout")
        except (ConnectionRefusedError, socket.gaierror):
            record_error("tcp_refused")
            return None
        except:
            record_error("tcp_other")
            return None

    return None

# ==================== OUTPUT ====================
def add_comment_to_uri(uri, latency_ms, protocol="TCP"):
    base = uri.split("#", 1)[0]
    tag = f"prefilter {latency_ms}ms {protocol} {MY_CHANNEL}"
    return f"{base}#{quote(tag, safe='')}"

def save_results_tcp_only(keys, ts):
    if not keys or len(keys) < CONFIG.MIN_RESULTS_TO_SAVE:
        log(f"\n⚠️  Too few TCP-alive results ({len(keys)}), not saving")
        return

    out_file = RESULTS_FOLDER / f"verified_{ts}.txt"
    meta_file = RESULTS_FOLDER / f"verified_meta_{ts}.jsonl"

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"# {MY_CHANNEL}\n")
        f.write(f"# {now}\n")
        f.write(f"# Total TCP-alive: {len(keys)}\n#\n\n")
        for k in keys:
            # latency неизвестна, ставим 0ms и протокол TCP
            f.write(add_comment_to_uri(k, 0, "TCP") + "\n")

    with open(meta_file, "w", encoding="utf-8") as f:
        ts_now = time.time()
        for k in keys:
            host, port = extract_host_port(k)
            meta = {
                "ts": ts_now,
                "latency": 0,
                "protocol": "TCP",
                "host": host,
                "port": port,
            }
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")

    log(f"\n💾 Saved (TCP-only): {out_file}")
    log(f"💾 Meta: {meta_file}")

# ==================== MAIN ====================
def main():
    global _start_time
    _start_time = time.time()

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    print("\n" + "=" * 70)
    print(" " * 20 + "🔥 PRIMARY PREFILTER v2 (TCP ONLY) 🔥")
    print(" " * 25 + f"{MY_CHANNEL}")
    print("=" * 70)
    print(f"\n⚙️  Config:")
    print(f"   Max time: {CONFIG.MAX_RUNTIME_MINUTES} min")
    print(f"   Max keys: {CONFIG.MAX_KEYS_TO_CHECK}")
    print(f"   TCP: {CONFIG.TCP_WORKERS} workers, {CONFIG.TCP_TIMEOUT}s timeout")
    print()

    keys = download_keys()
    if not keys:
        log("❌ No keys")
        return 1

    # ========== STAGE 1: TCP ==========
    print("\n" + "=" * 70)
    log("⚡ STAGE 1: TCP check")
    print("=" * 70 + "\n")

    tcp_alive = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.TCP_WORKERS) as ex:
        futures = [ex.submit(tcp_check_one, k) for k in keys]
        done = 0
        total = len(futures)
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            if _stop_flag.is_set() or is_time_exceeded():
                break
            try:
                r = fut.result(timeout=0.1)
                if r:
                    tcp_alive.append(r)
            except:
                pass

            if done % 250 == 0 or done == total:
                elapsed = (time.time() - _start_time) / 60.0
                log(f"  📊 TCP: {done}/{total} | Alive: {len(tcp_alive)} | Time: {elapsed:.1f}m")

    log(f"\n✅ TCP alive: {len(tcp_alive)}/{len(keys)}")

    if not tcp_alive:
        log("❌ No TCP-alive keys")
        return 1

    if _stop_flag.is_set() or is_time_exceeded():
        log("⏰ Time exceeded / interrupted")
        # но TCP-результаты есть — всё равно сохраним
        save_results_tcp_only(tcp_alive, ts)
        return 0

    # Сохраняем только TCP-OK как префильтр
    save_results_tcp_only(tcp_alive, ts)

    print("\n" + "=" * 70)
    print("🎉 TCP PREFILTER RESULTS")
    print("=" * 70)
    print(f"  ✅ TCP-alive: {len(tcp_alive)}")
    print(f"  ⏱️  Total time: {(time.time() - _start_time) / 60:.1f} min")
    print("=" * 70)

    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        cleanup_all_processes()

