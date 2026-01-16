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

# 🔥 НОВОЕ: Тестовые сайты для 4-й ступени
TEST_SITES = {
    "youtube": {
        "url": "https://www.youtube.com/",
        "timeout": 12,
        "min_size": 50000,
        "keywords": ["youtube", "video"]
    },
    "instagram": {
        "url": "https://www.instagram.com/",
        "timeout": 12,
        "min_size": 30000,
        "keywords": ["instagram"]
    },
    "whatsapp": {
        "url": "https://web.whatsapp.com/",
        "timeout": 12,
        "min_size": 20000,
        "keywords": ["whatsapp"]
    },
    "telegram": {
        "url": "https://web.telegram.org/",
        "timeout": 12,
        "min_size": 15000,
        "keywords": ["telegram"]
    },
    "sberbank": {
        "url": "https://www.sberbank.ru/",
        "timeout": 15,
        "min_size": 10000,
        "keywords": ["сбербанк", "sberbank", "sber"]
    },
    "tinkoff": {
        "url": "https://www.tinkoff.ru/",
        "timeout": 15,
        "min_size": 10000,
        "keywords": ["тинькофф", "tinkoff"]
    },
    "google": {
        "url": "https://www.google.com/",
        "timeout": 10,
        "min_size": 5000,
        "keywords": ["google"]
    }
}

MY_CHANNEL = "@vlesstrojan"
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
FINAL_FILE = os.path.join(RESULTS_FOLDER, f"verified_{timestamp}.txt")
SEMI_DEAD_FILE = os.path.join(RESULTS_FOLDER, f"semi_dead_{timestamp}.txt")

# Счетчики
stage1_checked = [0]
stage1_live = [0]
stage2_checked = [0]
stage2_live = [0]
stage3_checked = [0]
stage3_perfect = [0]
stage3_partial = [0]
total = [0]

def log(msg):
    print(msg)

# ------------------ Установка XRAY ------------------
def setup_xray():
    exe_path = os.path.join(XRAY_FOLDER, "xray.exe" if os.name == 'nt' else "xray")
    
    if os.path.exists(exe_path):
        log(f"✅ Используется xray: {exe_path}")
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
        
        if system != "windows":
            os.chmod(exe_path, 0o755)
        
        log("✅ Xray установлен")
        return exe_path
        
    except Exception as e:
        log(f"❌ Ошибка установки xray: {e}")
        return None

# ------------------ ИЗВЛЕЧЕНИЕ HOST:PORT ------------------
def extract_host_port(key):
    """Универсальное извлечение host:port из любого ключа"""
    try:
        # Удаляем префикс протокола
        for prefix in ["vless://", "vmess://", "trojan://", "ss://"]:
            if key.lower().startswith(prefix):
                key = key[len(prefix):]
                break
        
        # Для VMess (base64)
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
        
        # Для остальных (vless/trojan/ss)
        if "@" in key:
            key = key.split("@", 1)[1]
        
        if "?" in key:
            key = key.split("?")[0]
        
        if "#" in key:
            key = key.split("#")[0]
        
        if ":" in key:
            host, port = key.rsplit(":", 1)
            return host, int(port)
        
        return None, None
    except:
        return None, None

# ------------------ СТУПЕНЬ 1: БЫСТРАЯ TCP ПРОВЕРКА ------------------
def stage1_tcp_check(key):
    """Быстрая TCP проверка - отсеиваем мусор"""
    stage1_checked[0] += 1
    
    if stage1_checked[0] % 100 == 0:
        log(f"📊 Ступень 1: {stage1_checked[0]}/{total[0]} | Живых: {stage1_live[0]}")
    
    host, port = extract_host_port(key)
    if not host or not port:
        return None
    
    try:
        # Определяем нужен ли TLS
        use_tls = "tls" in key.lower() or key.lower().startswith("trojan://")
        
        with socket.create_connection((host, port), timeout=5) as sock:
            if use_tls:
                context = ssl.create_default_context()
                context.check_hostname = False
                context.verify_mode = ssl.CERT_NONE
                
                with context.wrap_socket(sock, server_hostname=host) as ssock:
                    ssock.sendall(b"GET / HTTP/1.1\r\nHost: " + host.encode() + b"\r\n\r\n")
                    ssock.settimeout(3)
                    response = ssock.recv(1024)
                    
                    if len(response) > 0:
                        stage1_live[0] += 1
                        return key
            else:
                sock.sendall(b"GET / HTTP/1.1\r\nHost: " + host.encode() + b"\r\n\r\n")
                sock.settimeout(3)
                response = sock.recv(1024)
                
                if len(response) > 0:
                    stage1_live[0] += 1
                    return key
    except:
        pass
    
    return None

# ------------------ ПАРСЕРЫ ПРОТОКОЛОВ ------------------
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

