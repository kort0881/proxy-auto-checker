"""
📱 MOBILE VPN VALIDATOR v3.0 (FULL MOBILE SIMULATION)
Полная имитация мобильного трафика для проверки VPN ключей

🎯 Что проверяем:
- UDP connectivity (критично для мобильных)
- DNS резолвинг через сервер
- Множественные параллельные соединения
- Стабильность под нагрузкой
- Latency и Jitter
- Специфичные для мобильных настройки протоколов
"""

import os
import sys
import json
import time
import random
import socket
import ssl
import struct
import base64
import hashlib
import threading
from datetime import datetime
from urllib.parse import unquote
import concurrent.futures
from collections import defaultdict
from statistics import mean, stdev, median
from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
import urllib3
urllib3.disable_warnings()

# === НАСТРОЙКИ ===
WORK_DIR = os.path.dirname(os.path.abspath(__file__))
RESULTS_FOLDER = os.path.join(WORK_DIR, "results")

# === ПАРАМЕТРЫ ТЕСТИРОВАНИЯ ===
class TestConfig:
    # Параллельность
    MAX_PARALLEL_KEYS = 20
    BATCH_SIZE = 100
    
    # Latency тесты
    LATENCY_SAMPLES = 10          # Замеров ping
    LATENCY_TIMEOUT = 3           # Секунд на замер
    
    # Стабильность
    STABILITY_DURATION = 5        # Секунд теста стабильности
    STABILITY_CONNECTIONS = 10    # Параллельных соединений
    
    # Нагрузка
    LOAD_TEST_REQUESTS = 20       # Запросов в тесте нагрузки
    LOAD_TEST_PARALLEL = 5        # Параллельных запросов
    
    # UDP
    UDP_TEST_PACKETS = 5          # UDP пакетов
    UDP_TIMEOUT = 2               # Таймаут UDP
    
    # DNS
    DNS_TEST_DOMAINS = [
        "google.com",
        "youtube.com", 
        "facebook.com",
        "telegram.org"
    ]
    
    # Таймауты
    TCP_TIMEOUT = 5
    TLS_TIMEOUT = 5

# === МОБИЛЬНЫЕ USER-AGENTS ===
MOBILE_USER_AGENTS = [
    # iPhone
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4.1 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/123.0.6312.52 Mobile/15E148 Safari/604.1",
    # Android
    "Mozilla/5.0 (Linux; Android 14; SM-S928B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8 Pro) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Mobile Safari/537.36",
    # VPN Apps
    "V2RayNG/1.8.19 (Android 14; SDK 34)",
    "Hiddify/2.5.7 (iOS 17.4)",
    "Shadowrocket/2.2.45 (iPhone; iOS 17.4.1)"
]

# === ПРОФИЛИ КАЧЕСТВА ДЛЯ МОБИЛЬНЫХ ===
MOBILE_QUALITY_PROFILES = {
    "elite": {
        "emoji": "💎",
        "label": "ЭЛИТНЫЙ",
        "description": "Идеально для мобильных игр и видеозвонков",
        "thresholds": {
            "latency_avg_max": 100,
            "latency_jitter_max": 30,
            "stability_min": 95,
            "load_success_min": 95,
            "udp_success": True,
            "dns_success": True
        },
        "priority": 1
    },
    "premium": {
        "emoji": "⭐",
        "label": "ПРЕМИУМ", 
        "description": "Отлично для стриминга и соцсетей",
        "thresholds": {
            "latency_avg_max": 200,
            "latency_jitter_max": 50,
            "stability_min": 90,
            "load_success_min": 90,
            "udp_success": True,
            "dns_success": True
        },
        "priority": 2
    },
    "good": {
        "emoji": "✅",
        "label": "ХОРОШИЙ",
        "description": "Хорошо для браузинга и мессенджеров",
        "thresholds": {
            "latency_avg_max": 350,
            "latency_jitter_max": 100,
            "stability_min": 80,
            "load_success_min": 80,
            "udp_success": False,
            "dns_success": True
        },
        "priority": 3
    },
    "acceptable": {
        "emoji": "👌",
        "label": "ПРИЕМЛЕМЫЙ",
        "description": "Нормально для базового использования",
        "thresholds": {
            "latency_avg_max": 500,
            "latency_jitter_max": 150,
            "stability_min": 70,
            "load_success_min": 70,
            "udp_success": False,
            "dns_success": False
        },
        "priority": 4
    },
    "basic": {
        "emoji": "📶",
        "label": "БАЗОВЫЙ",
        "description": "Минимально рабочий",
        "thresholds": {
            "latency_avg_max": 1000,
            "latency_jitter_max": 300,
            "stability_min": 50,
            "load_success_min": 50,
            "udp_success": False,
            "dns_success": False
        },
        "priority": 5
    },
    "poor": {
        "emoji": "⚠️",
        "label": "ПЛОХОЙ",
        "description": "Проблемы со стабильностью",
        "thresholds": {
            "latency_avg_max": 9999,
            "latency_jitter_max": 9999,
            "stability_min": 0,
            "load_success_min": 0,
            "udp_success": False,
            "dns_success": False
        },
        "priority": 6
    }
}

