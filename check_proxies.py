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
import concurrent.futures
from datetime import datetime
from urllib.parse import quote, unquote, urlparse, parse_qs, urlencode, urlunparse
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ------------------ Настройки ------------------
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
XRAY_FOLDER = os.path.join(WORK_DIR, "xray")
RESULTS_FOLDER = os.path.join(WORK_DIR, "results")

os.makedirs(XRAY_FOLDER, exist_ok=True)
os.makedirs(RESULTS_FOLDER, exist_ok=True)

# === НАСТРОЙКИ ФИЛЬТРАЦИИ ===
MAX_LATENCY = 2000       # Макс латентность (мс)
TCP_TIMEOUT = 3          # Таймаут TCP
HTTP_TIMEOUT = 5         # Таймаут HTTP
XRAY_STARTUP = 0.8       # Время на запуск

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
RAW_FILE = os.path.join(RESULTS_FOLDER, f"raw_{timestamp}.txt")

stats = {
    "tcp_checked": 0, "tcp_live": 0, "tcp_timeout": 0,
    "xray_checked": 0, "xray_live": 0, "xray_timeout": 0, 
    "total": 0,
    "by_protocol": {},
    "ss_skipped_plugin": 0  # Счётчик SS с неподдерживаемыми плагинами
}

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
        if system != "windows": 
            os.chmod(exe_path, 0o755)
        return exe_path
    except Exception as e:
        log(f"❌ Ошибка установки xray: {e}")
        return None

# ------------------ ИЗВЛЕЧЕНИЕ HOST:PORT ------------------
def extract_host_port(key):
    try:
        for prefix in ["vless://", "vmess://", "trojan://", "ss://"]:
            if key.lower().startswith(prefix):
                key = key[len(prefix):]
                break
        
        # VMess (base64 JSON)
        if "@" not in key and ":" not in key:
            try:
                padding = len(key) % 4
                if padding: 
                    key += '=' * (4 - padding)
                decoded = base64.b64decode(key).decode('utf-8')
                data = json.loads(decoded)
                return data.get("add"), int(data.get("port", 443))
            except: 
                return None, None
        
        if "@" in key: 
            key = key.split("@", 1)[1]
        if "?" in key: 
            key = key.split("?", 1)[0]
        if "#" in key: 
            key = key.split("#", 1)[0]
        
        if ":" in key:
            host, port = key.rsplit(":", 1)
            return host, int(port)
        return None, None
    except: 
        return None, None

# ------------------ СТУПЕНЬ 1: TCP ------------------
def stage1_tcp_check(key):
    stats["tcp_checked"] += 1
    if stats["tcp_checked"] % 100 == 0:
        log(f"📊 TCP: {stats['tcp_checked']}/{stats['total']} | ✅ {stats['tcp_live']} | ⏱️ {stats['tcp_timeout']}")
    
    host, port = extract_host_port(key)
    if not host or not port: 
        return None
    
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(TCP_TIMEOUT)
        sock.connect((host, port))
        stats["tcp_live"] += 1
        return key
    except socket.timeout:
        stats["tcp_timeout"] += 1
        return None
    except: 
        return None
    finally:
        if sock:
            try: 
                sock.close()
            except: 
                pass

# ------------------ ПАРСЕРЫ ------------------

def parse_vless(key):
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
        
        # TLS
        if params.get("security") == "tls":
            tls_settings = {
                "serverName": params.get("sni", host), 
                "allowInsecure": params.get("allowInsecure", "0") == "1"
            }
            if params.get("alpn"):
                tls_settings["alpn"] = [a.strip() for a in params["alpn"].split(",") if a.strip()]
            if params.get("fp"):
                tls_settings["fingerprint"] = params["fp"]
            config["streamSettings"]["tlsSettings"] = tls_settings
            
        # Reality
        elif params.get("security") == "reality":
            config["streamSettings"]["realitySettings"] = {
                "serverName": params.get("sni", host), 
                "publicKey": params.get("pbk", ""), 
                "shortId": params.get("sid", ""), 
                "fingerprint": params.get("fp", "chrome")
            }
        
        # WebSocket
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"), 
                "headers": {"Host": params.get("host", host)}
            }
        # gRPC
        elif params.get("type") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": params.get("serviceName", ""), 
                "multiMode": params.get("mode", "gun") == "multi"
            }
        # TCP с HTTP header
        elif params.get("type") == "tcp" and params.get("headerType") == "http":
            config["streamSettings"]["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "path": [params.get("path", "/")],
                        "headers": {"Host": [params.get("host", host)]}
                    }
                }
            }
        
        return config
    except: 
        return None


