import os
import sys
import json
import time
import random
import requests
import subprocess
import base64
from datetime import datetime
from urllib.parse import unquote

# === НАСТРОЙКИ ===
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FOLDER = os.path.join(WORK_DIR, "results")
XRAY_FOLDER = os.path.join(WORK_DIR, "xray")

# === ЖЕСТКИЕ УСЛОВИЯ ===
MAX_LATENCY_STRICT = 500         # Максимум 500ms (было 2000)
MIN_SPEED_MBPS = 5.0             # Минимум 5 Mbps
STABILITY_CHECKS = 5             # 5 проверок
STABILITY_SUCCESS_RATE = 0.9     # 90% успеха
CONNECTION_TIMEOUT = 3

timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
OUTPUT_FILE = os.path.join(RESULTS_FOLDER, f"premium_{timestamp}.txt")
STATS_FILE = os.path.join(RESULTS_FOLDER, f"premium_stats_{timestamp}.json")

stats = {
    "source_keys": 0,
    "latency_failed": 0,
    "speed_failed": 0,
    "stability_failed": 0,
    "passed": 0,
    "total_time": 0
}

def log(msg):
    print(msg)

# ========== КОПИРУЕМ ФУНКЦИИ ИЗ check_proxies.py ==========

def parse_vless(key):
    """Парсер VLESS из check_proxies.py"""
    try:
        if not key.startswith("vless://"):
            return None
        key = key[8:]
        if "@" not in key:
            return None
        
        uuid_part, rest = key.split("@", 1)
        
        if "?" in rest:
            server_part, params_part = rest.split("?", 1)
        else:
            server_part = rest
            params_part = ""
        
        if "#" in params_part:
            params_part = params_part.split("#")[0]
        if "#" in server_part:
            server_part = server_part.split("#")[0]
        
        if ":" not in server_part:
            return None
        
        host, port = server_part.rsplit(":", 1)
        port = int(port)
        
        params = {}
        if params_part:
            for param in params_part.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    params[k] = unquote(v)
        
        config = {
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
                "network": params.get("type", "tcp"),
                "security": params.get("security", "none")
            }
        }
        
        if params.get("security") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": params.get("sni", host),
                "allowInsecure": params.get("allowInsecure", "0") == "1"
            }
        
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)}
            }
        
        return config
    except:
        return None

def parse_vmess(key):
    """Парсер VMess из check_proxies.py"""
    try:
        if not key.startswith("vmess://"):
            return None
        
        encoded = key[8:]
        if "#" in encoded:
            encoded = encoded.split("#")[0]
        
        padding = len(encoded) % 4
        if padding:
            encoded += '=' * (4 - padding)
        
        decoded = base64.b64decode(encoded).decode('utf-8')
        data = json.loads(decoded)
        
        config = {
            "protocol": "vmess",
            "settings": {
                "vnext": [{
                    "address": data.get("add"),
                    "port": int(data.get("port", 443)),
                    "users": [{
                        "id": data.get("id"),
                        "alterId": int(data.get("aid", 0)),
                        "security": data.get("scy", "auto")
                    }]
                }]
            },
            "streamSettings": {
                "network": data.get("net", "tcp"),
                "security": data.get("tls", "")
            }
        }
        
        if data.get("tls") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": data.get("sni", data.get("add")),
                "allowInsecure": data.get("allowInsecure", False)
            }
        
        if data.get("net") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": data.get("path", "/"),
                "headers": {"Host": data.get("host", data.get("add"))}
            }
        
        return config
    except:
        return None

def parse_trojan(key):
    """Парсер Trojan из check_proxies.py"""
    try:
        if not key.startswith("trojan://"):
            return None
        
        key = key[9:]
        if "@" not in key:
            return None
        
        password, rest = key.split("@", 1)
        
        if "?" in rest:
            server_part, params_part = rest.split("?", 1)
        else:
            server_part = rest
            params_part = ""
        
        if "#" in params_part:
            params_part = params_part.split("#")[0]
        if "#" in server_part:
            server_part = server_part.split("#")[0]
        
        if ":" not in server_part:
            return None
        
        host, port = server_part.rsplit(":", 1)
        port = int(port)
        
        params = {}
        if params_part:
            for param in params_part.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    params[k] = unquote(v)
        
        security = params.get("security", "tls")
        if security == "none" or security == "":
            security = "tls"
        
        config = {
            "protocol": "trojan",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": port,
                    "password": password
                }]
            },
            "streamSettings": {
                "network": params.get("type", "tcp"),
                "security": security
            }
        }
        
        if security == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": params.get("sni", host),
                "allowInsecure": params.get("allowInsecure", "0") == "1"
            }
        
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)}
            }
        
        return config
    except:
        return None