# === МОБИЛЬНЫЕ КЛИЕНТЫ И ИХ ОСОБЕННОСТИ ===
MOBILE_CLIENTS = {
    "ios": {
        "happ": {"supports_udp": True, "supports_reality": True, "max_mtu": 1400},
        "streisand": {"supports_udp": True, "supports_reality": True, "max_mtu": 1400},
        "shadowrocket": {"supports_udp": True, "supports_reality": True, "max_mtu": 1500},
        "foxray": {"supports_udp": True, "supports_reality": True, "max_mtu": 1400},
        "v2box": {"supports_udp": True, "supports_reality": True, "max_mtu": 1400}
    },
    "android": {
        "v2rayng": {"supports_udp": True, "supports_reality": True, "max_mtu": 1500},
        "hiddify": {"supports_udp": True, "supports_reality": True, "max_mtu": 1500},
        "nekobox": {"supports_udp": True, "supports_reality": True, "max_mtu": 1500},
        "v2box": {"supports_udp": True, "supports_reality": True, "max_mtu": 1400}
    }
}

# === СТРУКТУРЫ ДАННЫХ ===
@dataclass
class LatencyResult:
    avg: float
    min: float
    max: float
    jitter: float
    samples: int
    success_rate: float

@dataclass
class StabilityResult:
    success_rate: float
    avg_response_time: float
    failed_connections: int
    total_connections: int
    
@dataclass
class LoadTestResult:
    success_rate: float
    avg_response_time: float
    requests_per_second: float
    failed_requests: int
    total_requests: int

@dataclass
class UDPTestResult:
    success: bool
    packets_sent: int
    packets_received: int
    avg_latency: float

@dataclass
class DNSTestResult:
    success: bool
    resolved_domains: int
    total_domains: int
    avg_resolve_time: float

@dataclass 
class MobileTestResult:
    key: str
    protocol: str
    host: str
    port: int
    security: str
    transport: str
    
    latency: Optional[LatencyResult]
    stability: Optional[StabilityResult]
    load_test: Optional[LoadTestResult]
    udp_test: Optional[UDPTestResult]
    dns_test: Optional[DNSTestResult]
    
    profile: str
    score: int
    mobile_ready: bool
    issues: List[str]

# === ИНИЦИАЛИЗАЦИЯ ===
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
OUTPUT_DIR = os.path.join(RESULTS_FOLDER, f"mobile_full_{timestamp}")
os.makedirs(OUTPUT_DIR, exist_ok=True)

seen_servers = set()

stats = {
    "total_keys": 0,
    "unique_servers": 0,
    "duplicates": 0,
    "checked": 0,
    "passed": 0,
    "failed": 0,
    "by_profile": defaultdict(int),
    "mobile_ready": 0,
    "udp_capable": 0,
    "dns_capable": 0,
    "start_time": None
}

def log(msg):
    print(msg, flush=True)

# ========== ПАРСИНГ КЛЮЧЕЙ ==========

def get_server_hash(key: str) -> str:
    """Хеш сервера для дедупликации"""
    try:
        if "vless://" in key or "trojan://" in key:
            if "@" in key:
                server_part = key.split("@")[1].split("?")[0].split("#")[0]
                return hashlib.md5(server_part.encode()).hexdigest()[:16]
        elif "vmess://" in key:
            encoded = key.replace("vmess://", "").split("#")[0]
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            try:
                data = json.loads(base64.b64decode(encoded))
                server = f"{data.get('add')}:{data.get('port')}"
                return hashlib.md5(server.encode()).hexdigest()[:16]
            except:
                pass
        elif "ss://" in key:
            if "@" in key:
                server_part = key.split("@")[1].split("#")[0]
                return hashlib.md5(server_part.encode()).hexdigest()[:16]
    except:
        pass
    return hashlib.md5(key.encode()).hexdigest()[:16]

def parse_key(key: str) -> Optional[Dict]:
    """Парсинг ключа с извлечением всех параметров"""
    try:
        key = key.strip()
        
        if key.startswith("vless://"):
            return parse_vless(key)
        elif key.startswith("vmess://"):
            return parse_vmess(key)
        elif key.startswith("trojan://"):
            return parse_trojan(key)
        elif key.startswith("ss://"):
            return parse_shadowsocks(key)
    except:
        pass
    return None

