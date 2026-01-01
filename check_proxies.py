import os
import re
import html
import socket
import ssl
import time
import sys
import subprocess
import requests
import base64
import json
import random
from datetime import datetime
from urllib.parse import quote, unquote, urlparse, parse_qs, urlencode, urlunparse

# ------------------ Настройки ------------------
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
XRAY_FOLDER = os.path.join(WORK_DIR, "xray")
RESULTS_FOLDER = os.path.join(WORK_DIR, "results")

os.makedirs(XRAY_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

# Источники ключей
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
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FINAL_FILE = os.path.join(RESULTS_FOLDER, f"verified_{timestamp}.txt")

checked = [0]
live = [0]
total = [0]

def log(msg):
    print(msg)

# ------------------ Установка XRAY ------------------
def setup_xray():
    exe_path = os.path.join(XRAY_FOLDER, "xray.exe" if os.name == 'nt' else "xray")
    
    if os.path.exists(exe_path):
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
            arch = "64" if "64" in machine or "aarch64" in machine or "x86_64" in machine else "32"
            filename = f"Xray-linux-{arch}.zip"
        else:
            log("❌ Неподдерживаемая ОС")
            return None
        
        url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{filename}"
        
        r = requests.get(url, stream=True, timeout=120)
        zip_path = os.path.join(XRAY_FOLDER, "xray.zip")
        
        with open(zip_path, 'wb') as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)
        
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(XRAY_FOLDER)
        
        os.remove(zip_path)
        
        # Права на выполнение для Linux
        if system != "windows":
            os.chmod(exe_path, 0o755)
        
        log("✅ Xray установлен")
        return exe_path
        
    except Exception as e:
        log(f"❌ Ошибка установки xray: {e}")
        return None

# ------------------ ПАРСЕРЫ ПРОТОКОЛОВ ------------------
def parse_vless(key):
    """Парсинг VLESS"""
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
        elif params.get("security") == "reality":
            config["streamSettings"]["realitySettings"] = {
                "serverName": params.get("sni", host),
                "publicKey": params.get("pbk", ""),
                "shortId": params.get("sid", ""),
                "fingerprint": params.get("fp", "chrome")
            }
        
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)}
            }
        elif params.get("type") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": params.get("serviceName", ""),
                "multiMode": params.get("mode", "gun") == "multi"
            }
        
        return config
        
    except:
        return None

def parse_vmess(key):
    """Парсинг VMess"""
    try:
        if not key.startswith("vmess://"):
            return None
        
        encoded = key[8:]
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
        elif data.get("net") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": data.get("path", "")
            }
        
        return config
        
    except:
        return None

def parse_trojan(key):
    """Парсинг Trojan"""
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
                "security": "tls"
            }
        }
        
        config["streamSettings"]["tlsSettings"] = {
            "serverName": params.get("sni", host),
            "allowInsecure": params.get("allowInsecure", "0") == "1"
        }
        
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)}
            }
        elif params.get("type") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": params.get("serviceName", "")
            }
        
        return config
        
    except:
        return None

def parse_shadowsocks(key):
    """Парсинг Shadowsocks"""
    try:
        if not key.startswith("ss://"):
            return None
        
        key = key[5:]
        
        if "@" in key:
            encoded, rest = key.split("@", 1)
            
            if "#" in rest:
                rest = rest.split("#")[0]
            
            if ":" not in rest:
                return None
            
            host, port = rest.rsplit(":", 1)
            port = int(port)
            
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            
            decoded = base64.b64decode(encoded).decode('utf-8')
            
            if ":" not in decoded:
                return None
            
            method, password = decoded.split(":", 1)
        else:
            if "#" in key:
                key = key.split("#")[0]
            
            padding = len(key) % 4
            if padding:
                key += '=' * (4 - padding)
            
            decoded = base64.b64decode(key).decode('utf-8')
            
            if "@" not in decoded or ":" not in decoded:
                return None
            
            creds, server = decoded.rsplit("@", 1)
            method, password = creds.split(":", 1)
            host, port = server.rsplit(":", 1)
            port = int(port)
        
        config = {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": port,
                    "method": method,
                    "password": password
                }]
            }
        }
        
        return config
        
    except:
        return None

def parse_proxy_key(key):
    """Универсальный парсер"""
    key_lower = key.lower()
    
    if key_lower.startswith("vless://"):
        return parse_vless(key), "VLESS"
    elif key_lower.startswith("vmess://"):
        return parse_vmess(key), "VMess"
    elif key_lower.startswith("trojan://"):
        return parse_trojan(key), "Trojan"
    elif key_lower.startswith("ss://"):
        return parse_shadowsocks(key), "SS"
    
    return None, None

def create_xray_config(proxy_config, socks_port=10808):
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": socks_port,
            "listen": "127.0.0.1",
            "protocol": "socks",
            "settings": {"udp": False}
        }],
        "outbounds": [proxy_config]
    }