def parse_shadowsocks(key):
    """Парсер Shadowsocks из check_proxies.py (упрощенный)"""
    try:
        if not key.startswith("ss://"):
            return None
        
        key = key[5:]
        if "#" in key:
            key = key.split("#")[0]
        
        if "@" in key:
            encoded, server = key.rsplit("@", 1)
            if ":" not in server:
                return None
            
            host, port = server.rsplit(":", 1)
            port = int(port)
            
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            
            decoded = base64.b64decode(encoded).decode('utf-8')
            if ":" in decoded:
                method, password = decoded.split(":", 1)
            else:
                return None
        else:
            return None
        
        config = {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": port,
                    "method": method,
                    "password": password
                }]
            },
            "streamSettings": {
                "network": "tcp"
            }
        }
        
        return config
    except:
        return None

def parse_proxy_key(key):
    """Парсинг ключа с определением протокола"""
    key_lower = key.lower()
    
    if key_lower.startswith("vless://"):
        config = parse_vless(key)
        return (config, "VLESS") if config else (None, None)
    elif key_lower.startswith("vmess://"):
        config = parse_vmess(key)
        return (config, "VMess") if config else (None, None)
    elif key_lower.startswith("trojan://"):
        config = parse_trojan(key)
        return (config, "Trojan") if config else (None, None)
    elif key_lower.startswith("ss://"):
        config = parse_shadowsocks(key)
        return (config, "SS") if config else (None, None)
    
    return None, None

def create_xray_config(proxy_config, socks_port=10808):
    """Создание конфига Xray"""
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": True}
        }],
        "outbounds": [proxy_config]
    }

def kill_process(process):
    """Убить процесс"""
    if not process:
        return
    try:
        process.terminate()
        process.wait(timeout=1)
    except:
        try:
            process.kill()
            process.wait(timeout=1)
        except:
            pass

def safe_remove_file(filepath):
    """Безопасное удаление файла"""
    try:
        if os.path.exists(filepath):
            os.remove(filepath)
    except:
        pass

# ========== ФУНКЦИИ ЖЕСТКОЙ ПРОВЕРКИ ==========

def find_latest_verified():
    """Найти последний verified файл"""
    if not os.path.exists(RESULTS_FOLDER):
        return None
    
    verified_files = [
        f for f in os.listdir(RESULTS_FOLDER)
        if f.startswith("verified_") and f.endswith(".txt")
    ]
    
    if not verified_files:
        return None
    
    latest = max(
        verified_files,
        key=lambda f: os.path.getmtime(os.path.join(RESULTS_FOLDER, f))
    )
    
    return os.path.join(RESULTS_FOLDER, latest)