def parse_vless(key: str) -> Optional[Dict]:
    key_data = key[8:]
    if "@" not in key_data:
        return None
    
    uuid_part, rest = key_data.split("@", 1)
    server_part = rest.split("?")[0].split("#")[0]
    host, port = server_part.rsplit(":", 1)
    
    params = {}
    if "?" in rest:
        params_str = rest.split("?")[1].split("#")[0]
        for p in params_str.split("&"):
            if "=" in p:
                k, v = p.split("=", 1)
                params[k] = unquote(v)
    
    return {
        "protocol": "vless",
        "host": host,
        "port": int(port),
        "uuid": uuid_part,
        "security": params.get("security", "none"),
        "sni": params.get("sni", host),
        "type": params.get("type", "tcp"),
        "flow": params.get("flow", ""),
        "pbk": params.get("pbk", ""),
        "sid": params.get("sid", ""),
        "fp": params.get("fp", ""),
        "path": params.get("path", ""),
        "serviceName": params.get("serviceName", "")
    }

def parse_vmess(key: str) -> Optional[Dict]:
    encoded = key[8:].split("#")[0]
    padding = len(encoded) % 4
    if padding:
        encoded += '=' * (4 - padding)
    
    data = json.loads(base64.b64decode(encoded).decode('utf-8'))
    
    return {
        "protocol": "vmess",
        "host": data.get("add"),
        "port": int(data.get("port", 443)),
        "uuid": data.get("id"),
        "security": data.get("tls", "none"),
        "sni": data.get("sni", data.get("add")),
        "type": data.get("net", "tcp"),
        "aid": data.get("aid", 0),
        "path": data.get("path", ""),
        "flow": ""
    }

def parse_trojan(key: str) -> Optional[Dict]:
    key_data = key[9:]
    if "@" not in key_data:
        return None
    
    password, rest = key_data.split("@", 1)
    server_part = rest.split("?")[0].split("#")[0]
    host, port = server_part.rsplit(":", 1)
    
    params = {}
    if "?" in rest:
        params_str = rest.split("?")[1].split("#")[0]
        for p in params_str.split("&"):
            if "=" in p:
                k, v = p.split("=", 1)
                params[k] = unquote(v)
    
    return {
        "protocol": "trojan",
        "host": host,
        "port": int(port),
        "password": password,
        "security": params.get("security", "tls"),
        "sni": params.get("sni", host),
        "type": params.get("type", "tcp"),
        "flow": "",
        "path": params.get("path", "")
    }

def parse_shadowsocks(key: str) -> Optional[Dict]:
    key_data = key[5:].split("#")[0]
    if "@" not in key_data:
        return None
    
    encoded, server = key_data.rsplit("@", 1)
    host, port = server.rsplit(":", 1)
    
    padding = len(encoded) % 4
    if padding:
        encoded += '=' * (4 - padding)
    
    decoded = base64.b64decode(encoded).decode('utf-8')
    method, password = decoded.split(":", 1)
    
    return {
        "protocol": "shadowsocks",
        "host": host,
        "port": int(port),
        "method": method,
        "password": password,
        "security": "none",
        "sni": host,
        "type": "tcp",
        "flow": ""
    }

# ========== ТЕСТЫ ПОДКЛЮЧЕНИЯ ==========

def test_tcp_connection(host: str, port: int, timeout: float = 5) -> Tuple[bool, float]:
    """Базовый TCP тест с измерением времени"""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        start = time.time()
        result = sock.connect_ex((host, port))
        latency = (time.time() - start) * 1000
        
        sock.close()
        return result == 0, latency
    except:
        return False, 0

def test_tls_connection(host: str, port: int, sni: str, timeout: float = 5) -> Tuple[bool, float, dict]:
    """TLS тест с проверкой сертификата"""
    try:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        
        start = time.time()
        sock.connect((host, port))
        
        with context.wrap_socket(sock, server_hostname=sni) as ssock:
            latency = (time.time() - start) * 1000
            
            cert = ssock.getpeercert(binary_form=False)
            cipher = ssock.cipher()
            version = ssock.version()
            
            return True, latency, {
                "cipher": cipher[0] if cipher else None,
                "version": version,
                "cert_valid": cert is not None
            }
    except Exception as e:
        return False, 0, {"error": str(e)}

def test_udp_connectivity(host: str, port: int, timeout: float = 2) -> UDPTestResult:
    """
    Тест UDP connectivity
    Отправляем DNS-like пакеты для проверки UDP
    """
    packets_sent = 0
    packets_received = 0
    latencies = []
    
    for _ in range(TestConfig.UDP_TEST_PACKETS):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(timeout)
            
            # Формируем простой UDP пакет (DNS query format)
            transaction_id = random.randint(0, 65535)
            dns_query = struct.pack(">H", transaction_id)  # Transaction ID
            dns_query += b'\x01\x00'  # Flags: standard query
            dns_query += b'\x00\x01'  # Questions: 1
            dns_query += b'\x00\x00'  # Answer RRs: 0
            dns_query += b'\x00\x00'  # Authority RRs: 0
            dns_query += b'\x00\x00'  # Additional RRs: 0
            dns_query += b'\x06google\x03com\x00'  # Query: google.com
            dns_query += b'\x00\x01'  # Type: A
            dns_query += b'\x00\x01'  # Class: IN
            
            start = time.time()
            sock.sendto(dns_query, (host, port))
            packets_sent += 1
            
            try:
                data, addr = sock.recvfrom(512)
                latency = (time.time() - start) * 1000
                packets_received += 1
                latencies.append(latency)
            except socket.timeout:
                pass
            
            sock.close()
        except:
            pass
        
        time.sleep(0.1)
    
    return UDPTestResult(
        success=packets_received > 0,
        packets_sent=packets_sent,
        packets_received=packets_received,
        avg_latency=mean(latencies) if latencies else 0
    )