# ------------------ СТУПЕНЬ 2: XRAY БАЗОВАЯ ------------------
def stage2_xray_check(key, xray_exe):
    """Базовая проверка через xray (gstatic + Cloudflare)"""
    stage2_checked[0] += 1
    
    if stage2_checked[0] % 10 == 0:
        log(f"🔥 Ступень 2: {stage2_checked[0]}/{stage1_live[0]} | Рабочих: {stage2_live[0]}")
    
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
        
        # Даём xray подняться (для GitHub больше времени)
        time.sleep(2.5 if os.environ.get('GITHUB_ACTIONS') else 1.5)
        
        start = time.time()
        success = False
        latency = None
        
        try:
            proxies = {
                'http': f'socks5://127.0.0.1:{socks_port}',
                'https': f'socks5://127.0.0.1:{socks_port}'
            }
            
            # Проверка 1: gstatic
            resp1 = requests.get(
                'http://www.gstatic.com/generate_204',
                proxies=proxies,
                timeout=12,
                allow_redirects=False
            )
            if resp1.status_code not in [200, 204]:
                success = False
            else:
                # Проверка 2: cloudflare
                try:
                    resp2 = requests.get(
                        'https://cp.cloudflare.com/generate_204',
                        proxies=proxies,
                        timeout=12,
                        allow_redirects=False
                    )
                    if resp2.status_code in [200, 204]:
                        latency = int((time.time() - start) * 1000)
                        success = True
                    else:
                        success = False
                except:
                    success = False
        except:
            success = False
        
        if process:
            process.terminate()
            try:
                process.wait(timeout=2)
            except:
                try:
                    process.kill()
                except:
                    pass
        
        try:
            os.remove(config_file)
        except:
            pass
        
        if success:
            stage2_live[0] += 1
            quality = "good" if latency < 150 else "normal" if latency < 400 else "weak"
            
            if protocol in ["VLESS", "VMess"]:
                host = proxy_config["settings"]["vnext"][0]["address"]
                port = proxy_config["settings"]["vnext"][0]["port"]
            else:
                host = proxy_config["settings"]["servers"][0]["address"]
                port = proxy_config["settings"]["servers"][0]["port"]
            
            return (latency, quality, protocol, host, port, key)
        
        return None
        
    except Exception as e:
        if process:
            try:
                process.kill()
            except:
                pass
        try:
            os.remove(config_file)
        except:
            pass
        return None

# 🔥 ------------------ СТУПЕНЬ 3: РЕАЛЬНЫЕ САЙТЫ ------------------
def stage3_real_world_test(key_data, xray_exe):
    """Глубокое тестирование на реальных сайтах (YouTube, Instagram, банки и т.д.)"""
    stage3_checked[0] += 1
    latency, quality, protocol, host, port, key = key_data
    
    if stage3_checked[0] % 5 == 0:
        log(f"🌐 Ступень 3: {stage3_checked[0]}/{stage2_live[0]} | Идеальных: {stage3_perfect[0]} | Полудохлых: {stage3_partial[0]}")
    
    proxy_config, _ = parse_proxy_key(key)
    if not proxy_config:
        return None
    
    socks_port = random.randint(30000, 40000)
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
        
        time.sleep(2.5 if os.environ.get('GITHUB_ACTIONS') else 2)
        
        proxies = {
            'http': f'socks5://127.0.0.1:{socks_port}',
            'https': f'socks5://127.0.0.1:{socks_port}'
        }
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
        }
        
        working_sites = []
        failed_sites = []
        total_latency = 0
        
        # Проверяем каждый тестовый сайт
        for site_name, site_config in TEST_SITES.items():
            try:
                start_time = time.time()
                
                resp = requests.get(
                    site_config["url"],
                    proxies=proxies,
                    timeout=site_config["timeout"],
                    allow_redirects=True,
                    headers=headers,
                    verify=False
                )
                
                request_time = time.time() - start_time
                
                # Проверяем статус, размер и ключевые слова
                if resp.status_code == 200 and len(resp.content) >= site_config["min_size"]:
                    content_lower = resp.text.lower()
                    if any(keyword.lower() in content_lower for keyword in site_config["keywords"]):
                        working_sites.append(site_name)
                        total_latency += request_time
                    else:
                        failed_sites.append(site_name)
                else:
                    failed_sites.append(site_name)
                    
            except requests.exceptions.Timeout:
                failed_sites.append(f"{site_name}(timeout)")
            except requests.exceptions.ConnectionError:
                failed_sites.append(f"{site_name}(conn)")
            except Exception:
                failed_sites.append(f"{site_name}(err)")
            
            # Пауза между запросами
            time.sleep(0.5)
        
        if process:
            process.terminate()
            try:
                process.wait(timeout=2)
            except:
                try:
                    process.kill()
                except:
                    pass
        
        try:
            os.remove(config_file)
        except:
            pass
        
        total_sites = len(TEST_SITES)
        working_count = len(working_sites)
        
        # Вычисляем среднюю латентность
        if working_count > 0:
            avg_latency = int((total_latency / working_count) * 1000)
        else:
            avg_latency = latency
        
        # Классификация
        if working_count == total_sites:
            # Идеальный - все работают
            stage3_perfect[0] += 1
            return (key, avg_latency, "perfect", protocol, host, port, working_sites, failed_sites)
        elif working_count >= total_sites * 0.6:
            # Хороший - 60%+ работают
            stage3_perfect[0] += 1
            return (key, avg_latency, "good", protocol, host, port, working_sites, failed_sites)
        elif working_count > 0:
            # Полудохлый - хоть что-то работает
            stage3_partial[0] += 1
            return (key, avg_latency, "partial", protocol, host, port, working_sites, failed_sites)
        else:
            # Дохлый - ничего не работает
            return None
        
    except Exception:
        if process:
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
    
    # Удаляем дубли
    all_keys = list(set(all_keys))
    log(f"\n📦 Всего уникальных ключей: {len(all_keys)}")
    
    return all_keys