def test_key_with_xray(key, xray_exe):
    checked[0] += 1
    
    proxy_config, protocol = parse_proxy_key(key)
    if not proxy_config:
        return None
    
    socks_port = random.randint(20000, 30000)
    config = create_xray_config(proxy_config, socks_port)
    config_file = os.path.join(XRAY_FOLDER, f"config_{socks_port}.json")
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
        
        process = subprocess.Popen(
            [xray_exe, "run", "-c", config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        
        time.sleep(1.5)
        
        start = time.time()
        success = False
        
        try:
            proxies = {
                'http': f'socks5://127.0.0.1:{socks_port}',
                'https': f'socks5://127.0.0.1:{socks_port}'
            }
            
            response = requests.get(
                'http://www.gstatic.com/generate_204',
                proxies=proxies,
                timeout=10,
                allow_redirects=False
            )
            
            if response.status_code in [200, 204]:
                latency = int((time.time() - start) * 1000)
                success = True
        except:
            pass
        
        process.terminate()
        try:
            process.wait(timeout=2)
        except:
            process.kill()
        
        try:
            os.remove(config_file)
        except:
            pass
        
        if success:
            live[0] += 1
            quality = "good" if latency < 150 else "normal" if latency < 400 else "weak"
            
            if protocol in ["VLESS", "VMess"]:
                host = proxy_config["settings"]["vnext"][0]["address"]
                port = proxy_config["settings"]["vnext"][0]["port"]
            else:
                host = proxy_config["settings"]["servers"][0]["address"]
                port = proxy_config["settings"]["servers"][0]["port"]
            
            log(f"✅ {protocol} {host}:{port} | {latency}ms | {quality}")
            return (latency, quality, protocol, host, port, key)
        
        return None
        
    except Exception as e:
        try:
            process.kill()
        except:
            pass
        try:
            os.remove(config_file)
        except:
            pass
        return None

def download_keys():
    all_keys = []
    
    log("📥 Загрузка ключей из GitHub...")
    
    for region, urls in KEY_SOURCES.items():
        log(f"\n🌍 {region}:")
        for url in urls:
            try:
                r = requests.get(url, timeout=30)
                lines = r.text.strip().split('\n')
                
                for line in lines:
                    line = html.unescape(line.strip())
                    if line and line.lower().startswith(("vless://", "vmess://", "trojan://", "ss://")):
                        all_keys.append(line)
                
                log(f"  ✅ {url.split('/')[-1]}: {len(lines)} строк")
            except Exception as e:
                log(f"  ❌ Ошибка: {e}")
    
    all_keys = list(set(all_keys))
    log(f"\n📦 Всего уникальных ключей: {len(all_keys)}")
    
    return all_keys

def add_comment_to_uri(uri: str, latency: int, quality: str, protocol: str) -> str:
    if "#" in uri:
        base = uri.split("#")[0]
    else:
        base = uri
    new_tag = f"[{latency}ms {quality} {protocol} {MY_CHANNEL}]"
    return f"{base}#{quote(new_tag, safe=' @[]-_./=')}"

def main():
    print("\n" + "="*70)
    print(" " * 8 + "🔥 XRAY-BASED AUTO PROXY CHECKER 🔥")
    print("="*70 + "\n")
    
    xray_exe = setup_xray()
    if not xray_exe:
        log("❌ Не удалось установить xray")
        return 1
    
    all_keys = download_keys()
    if not all_keys:
        log("❌ Нет ключей для проверки")
        return 1
    
    total[0] = len(all_keys)
    
    print("\n" + "="*70)
    log(f"⚡ Начинаем проверку {total[0]} ключей...")
    log(f"🔧 Потоков: 20")
    print("="*70 + "\n")
    
    start_time = time.time()
    results = []
    
    import concurrent.futures
    with concurrent.futures.ThreadPoolExecutor(max_workers=20) as executor:
        futures = {executor.submit(test_key_with_xray, key, xray_exe): key for key in all_keys}
        
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result:
                results.append(result)
            
            if checked[0] % 10 == 0:
                percent = (checked[0] / total[0] * 100)
                log(f"📊 Прогресс: {checked[0]}/{total[0]} ({percent:.1f}%) | Рабочих: {live[0]}")
    
    elapsed = time.time() - start_time
    
    if results:
        results.sort(key=lambda x: x[0])
        
        with open(FINAL_FILE, 'w', encoding='utf-8') as f:
            f.write(f"# Channel: {MY_CHANNEL}\n")
            f.write(f"# Date: {datetime.now()}\n")
            f.write(f"# Verified: {len(results)} / {total[0]}\n")
            f.write(f"# Method: XRAY-CORE REAL TEST\n\n")
            
            for latency, quality, protocol, host, port, key in results:
                key_with_tag = add_comment_to_uri(key, latency, quality, protocol)
                f.write(key_with_tag + "\n")
        
        print("\n" + "="*70)
        print("🎉 РЕЗУЛЬТАТЫ")
        print("="*70)
        print(f"✅ Проверено: {checked[0]} / {total[0]}")
        print(f"✅ Рабочих: {len(results)} ({len(results)/total[0]*100:.1f}%)")
        print(f"⏱️  Время: {elapsed:.1f}с ({elapsed/60:.1f} мин)")
        print(f"📁 Файл: {FINAL_FILE}")
        print("="*70)
        
        return 0
    else:
        log("\n❌ НЕТ РАБОЧИХ КЛЮЧЕЙ")
        return 1

if __name__ == "__main__":
    exit(main())
