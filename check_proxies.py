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
import threading
import concurrent.futures
import atexit
import signal
from datetime import datetime
from urllib.parse import quote, unquote

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

# Потокобезопасные счётчики
class ThreadSafeCounter:
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()
    
    def increment(self):
        with self._lock:
            self._value += 1
            return self._value
    
    @property
    def value(self):
        with self._lock:
            return self._value

stage1_checked = ThreadSafeCounter()
stage1_live = ThreadSafeCounter()
stage2_checked = ThreadSafeCounter()
stage2_live = ThreadSafeCounter()
total_keys = ThreadSafeCounter()

# Управление процессами xray (для cleanup)
_active_processes = []
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

# Регистрируем cleanup
atexit.register(cleanup_all_processes)

def signal_handler(signum, frame):
    print("\n\n⚠️  Прерывание! Завершаю процессы xray...")
    cleanup_all_processes()
    sys.exit(1)

signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

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
        elif system == "darwin":
            arch = "arm64" if "arm" in machine else "64"
            filename = f"Xray-macos-{arch}.zip"
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
def extract_host_port(original_key):
    """Универсальное извлечение host:port из любого ключа"""
    try:
        key = original_key.strip()
        
        # VMess — отдельная обработка (base64 JSON)
        if key.lower().startswith("vmess://"):
            try:
                encoded = key[8:]
                padding = len(encoded) % 4
                if padding:
                    encoded += '=' * (4 - padding)
                decoded = base64.b64decode(encoded).decode('utf-8')
                data = json.loads(decoded)
                return data.get("add"), int(data.get("port", 443))
            except:
                return None, None
        
        # Для vless/trojan/ss — парсим URI
        for prefix in ["vless://", "trojan://", "ss://"]:
            if key.lower().startswith(prefix):
                key = key[len(prefix):]
                break
        
        # SS может быть полностью в base64
        if "@" not in key and not key.lower().startswith(("vless", "trojan")):
            try:
                padding = len(key) % 4
                if padding:
                    key += '=' * (4 - padding)
                decoded = base64.b64decode(key).decode('utf-8')
                if "@" in decoded:
                    key = decoded
            except:
                pass
        
        # Формат: uuid@host:port?params#tag или method:pass@host:port
        if "@" in key:
            key = key.split("@", 1)[1]
        
        if "?" in key:
            key = key.split("?")[0]
        
        if "#" in key:
            key = key.split("#")[0]
        
        if ":" in key:
            host, port = key.rsplit(":", 1)
            # Убираем возможные скобки IPv6
            host = host.strip("[]")
            return host, int(port)
        
        return None, None
    except:
        return None, None

# ------------------ СТУПЕНЬ 1: БЫСТРАЯ ПРОВЕРКА ПОРТА ------------------
def stage1_port_check(key):
    """Быстрая проверка что порт открыт — отсеиваем явно мёртвые"""
    checked = stage1_checked.increment()
    
    if checked % 100 == 0:
        log(f"📊 Ступень 1: {checked}/{total_keys.value} | Живых: {stage1_live.value}")
    
    host, port = extract_host_port(key)
    if not host or not port:
        return None
    
    try:
        with socket.create_connection((host, port), timeout=5):
            stage1_live.increment()
            return key
    except:
        return None

# ------------------ ПАРСЕРЫ ПРОТОКОЛОВ ------------------
def parse_vless(key):
    try:
        if not key.lower().startswith("vless://"):
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
        host = host.strip("[]")
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
                "allowInsecure": params.get("allowInsecure", "0") == "1",
                "fingerprint": params.get("fp", "")
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
        if not key.lower().startswith("vmess://"):
            return None
        
        encoded = key[8:]
        padding = len(encoded) % 4
        if padding:
            encoded += '=' * (4 - padding)
        
        decoded = base64.b64decode(encoded).decode('utf-8')
        data = json.loads(decoded)
        
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
                        "security": data.get("scy", "auto")
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
                "allowInsecure": data.get("allowInsecure", False)
            }
        
        if data.get("net") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": data.get("path", "/"),
                "headers": {"Host": data.get("host", host)}
            }
        elif data.get("net") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": data.get("path", "")
            }
        elif data.get("net") == "tcp" and data.get("type") == "http":
            config["streamSettings"]["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "path": [data.get("path", "/")],
                        "headers": {"Host": [data.get("host", host)]}
                    }
                }
            }
        
        return config
        
    except:
        return None