def parse_vmess(key):
    try:
        if not key.startswith("vmess://"): 
            return None
        
        encoded = key[8:]
        
        # Убираем фрагмент если есть
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
        
        # TLS
        if data.get("tls") == "tls":
            tls_settings = {
                "serverName": data.get("sni", data.get("add")), 
                "allowInsecure": data.get("allowInsecure", False)
            }
            if data.get("alpn"):
                alpn = data["alpn"]
                if isinstance(alpn, str):
                    tls_settings["alpn"] = [a.strip() for a in alpn.split(",") if a.strip()]
                elif isinstance(alpn, list):
                    tls_settings["alpn"] = alpn
            if data.get("fp"):
                tls_settings["fingerprint"] = data["fp"]
            config["streamSettings"]["tlsSettings"] = tls_settings
        
        # WebSocket
        if data.get("net") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": data.get("path", "/"), 
                "headers": {"Host": data.get("host", data.get("add"))}
            }
        # gRPC
        elif data.get("net") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": data.get("path", "")
            }
        # TCP с HTTP header
        elif data.get("net") == "tcp" and data.get("type") == "http":
            config["streamSettings"]["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "path": [data.get("path", "/")],
                        "headers": {"Host": [data.get("host", data.get("add"))]}
                    }
                }
            }
        
        return config
    except: 
        return None


def parse_trojan(key):
    """Улучшенный парсер Trojan с полной поддержкой TLS/Reality"""
    try:
        if not key.startswith("trojan://"): 
            return None
        
        key = key[9:]
        
        if "@" not in key: 
            return None
        
        password, rest = key.split("@", 1)
        
        # Отделяем параметры
        if "?" in rest: 
            server_part, params_part = rest.split("?", 1)
        else: 
            server_part = rest
            params_part = ""
        
        # Отделяем фрагмент
        if "#" in params_part: 
            params_part = params_part.split("#")[0]
        if "#" in server_part:
            server_part = server_part.split("#")[0]
        
        if ":" not in server_part: 
            return None
        
        host, port = server_part.rsplit(":", 1)
        port = int(port)
        
        # Парсим параметры
        params = {}
        if params_part:
            for param in params_part.split("&"):
                if "=" in param: 
                    k, v = param.split("=", 1)
                    params[k] = unquote(v)
        
        # Определяем тип сети
        network = params.get("type", "tcp")
        
        # Определяем security (Trojan всегда использует TLS по умолчанию)
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
                "network": network, 
                "security": security
            }
        }
        
        # SNI и другие параметры
        sni = params.get("sni") or params.get("peer") or host
        allow_insecure = params.get("allowInsecure", "0") == "1" or params.get("allowInsecure", "false") == "true"
        fingerprint = params.get("fp", "")
        
        # TLS настройки
        if security == "tls":
            tls_settings = {
                "serverName": sni,
                "allowInsecure": allow_insecure
            }
            
            # ALPN
            if params.get("alpn"):
                tls_settings["alpn"] = [a.strip() for a in params["alpn"].split(",") if a.strip()]
            
            # Fingerprint
            if fingerprint:
                tls_settings["fingerprint"] = fingerprint
            
            config["streamSettings"]["tlsSettings"] = tls_settings
            
        # Reality настройки
        elif security == "reality":
            config["streamSettings"]["realitySettings"] = {
                "serverName": sni,
                "publicKey": params.get("pbk", ""),
                "shortId": params.get("sid", ""),
                "fingerprint": fingerprint or "chrome"
            }
        
        # WebSocket
        if network == "ws":
            ws_path = params.get("path", "/")
            ws_host = params.get("host", sni)
            config["streamSettings"]["wsSettings"] = {
                "path": ws_path,
                "headers": {"Host": ws_host}
            }
        
        # gRPC
        elif network == "grpc":
            service_name = params.get("serviceName") or params.get("path", "")
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": service_name,
                "multiMode": params.get("mode", "gun") == "multi"
            }
        
        # TCP с HTTP маскировкой
        elif network == "tcp" and params.get("headerType") == "http":
            config["streamSettings"]["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "path": [params.get("path", "/")],
                        "headers": {"Host": [params.get("host", host)]}
                    }
                }
            }
        
        return config
    except: 
        return None