def add_comment_to_uri(uri: str, latency: int, quality: str, protocol: str, sites_status: str = "") -> str:
    if "#" in uri:
        base = uri.split("#")[0]
    else:
        base = uri
    
    quality_emoji = {
        "perfect": "🟢",
        "good": "🟡",
        "partial": "🟠",
        "weak": "⚪"
    }.get(quality, quality)
    
    if sites_status:
        new_tag = f"{quality_emoji} {latency}ms {protocol} {sites_status} {MY_CHANNEL}"
    else:
        new_tag = f"[{latency}ms {quality} {protocol} {MY_CHANNEL}]"
    
    return f"{base}#{quote(new_tag, safe=' @[]-_./=🟢🟡🟠⚪✅❌')}"

def cleanup_xray():
    """Очистка временных файлов"""
    try:
        for f in os.listdir(XRAY_FOLDER):
            if f.startswith("config_") and f.endswith(".json"):
                try:
                    os.remove(os.path.join(XRAY_FOLDER, f))
                except:
                    pass
    except:
        pass

def main():
    # Отключаем SSL warnings
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    print("\n" + "="*70)
    print(" " * 5 + "🔥 QUAD-STAGE REAL-WORLD PROXY CHECKER 🔥")
    print("="*70 + "\n")
    
    xray_exe = setup_xray()
    if not xray_exe:
        log("❌ Не удалось установить xray")
        return 1
    
    cleanup_xray()
    
    all_keys = download_keys()
    if not all_keys:
        log("❌ Нет ключей для проверки")
        return 1
    
    total[0] = len(all_keys)
    
    # ========== СТУПЕНЬ 1: TCP ==========
    print("\n" + "="*70)
    log("⚡ СТУПЕНЬ 1: Быстрая TCP проверка (отсев мусора)")
    print("="*70 + "\n")
    
    start_time = time.time()
    stage1_results = []
    
    # Для GitHub меньше потоков
    max_workers_1 = 80 if os.environ.get('GITHUB_ACTIONS') else 100
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_1) as executor:
        futures = {executor.submit(stage1_tcp_check, key): key for key in all_keys}
        
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result(timeout=10)
                if result:
                    stage1_results.append(result)
            except:
                pass
    
    stage1_time = time.time() - start_time
    
    log(f"\n✅ Ступень 1: {stage1_live[0]}/{total[0]} ({stage1_live[0]/total[0]*100:.1f}%)")
    log(f"   Время: {stage1_time:.1f}с\n")
    
    if not stage1_results:
        log("❌ Нет ключей после ступени 1")
        return 1
    
    # ========== СТУПЕНЬ 2: XRAY БАЗОВАЯ ==========
    print("="*70)
    log("⚡ СТУПЕНЬ 2: Проверка через xray (gstatic + cloudflare)")
    print("="*70 + "\n")
    
    stage2_start = time.time()
    stage2_results = []
    
    max_workers_2 = 10 if os.environ.get('GITHUB_ACTIONS') else 20
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_2) as executor:
        futures = {executor.submit(stage2_xray_check, key, xray_exe): key for key in stage1_results}
        
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result(timeout=30)
                if result:
                    stage2_results.append(result)
            except:
                pass
    
    stage2_time = time.time() - stage2_start
    
    log(f"\n✅ Ступень 2: {stage2_live[0]}/{stage1_live[0]} ({stage2_live[0]/stage1_live[0]*100:.1f}%)")
    log(f"   Время: {stage2_time:.1f}с\n")
    
    if not stage2_results:
        log("❌ Нет ключей после ступени 2")
        return 1
    
    # ========== СТУПЕНЬ 3: РЕАЛЬНЫЕ САЙТЫ ==========
    print("="*70)
    log("⚡ СТУПЕНЬ 3: Тестирование на реальных сайтах")
    log(f"   Проверяем: {', '.join(TEST_SITES.keys())}")
    print("="*70 + "\n")
    
    stage3_start = time.time()
    perfect_keys = []
    partial_keys = []
    
    max_workers_3 = 5 if os.environ.get('GITHUB_ACTIONS') else 10
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers_3) as executor:
        futures = {executor.submit(stage3_real_world_test, key_data, xray_exe): key_data for key_data in stage2_results}
        
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result(timeout=90)
                if result:
                    key, lat, qual, prot, h, p, working, failed = result
                    
                    if qual in ["perfect", "good"]:
                        perfect_keys.append(result)
                    elif qual == "partial":
                        partial_keys.append(result)
            except:
                pass
    
    stage3_time = time.time() - stage3_start
    elapsed = time.time() - start_time
    
    # ========== СОХРАНЕНИЕ ==========
    
    if perfect_keys:
        perfect_keys.sort(key=lambda x: x[1])
        
        with open(FINAL_FILE, 'w', encoding='utf-8') as f:
            f.write(f"# Channel: {MY_CHANNEL}\n")
            f.write(f"# Date: {datetime.now().isoformat()}\n")
            f.write(f"# Perfect keys: {len(perfect_keys)} / {total[0]}\n")
            f.write(f"# Method: QUAD-STAGE (TCP + XRAY + 2xHTTP + REAL-SITES)\n")
            f.write(f"# Test sites: {', '.join(TEST_SITES.keys())}\n\n")
            
            for key, lat, qual, prot, h, p, working, failed in perfect_keys:
                sites_status = f"✅{len(working)}/{len(TEST_SITES)}"
                key_with_tag = add_comment_to_uri(key, lat, qual, prot, sites_status)
                f.write(key_with_tag + "\n")
        
        log(f"✅ Сохранено {len(perfect_keys)} идеальных: {FINAL_FILE}")
    
    if partial_keys:
        partial_keys.sort(key=lambda x: -len(x[6]))
        
        with open(SEMI_DEAD_FILE, 'w', encoding='utf-8') as f:
            f.write(f"# Channel: {MY_CHANNEL}\n")
            f.write(f"# Date: {datetime.now().isoformat()}\n")
            f.write(f"# Partial keys: {len(partial_keys)} / {total[0]}\n")
            f.write(f"# Warning: работают частично!\n\n")
            
            for key, lat, qual, prot, h, p, working, failed in partial_keys:
                sites_info = f"✅{','.join(working)} ❌{','.join(failed)}"
                key_with_tag = add_comment_to_uri(key, lat, qual, prot, sites_info)
                f.write(key_with_tag + "\n")
        
        log(f"⚠️  Сохранено {len(partial_keys)} полудохлых: {SEMI_DEAD_FILE}")
    
    # ========== СТАТИСТИКА ==========
    print("\n" + "="*70)
    print("🎉 РЕЗУЛЬТАТЫ")
    print("="*70)
    print(f"📊 Ступень 1 (TCP):         {stage1_live[0]}/{total[0]} за {stage1_time:.1f}с")
    print(f"📊 Ступень 2 (XRAY):        {stage2_live[0]}/{stage1_live[0]} за {stage2_time:.1f}с")
    print(f"📊 Ступень 3 (Real-World):")
    print(f"   🟢 Идеальных:            {len(perfect_keys)} ({len(perfect_keys)/total[0]*100:.1f}%)")
    print(f"   🟠 Полудохлых:           {len(partial_keys)} ({len(partial_keys)/total[0]*100:.1f}%)")
    print(f"   ❌ Дохлых:               {stage2_live[0] - len(perfect_keys) - len(partial_keys)}")
    print(f"\n⏱️  Общее время: {elapsed:.1f}с ({elapsed/60:.1f} мин)")
    
    if perfect_keys:
        print(f"📁 Идеальные: {FINAL_FILE}")
    if partial_keys:
        print(f"📁 Полудохлые: {SEMI_DEAD_FILE}")
    
    print("="*70)
    print(f"💡 Итого рабочих: {len(perfect_keys)} из {total[0]} ({len(perfect_keys)/total[0]*100:.1f}%)")
    print("="*70)
    
    cleanup_xray()
    
    return 0

if __name__ == "__main__":
    try:
        exit(main())
    except KeyboardInterrupt:
        print("\n⚠️  Прервано")
        cleanup_xray()
        exit(1)
    except Exception as e:
        print(f"\n❌ Ошибка: {e}")
        import traceback
        traceback.print_exc()
        cleanup_xray()
        exit(1)