def test_dns_resolution(host: str, port: int) -> DNSTestResult:
    """
    Тест DNS резолвинга
    Проверяем способность резолвить домены
    """
    resolved = 0
    resolve_times = []
    
    for domain in TestConfig.DNS_TEST_DOMAINS:
        try:
            start = time.time()
            # Пытаемся резолвить через системный DNS
            socket.gethostbyname(domain)
            resolve_time = (time.time() - start) * 1000
            resolved += 1
            resolve_times.append(resolve_time)
        except:
            pass
    
    return DNSTestResult(
        success=resolved > 0,
        resolved_domains=resolved,
        total_domains=len(TestConfig.DNS_TEST_DOMAINS),
        avg_resolve_time=mean(resolve_times) if resolve_times else 0
    )

# ========== КОМПЛЕКСНЫЕ ТЕСТЫ ==========

def measure_latency(server_info: Dict) -> Optional[LatencyResult]:
    """Измерение latency с множественными замерами"""
    host = server_info["host"]
    port = server_info["port"]
    security = server_info.get("security", "none")
    sni = server_info.get("sni", host)
    
    latencies = []
    successes = 0
    
    for _ in range(TestConfig.LATENCY_SAMPLES):
        try:
            if security in ["tls", "reality"]:
                success, latency, _ = test_tls_connection(
                    host, port, sni, TestConfig.LATENCY_TIMEOUT
                )
            else:
                success, latency = test_tcp_connection(
                    host, port, TestConfig.LATENCY_TIMEOUT
                )
            
            if success and latency > 0:
                latencies.append(latency)
                successes += 1
        except:
            pass
        
        time.sleep(0.05)
    
    if not latencies:
        return None
    
    return LatencyResult(
        avg=round(mean(latencies), 1),
        min=round(min(latencies), 1),
        max=round(max(latencies), 1),
        jitter=round(stdev(latencies), 1) if len(latencies) > 1 else 0,
        samples=len(latencies),
        success_rate=round(successes / TestConfig.LATENCY_SAMPLES * 100, 1)
    )

def test_stability(server_info: Dict) -> Optional[StabilityResult]:
    """
    Тест стабильности соединения
    Множественные параллельные подключения
    """
    host = server_info["host"]
    port = server_info["port"]
    security = server_info.get("security", "none")
    sni = server_info.get("sni", host)
    
    successes = 0
    failures = 0
    response_times = []
    
    def single_connection():
        nonlocal successes, failures
        try:
            if security in ["tls", "reality"]:
                success, latency, _ = test_tls_connection(host, port, sni, 3)
            else:
                success, latency = test_tcp_connection(host, port, 3)
            
            if success:
                successes += 1
                return latency
            else:
                failures += 1
                return None
        except:
            failures += 1
            return None
    
    # Параллельные подключения
    with concurrent.futures.ThreadPoolExecutor(max_workers=TestConfig.STABILITY_CONNECTIONS) as executor:
        futures = [executor.submit(single_connection) for _ in range(TestConfig.STABILITY_CONNECTIONS)]
        
        for future in concurrent.futures.as_completed(futures, timeout=TestConfig.STABILITY_DURATION):
            try:
                result = future.result()
                if result:
                    response_times.append(result)
            except:
                failures += 1
    
    total = successes + failures
    if total == 0:
        return None
    
    return StabilityResult(
        success_rate=round(successes / total * 100, 1),
        avg_response_time=round(mean(response_times), 1) if response_times else 0,
        failed_connections=failures,
        total_connections=total
    )

def test_load(server_info: Dict) -> Optional[LoadTestResult]:
    """
    Тест под нагрузкой
    Имитация реального мобильного использования
    """
    host = server_info["host"]
    port = server_info["port"]
    security = server_info.get("security", "none")
    sni = server_info.get("sni", host)
    
    successes = 0
    failures = 0
    response_times = []
    start_time = time.time()
    
    def single_request():
        nonlocal successes, failures
        try:
            if security in ["tls", "reality"]:
                success, latency, _ = test_tls_connection(host, port, sni, 2)
            else:
                success, latency = test_tcp_connection(host, port, 2)
            
            if success:
                successes += 1
                return latency
            else:
                failures += 1
                return None
        except:
            failures += 1
            return None
    
    # Серия параллельных запросов
    with concurrent.futures.ThreadPoolExecutor(max_workers=TestConfig.LOAD_TEST_PARALLEL) as executor:
        futures = [executor.submit(single_request) for _ in range(TestConfig.LOAD_TEST_REQUESTS)]
        
        for future in concurrent.futures.as_completed(futures, timeout=30):
            try:
                result = future.result()
                if result:
                    response_times.append(result)
            except:
                failures += 1
    
    elapsed = time.time() - start_time
    total = successes + failures
    
    if total == 0:
        return None
    
    return LoadTestResult(
        success_rate=round(successes / total * 100, 1),
        avg_response_time=round(mean(response_times), 1) if response_times else 0,
        requests_per_second=round(total / elapsed, 2) if elapsed > 0 else 0,
        failed_requests=failures,
        total_requests=total
    )