def parse_shadowsocks(key):
    """Улучшенный парсер Shadowsocks с поддержкой плагинов и SIP002"""
    try:
        if not key.startswith("ss://"): 
            return None
        
        key = key[5:]
        
        # Отделяем фрагмент (имя)
        fragment = ""
        if "#" in key:
            key, fragment = key.rsplit("#", 1)
        
        # Отделяем плагин если есть
        plugin = None
        plugin_opts = {}
        
        if "?" in key:
            key, query = key.split("?", 1)
            query_params = {}
            for param in query.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    query_params[k] = unquote(v)
            
            plugin_str = query_params.get("plugin", "")
            if plugin_str:
                # Формат: plugin_name;opt1=val1;opt2=val2
                plugin_parts = plugin_str.split(";")
                plugin = plugin_parts[0]
                for part in plugin_parts[1:]:
                    if "=" in part:
                        pk, pv = part.split("=", 1)
                        plugin_opts[pk] = pv
                    else:
                        plugin_opts[part] = "true"
        
        # Парсим основную часть
        host = None
        port = None
        method = None
        password = None
        
        if "@" in key:
            # SIP002 формат: base64(method:password)@host:port
            encoded, server = key.rsplit("@", 1)
            
            if ":" not in server:
                return None
            
            host, port = server.rsplit(":", 1)
            port = int(port)
            
            # Декодируем credentials
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            
            try:
                decoded = base64.b64decode(encoded).decode('utf-8')
                if ":" in decoded:
                    method, password = decoded.split(":", 1)
                else:
                    return None
            except:
                # Может быть URL-encoded или plain text
                try:
                    decoded = unquote(encoded)
                    if ":" in decoded:
                        method, password = decoded.split(":", 1)
                    else:
                        return None
                except:
                    return None
        else:
            # Legacy формат: base64(method:password@host:port)
            padding = len(key) % 4
            if padding:
                key += '=' * (4 - padding)
            
            try:
                decoded = base64.b64decode(key).decode('utf-8')
            except:
                return None
            
            if "@" not in decoded:
                return None
            
            creds, server = decoded.rsplit("@", 1)
            
            if ":" not in creds or ":" not in server:
                return None
            
            method, password = creds.split(":", 1)
            host, port = server.rsplit(":", 1)
            port = int(port)
        
        # Проверяем что всё распарсилось
        if not all([host, port, method, password]):
            return None
        
        # Базовый конфиг
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
        
        # Обработка плагинов
        if plugin:
            plugin_lower = plugin.lower()
            
            # v2ray-plugin / xray-plugin
            if "v2ray" in plugin_lower or "xray" in plugin_lower:
                mode = plugin_opts.get("mode", "websocket")
                
                if mode in ["websocket", "ws"]:
                    config["streamSettings"]["network"] = "ws"
                    
                    ws_settings = {
                        "path": plugin_opts.get("path", "/")
                    }
                    
                    ws_host = plugin_opts.get("host", host)
                    if ws_host:
                        ws_settings["headers"] = {"Host": ws_host}
                    
                    config["streamSettings"]["wsSettings"] = ws_settings
                    
                    # TLS
                    if plugin_opts.get("tls") == "true" or plugin_opts.get("tls") == "1":
                        config["streamSettings"]["security"] = "tls"
                        config["streamSettings"]["tlsSettings"] = {
                            "serverName": plugin_opts.get("host", host),
                            "allowInsecure": True
                        }
                        
                elif mode == "grpc":
                    config["streamSettings"]["network"] = "grpc"
                    config["streamSettings"]["grpcSettings"] = {
                        "serviceName": plugin_opts.get("serviceName", plugin_opts.get("path", ""))
                    }
                    
                    if plugin_opts.get("tls") == "true":
                        config["streamSettings"]["security"] = "tls"
                        config["streamSettings"]["tlsSettings"] = {
                            "serverName": plugin_opts.get("host", host),
                            "allowInsecure": True
                        }
            
            # simple-obfs / obfs-local - xray НЕ поддерживает
            elif "obfs" in plugin_lower:
                stats["ss_skipped_plugin"] += 1
                return None
            
            # kcptun - xray НЕ поддерживает
            elif "kcptun" in plugin_lower:
                stats["ss_skipped_plugin"] += 1
                return None
        
        return config
        
    except Exception as e:
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
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": socks_port, 
            "listen": "127.0.0.1", 
            "protocol": "socks", 
            "settings": {"udp": True}  # Включаем UDP для SS
        }],
        "outbounds": [proxy_config]
    }


def kill_process(process):
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


