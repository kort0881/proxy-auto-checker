#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
PRIMARY PREFILTER v2 (ALL) - Быстрая фильтрация мусора перед тяжёлым RF-чекером
Источники: чанки из checked/ALL второго репо (vpn-checker-backend)
"""

import os
import sys
import html
import time
import json
import base64
import socket
import random
import signal
import atexit
import threading
import subprocess
import requests
import concurrent.futures

from pathlib import Path
from datetime import datetime
from urllib.parse import unquote, quote
from collections import defaultdict
from queue import Queue, Empty

# ==================== CONFIG ====================
WORK_DIR = Path(__file__).resolve().parent
XRAY_FOLDER = WORK_DIR / "xray"
RESULTS_FOLDER = WORK_DIR / "results"

XRAY_FOLDER.mkdir(parents=True, exist_ok=True)
RESULTS_FOLDER.mkdir(parents=True, exist_ok=True)

# Все чанки из checked/ALL второго репо (ALL_all_part*.txt)
BASE_ALL_URL = "https://raw.githubusercontent.com/kort0881/vpn-checker-backend/main/checked/ALL"
MAX_PART = 1000  # верхний предел, лишние просто дадут 404 в логах

KEY_SOURCES = {
    "ALL": [
        f"{BASE_ALL_URL}/ALL_all_part{i}.txt"
        for i in range(1, MAX_PART + 1)
    ]
}

MY_CHANNEL = "@vlesstrojan"

class Config:
    # Лимиты
    MAX_RUNTIME_MINUTES = 90
    MAX_KEYS_TO_CHECK = 5000

    # Stage 1: TCP
    TCP_WORKERS = 60
    TCP_TIMEOUT = 3
    TCP_RETRIES = 0  # для первички без retry = быстрее

    # Stage 2: XRAY
    XRAY_WORKERS = 12
    XRAY_STARTUP_TIMEOUT = 4.5
    XRAY_REQUEST_TIMEOUT = 8

    # Проверка: только нейтральные URL (1 успех = ок)
    NEUTRAL_URLS = [
        "https://cp.cloudflare.com/generate_204",
        "http://www.gstatic.com/generate_204",
    ]

    # Защита от зависания на мёртвых host:port
    SKIP_HOSTPORT_AFTER_FAILS = 3
    MIN_KEYS_PER_HOSTPORT_BEFORE_SKIP = 3

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

# Process cleanup
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

# ==================== XRAY SETUP ====================
def setup_xray():
    exe_name = "xray.exe" if os.name == "nt" else "xray"

    # 1) Пробуем локальный бинарь в папке xray/
    local_exe = XRAY_FOLDER / exe_name
    if local_exe.exists():
        try:
            if os.name != "nt":
                local_exe.chmod(0o755)
            log(f"[OK] Xray found (local): {local_exe}")
            return local_exe
        except Exception as e:
            log(f"[WARN] Local Xray exists but not usable: {e}")

    # 2) Пробуем скачать, как раньше
    log("[DL] Downloading xray-core...")
    try:
        import platform, zipfile

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
            log("[ERR] Unsupported OS")
            return None

        url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{filename}"
        r = requests.get(url, stream=True, timeout=120)
        r.raise_for_status()

        zip_path = XRAY_FOLDER / "xray.zip"
        with open(zip_path, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)

        import zipfile as _zip
        with _zip.ZipFile(zip_path, "r") as zf:
            zf.extractall(XRAY_FOLDER)

        zip_path.unlink(missing_ok=True)

        if system != "windows":
            local_exe.chmod(0o755)

        log("[OK] Xray installed (downloaded)")
        return local_exe

    except Exception as e:
        log(f"[ERR] Xray setup failed: {e}")
        return None

# ==================== UTILS ====================
def normalize_key(line):
    line = line.strip()
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

# ==================== PARSERS ====================
def parse_vless(uri):
    try:
        if not uri.lower().startswith("vless://"):
            return None, None
        raw = uri[8:]
        if "@" not in raw:
            return None, None

        uuid_part, rest = raw.split("@", 1)
        server_part, params_part = (rest.split("?", 1) + [""])[:2]
        server_part = server_part.split("#", 1)[0]
        params_part = params_part.split("#", 1)[0]

        if ":" not in server_part:
            return None, None
        host, port = server_part.rsplit(":", 1)
        host = host.strip("[]")
        port = int(port)

        params = {}
        if params_part:
            for p in params_part.split("&"):
                if "=" in p:
                    k, v = p.split("=", 1)
                    params[k] = unquote(v)

        network = params.get("type", "tcp")
        security = params.get("security", "none")

        out = {
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
                "network": network,
                "security": security,
            }
        }

        if security == "tls":
            out["streamSettings"]["tlsSettings"] = {
                "serverName": params.get("sni", host),
                "allowInsecure": True,
                "fingerprint": params.get("fp", "chrome"),
            }
        elif security == "reality":
            out["streamSettings"]["realitySettings"] = {
                "serverName": params.get("sni", host),
                "publicKey": params.get("pbk", ""),
                "shortId": params.get("sid", ""),
                "fingerprint": params.get("fp", "chrome"),
            }

        if network == "ws":
            out["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)},
            }
        elif network == "grpc":
            out["streamSettings"]["grpcSettings"] = {
                "serviceName": params.get("serviceName", ""),
                "multiMode": (params.get("mode", "gun") == "multi"),
            }
        elif network == "xhttp":
            out["streamSettings"]["xhttpSettings"] = {
                "path": params.get("path", "/"),
            }

        return out, ("VLESS", host, port)
    except:
        return None, None

def parse_vmess(uri):
    try:
        if not uri.lower().startswith("vmess://"):
            return None, None
        encoded = uri[8:]
        pad = len(encoded) % 4
        if pad:
            encoded += "=" * (4 - pad)
        data = json.loads(base64.b64decode(encoded).decode("utf-8", errors="ignore"))

        host = data.get("add", "")
        port = int(data.get("port", 443))

        out = {
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": host,
                    "port": port,
                    "users": [{
                        "id": data.get("id"),
                        "alterId": int(data.get("aid", 0)),
                        "security": data.get("scy", "auto"),
                    }]
                }]
            },
            "streamSettings": {
                "network": data.get("net", "tcp"),
                "security": "tls" if data.get("tls") else "none",
            }
        }

        if data.get("tls") == "tls":
            out["streamSettings"]["tlsSettings"] = {
                "serverName": data.get("sni", host),
                "allowInsecure": True,
            }
        if data.get("net") == "ws":
            out["streamSettings"]["wsSettings"] = {
                "path": data.get("path", "/"),
                "headers": {"Host": data.get("host", host)},
            }

        return out, ("VMess", host, port)
    except:
        return None, None

def parse_trojan(uri):
    try:
        if not uri.lower().startswith("trojan://"):
            return None, None
        raw = uri[9:]
        if "@" not in raw:
            return None, None

        password, rest = raw.split("@", 1)
        password = unquote(password)

        server_part, params_part = (rest.split("?", 1) + [""])[:2]
        server_part = server_part.split("#", 1)[0]
        params_part = params_part.split("#", 1)[0]

        if ":" not in server_part:
            return None, None
        host, port = server_part.rsplit(":", 1)
        host = host.strip("[]")
        port = int(port)

        params = {}
        if params_part:
            for p in params_part.split("&"):
                if "=" in p:
                    k, v = p.split("=", 1)
                    params[k] = unquote(v)

        out = {
            "protocol": "trojan",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": port,
                    "password": password,
                }]
            },
            "streamSettings": {
                "network": params.get("type", "tcp"),
                "security": "tls",
                "tlsSettings": {
                    "serverName": params.get("sni", host),
                    "allowInsecure": True,
                    "fingerprint": params.get("fp", "chrome"),
                }
            }
        }

        if params.get("type") == "ws":
            out["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)},
            }

        return out, ("Trojan", host, port)
    except:
        return None, None

def parse_ss(uri):
    try:
        if not uri.lower().startswith("ss://"):
            return None, None
        key = uri[5:].split("#", 1)[0]

        method = password = host = None
        port = None

        if "@" in key:
            encoded, server = key.split("@", 1)
            host, port = server.rsplit(":", 1)
            host = host.strip("[]")
            port = int(port)

            pad = len(encoded) % 4
            if pad:
                encoded += "=" * (4 - pad)
            try:
                decoded = base64.b64decode(encoded).decode("utf-8", errors="ignore")
                if ":" in decoded:
                    method, password = decoded.split(":", 1)
                else:
                    return None, None
            except:
                if ":" in encoded:
                    method, password = encoded.split(":", 1)
                else:
                    return None, None
        else:
            pad = len(key) % 4
            if pad:
                key += "=" * (4 - pad)
            decoded = base64.b64decode(key).decode("utf-8", errors="ignore")
            creds, server = decoded.rsplit("@", 1)
            method, password = creds.split(":", 1)
            host, port = server.rsplit(":", 1)
            host = host.strip("[]")
            port = int(port)

        out = {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": port,
                    "method": method,
                    "password": password,
                }]
            },
            "streamSettings": {"network": "tcp"},
        }

        return out, ("SS", host, port)
    except:
        return None, None

def parse_proxy_key(uri):
    ul = uri.lower()
    if ul.startswith("vless://"):
        return parse_vless(uri)
    if ul.startswith("vmess://"):
        return parse_vmess(uri)
    if ul.startswith("trojan://"):
        return parse_trojan(uri)
    if ul.startswith("ss://"):
        return parse_ss(uri)
    return None, None

# ==================== XRAY HELPERS ====================
def create_xray_config(outbound, http_port):
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": http_port,
            "listen": "127.0.0.1",
            "protocol": "http",
            "settings": {"timeout": 15}
        }],
        "outbounds": [outbound],
    }

def wait_for_port(port, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return True
        except:
            time.sleep(0.05)
    return False

_port_lock = threading.Lock()
_next_port = 20000

def alloc_port():
    global _next_port
    with _port_lock:
        p = _next_port
        _next_port += 1
        if _next_port > 50000:
            _next_port = 20000
        return p

# ==================== DOWNLOAD ====================
def download_keys():
    all_keys = []
    seen = set()

    log("[DL] Downloading keys (ALL)...")
    for region, urls in KEY_SOURCES.items():
        log(f"  🌍 {region}:")
        for url in urls:
            try:
                r = requests.get(url, timeout=30)
                r.raise_for_status()
                count = 0

                # HTML-чанк -> строки -> unescape -> split("<br>")
                for raw_line in r.text.splitlines():
                    raw_line = html.unescape(raw_line)
                    for part in raw_line.split("<br>"):
                        n = normalize_key(part)
                        if not n:
                            continue
                        if n in seen:
                            continue
                        seen.add(n)
                        all_keys.append(n)
                        count += 1

                log(f"    ✅ {url.split('/')[-1]}: {count}")
            except Exception as e:
                log(f"    ❌ {url.split('/')[-1]}: {e}")

    if len(all_keys) > CONFIG.MAX_KEYS_TO_CHECK:
        log(f"⚠️  Limited to {CONFIG.MAX_KEYS_TO_CHECK} keys (was {len(all_keys)})")
        all_keys = all_keys[:CONFIG.MAX_KEYS_TO_CHECK]

    log(f"\n📦 Unique keys: {len(all_keys)}")
    return all_keys

# ==================== STAGE 1: TCP ====================
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

# ==================== STAGE 2: XRAY ====================
def xray_check_one(key, xray_exe):
    outbound, meta = parse_proxy_key(key)
    if not outbound or not meta:
        record_error("xray_parse")
        return None

    proto, host, port = meta
    http_port = alloc_port()
    cfg = create_xray_config(outbound, http_port)
    cfg_path = XRAY_FOLDER / f"cfg_{http_port}.json"

    p = None
    try:
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False)

        p = subprocess.Popen(
            [str(xray_exe), "run", "-c", str(cfg_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        register_process(p)

        if not wait_for_port(http_port, CONFIG.XRAY_STARTUP_TIMEOUT):
            record_error("xray_startup")
            return None

        if p.poll() is not None:
            record_error("xray_crash")
            return None

        proxies = {
            "http": f"http://127.0.0.1:{http_port}",
            "https": f"http://127.0.0.1:{http_port}",
        }

        for url in CONFIG.NEUTRAL_URLS:
            try:
                t1 = time.time()
                resp = requests.get(
                    url,
                    proxies=proxies,
                    timeout=CONFIG.XRAY_REQUEST_TIMEOUT,
                    allow_redirects=False,
                )
                if resp.status_code in (200, 204):
                    latency = int((time.time() - t1) * 1000)
                    return {
                        "key": key,
                        "latency": latency,
                        "protocol": proto,
                        "host": host,
                        "port": port,
                    }
            except:
                pass

        record_error("xray_no_204")
        return None

    finally:
        if p:
            unregister_process(p)
            try:
                p.terminate()
                p.wait(timeout=1.5)
            except:
                try:
                    p.kill()
                except:
                    pass
        try:
            cfg_path.unlink(missing_ok=True)
        except:
            pass

# ==================== OUTPUT ====================
def add_comment_to_uri(uri, latency, protocol):
    base = uri.split("#", 1)[0]
    tag = f"prefilter {latency}ms {protocol} {MY_CHANNEL}"
    return f"{base}#{quote(tag, safe='')}"

def save_results(results, ts):
    if not results or len(results) < CONFIG.MIN_RESULTS_TO_SAVE:
        log(f"\n⚠️  Too few results ({len(results)}), not saving")
        return

    results.sort(key=lambda x: x["latency"])

    out_file = RESULTS_FOLDER / f"verified_all_{ts}.txt"
    meta_file = RESULTS_FOLDER / f"verified_all_meta_{ts}.jsonl"

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"# {MY_CHANNEL}\n")
        f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Total: {len(results)}\n#\n\n")
        for r in results:
            f.write(add_comment_to_uri(r["key"], r["latency"], r["protocol"]) + "\n")

    with open(meta_file, "w", encoding="utf-8") as f:
        for r in results:
            meta = {
                "ts": time.time(),
                "latency": r["latency"],
                "protocol": r["protocol"],
                "host": r["host"],
                "port": r["port"],
            }
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")

    log(f"\n💾 Saved: {out_file}")
    log(f"💾 Meta: {meta_file}")

    # стабильный файл для ai_checker_all.py
    latest = RESULTS_FOLDER / "verified_all_latest.txt"
    try:
        latest.unlink(missing_ok=True)
    except Exception:
        pass
    try:
        latest.symlink_to(out_file.name)
    except Exception:
        import shutil
        shutil.copy2(out_file, latest)
    log(f"💾 Latest: {latest}")

# ==================== MAIN ====================
def main():
    global _start_time
    _start_time = time.time()

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    print("\n" + "=" * 70)
    print(" " * 20 + "🔥 PRIMARY PREFILTER v2 (ALL) 🔥")
    print(" " * 25 + f"{MY_CHANNEL}")
    print("=" * 70)
    print("\n⚙️  Config:")
    print(f"   Max time: {CONFIG.MAX_RUNTIME_MINUTES} min")
    print(f"   Max keys: {CONFIG.MAX_KEYS_TO_CHECK}")
    print(f"   TCP: {CONFIG.TCP_WORKERS} workers, {CONFIG.TCP_TIMEOUT}s timeout")
    print(f"   XRAY: {CONFIG.XRAY_WORKERS} workers, {CONFIG.XRAY_REQUEST_TIMEOUT}s timeout")
    print()

    xray_exe = setup_xray()
    if not xray_exe:
        log("❌ Cannot setup xray")
        return 1

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
        for fut in concurrent.futures.as_completed(futures):
            done += 1
            if _stop_flag.is_set() or is_time_exceeded():
                break
            try:
                r = fut.result()
                if r:
                    tcp_alive.append(r)
            except Exception:
                pass

            if done % 250 == 0:
                elapsed = (time.time() - _start_time) / 60.0
                log(f"  📊 TCP: {done}/{len(keys)} | Alive: {len(tcp_alive)} | Time: {elapsed:.1f}m")

    log(f"\n✅ TCP alive: {len(tcp_alive)}/{len(keys)}")

    if not tcp_alive:
        log("❌ No TCP-alive keys")
        return 1

    if _stop_flag.is_set() or is_time_exceeded():
        log("⏰ Time exceeded / interrupted")
        return 0

    # ========== STAGE 2: XRAY ==========
    print("\n" + "=" * 70)
    log("⚡ STAGE 2: XRAY minimal (neutral 204)")
    print("=" * 70 + "\n")

    hp_lock = threading.Lock()
    hp_fails = defaultdict(int)
    hp_seen = defaultdict(int)
    hp_skipped = set()

    results = []
    results_lock = threading.Lock()

    q = Queue()
    for k in tcp_alive:
        q.put(k)

    def worker(tid):
        while not _stop_flag.is_set() and not is_time_exceeded():
            try:
                key = q.get_nowait()
            except Empty:
                return

            host, port = extract_host_port(key)
            hp = f"{host}:{port}" if host and port else ""

            if hp:
                with hp_lock:
                    hp_seen[hp] += 1
                    if hp in hp_skipped:
                        q.task_done()
                        continue

            r = xray_check_one(key, xray_exe)

            if r:
                with results_lock:
                    results.append(r)
                if hp:
                    with hp_lock:
                        hp_fails[hp] = 0
            else:
                if hp:
                    with hp_lock:
                        hp_fails[hp] += 1
                        if (hp_seen[hp] >= CONFIG.MIN_KEYS_PER_HOSTPORT_BEFORE_SKIP and
                            hp_fails[hp] >= CONFIG.SKIP_HOSTPORT_AFTER_FAILS):
                            hp_skipped.add(hp)

            q.task_done()

    threads = []
    for i in range(CONFIG.XRAY_WORKERS):
        t = threading.Thread(target=worker, args=(i,), daemon=True)
        threads.append(t)
        t.start()

    total = len(tcp_alive)
    last_log = 0
    while any(t.is_alive() for t in threads):
        if _stop_flag.is_set() or is_time_exceeded():
            break
        time.sleep(1.0)
        done = total - q.qsize()
        if done - last_log >= 10 or done == total:
            elapsed = (time.time() - _start_time) / 60.0
            with results_lock:
                okc = len(results)
            log(f"  🔥 XRAY: {done}/{total} | OK: {okc} | Skipped HP: {len(hp_skipped)} | Time: {elapsed:.1f}m")
            last_log = done

    _stop_flag.set()
    for t in threads:
        t.join(timeout=0.2)

    # ========== RESULTS ==========
    save_results(results, ts)

    if results:
        print("\n" + "=" * 70)
        print("🎉 RESULTS (ALL)")
        print("=" * 70)
        print(f"  ✅ Alive: {len(results)}")
        print(f"  ⏱️  Total time: {(time.time() - _start_time) / 60:.1f} min")
        print("=" * 70)
        return 0
    else:
        log("\n❌ NO ALIVE KEYS")
        return 1

if __name__ == "__main__":
    try:
        sys.exit(main())
    finally:
        cleanup_all_processes()