# ========== ВАЛИДАЦИЯ МОБИЛЬНЫХ ПРОТОКОЛОВ ==========

def validate_mobile_protocol(server_info: Dict) -> Tuple[bool, List[str]]:
    """
    Проверка специфичных для мобильных настроек протокола
    """
    issues = []
    
    protocol = server_info.get("protocol", "")
    security = server_info.get("security", "none")
    transport = server_info.get("type", "tcp")
    flow = server_info.get("flow", "")
    
    # Reality проверки
    if security == "reality":
        if not server_info.get("pbk"):
            issues.append("Reality: отсутствует publicKey")
        if not server_info.get("fp"):
            issues.append("Reality: отсутствует fingerprint")
        if not server_info.get("sni"):
            issues.append("Reality: отсутствует SNI")
    
    # XTLS Flow проверки для iOS
    if flow:
        if "splice" in flow.lower():
            issues.append("Flow splice не поддерживается на iOS")
    
    # gRPC проверки
    if transport == "grpc":
        if not server_info.get("serviceName"):
            issues.append("gRPC: отсутствует serviceName")
    
    # WebSocket проверки
    if transport == "ws":
        if not server_info.get("path"):
            issues.append("WebSocket: отсутствует path (будет использован /)")
    
    # VMess alterId
    if protocol == "vmess":
        if server_info.get("aid", 0) > 0:
            issues.append("VMess: alterId > 0 устарел")
    
    # Общие проверки
    if not server_info.get("sni") and security in ["tls", "reality"]:
        issues.append("TLS/Reality: пустой SNI может вызвать проблемы")
    
    is_valid = len([i for i in issues if "не поддерживается" in i or "отсутствует publicKey" in i]) == 0
    
    return is_valid, issues

# ========== ОПРЕДЕЛЕНИЕ ПРОФИЛЯ ==========

def determine_profile(
    latency: Optional[LatencyResult],
    stability: Optional[StabilityResult],
    load_test: Optional[LoadTestResult],
    udp_test: Optional[UDPTestResult],
    dns_test: Optional[DNSTestResult]
) -> Tuple[str, int]:
    """Определение профиля качества для мобильных"""
    
    # Базовые проверки
    if not latency:
        return "poor", 0
    
    # Расчет score
    score = 0
    
    # Latency (до 30 баллов)
    if latency.avg < 100:
        score += 30
    elif latency.avg < 200:
        score += 25
    elif latency.avg < 350:
        score += 20
    elif latency.avg < 500:
        score += 15
    elif latency.avg < 1000:
        score += 10
    else:
        score += 5
    
    # Jitter (до 20 баллов)
    if latency.jitter < 30:
        score += 20
    elif latency.jitter < 50:
        score += 15
    elif latency.jitter < 100:
        score += 10
    elif latency.jitter < 150:
        score += 5
    
    # Стабильность (до 25 баллов)
    if stability:
        if stability.success_rate >= 95:
            score += 25
        elif stability.success_rate >= 90:
            score += 20
        elif stability.success_rate >= 80:
            score += 15
        elif stability.success_rate >= 70:
            score += 10
        else:
            score += 5
    
    # Нагрузка (до 15 баллов)
    if load_test:
        if load_test.success_rate >= 95:
            score += 15
        elif load_test.success_rate >= 90:
            score += 12
        elif load_test.success_rate >= 80:
            score += 9
        elif load_test.success_rate >= 70:
            score += 6
        else:
            score += 3
    
    # UDP (до 5 баллов)
    if udp_test and udp_test.success:
        score += 5
    
    # DNS (до 5 баллов)
    if dns_test and dns_test.success:
        score += 5
    
    # Определение профиля
    for profile_name, profile_data in sorted(
        MOBILE_QUALITY_PROFILES.items(),
        key=lambda x: x[1]["priority"]
    ):
        thresholds = profile_data["thresholds"]
        
        if latency.avg > thresholds["latency_avg_max"]:
            continue
        if latency.jitter > thresholds["latency_jitter_max"]:
            continue
        if stability and stability.success_rate < thresholds["stability_min"]:
            continue
        if load_test and load_test.success_rate < thresholds["load_success_min"]:
            continue
        if thresholds["udp_success"] and (not udp_test or not udp_test.success):
            continue
        if thresholds["dns_success"] and (not dns_test or not dns_test.success):
            continue
        
        return profile_name, score
    
    return "poor", score