def parse_trojan(key):
    try:
        if not key.lower().startswith("trojan://"):
            return None
        
        key = key[9:]
        if "@" not in key:
            return None
        
        password, rest = key.split("@", 1)
        password = unquote(password)
        
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
        host = host.strip("[]")
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
                "security": params.get("security", "tls")
            }
        }
        
        if config["streamSettings"]["security"] in ["tls", ""]:
            config["streamSettings"]["security"] = "tls"
            config["streamSettings"]["tlsSettings"] = {
                "serverName": params.get("sni", host),
                "allowInsecure": params.get("allowInsecure", "0") == "1",
                "fingerprint": params.get("fp", "")
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
        if not key.lower().startswith("ss://"):
            return None
        
        key = key[5:]
        
        # Убираем tag
        if "#" in key:
            key = key.split("#")[0]
        
        # Формат 1: base64(method:password)@host:port
        if "@" in key:
            encoded, server = key.split("@", 1)
            
            if ":" not in server:
                return None
            
            host, port = server.rsplit(":", 1)
            host = host.strip("[]")
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
                # Может быть уже plain text
                if ":" in encoded:
                    method, password = encoded.split(":", 1)
                else:
                    return None
        else:
            # Формат 2: base64(method:password@host:port)
            padding = len(key) % 4
            if padding:
                key += '=' * (4 - padding)
            
            decoded = base64.b64decode(key).decode('utf-8')
            
            if "@" not in decoded or ":" not in decoded:
                return None
            
            creds, server = decoded.rsplit("@", 1)
            method, password = creds.split(":", 1)
            host, port = server.rsplit(":", 1)
            host = host.strip("[]")
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
            },
            "streamSettings": {
                "network": "tcp"
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

def create_xray_config(proxy_config, http_port=10808):
    """Создаёт конфиг xray с HTTP inbound (не SOCKS!)"""
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": http_port,
            "listen": "127.0.0.1",
            "protocol": "http",  # HTTP вместо SOCKS — работает с requests без PySocks
            "settings": {
                "timeout": 10
            }
        }],
        "outbounds": [proxy_config]
    }