def advanced_latency_check(key, xray_exe):
    """Проверка латентности с жесткими требованиями"""
    try:
        proxy_config, protocol = parse_proxy_key(key)
        if not proxy_config:
            return None
        
        socks_port = random.randint(30000, 40000)
        config = create_xray_config(proxy_config, socks_port)
        config_file = os.path.join(XRAY_FOLDER, f"adv_{socks_port}.json")
        
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        
        process = subprocess.Popen(
            [xray_exe, "run", "-c", config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        time.sleep(0.5)
        
        if process.poll() is not None:
            safe_remove_file(config_file)
            return None
        
        proxies = {
            'http': f'socks5://127.0.0.1:{socks_port}',
            'https': f'socks5://127.0.0.1:{socks_port}'
        }
        
        latencies = []
        
        for _ in range(3):
            try:
                start = time.time()
                r = requests.get(
                    'http://www.gstatic.com/generate_204',
                    proxies=proxies,
                    timeout=CONNECTION_TIMEOUT,
                    allow_redirects=False
                )
                latency = int((time.time() - start) * 1000)
                
                if r.status_code in [200, 204]:
                    latencies.append(latency)
            except:
                pass
            
            time.sleep(0.2)
        
        kill_process(process)
        safe_remove_file(config_file)
        
        if len(latencies) >= 2:
            avg_latency = sum(latencies) / len(latencies)
            
            if avg_latency <= MAX_LATENCY_STRICT:
                return {
                    'key': key,
                    'protocol': protocol,
                    'avg_latency': round(avg_latency, 1),
                    'config': proxy_config
                }
        
        stats["latency_failed"] += 1
        return None
        
    except:
        return None

def advanced_stability_check(proxy_data, xray_exe):
    """Проверка стабильности"""
    try:
        proxy_config = proxy_data['config']
        success_count = 0
        
        for i in range(STABILITY_CHECKS):
            socks_port = random.randint(30000, 40000)
            config = create_xray_config(proxy_config, socks_port)
            config_file = os.path.join(XRAY_FOLDER, f"stab_{socks_port}.json")
            
            with open(config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            
            process = subprocess.Popen(
                [xray_exe, "run", "-c", config_file],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(0.5)
            
            proxies = {
                'http': f'socks5://127.0.0.1:{socks_port}',
                'https': f'socks5://127.0.0.1:{socks_port}'
            }
            
            try:
                r = requests.get(
                    'http://www.gstatic.com/generate_204',
                    proxies=proxies,
                    timeout=CONNECTION_TIMEOUT,
                    allow_redirects=False
                )
                if r.status_code in [200, 204]:
                    success_count += 1
            except:
                pass
            
            kill_process(process)
            safe_remove_file(config_file)
            time.sleep(0.3)
        
        success_rate = success_count / STABILITY_CHECKS
        
        if success_rate >= STABILITY_SUCCESS_RATE:
            proxy_data['stability_rate'] = round(success_rate, 2)
            return proxy_data
        
        stats["stability_failed"] += 1
        return None
        
    except:
        stats["stability_failed"] += 1
        return None

def main():
    start_time = time.time()
    
    print("\n" + "="*80)
    print(" "*25 + "🔥 ADVANCED KEY CHECKER")
    print("="*80 + "\n")
    
    xray_exe = os.path.join(XRAY_FOLDER, "xray.exe" if os.name == 'nt' else "xray")
    if not os.path.exists(xray_exe):
        log("❌ XRAY не найден")
        return 1
    
    source_file = find_latest_verified()
    if not source_file:
        log("❌ Не найден verified файл в results/")
        return 1
    
    log(f"📁 Источник: {os.path.basename(source_file)}")
    
    with open(source_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    keys = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            if '#' in line:
                key = line.split('#')[0].strip()
            else:
                key = line
            keys.append(key)
    
    stats["source_keys"] = len(keys)
    log(f"📦 Загружено ключей: {len(keys)}\n")
    
    premium_keys = []
    
    log("=" * 80)
    log("🔍 Начинаем жесткую проверку...")
    log("=" * 80 + "\n")
    
    for idx, key in enumerate(keys, 1):
        log(f"[{idx}/{len(keys)}] Проверка...")
        
        result = advanced_latency_check(key, xray_exe)
        if not result:
            log(f"  ❌ Латентность > {MAX_LATENCY_STRICT}ms")
            continue
        
        log(f"  ✅ Латентность: {result['avg_latency']}ms")
        
        result = advanced_stability_check(result, xray_exe)
        if not result:
            log(f"  ❌ Стабильность < {STABILITY_SUCCESS_RATE*100}%")
            continue
        
        log(f"  ✅ Стабильность: {result['stability_rate']*100}%")
        
        premium_keys.append(key)
        stats["passed"] += 1
        log(f"  🌟 ПРЕМИУМ КЛЮЧ #{stats['passed']}\n")
    
    if premium_keys:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write(f"# Premium Keys - Advanced Check\n")
            f.write(f"# Date: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# Source: {len(keys)} keys\n")
            f.write(f"# Passed: {len(premium_keys)} keys\n\n")
            
            for key in premium_keys:
                f.write(key + "\n")
        
        log(f"\n✅ Сохранено premium ключей: {len(premium_keys)}")
        log(f"📄 Файл: {os.path.basename(OUTPUT_FILE)}")
    
    stats["total_time"] = int(time.time() - start_time)
    
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats, f, indent=2)
    
    print("\n" + "="*80)
    print("📊 СТАТИСТИКА")
    print("="*80)
    print(f"Исходных ключей:       {stats['source_keys']}")
    print(f"Прошло проверку:       {stats['passed']} ({stats['passed']/stats['source_keys']*100:.1f}%)")
    print(f"Отсев по латентности:  {stats['latency_failed']}")
    print(f"Отсев по стабильности: {stats['stability_failed']}")
    print(f"Время работы:          {stats['total_time']} сек")
    print("="*80 + "\n")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