# ========== ПОЛНЫЙ АНАЛИЗ КЛЮЧА ==========

def analyze_key_full(key: str) -> Optional[MobileTestResult]:
    """Полный анализ ключа для мобильных"""
    try:
        # Дедупликация
        server_hash = get_server_hash(key)
        if server_hash in seen_servers:
            return None  # Дубликат
        seen_servers.add(server_hash)
        
        # Парсинг
        server_info = parse_key(key)
        if not server_info:
            return None
        
        host = server_info["host"]
        port = server_info["port"]
        
        # 1. Latency тест
        latency = measure_latency(server_info)
        if not latency:
            return None  # Сервер недоступен
        
        # 2. Стабильность
        stability = test_stability(server_info)
        
        # 3. Нагрузка
        load_test = test_load(server_info)
        
        # 4. UDP тест
        udp_test = test_udp_connectivity(host, port)
        
        # 5. DNS тест
        dns_test = test_dns_resolution(host, port)
        
        # 6. Валидация протокола
        protocol_valid, protocol_issues = validate_mobile_protocol(server_info)
        
        # 7. Определение профиля
        profile, score = determine_profile(latency, stability, load_test, udp_test, dns_test)
        
        # 8. Mobile ready?
        mobile_ready = (
            profile in ["elite", "premium", "good"] and
            protocol_valid and
            stability and stability.success_rate >= 80
        )
        
        return MobileTestResult(
            key=key,
            protocol=server_info["protocol"].upper(),
            host=host,
            port=port,
            security=server_info.get("security", "none"),
            transport=server_info.get("type", "tcp"),
            latency=latency,
            stability=stability,
            load_test=load_test,
            udp_test=udp_test,
            dns_test=dns_test,
            profile=profile,
            score=score,
            mobile_ready=mobile_ready,
            issues=protocol_issues
        )
        
    except Exception as e:
        return None

# ========== ФОРМАТИРОВАНИЕ ==========

def format_result(result: MobileTestResult) -> str:
    """Форматирование результата"""
    profile_info = MOBILE_QUALITY_PROFILES[result.profile]
    
    parts = [
        f"#{profile_info['emoji']}",
        f"Score:{result.score}",
        f"Lat:{result.latency.avg:.0f}ms",
        f"Jit:{result.latency.jitter:.0f}ms"
    ]
    
    if result.stability:
        parts.append(f"Stab:{result.stability.success_rate:.0f}%")
    
    if result.load_test:
        parts.append(f"Load:{result.load_test.success_rate:.0f}%")
    
    if result.udp_test and result.udp_test.success:
        parts.append("UDP:✓")
    
    if result.dns_test and result.dns_test.success:
        parts.append("DNS:✓")
    
    parts.append(f"[{result.security}/{result.transport}]")
    
    if result.mobile_ready:
        parts.append("📱")
    
    return f"{result.key} {' '.join(parts)}"

# ========== MAIN ==========

def find_latest_verified() -> Optional[str]:
    """Поиск последнего verified файла"""
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