def wait_for_port(port, timeout=5):
    """Ждём пока xray откроет порт"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except:
            time.sleep(0.1)
    return False

# ------------------ СТУПЕНЬ 2: XRAY + HTTP ПРОВЕРКА ------------------
def stage2_xray_check(key, xray_exe):
    """Проверка через xray: Cloudflare HTTPS (обязательно) + gstatic (опционально)"""
    checked = stage2_checked.increment()
    
    if checked % 10 == 0:
        log(f"🔥 Ступень 2: {checked}/{stage1_live.value} | Рабочих: {stage2_live.value}")
    
    proxy_config, protocol = parse_proxy_key(key)
    if not proxy_config:
        return None
    
    # Случайный порт для параллельных проверок
    http_port = random.randint(20000, 50000)
    xray_config = create_xray_config(proxy_config, http_port)
    config_file = os.path.join(XRAY_FOLDER, f"config_{http_port}.json")
    
    process = None
    success = False
    latency = 0
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(xray_config, f, indent=2)
        
        process = subprocess.Popen(
            [xray_exe, "run", "-c", config_file],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        register_process(process)
        
        # Ждём пока порт откроется (вместо sleep)
        if not wait_for_port(http_port, timeout=5):
            return None
        
        # Проверяем что процесс не упал
        if process.poll() is not None:
            return None
        
        proxies = {
            'http': f'http://127.0.0.1:{http_port}',
            'https': f'http://127.0.0.1:{http_port}'
        }
        
        # === ТЕСТ 1: Cloudflare HTTPS (обязательный — проверяет TLS туннель) ===
        try:
            t1 = time.time()
            resp1 = requests.get(
                'https://cp.cloudflare.com/generate_204',
                proxies=proxies,
                timeout=12,
                allow_redirects=False
            )
            
            if resp1.status_code in [200, 204]:
                latency = int((time.time() - t1) * 1000)
                success = True
            else:
                return None
        except:
            return None
        
        # === ТЕСТ 2: gstatic HTTP (опциональный — уточняет latency) ===
        try:
            t2 = time.time()
            resp2 = requests.get(
                'http://www.gstatic.com/generate_204',
                proxies=proxies,
                timeout=8,
                allow_redirects=False
            )
            
            if resp2.status_code in [200, 204]:
                gstatic_latency = int((time.time() - t2) * 1000)
                latency = min(latency, gstatic_latency)  # Берём лучший
        except:
            pass  # Не критично, Cloudflare уже прошёл
        
        if success:
            stage2_live.increment()
            
            # Определяем качество
            if latency < 150:
                quality = "⚡fast"
            elif latency < 300:
                quality = "✓good"
            elif latency < 500:
                quality = "~normal"
            else:
                quality = "slow"
            
            # Извлекаем host и port для лога
            if protocol in ["VLESS", "VMess"]:
                host = proxy_config["settings"]["vnext"][0]["address"]
                port = proxy_config["settings"]["vnext"][0]["port"]
            else:
                host = proxy_config["settings"]["servers"][0]["address"]
                port = proxy_config["settings"]["servers"][0]["port"]
            
            return (latency, quality, protocol, host, port, key)
        
        return None
        
    except Exception as e:
        return None
    finally:
        # Cleanup
        if process:
            unregister_process(process)
            try:
                process.terminate()
                process.wait(timeout=2)
            except:
                try:
                    process.kill()
                    process.wait(timeout=1)
                except:
                    pass
        
        try:
            if os.path.exists(config_file):
                os.remove(config_file)
        except:
            pass

def download_keys():
    all_keys = []
    
    log("📥 Загрузка ключей из источников...")
    
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
                    if line and line.lower().startswith(("vless://", "vmess://", "trojan://", "ss://")):
                        all_keys.append(line)
                        count += 1
                
                log(f"  ✅ {url.split('/')[-1]}: {count} ключей")
            except Exception as e:
                log(f"  ❌ {url.split('/')[-1]}: {e}")
    
    # Удаляем дубли, сохраняя порядок
    seen = set()
    unique_keys = []
    for key in all_keys:
        # Нормализуем для дедупликации (убираем tag)
        key_normalized = key.split("#")[0] if "#" in key else key
        if key_normalized not in seen:
            seen.add(key_normalized)
            unique_keys.append(key)
    
    log(f"\n📦 Всего уникальных ключей: {len(unique_keys)}")
    
    return unique_keys

def add_comment_to_uri(uri: str, latency: int, quality: str, protocol: str) -> str:
    """Добавляет информативный тег к URI"""
    if "#" in uri:
        base = uri.split("#")[0]
    else:
        base = uri
    
    new_tag = f"{quality} {latency}ms {protocol} {MY_CHANNEL}"
    return f"{base}#{quote(new_tag, safe='')}"

def main():
    print("\n" + "="*70)
    print(" " * 10 + "🔥 TRIPLE-STAGE XRAY PROXY CHECKER v3 🔥")
    print(" " * 15 + f"Канал: {MY_CHANNEL}")
    print("="*70 + "\n")
    
    # Устанавливаем xray
    xray_exe = setup_xray()
    if not xray_exe:
        log("❌ Не удалось установить xray")
        return 1
    
    # Загружаем ключи
    all_keys = download_keys()
    if not all_keys:
        log("❌ Нет ключей для проверки")
        return 1
    
    for _ in range(len(all_keys)):
        total_keys.increment()
    
    # ========== СТУПЕНЬ 1 ==========
    print("\n" + "="*70)
    log("⚡ СТУПЕНЬ 1: Быстрая проверка портов (отсев мёртвых серверов)")
    print("="*70 + "\n")
    
    start_time = time.time()
    stage1_results = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=100) as executor:
        futures = {executor.submit(stage1_port_check, key): key for key in all_keys}
        
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result(timeout=10)
                if result:
                    stage1_results.append(result)
            except:
                pass
    
    stage1_time = time.time() - start_time
    
    log(f"\n✅ Ступень 1 завершена: {stage1_live.value}/{total_keys.value} ({stage1_live.value/total_keys.value*100:.1f}%)")
    log(f"   Время: {stage1_time:.1f}с")
    
    if not stage1_results:
        log("\n❌ Все серверы недоступны на этапе TCP")
        return 1
    
    # ========== СТУПЕНЬ 2 ==========
    print("\n" + "="*70)
    log("⚡ СТУПЕНЬ 2: Проверка через XRAY (Cloudflare HTTPS + gstatic)")
    print("="*70 + "\n")
    
    stage2_start = time.time()
    results = []
    
    # Меньше воркеров — меньше нагрузка на систему
    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        futures = {executor.submit(stage2_xray_check, key, xray_exe): key for key in stage1_results}
        
        for future in concurrent.futures.as_completed(futures):
            try:
                result = future.result(timeout=30)
                if result:
                    results.append(result)
            except:
                pass
    
    stage2_time = time.time() - stage2_start
    total_time = time.time() - start_time
    
    # ========== РЕЗУЛЬТАТЫ ==========
    if results:
        # Сортируем по latency (лучшие сверху)
        results.sort(key=lambda x: x[0])
        
        with open(FINAL_FILE, 'w', encoding='utf-8') as f:
            f.write(f"# Канал: {MY_CHANNEL}\n")
            f.write(f"# Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Проверено: {len(results)} рабочих из {total_keys.value}\n")
            f.write(f"# Метод: TCP + XRAY (Cloudflare HTTPS + gstatic)\n")
            f.write(f"#\n")
            f.write(f"# Качество: ⚡fast (<150ms), ✓good (<300ms), ~normal (<500ms), slow (>500ms)\n")
            f.write(f"#\n\n")
            
            for latency, quality, protocol, host, port, key in results:
                key_with_tag = add_comment_to_uri(key, latency, quality, protocol)
                f.write(key_with_tag + "\n")
        
        print("\n" + "="*70)
        print("🎉 РЕЗУЛЬТАТЫ ПРОВЕРКИ")
        print("="*70)
        print(f"")
        print(f"  📊 Ступень 1 (TCP):     {stage1_live.value:>4}/{total_keys.value} за {stage1_time:.1f}с")
        print(f"  📊 Ступень 2 (XRAY):    {len(results):>4}/{stage1_live.value} за {stage2_time:.1f}с")
        print(f"")
        print(f"  ✅ ИТОГО РАБОЧИХ:       {len(results)}/{total_keys.value} ({len(results)/total_keys.value*100:.1f}%)")
        print(f"  ⏱️  Общее время:         {total_time:.1f}с ({total_time/60:.1f} мин)")
        print(f"")
        print(f"  📁 Результат сохранён:")
        print(f"     {FINAL_FILE}")
        print("")
        
        # Статистика по качеству
        fast = sum(1 for r in results if r[0] < 150)
        good = sum(1 for r in results if 150 <= r[0] < 300)
        normal = sum(1 for r in results if 300 <= r[0] < 500)
        slow = sum(1 for r in results if r[0] >= 500)
        
        print(f"  📈 Распределение по качеству:")
        print(f"     ⚡ fast (<150ms):   {fast}")
        print(f"     ✓ good (<300ms):   {good}")
        print(f"     ~ normal (<500ms): {normal}")
        print(f"     ⊘ slow (>500ms):   {slow}")
        print("="*70)
        
        return 0
    else:
        print("\n" + "="*70)
        log("❌ НЕТ РАБОЧИХ КЛЮЧЕЙ")
        log(f"   Проверено: {total_keys.value}")
        log(f"   Прошли TCP: {stage1_live.value}")
        log(f"   Прошли XRAY: 0")
        print("="*70)
        return 1

if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Прервано пользователем")
        cleanup_all_processes()
        exit_code = 1
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        cleanup_all_processes()
        exit_code = 1
    
    sys.exit(exit_code)