# ------------------ СТУПЕНЬ 2: XRAY ПРОВЕРКА ------------------
def stage2_xray_check(key, xray_exe):
    stats["xray_checked"] += 1
    if stats["xray_checked"] % 10 == 0:
        log(f"🔥 XRAY: {stats['xray_checked']}/{stats['tcp_live']} | ✅ {stats['xray_live']} | ⏱️ {stats['xray_timeout']}")
    
    proxy_config, protocol = parse_proxy_key(key)
    if not proxy_config: 
        return None
    
    socks_port = random.randint(20000, 30000)
    config = create_xray_config(proxy_config, socks_port)
    config_file = os.path.join(XRAY_FOLDER, f"config_{socks_port}.json")
    process = None
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f: 
            json.dump(config, f, indent=2)
        
        process = subprocess.Popen(
            [xray_exe, "run", "-c", config_file], 
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        time.sleep(XRAY_STARTUP)
        
        if process.poll() is not None:
            try: 
                os.remove(config_file)
            except: 
                pass
            return None
        
        proxies = {
            'http': f'socks5://127.0.0.1:{socks_port}', 
            'https': f'socks5://127.0.0.1:{socks_port}'
        }
        
        tests = [
            ('http://www.gstatic.com/generate_204', 'gstatic'), 
            ('http://cp.cloudflare.com/generate_204', 'cloudflare'), 
            ('http://connectivitycheck.android.com/generate_204', 'android')
        ]
        
        success_count = 0
        first_latency = None
        
        for url, name in tests:
            try:
                start = time.time()
                r = requests.get(url, proxies=proxies, timeout=HTTP_TIMEOUT, allow_redirects=False)
                latency = int((time.time() - start) * 1000)
                if r.status_code in [200, 204]:
                    success_count += 1
                    if first_latency is None: 
                        first_latency = latency
            except requests.exceptions.Timeout:
                stats["xray_timeout"] += 1
                if success_count == 0:
                    kill_process(process)
                    try: 
                        os.remove(config_file)
                    except: 
                        pass
                    return None
            except: 
                pass
        
        kill_process(process)
        try: 
            os.remove(config_file)
        except: 
            pass
        
        if success_count >= 2 and first_latency and first_latency < MAX_LATENCY:
            stats["xray_live"] += 1
            stats["by_protocol"][protocol] = stats["by_protocol"].get(protocol, 0) + 1
            
            if first_latency < 300: 
                quality = "fast"
            elif first_latency < 800: 
                quality = "good"
            elif first_latency < 1500: 
                quality = "ok"
            else: 
                quality = "slow"
            
            if protocol in ["VLESS", "VMess"]:
                host = proxy_config["settings"]["vnext"][0]["address"]
                port = proxy_config["settings"]["vnext"][0]["port"]
            else:
                host = proxy_config["settings"]["servers"][0]["address"]
                port = proxy_config["settings"]["servers"][0]["port"]
            
            return (first_latency, quality, protocol, host, port, key)
        
        return None
        
    except Exception:
        kill_process(process)
        try: 
            os.remove(config_file)
        except: 
            pass
        return None


def download_keys():
    all_keys = []
    log("📥 Загрузка ключей...")
    
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
                log(f"  ❌ {e}")
    
    all_keys = list(set(all_keys))
    log(f"\n📦 Уникальных: {len(all_keys)}")
    return all_keys


# ------------------ ФУНКЦИИ ДЛЯ КОММЕНТАРИЕВ ------------------
def add_comment_to_uri(uri: str, latency: int, quality: str, protocol: str) -> str:
    """Добавление комментария к URI"""
    
    tag = f"[{latency}ms {quality} {protocol} {MY_CHANNEL}]"
    
    # VMess - меняем поле ps внутри JSON
    if uri.lower().startswith("vmess://"):
        try:
            b64_part = uri[8:]
            if "#" in b64_part:
                b64_part = b64_part.split("#")[0]
            
            padding = len(b64_part) % 4
            if padding: 
                b64_part += '=' * (4 - padding)
            
            json_str = base64.b64decode(b64_part).decode('utf-8')
            data = json.loads(json_str)
            data['ps'] = tag
            
            new_json = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
            new_b64 = base64.b64encode(new_json.encode('utf-8')).decode('utf-8')
            return f"vmess://{new_b64}"
        except:
            pass
    
    # Остальные - добавляем фрагмент
    base_uri = uri.split("#")[0]
    return f"{base_uri}#{quote(tag)}"


def get_raw_key(uri: str) -> str:
    """Получить ключ без комментария"""
    if uri.lower().startswith("vmess://"):
        try:
            b64_part = uri[8:]
            if "#" in b64_part:
                b64_part = b64_part.split("#")[0]
            
            padding = len(b64_part) % 4
            if padding: 
                b64_part += '=' * (4 - padding)
            
            json_str = base64.b64decode(b64_part).decode('utf-8')
            data = json.loads(json_str)
            data['ps'] = ""
            
            new_json = json.dumps(data, separators=(',', ':'), ensure_ascii=False)
            new_b64 = base64.b64encode(new_json.encode('utf-8')).decode('utf-8')
            return f"vmess://{new_b64}"
        except:
            return uri.split("#")[0]
    
    return uri.split("#")[0]


# ------------------ MAIN ------------------
def main():
    print("\n" + "="*70)
    print(" " * 10 + "🔥 XRAY CHECKER [SS/TROJAN FIX] 🔥")
    print("="*70)
    print(f"⚙️  TCP: {TCP_TIMEOUT}s | HTTP: {HTTP_TIMEOUT}s | Max Latency: {MAX_LATENCY}ms")
    print("="*70 + "\n")
    
    xray_exe = setup_xray()
    if not xray_exe: 
        return 1
    
    all_keys = download_keys()
    if not all_keys: 
        return 1
    
    stats["total"] = len(all_keys)
    
    # === СТУПЕНЬ 1: TCP ===
    print("\n" + "="*70)
    log("⚡ СТУПЕНЬ 1: TCP проверка")
    print("="*70 + "\n")
    
    start_time = time.time()
    stage1_results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=150) as executor:
        futures = {executor.submit(stage1_tcp_check, key): key for key in all_keys}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result: 
                stage1_results.append(result)
    
    stage1_time = time.time() - start_time
    log(f"\n✅ TCP: {stats['tcp_live']}/{stats['total']} ({stats['tcp_live']/stats['total']*100:.1f}%) за {stage1_time:.1f}с")
    log(f"   Таймаутов: {stats['tcp_timeout']}")
    
    if not stage1_results: 
        log("❌ Нет живых после TCP")
        return 1
    
    # === СТУПЕНЬ 2: XRAY ===
    print("\n" + "="*70)
    log("⚡ СТУПЕНЬ 2: XRAY + HTTP/204")
    print("="*70 + "\n")
    
    stage2_start = time.time()
    results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=25) as executor:
        futures = {executor.submit(stage2_xray_check, key, xray_exe): key for key in stage1_results}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result: 
                results.append(result)
    
    stage2_time = time.time() - stage2_start
    total_time = time.time() - start_time
    
    if results:
        results.sort(key=lambda x: x[0])
        
        # Файл с тегами
        with open(FINAL_FILE, 'w', encoding='utf-8') as f:
            f.write(f"# {MY_CHANNEL}\n")
            f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Verified: {len(results)} / {stats['total']}\n\n")
            
            for latency, quality, protocol, host, port, key in results:
                f.write(add_comment_to_uri(key, latency, quality, protocol) + "\n")
        
        # Сырой файл
        with open(RAW_FILE, 'w', encoding='utf-8') as f:
            f.write(f"# {MY_CHANNEL} - RAW\n\n")
            for _, _, _, _, _, key in results:
                f.write(get_raw_key(key) + "\n")
        
        # Статистика
        by_quality = {}
        for r in results:
            q = r[1]
            by_quality[q] = by_quality.get(q, 0) + 1
        
        print("\n" + "="*70)
        print("🎉 РЕЗУЛЬТАТЫ")
        print("="*70)
        print(f"📊 TCP: {stats['tcp_live']}/{stats['total']} за {stage1_time:.1f}с")
        print(f"📊 XRAY: {len(results)}/{stats['tcp_live']} за {stage2_time:.1f}с")
        print(f"✅ ИТОГО: {len(results)} рабочих ({len(results)/stats['total']*100:.1f}%)")
        
        if stats["ss_skipped_plugin"] > 0:
            print(f"⚠️  SS с неподдерживаемыми плагинами: {stats['ss_skipped_plugin']}")
        
        print(f"\n📈 По качеству:")
        for q in ['fast', 'good', 'ok', 'slow']:
            if q in by_quality:
                icon = {'fast': '🚀', 'good': '✅', 'ok': '📊', 'slow': '🐢'}[q]
                print(f"   {icon} {q}: {by_quality[q]}")
        
        print(f"\n📈 По протоколам:")
        for proto, count in sorted(stats["by_protocol"].items(), key=lambda x: -x[1]):
            print(f"   • {proto}: {count}")
        
        print(f"\n⏱️  Время: {total_time:.1f}с ({total_time/60:.1f} мин)")
        print(f"📁 С тегами: {FINAL_FILE}")
        print(f"📁 Сырые: {RAW_FILE}")
        print("="*70)
        return 0
    else:
        log("\n❌ НЕТ РАБОЧИХ КЛЮЧЕЙ")
        return 1


if __name__ == "__main__":
    exit(main())