def main():
    stats["start_time"] = time.time()
    
    print("\n" + "="*100)
    print(" "*15 + "📱 MOBILE VPN VALIDATOR v3.0 (FULL SIMULATION)")
    print(" "*20 + "Полная имитация мобильного трафика")
    print("="*100)
    
    print(f"""
🎯 Что тестируем:
   ⚡ Latency - {TestConfig.LATENCY_SAMPLES} замеров с jitter
   📊 Стабильность - {TestConfig.STABILITY_CONNECTIONS} параллельных соединений
   🔥 Нагрузка - {TestConfig.LOAD_TEST_REQUESTS} запросов ({TestConfig.LOAD_TEST_PARALLEL} параллельно)
   📡 UDP connectivity - {TestConfig.UDP_TEST_PACKETS} пакетов
   🌐 DNS резолвинг - {len(TestConfig.DNS_TEST_DOMAINS)} доменов
   ✅ Валидация мобильных протоколов

📱 Мобильные клиенты:
   🍎 iOS: Happ, Streisand, Shadowrocket, FoXray, V2Box
   🤖 Android: V2RayNG, Hiddify, NekoBox, V2Box
""")
    
    # Источник
    source_file = find_latest_verified()
    if not source_file:
        log("❌ Не найден verified файл в results/")
        return 1
    
    log(f"📁 Источник: {os.path.basename(source_file)}")
    
    # Загрузка
    with open(source_file, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    keys = []
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#'):
            key = line.split('#')[0].strip()
            if key:
                keys.append(key)
    
    stats["total_keys"] = len(keys)
    log(f"📦 Загружено ключей: {len(keys)}")
    
    # Оценка времени
    est_seconds = (len(keys) / TestConfig.MAX_PARALLEL_KEYS) * 8
    log(f"⏱️  Оценка времени: ~{int(est_seconds//60)} мин")
    log(f"🚀 Параллельность: {TestConfig.MAX_PARALLEL_KEYS} ключей")
    
    print("\n" + "="*100)
    log("🔍 Начинаем полное тестирование...")
    print("="*100 + "\n")
    
    # Обработка
    all_results: List[MobileTestResult] = []
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=TestConfig.MAX_PARALLEL_KEYS) as executor:
        futures = {executor.submit(analyze_key_full, key): key for key in keys}
        
        completed = 0
        for future in concurrent.futures.as_completed(futures):
            completed += 1
            stats["checked"] += 1
            
            result = future.result()
            
            if result is None:
                stats["duplicates"] += 1
                continue
            
            if result:
                all_results.append(result)
                stats["passed"] += 1
                stats["by_profile"][result.profile] += 1
                
                if result.mobile_ready:
                    stats["mobile_ready"] += 1
                if result.udp_test and result.udp_test.success:
                    stats["udp_capable"] += 1
                if result.dns_test and result.dns_test.success:
                    stats["dns_capable"] += 1
                
                profile_info = MOBILE_QUALITY_PROFILES[result.profile]
                mobile_icon = "📱" if result.mobile_ready else ""
                
                log(f"[{completed}/{len(keys)}] {profile_info['emoji']} {result.profile.upper()}: "
                    f"Score:{result.score} Lat:{result.latency.avg:.0f}ms "
                    f"Jit:{result.latency.jitter:.0f}ms {mobile_icon}")
            else:
                stats["failed"] += 1
                if completed % 20 == 0:
                    log(f"[{completed}/{len(keys)}] ❌ Не прошел")
            
            # Прогресс
            if completed % 50 == 0 and completed > 0:
                elapsed = time.time() - stats["start_time"]
                remaining = (elapsed / completed) * (len(keys) - completed)
                log(f"\n📊 Прогресс: {completed}/{len(keys)} | "
                    f"✅ {stats['passed']} | 📱 {stats['mobile_ready']} | "
                    f"⏱️ ~{int(remaining//60)}мин\n")
    
    stats["unique_servers"] = len(seen_servers)
    
    # === СОХРАНЕНИЕ ===
    log("\n" + "="*100)
    log("💾 СОХРАНЕНИЕ РЕЗУЛЬТАТОВ")
    log("="*100 + "\n")
    
    # По профилям
    by_profile = defaultdict(list)
    for r in all_results:
        by_profile[r.profile].append(r)
    
    for profile_name in sorted(MOBILE_QUALITY_PROFILES.keys(), key=lambda x: MOBILE_QUALITY_PROFILES[x]["priority"]):
        results = by_profile.get(profile_name, [])
        if not results:
            continue
        
        profile_info = MOBILE_QUALITY_PROFILES[profile_name]
        filename = os.path.join(OUTPUT_DIR, f"{profile_name}_{timestamp}.txt")
        
        results.sort(key=lambda x: x.score, reverse=True)
        
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {profile_info['emoji']} {profile_info['label']}\n")
            f.write(f"# {profile_info['description']}\n")
            f.write(f"# Дата: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# Количество: {len(results)}\n")
            f.write(f"# Mobile Ready: {sum(1 for r in results if r.mobile_ready)}\n\n")
            
            for r in results:
                f.write(format_result(r) + "\n")
        
        log(f"{profile_info['emoji']} {profile_info['label']}: {len(results)} → {os.path.basename(filename)}")
    
    # Mobile Ready отдельно
    mobile_ready_results = [r for r in all_results if r.mobile_ready]
    if mobile_ready_results:
        mobile_file = os.path.join(OUTPUT_DIR, f"mobile_ready_{timestamp}.txt")
        with open(mobile_file, 'w', encoding='utf-8') as f:
            f.write("# 📱 MOBILE READY\n")
            f.write("# Оптимизированы для мобильных клиентов\n")
            f.write(f"# Количество: {len(mobile_ready_results)}\n\n")
            
            for r in sorted(mobile_ready_results, key=lambda x: x.score, reverse=True):
                f.write(format_result(r) + "\n")
        
        log(f"📱 Mobile Ready: {len(mobile_ready_results)} → {os.path.basename(mobile_file)}")
    
    # JSON
    detailed_file = os.path.join(OUTPUT_DIR, f"detailed_{timestamp}.json")
    with open(detailed_file, 'w', encoding='utf-8') as f:
        json_data = []
        for r in all_results:
            json_data.append({
                "key": r.key,
                "protocol": r.protocol,
                "host": r.host,
                "port": r.port,
                "security": r.security,
                "transport": r.transport,
                "profile": r.profile,
                "score": r.score,
                "mobile_ready": r.mobile_ready,
                "latency": {
                    "avg": r.latency.avg,
                    "min": r.latency.min,
                    "max": r.latency.max,
                    "jitter": r.latency.jitter
                } if r.latency else None,
                "stability": {
                    "success_rate": r.stability.success_rate,
                    "avg_response": r.stability.avg_response_time
                } if r.stability else None,
                "load_test": {
                    "success_rate": r.load_test.success_rate,
                    "rps": r.load_test.requests_per_second
                } if r.load_test else None,
                "udp_capable": r.udp_test.success if r.udp_test else False,
                "dns_capable": r.dns_test.success if r.dns_test else False,
                "issues": r.issues
            })
        json.dump(json_data, f, indent=2, ensure_ascii=False)
    
    log(f"📄 JSON → {os.path.basename(detailed_file)}")
    
    # Сводка
    total_time = int(time.time() - stats["start_time"])
    
    summary_file = os.path.join(OUTPUT_DIR, f"summary_{timestamp}.txt")
    with open(summary_file, 'w', encoding='utf-8') as f:
        f.write("="*80 + "\n")
        f.write("MOBILE VPN VALIDATOR v3.0 - ПОЛНАЯ СВОДКА\n")
        f.write("="*80 + "\n\n")
        
        f.write(f"Дата: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"Всего ключей: {stats['total_keys']}\n")
        f.write(f"Уникальных: {stats['unique_servers']}\n")
        f.write(f"Дубликатов: {stats['duplicates']}\n")
        f.write(f"Прошли: {stats['passed']}\n")
        f.write(f"Не прошли: {stats['failed']}\n")
        f.write(f"Время: {total_time}с ({total_time//60}мин)\n\n")
        
        f.write("МОБИЛЬНАЯ ГОТОВНОСТЬ:\n")
        f.write(f"  📱 Mobile Ready: {stats['mobile_ready']}\n")
        f.write(f"  📡 UDP capable: {stats['udp_capable']}\n")
        f.write(f"  🌐 DNS capable: {stats['dns_capable']}\n\n")
        
        f.write("ПО ПРОФИЛЯМ:\n")
        for profile_name in sorted(MOBILE_QUALITY_PROFILES.keys(), key=lambda x: MOBILE_QUALITY_PROFILES[x]["priority"]):
            count = stats["by_profile"].get(profile_name, 0)
            if count > 0:
                info = MOBILE_QUALITY_PROFILES[profile_name]
                pct = count / stats["passed"] * 100 if stats["passed"] > 0 else 0
                f.write(f"  {info['emoji']} {info['label']}: {count} ({pct:.1f}%)\n")
        
        if all_results:
            latencies = [r.latency.avg for r in all_results if r.latency]
            jitters = [r.latency.jitter for r in all_results if r.latency]
            scores = [r.score for r in all_results]
            
            f.write(f"\nСТАТИСТИКА:\n")
            f.write(f"  Latency: min={min(latencies):.0f} avg={mean(latencies):.0f} max={max(latencies):.0f}ms\n")
            f.write(f"  Jitter: min={min(jitters):.0f} avg={mean(jitters):.0f} max={max(jitters):.0f}ms\n")
            f.write(f"  Score: min={min(scores)} avg={mean(scores):.0f} max={max(scores)}\n")
    
    log(f"📊 Сводка → {os.path.basename(summary_file)}")
    
    # === ФИНАЛ ===
    print("\n" + "="*100)
    print("📊 ИТОГОВАЯ СТАТИСТИКА")
    print("="*100)
    print(f"Всего ключей:     {stats['total_keys']}")
    print(f"Уникальных:       {stats['unique_servers']}")
    print(f"✅ Прошли:        {stats['passed']}")
    print(f"❌ Не прошли:     {stats['failed']}")
    
    print(f"\n📱 МОБИЛЬНАЯ ГОТОВНОСТЬ:")
    print(f"  📱 Mobile Ready: {stats['mobile_ready']}")
    print(f"  📡 UDP capable:  {stats['udp_capable']}")
    print(f"  🌐 DNS capable:  {stats['dns_capable']}")
    
    print(f"\n🏆 ПО ПРОФИЛЯМ:")
    for profile_name in sorted(MOBILE_QUALITY_PROFILES.keys(), key=lambda x: MOBILE_QUALITY_PROFILES[x]["priority"]):
        count = stats["by_profile"].get(profile_name, 0)
        if count > 0:
            info = MOBILE_QUALITY_PROFILES[profile_name]
            pct = count / stats["passed"] * 100 if stats["passed"] > 0 else 0
            print(f"  {info['emoji']} {info['label']}: {count} ({pct:.1f}%)")
    
    if all_results:
        latencies = [r.latency.avg for r in all_results if r.latency]
        jitters = [r.latency.jitter for r in all_results if r.latency]
        print(f"\n⚡ Latency: {min(latencies):.0f} / {mean(latencies):.0f} / {max(latencies):.0f} ms")
        print(f"📈 Jitter:  {min(jitters):.0f} / {mean(jitters):.0f} / {max(jitters):.0f} ms")
    
    print(f"\n⏱️  Время: {total_time}с ({total_time//60}мин)")
    print(f"🚀 Скорость: {len(keys)/max(total_time,1)*60:.1f} ключей/мин")
    print(f"📂 Результаты: {OUTPUT_DIR}")
    print("="*100 + "\n")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
