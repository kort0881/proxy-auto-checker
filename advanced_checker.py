#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Proxy Checker Pro v3.1
Advanced proxy validation with AI predictions and mutation strategies
"""

import os
import html
import socket
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
import gc
import argparse
import logging
from datetime import datetime
from urllib.parse import quote, unquote
from collections import defaultdict
from pathlib import Path
from typing import List, Dict, Optional, Tuple, Set, Any
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean, stdev
from logging.handlers import RotatingFileHandler

# ==================== EXTERNAL LIBRARIES ====================
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False
    print("⚠️ tqdm not found. Install: pip install tqdm")

try:
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)
    COLOR_AVAILABLE = True
except ImportError:
    COLOR_AVAILABLE = False
    print("⚠️ colorama not found. Install: pip install colorama")
    class Fore:
        RED = GREEN = YELLOW = CYAN = MAGENTA = RESET = ''
    class Style:
        RESET_ALL = BRIGHT = ''

AI_AVAILABLE = False
try:
    from sklearn.ensemble import RandomForestClassifier, IsolationForest
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    AI_AVAILABLE = True
except ImportError:
    print("⚠️ AI libraries not found. Install: pip install scikit-learn")

# ==================== CONFIGURATION ====================
WORK_DIR = Path(__file__).parent.absolute()
XRAY_FOLDER = WORK_DIR / "xray"
RESULTS_FOLDER = WORK_DIR / "results"
PREMIUM_FOLDER = RESULTS_FOLDER / "premium"
HISTORY_FILE = RESULTS_FOLDER / "history.jsonl"
STATS_FILE = RESULTS_FOLDER / "stats_latest.json"
LOG_FILE = RESULTS_FOLDER / "checker.log"

# Create directories
for d in [XRAY_FOLDER, RESULTS_FOLDER, PREMIUM_FOLDER]:
    d.mkdir(parents=True, exist_ok=True)

# ==================== KEY SOURCES ====================
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
    ],
    "US": [
        "https://raw.githubusercontent.com/yebekhe/TelegramV2rayCollector/main/sub/base64/vmess",
        "https://raw.githubusercontent.com/mfuu/v2ray/master/v2ray",
    ]
}

MY_CHANNEL = "@vlesstrojan"
SAFE_SNI_LIST = [
    "www.google.com", "www.microsoft.com", "www.amazon.com", 
    "dl.google.com", "www.samsung.com", "www.cloudflare.com",
    "www.apple.com", "www.netflix.com", "www.spotify.com"
]

# ==================== DATACLASSES ====================
@dataclass
class Config:
    # TCP Settings
    TCP_WORKERS: int = 50
    TCP_TIMEOUT: int = 5
    TCP_RETRIES: int = 1
    
    # Xray Settings
    XRAY_WORKERS: int = 16
    XRAY_STARTUP: float = 1.5
    XRAY_STARTUP_QUICK: float = 0.8
    XRAY_TIMEOUT: int = 10
    
    # Test Settings
    LATENCY_SAMPLES: int = 5
    MIN_LATENCY_SUCCESS: int = 3
    RECONNECT_TESTS: int = 3
    MIN_RECONNECT_SUCCESS: int = 2
    
    # URLs for testing
    CHECK_URLS: List[str] = field(default_factory=lambda: [
        'https://cp.cloudflare.com/generate_204',
        'http://www.gstatic.com/generate_204',
        'http://connectivitycheck.gstatic.com/generate_204',
    ])
    
    CATEGORY_URLS: List[Tuple[str, str]] = field(default_factory=lambda: [
        ("https://www.google.com", "google"),
        ("https://web.telegram.org", "telegram"),
        ("https://www.youtube.com", "youtube"),
        ("https://www.netflix.com", "netflix"),
        ("https://www.instagram.com", "instagram"),
    ])
    
    # Memory
    GC_EVERY: int = 100
    MAX_BATCH_SIZE: int = 500

CONFIG = Config()

# ==================== QUALITY LEVELS ====================
class Quality(Enum):
    ELITE = "elite"
    PREMIUM = "premium"
    GOOD = "good"
    STANDARD = "standard"

@dataclass
class QualityThreshold:
    latency_max: float
    jitter_max: float
    categories_min: int
    reconnect_min: int

QUALITY_THRESHOLDS = {
    Quality.ELITE: QualityThreshold(80, 20, 5, 3),
    Quality.PREMIUM: QualityThreshold(150, 40, 4, 2),
    Quality.GOOD: QualityThreshold(250, 60, 3, 2),
    Quality.STANDARD: QualityThreshold(500, 100, 2, 1),
}

@dataclass
class CheckResult:
    key: str
    alive: bool
    latency: float = 0
    jitter: float = 0
    reconnect_success: int = 0
    categories: int = 0
    telegram: bool = False
    netflix: bool = False
    quality: Optional[Quality] = None
    protocol: str = ""
    host: str = ""
    port: int = 0
    security: str = ""
    error: Optional[str] = None
    
    # AI fields
    failure_risk: float = 0.0
    is_anomaly: bool = False
    ai_verdict: str = ""
    mutation_used: str = ""
    confidence_score: float = 0.0

@dataclass
class Stats:
    total_downloaded: int = 0
    duplicates: int = 0
    unique: int = 0
    tcp_passed: int = 0
    tcp_failed: int = 0
    xray_passed: int = 0
    xray_failed: int = 0
    by_quality: Dict[Quality, int] = field(default_factory=lambda: defaultdict(int))
    by_protocol: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    errors: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    ai_anomalies: int = 0
    mutations_success: int = 0
    total_mutations_tried: int = 0
    start_time: float = field(default_factory=time.time)

stats = Stats()
stats_lock = threading.Lock()

# ==================== LOGGING ====================
def setup_logging():
    """Setup dual logging: file + console"""
    handler = RotatingFileHandler(LOG_FILE, maxBytes=10*1024*1024, backupCount=3)
    handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)-8s | %(message)s'))
    
    logger = logging.getLogger('ProxyChecker')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    
    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter('%(message)s'))
    logger.addHandler(console)
    
    return logger

logger = setup_logging()

def log(msg: str, level: str = "info"):
    """Enhanced logging with colors"""
    if COLOR_AVAILABLE:
        colors = {
            "info": Fore.CYAN,
            "success": Fore.GREEN,
            "warning": Fore.YELLOW,
            "error": Fore.RED,
            "debug": Fore.MAGENTA
        }
        colored_msg = f"{colors.get(level, '')}{msg}{Style.RESET_ALL}"
        print(colored_msg)
    else:
        print(f"[{level.upper()}] {msg}")
    
    log_method = getattr(logger, level if level != "success" else "info")
    log_method(msg)

# ==================== PROCESS MANAGEMENT ====================
_active_processes: List[subprocess.Popen] = []
_processes_lock = threading.Lock()

def register_process(proc):
    with _processes_lock:
        _active_processes.append(proc)

def unregister_process(proc):
    with _processes_lock:
        if proc in _active_processes:
            _active_processes.remove(proc)

def cleanup_all_processes():
    """Kill all active xray processes"""
    with _processes_lock:
        for p in list(_active_processes):
            try:
                p.kill()
                p.wait(timeout=1)
            except:
                pass
        _active_processes.clear()

atexit.register(cleanup_all_processes)

def signal_handler(sig, frame):
    log("🛑 Interrupted! Cleaning up...", "warning")
    cleanup_all_processes()
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# ==================== AI ENGINE ====================
class AIEngine:
    """Advanced AI for proxy analysis and optimization"""
    
    def __init__(self):
        self.enabled = AI_AVAILABLE
        self.history: List[Dict] = []
        self.model_risk = None
        self.model_anomaly = None
        self.model_quality = None
        self.scaler = StandardScaler() if AI_AVAILABLE else None
        self.protocol_stats = defaultdict(lambda: {'success': 0, 'total': 0, 'avg_latency': []})
        self.mutation_effectiveness = defaultdict(lambda: {'success': 0, 'total': 0})
        self._load_history()
        if self.enabled:
            self._train_models()
    
    def _load_history(self):
        """Load historical data for training"""
        if not HISTORY_FILE.exists():
            return
        
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()[-10000:]  # Last 10k records
                for line in lines:
                    try:
                        rec = json.loads(line)
                        self.history.append(rec)
                        
                        # Update protocol statistics
                        proto = rec.get('protocol', 'unknown')
                        self.protocol_stats[proto]['total'] += 1
                        if rec.get('alive'):
                            self.protocol_stats[proto]['success'] += 1
                            if rec.get('latency'):
                                self.protocol_stats[proto]['avg_latency'].append(rec['latency'])
                        
                        # Track mutation effectiveness
                        if mut := rec.get('mutation'):
                            self.mutation_effectiveness[mut]['total'] += 1
                            if rec.get('alive'):
                                self.mutation_effectiveness[mut]['success'] += 1
                    except:
                        continue
        except Exception as e:
            log(f"Failed to load history: {e}", "warning")
    
    def _train_models(self):
        """Train AI models on historical data"""
        if len(self.history) < 100:
            log("Not enough data for AI training (need 100+ records)", "warning")
            return
        
        try:
            # Prepare features
            X = []
            y_alive = []
            y_quality = []
            
            for rec in self.history:
                features = [
                    rec.get('latency', 999),
                    rec.get('jitter', 100),
                    rec.get('reconnect', 0),
                    rec.get('categories', 0),
                    1 if rec.get('protocol') == 'vless' else 0,
                    1 if rec.get('protocol') == 'vmess' else 0,
                    1 if rec.get('protocol') == 'trojan' else 0,
                    1 if rec.get('security') == 'reality' else 0,
                    1 if rec.get('security') == 'tls' else 0,
                    len(rec.get('mutation', '')),
                ]
                
                X.append(features)
                y_alive.append(1 if rec.get('alive') else 0)
                
                # Map quality to numeric
                quality_map = {'elite': 3, 'premium': 2, 'good': 1, 'standard': 0}
                y_quality.append(quality_map.get(rec.get('quality', 'standard'), 0))
            
            X = np.array(X)
            X_scaled = self.scaler.fit_transform(X)
            
            # Train models
            self.model_risk = RandomForestClassifier(
                n_estimators=100, 
                max_depth=10,
                random_state=42
            ).fit(X_scaled, y_alive)
            
            self.model_anomaly = IsolationForest(
                contamination=0.1,
                random_state=42
            ).fit(X_scaled)
            
            if sum(y_quality) > 0:  # Only if we have quality data
                self.model_quality = RandomForestClassifier(
                    n_estimators=50,
                    random_state=42
                ).fit(X_scaled, y_quality)
            
            log(f"🧠 AI models trained on {len(X)} samples", "success")
            
        except Exception as e:
            log(f"AI training failed: {e}", "error")
            self.enabled = False
    
    def prioritize_keys(self, keys: List[str]) -> List[str]:
        """Smart key prioritization based on success rates"""
        if not self.enabled:
            return keys
        
        def calculate_priority(key: str) -> float:
            key_lower = key.lower()
            score = 0.5
            
            # Protocol scoring
            if 'vless://' in key_lower:
                proto = 'vless'
                score = 0.7
            elif 'trojan://' in key_lower:
                proto = 'trojan'
                score = 0.6
            elif 'vmess://' in key_lower:
                proto = 'vmess'
                score = 0.5
            else:
                proto = 'ss'
                score = 0.4
            
            # Adjust based on historical success
            if proto in self.protocol_stats:
                stats = self.protocol_stats[proto]
                if stats['total'] > 10:
                    success_rate = stats['success'] / stats['total']
                    score = score * 0.3 + success_rate * 0.7
            
            # Bonus for certain features
            if 'security=reality' in key_lower:
                score += 0.15
            if 'security=tls' in key_lower:
                score += 0.05
            if any(sni in key_lower for sni in ['cloudflare', 'amazon', 'microsoft']):
                score += 0.05
            
            return score
        
        return sorted(keys, key=calculate_priority, reverse=True)
    
    def analyze_result(self, result: CheckResult):
        """Analyze check result with AI"""
        if not self.enabled or not self.model_risk:
            return
        
        try:
            features = [[
                result.latency if result.latency else 999,
                result.jitter if result.jitter else 100,
                result.reconnect_success,
                result.categories,
                1 if result.protocol == 'vless' else 0,
                1 if result.protocol == 'vmess' else 0,
                1 if result.protocol == 'trojan' else 0,
                1 if result.security == 'reality' else 0,
                1 if result.security == 'tls' else 0,
                len(result.mutation_used),
            ]]
            
            features_scaled = self.scaler.transform(features)
            
            # Risk prediction
            if self.model_risk:
                prob = self.model_risk.predict_proba(features_scaled)[0]
                result.failure_risk = prob[0]  # Probability of failure
                result.confidence_score = max(prob)
                
                if result.failure_risk > 0.7:
                    result.ai_verdict += f"[HIGH_RISK:{int(result.failure_risk*100)}%]"
            
            # Anomaly detection
            if self.model_anomaly:
                is_anomaly = self.model_anomaly.predict(features_scaled)[0] == -1
                if is_anomaly:
                    result.is_anomaly = True
                    result.ai_verdict += "[ANOMALY]"
                    with stats_lock:
                        stats.ai_anomalies += 1
            
            # Quality prediction
            if self.model_quality and result.alive:
                quality_pred = self.model_quality.predict(features_scaled)[0]
                quality_map = {3: 'elite', 2: 'premium', 1: 'good', 0: 'standard'}
                predicted_quality = quality_map.get(quality_pred, 'standard')
                if predicted_quality != result.quality:
                    result.ai_verdict += f"[AI_QUALITY:{predicted_quality}]"
                    
        except Exception as e:
            log(f"AI analysis error: {e}", "debug")
    
    def save_result(self, result: CheckResult):
        """Save result to history"""
        record = {
            'timestamp': time.time(),
            'key_hash': hash(result.key) % 1000000,  # Privacy: store hash instead of key
            'alive': result.alive,
            'protocol': result.protocol,
            'latency': result.latency,
            'jitter': result.jitter,
            'reconnect': result.reconnect_success,
            'categories': result.categories,
            'quality': result.quality.value if result.quality else None,
            'security': result.security,
            'error': result.error,
            'mutation': result.mutation_used,
            'ai_risk': result.failure_risk,
            'ai_anomaly': result.is_anomaly
        }
        
        try:
            with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record) + '\n')
            
            self.history.append(record)
            
            # Update statistics
            self.protocol_stats[result.protocol]['total'] += 1
            if result.alive:
                self.protocol_stats[result.protocol]['success'] += 1
                self.protocol_stats[result.protocol]['avg_latency'].append(result.latency)
            
            if result.mutation_used:
                self.mutation_effectiveness[result.mutation_used]['total'] += 1
                if result.alive:
                    self.mutation_effectiveness[result.mutation_used]['success'] += 1
                    
        except Exception as e:
            log(f"Failed to save history: {e}", "debug")
    
    def get_best_mutation_strategy(self) -> List[str]:
        """Get mutation strategies sorted by effectiveness"""
        strategies = []
        for mutation, stats in self.mutation_effectiveness.items():
            if stats['total'] >= 5:  # Need at least 5 attempts
                success_rate = stats['success'] / stats['total']
                strategies.append((mutation, success_rate))
        
        return [s[0] for s in sorted(strategies, key=lambda x: x[1], reverse=True)]
    
    def mutate_config(self, proxy_config: Dict, attempt: int) -> Tuple[Dict, str]:
        """Advanced config mutation with 10 strategies"""
        mutated = json.loads(json.dumps(proxy_config))  # Deep copy
        mutation_name = ""
        
        stream = mutated.get('streamSettings', {})
        
        # Get best strategies from history
        best_strategies = self.get_best_mutation_strategy()
        
        mutations = {
            1: lambda: self._rotate_fingerprint(stream),
            2: lambda: self._spoof_sni(stream),
            3: lambda: self._change_alpn(stream),
            4: lambda: self._enable_mux(mutated),
            5: lambda: self._randomize_headers(stream),
            6: lambda: self._change_cipher(mutated),
            7: lambda: self._fragment_packets(stream),
            8: lambda: self._add_path_confusion(stream),
            9: lambda: self._enable_xtls(mutated),
            10: lambda: self._randomize_port(mutated)
        }
        
        # Try best strategy first if available
        if best_strategies and attempt == 1:
            for strategy in best_strategies:
                if 'FP_' in strategy:
                    mutation_name = self._rotate_fingerprint(stream)
                    break
                elif 'SNI_' in strategy:
                    mutation_name = self._spoof_sni(stream)
                    break
                elif 'MUX_' in strategy:
                    mutation_name = self._enable_mux(mutated)
                    break
        
        if not mutation_name and attempt in mutations:
            mutation_name = mutations[attempt]()
        
        with stats_lock:
            stats.total_mutations_tried += 1
        
        return mutated, mutation_name
    
    def _rotate_fingerprint(self, stream):
        """Rotate TLS fingerprint"""
        fingerprints = ['chrome', 'firefox', 'safari', 'edge', 'ios', 'android', 'random', 'randomized']
        
        if 'tlsSettings' in stream:
            old_fp = stream['tlsSettings'].get('fingerprint', 'chrome')
            new_fp = random.choice([f for f in fingerprints if f != old_fp])
            stream['tlsSettings']['fingerprint'] = new_fp
            return f"FP_{new_fp}"
        elif 'realitySettings' in stream:
            old_fp = stream['realitySettings'].get('fingerprint', 'chrome')
            new_fp = random.choice([f for f in fingerprints if f != old_fp])
            stream['realitySettings']['fingerprint'] = new_fp
            return f"FP_{new_fp}"
        return ""
    
    def _spoof_sni(self, stream):
        """Change SNI to bypass blocks"""
        if 'tlsSettings' in stream and 'realitySettings' not in stream:
            sni = random.choice(SAFE_SNI_LIST)
            stream['tlsSettings']['serverName'] = sni
            return f"SNI_{sni.split('.')[1]}"
        return ""
    
    def _change_alpn(self, stream):
        """Modify ALPN negotiation"""
        alpn_options = [
            ['h2', 'http/1.1'],
            ['h3', 'h2'],
            ['http/1.1'],
            ['h2'],
            ['h3']
        ]
        
        if 'tlsSettings' in stream:
            stream['tlsSettings']['alpn'] = random.choice(alpn_options)
            return "ALPN_modified"
        return ""
    
    def _enable_mux(self, config):
        """Enable multiplexing"""
        if 'mux' not in config or not config.get('mux', {}).get('enabled'):
            config['mux'] = {
                "enabled": True,
                "concurrency": random.choice([8, 16, 32, 64]),
                "xudpConcurrency": 16
            }
            return f"MUX_{config['mux']['concurrency']}"
        return ""
    
    def _randomize_headers(self, stream):
        """Randomize HTTP headers"""
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Safari/605.1.15',
            'Mozilla/5.0 (X11; Linux x86_64) Chrome/120.0.0.0',
            'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Safari/604.1'
        ]
        
        if 'wsSettings' in stream:
            if 'headers' not in stream['wsSettings']:
                stream['wsSettings']['headers'] = {}
            stream['wsSettings']['headers']['User-Agent'] = random.choice(user_agents)
            return "UA_randomized"
        elif 'httpSettings' in stream:
            if 'headers' not in stream['httpSettings']:
                stream['httpSettings']['headers'] = {}
            stream['httpSettings']['headers']['User-Agent'] = random.choice(user_agents)
            return "UA_randomized"
        return ""
    
    def _change_cipher(self, config):
        """Change encryption cipher"""
        if config.get('protocol') == 'vmess':
            settings = config.get('settings', {})
            if 'vnext' in settings:
                for vnext in settings['vnext']:
                    for user in vnext.get('users', []):
                        user['security'] = random.choice(['auto', 'aes-128-gcm', 'chacha20-poly1305'])
                return "CIPHER_rotated"
        return ""
    
    def _fragment_packets(self, stream):
        """Enable packet fragmentation"""
        if 'sockopt' not in stream:
            stream['sockopt'] = {}
        
        stream['sockopt']['tcpFastOpen'] = True
        stream['sockopt']['tcpNoDelay'] = True
        stream['sockopt']['tcpKeepAliveInterval'] = 30
        
        if random.random() > 0.5:
            stream['sockopt']['dialerProxy'] = "fragment"
        
        return "FRAGMENT_enabled"
    
    def _add_path_confusion(self, stream):
        """Add path confusion for WebSocket/gRPC"""
        if 'wsSettings' in stream:
            paths = ['/ws', '/socket', '/api/v1/ws', '/graphql', '/chat', f'/{"".join(random.choices("abcdefghijklmnopqrstuvwxyz", k=8))}']
            stream['wsSettings']['path'] = random.choice(paths)
            return "PATH_confused"
        elif 'grpcSettings' in stream:
            stream['grpcSettings']['serviceName'] = f'service_{random.randint(1000, 9999)}'
            return "GRPC_confused"
        return ""
    
    def _enable_xtls(self, config):
        """Try to enable XTLS flow"""
        if config.get('protocol') == 'vless':
            settings = config.get('settings', {})
            if 'vnext' in settings:
                for vnext in settings['vnext']:
                    for user in vnext.get('users', []):
                        if not user.get('flow'):
                            user['flow'] = random.choice(['xtls-rprx-vision', 'xtls-rprx-vision-udp443'])
                            return "XTLS_enabled"
        return ""
    
    def _randomize_port(self, config):
        """Change port slightly (same range)"""
        if 'settings' in config:
            if 'vnext' in config['settings']:
                for vnext in config['settings']['vnext']:
                    old_port = vnext.get('port', 443)
                    if old_port == 443:
                        vnext['port'] = random.choice([443, 8443, 2053, 2083, 2087, 2096])
                    elif old_port == 80:
                        vnext['port'] = random.choice([80, 8080, 8880, 2052, 2082, 2086, 2095])
                    return f"PORT_{vnext['port']}"
            elif 'servers' in config['settings']:
                for server in config['settings']['servers']:
                    old_port = server.get('port', 443)
                    if old_port == 443:
                        server['port'] = random.choice([443, 8443, 2053, 2083, 2087, 2096])
                    return f"PORT_{server['port']}"
        return ""

# Initialize AI Engine
ai_engine = AIEngine()

# ==================== PARSERS ====================
def extract_host_port(key: str) -> Tuple[Optional[str], Optional[int]]:
    """Extract host and port from proxy key"""
    try:
        key = key.strip()
        
        # Handle VMess separately (base64 encoded)
        if key.lower().startswith("vmess://"):
            encoded = key[8:]
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            try:
                data = json.loads(base64.b64decode(encoded).decode('utf-8'))
                return data.get("add"), int(data.get("port", 443))
            except:
                return None, None
        
        # Remove protocol prefix
        for prefix in ["vless://", "trojan://", "ss://", "ssr://", "hysteria://", "hysteria2://", "tuic://"]:
            if key.lower().startswith(prefix):
                key = key[len(prefix):]
                break
        
        # Parse user@host:port format
        if "@" in key:
            key = key.split("@", 1)[1]
        
        # Remove query and fragment
        if "?" in key:
            key = key.split("?")[0]
        if "#" in key:
            key = key.split("#")[0]
        
        # Handle IPv6
        if key.startswith("["):
            # IPv6 format: [::1]:8080
            if "]:" in key:
                host = key[1:key.index("]")]
                port = key[key.index("]:")+2:]
                return host, int(port)
        
        # Standard host:port
        if ":" in key:
            parts = key.rsplit(":", 1)
            if len(parts) == 2:
                host, port = parts
                return host.strip("[]"), int(port)
        
        return None, None
        
    except Exception as e:
        log(f"Failed to extract host/port: {e}", "debug")
        return None, None

def parse_vless(key: str) -> Optional[Dict]:
    """Parse VLESS proxy key"""
    try:
        if not key.lower().startswith("vless://"):
            return None
        
        key = key[8:]  # Remove vless://
        
        if "@" not in key:
            return None
        
        # Split UUID and server parts
        uuid_part, rest = key.split("@", 1)
        
        # Extract server and port
        server_part = rest.split("?")[0].split("#")[0]
        if ":" not in server_part:
            return None
        
        host, port = server_part.rsplit(":", 1)
        host = host.strip("[]")  # Remove IPv6 brackets if present
        
        # Parse parameters
        params = {}
        if "?" in rest:
            param_string = rest.split("?")[1].split("#")[0]
            for param in param_string.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    params[k] = unquote(v)
        
        # Build config
        config = {
            "protocol": "vless",
            "settings": {
                "vnext": [{
                    "address": host,
                    "port": int(port),
                    "users": [{
                        "id": uuid_part,
                        "encryption": "none",
                        "flow": params.get("flow", "")
                    }]
                }]
            },
            "streamSettings": {
                "network": params.get("type", "tcp"),
                "security": params.get("security", "none")
            }
        }
        
        # TLS settings
        if params.get("security") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": params.get("sni", params.get("host", host)),
                "allowInsecure": params.get("allowInsecure", "true").lower() == "true",
                "fingerprint": params.get("fp", "chrome"),
                "alpn": params.get("alpn", "").split(",") if params.get("alpn") else []
            }
        elif params.get("security") == "reality":
            config["streamSettings"]["realitySettings"] = {
                "serverName": params.get("sni", params.get("host", host)),
                "publicKey": params.get("pbk", ""),
                "shortId": params.get("sid", ""),
                "fingerprint": params.get("fp", "chrome"),
                "spiderX": params.get("spx", "")
            }
        elif params.get("security") == "xtls":
            config["streamSettings"]["xtlsSettings"] = {
                "serverName": params.get("sni", params.get("host", host)),
                "allowInsecure": True,
                "fingerprint": params.get("fp", "chrome")
            }
        
        # Transport settings
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {
                    "Host": params.get("host", host)
                }
            }
        elif params.get("type") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": params.get("serviceName", ""),
                "multiMode": params.get("mode", "") == "multi"
            }
        elif params.get("type") == "tcp" and params.get("headerType") == "http":
            config["streamSettings"]["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "version": "1.1",
                        "method": "GET",
                        "path": [params.get("path", "/")],
                        "headers": {
                            "Host": [params.get("host", host)],
                            "User-Agent": ["Mozilla/5.0"],
                            "Accept-Encoding": ["gzip, deflate"],
                            "Connection": ["keep-alive"],
                            "Pragma": "no-cache"
                        }
                    }
                }
            }
        elif params.get("type") == "kcp":
            config["streamSettings"]["kcpSettings"] = {
                "mtu": 1350,
                "tti": 50,
                "uplinkCapacity": 12,
                "downlinkCapacity": 100,
                "congestion": False,
                "readBufferSize": 2,
                "writeBufferSize": 2,
                "header": {
                    "type": params.get("headerType", "none")
                },
                "seed": params.get("seed")
            }
        elif params.get("type") == "quic":
            config["streamSettings"]["quicSettings"] = {
                "security": params.get("quicSecurity", "none"),
                "key": params.get("key", ""),
                "header": {
                    "type": params.get("headerType", "none")
                }
            }
        elif params.get("type") == "h2":
            config["streamSettings"]["httpSettings"] = {
                "host": [params.get("host", host)],
                "path": params.get("path", "/")
            }
        
        return config
        
    except Exception as e:
        log(f"VLESS parse error: {e}", "debug")
        return None

def parse_vmess(key: str) -> Optional[Dict]:
    """Parse VMess proxy key"""
    try:
        if not key.lower().startswith("vmess://"):
            return None
        
        # Decode base64
        encoded = key[8:]
        padding = len(encoded) % 4
        if padding:
            encoded += '=' * (4 - padding)
        
        try:
            decoded = base64.b64decode(encoded).decode('utf-8')
            data = json.loads(decoded)
        except:
            return None
        
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
                "security": "tls" if data.get("tls") == "tls" else "none"
            }
        }
        
        # TLS settings
        if data.get("tls") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": data.get("sni", data.get("host", host)),
                "allowInsecure": True,
                "fingerprint": data.get("fp", "chrome"),
                "alpn": data.get("alpn", "").split(",") if data.get("alpn") else []
            }
        
        # Transport settings
        if data.get("net") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": data.get("path", "/"),
                "headers": {
                    "Host": data.get("host", host)
                }
            }
        elif data.get("net") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": data.get("path", ""),
                "multiMode": data.get("type") == "multi"
            }
        elif data.get("net") == "tcp" and data.get("type") == "http":
            config["streamSettings"]["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "version": "1.1",
                        "method": "GET",
                        "path": [data.get("path", "/")],
                        "headers": {
                            "Host": [data.get("host", host)],
                            "User-Agent": ["Mozilla/5.0"],
                            "Accept-Encoding": ["gzip, deflate"],
                            "Connection": ["keep-alive"],
                            "Pragma": "no-cache"
                        }
                    }
                }
            }
        elif data.get("net") == "kcp":
            config["streamSettings"]["kcpSettings"] = {
                "mtu": 1350,
                "tti": 50,
                "uplinkCapacity": 12,
                "downlinkCapacity": 100,
                "congestion": False,
                "readBufferSize": 2,
                "writeBufferSize": 2,
                "header": {
                    "type": data.get("type", "none")
                },
                "seed": data.get("path")
            }
        elif data.get("net") == "quic":
            config["streamSettings"]["quicSettings"] = {
                "security": data.get("host", "none"),
                "key": data.get("path", ""),
                "header": {
                    "type": data.get("type", "none")
                }
            }
        elif data.get("net") == "h2":
            config["streamSettings"]["httpSettings"] = {
                "host": [data.get("host", host)],
                "path": data.get("path", "/")
            }
        
        return config
        
    except Exception as e:
        log(f"VMess parse error: {e}", "debug")
        return None

def parse_trojan(key: str) -> Optional[Dict]:
    """Parse Trojan proxy key"""
    try:
        if not key.lower().startswith("trojan://"):
            return None
        
        key = key[9:]  # Remove trojan://
        
        if "@" not in key:
            return None
        
        # Split password and server
        password, rest = key.split("@", 1)
        password = unquote(password)
        
        # Extract server and port
        server_part = rest.split("?")[0].split("#")[0]
        if ":" not in server_part:
            return None
        
        host, port = server_part.rsplit(":", 1)
        host = host.strip("[]")
        
        # Parse parameters
        params = {}
        if "?" in rest:
            param_string = rest.split("?")[1].split("#")[0]
            for param in param_string.split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    params[k] = unquote(v)
        
        config = {
            "protocol": "trojan",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": int(port),
                    "password": password
                }]
            },
            "streamSettings": {
                "network": params.get("type", "tcp"),
                "security": params.get("security", "tls")
            }
        }
        
        # TLS settings (Trojan always uses TLS)
        config["streamSettings"]["tlsSettings"] = {
            "serverName": params.get("sni", params.get("host", host)),
            "allowInsecure": params.get("allowInsecure", "true").lower() == "true",
            "fingerprint": params.get("fp", "chrome"),
            "alpn": params.get("alpn", "").split(",") if params.get("alpn") else []
        }
        
        # Transport settings
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {
                    "Host": params.get("host", host)
                }
            }
        elif params.get("type") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": params.get("serviceName", ""),
                "multiMode": params.get("mode") == "multi"
            }
        elif params.get("type") == "tcp" and params.get("headerType") == "http":
            config["streamSettings"]["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "version": "1.1",
                        "method": "GET",
                        "path": [params.get("path", "/")],
                        "headers": {
                            "Host": [params.get("host", host)]
                        }
                    }
                }
            }
        
        return config
        
    except Exception as e:
        log(f"Trojan parse error: {e}", "debug")
        return None

def parse_shadowsocks(key: str) -> Optional[Dict]:
    """Parse Shadowsocks proxy key"""
    try:
        if not key.lower().startswith("ss://"):
            return None
        
        key = key[5:]  # Remove ss://
        key = key.split("#")[0]  # Remove remark
        
        if "@" in key:
            # Format: ss://base64(method:password)@host:port
            encoded, server = key.split("@", 1)
            host, port = server.rsplit(":", 1)
            host = host.strip("[]")
            
            # Decode method and password
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            
            try:
                decoded = base64.b64decode(encoded).decode('utf-8')
                method, password = decoded.split(":", 1)
            except:
                # Sometimes it's not encoded
                method, password = encoded.split(":", 1)
        else:
            # Format: ss://base64(method:password@host:port)
            padding = len(key) % 4
            if padding:
                key += '=' * (4 - padding)
            
            decoded = base64.b64decode(key).decode('utf-8')
            
            # Split credentials and server
            if "@" in decoded:
                creds, server = decoded.rsplit("@", 1)
                method, password = creds.split(":", 1)
                host, port = server.rsplit(":", 1)
                host = host.strip("[]")
            else:
                return None
        
        config = {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": int(port),
                    "method": method,
                    "password": password,
                    "level": 0
                }]
            },
            "streamSettings": {
                "network": "tcp",
                "security": "none"
            }
        }
        
        return config
        
    except Exception as e:
        log(f"Shadowsocks parse error: {e}", "debug")
        return None

def parse_key_to_config(key: str) -> Tuple[Optional[Dict], str, str]:
    """Main parser dispatcher"""
    key = key.strip()
    key_lower = key.lower()
    
    # Extract security type for stats
    security = "none"
    if "security=reality" in key_lower:
        security = "reality"
    elif "security=tls" in key_lower or "tls=tls" in key_lower:
        security = "tls"
    elif "security=xtls" in key_lower:
        security = "xtls"
    
    try:
        if key_lower.startswith("vless://"):
            config = parse_vless(key)
            return config, "VLESS", security
        elif key_lower.startswith("vmess://"):
            config = parse_vmess(key)
            return config, "VMESS", security
        elif key_lower.startswith("trojan://"):
            config = parse_trojan(key)
            return config, "TROJAN", security
        elif key_lower.startswith("ss://"):
            config = parse_shadowsocks(key)
            return config, "SS", security
        else:
            return None, "UNKNOWN", security
    except Exception as e:
        log(f"Parse error: {e}", "debug")
        return None, "UNKNOWN", security

# ==================== XRAY CORE ====================
def setup_xray() -> Optional[Path]:
    """Download and setup xray-core"""
    exe_name = "xray.exe" if os.name == 'nt' else "xray"
    exe_path = XRAY_FOLDER / exe_name
    
    if exe_path.exists():
        log("✅ Xray-core already installed", "success")
        return exe_path
    
    log("📥 Downloading xray-core...", "info")
    
    try:
        import platform
        system = platform.system().lower()
        machine = platform.machine().lower()
        
        # Determine the right binary
        if system == "windows":
            if "64" in machine or "amd64" in machine:
                filename = "Xray-windows-64.zip"
            else:
                filename = "Xray-windows-32.zip"
        elif system == "linux":
            if "aarch64" in machine or "arm64" in machine:
                filename = "Xray-linux-arm64-v8a.zip"
            elif "arm" in machine:
                filename = "Xray-linux-arm32-v7a.zip"
            elif "64" in machine:
                filename = "Xray-linux-64.zip"
            else:
                filename = "Xray-linux-32.zip"
        elif system == "darwin":  # macOS
            if "arm" in machine:
                filename = "Xray-macos-arm64-v8a.zip"
            else:
                filename = "Xray-macos-64.zip"
        else:
            log(f"Unsupported system: {system}", "error")
            return None
        
        # Download from GitHub
        url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{filename}"
        log(f"Downloading from: {url}", "debug")
        
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()
        
        zip_path = XRAY_FOLDER / "xray.zip"
        total_size = int(response.headers.get('content-length', 0))
        
        # Download with progress
        with open(zip_path, 'wb') as f:
            downloaded = 0
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        print(f"\rDownloading: {percent:.1f}%", end='')
        print()
        
        # Extract
        log("📦 Extracting xray-core...", "info")
        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(XRAY_FOLDER)
        
        # Clean up
        zip_path.unlink()
        
        # Make executable on Unix systems
        if system != "windows":
            exe_path.chmod(0o755)
        
        log("✅ Xray-core installed successfully", "success")
        return exe_path
        
    except Exception as e:
        log(f"❌ Failed to setup xray-core: {e}", "error")
        return None

def create_xray_config(proxy_config: Dict, http_port: int) -> Dict:
    """Create xray client configuration"""
    return {
        "log": {
            "loglevel": "none"
        },
        "inbounds": [{
            "port": http_port,
            "listen": "127.0.0.1",
            "protocol": "http",
            "settings": {
                "timeout": 30,
                "allowTransparent": False,
                "userLevel": 0
            }
        }],
        "outbounds": [proxy_config],
        "routing": {
            "domainStrategy": "AsIs"
        },
        "policy": {
            "levels": {
                "0": {
                    "handshake": 4,
                    "connIdle": 300,
                    "uplinkOnly": 2,
                    "downlinkOnly": 5,
                    "bufferSize": 10240
                }
            }
        }
    }

class XraySession:
    """Context manager for xray process"""
    
    def __init__(self, xray_exe: Path, proxy_config: Dict, startup_delay: float = 1.5):
        self.xray_exe = xray_exe
        self.proxy_config = proxy_config
        self.startup_delay = startup_delay
        self.process = None
        self.port = random.randint(20000, 50000)
        self.config_file = XRAY_FOLDER / f"config_{self.port}.json"
        self.proxies = None
        self.ok = False
    
    def __enter__(self):
        try:
            # Write config
            config = create_xray_config(self.proxy_config, self.port)
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=2)
            
            # Start xray
            self.process = subprocess.Popen(
                [str(self.xray_exe), "run", "-c", str(self.config_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
            )
            
            register_process(self.process)
            
            # Wait for startup
            time.sleep(self.startup_delay)
            
            # Check if process is still alive
            if self.process.poll() is None:
                self.proxies = {
                    'http': f'http://127.0.0.1:{self.port}',
                    'https': f'http://127.0.0.1:{self.port}'
                }
                self.ok = True
            else:
                log(f"Xray process died immediately (exit code: {self.process.poll()})", "debug")
                
        except Exception as e:
            log(f"Failed to start xray session: {e}", "debug")
            self.ok = False
        
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Kill process
        if self.process:
            try:
                self.process.kill()
                self.process.wait(timeout=1)
            except:
                pass
            unregister_process(self.process)
        
        # Clean up config file
        try:
            if self.config_file.exists():
                self.config_file.unlink()
        except:
            pass

# ==================== DOWNLOAD & DEDUPLICATE ====================
def download_and_deduplicate(sources: Dict[str, List[str]] = None) -> List[str]:
    """Download proxy keys from sources and deduplicate"""
    if sources is None:
        sources = KEY_SOURCES
    
    all_keys = []
    seen_normalized = set()
    
    total_sources = sum(len(urls) for urls in sources.values())
    current_source = 0
    
    log(f"📥 Downloading from {total_sources} sources...", "info")
    
    for region, urls in sources.items():
        for url in urls:
            current_source += 1
            try:
                log(f"  [{current_source}/{total_sources}] {region}: {url.split('/')[-1][:30]}...", "debug")
                
                # Download with timeout and retry
                for attempt in range(3):
                    try:
                        response = requests.get(url, timeout=30, headers={
                            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0'
                        })
                        response.raise_for_status()
                        break
                    except requests.exceptions.RequestException as e:
                        if attempt == 2:
                            raise e
                        time.sleep(2)
                
                content = response.text.strip()
                
                # Handle base64 encoded lists
                if url.endswith('/base64/vmess') or 'base64' in url:
                    try:
                        decoded = base64.b64decode(content).decode('utf-8')
                        content = decoded
                    except:
                        pass
                
                lines = content.split('\n')
                
                for line in lines:
                    line = html.unescape(line.strip())
                    
                    # Skip empty lines and comments
                    if not line or line.startswith('#') or line.startswith('//'):
                        continue
                    
                    # Check if it's a valid proxy protocol
                    if not any(line.lower().startswith(p) for p in [
                        "vless://", "vmess://", "trojan://", "ss://", 
                        "ssr://", "hysteria://", "hysteria2://", "tuic://"
                    ]):
                        continue
                    
                    # Normalize for deduplication (remove remarks)
                    normalized = line.split("#")[0].strip()
                    
                    if normalized in seen_normalized:
                        with stats_lock:
                            stats.duplicates += 1
                        continue
                    
                    seen_normalized.add(normalized)
                    all_keys.append(line)
                    
                    with stats_lock:
                        stats.total_downloaded += 1
                
            except Exception as e:
                log(f"  Failed to download from {url}: {e}", "warning")
                continue
    
    with stats_lock:
        stats.unique = len(all_keys)
    
    log(f"📊 Downloaded: {stats.total_downloaded} | Unique: {len(all_keys)} | Duplicates: {stats.duplicates}", "info")
    
    return all_keys

# ==================== CHECKERS ====================
def tcp_check(key: str) -> Optional[str]:
    """Quick TCP connectivity check"""
    host, port = extract_host_port(key)
    
    if not host or not port:
        return None
    
    # Try multiple times with different timeouts
    for attempt in range(CONFIG.TCP_RETRIES + 1):
        try:
            # Create socket with timeout
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(CONFIG.TCP_TIMEOUT)
            
            # Try to connect
            result = sock.connect_ex((host, port))
            sock.close()
            
            if result == 0:
                with stats_lock:
                    stats.tcp_passed += 1
                return key
            
        except socket.gaierror:
            # DNS resolution failed
            break
        except:
            pass
        
        # Wait before retry
        if attempt < CONFIG.TCP_RETRIES:
            time.sleep(0.5)
    
    with stats_lock:
        stats.tcp_failed += 1
    
    return None

def xray_check_with_mutations(key: str, xray_exe: Path) -> CheckResult:
    """Full xray check with mutation attempts if needed"""
    # Parse the key
    base_config, protocol, security = parse_key_to_config(key)
    
    if not base_config:
        return CheckResult(
            key=key,
            alive=False,
            error="parse_failed",
            protocol=protocol
        )
    
    # Extract host and port for result
    host, port = extract_host_port(key)
    
    # First attempt with original config
    result = run_full_test(key, base_config, protocol, xray_exe, host, port, security)
    
    # If successful and high quality, return immediately
    if result.alive and result.quality in [Quality.ELITE, Quality.PREMIUM]:
        return result
    
    # Try mutations if first attempt failed or low quality
    if not result.alive or result.quality in [Quality.GOOD, Quality.STANDARD, None]:
        best_result = result
        
        for attempt in range(1, 11):  # Try up to 10 mutations
            mutated_config, mutation_name = ai_engine.mutate_config(base_config, attempt)
            
            if not mutation_name:
                continue
            
            log(f"  Trying mutation {attempt}: {mutation_name}", "debug")
            
            mut_result = run_full_test(
                key, mutated_config, protocol, xray_exe, host, port, security
            )
            
            # Check if this mutation is better
            if mut_result.alive:
                if not best_result.alive or (
                    mut_result.quality and best_result.quality and
                    list(Quality).index(mut_result.quality) < list(Quality).index(best_result.quality)
                ):
                    mut_result.mutation_used = mutation_name
                    mut_result.ai_verdict += f" [MUTATION:{mutation_name}]"
                    best_result = mut_result
                    
                    with stats_lock:
                        stats.mutations_success += 1
                    
                    # If we got elite quality, stop trying
                    if mut_result.quality == Quality.ELITE:
                        break
        
        return best_result
    
    return result

def run_full_test(
    key: str,
    config: Dict,
    protocol: str,
    xray_exe: Path,
    host: str,
    port: int,
    security: str
) -> CheckResult:
    """Run complete test suite on a proxy"""
    
    latencies = []
    categories_passed = 0
    telegram_works = False
    netflix_works = False
    
    # Phase 1: Latency test
    with XraySession(xray_exe, config, CONFIG.XRAY_STARTUP) as session:
        if not session.ok:
            return CheckResult(
                key=key,
                alive=False,
                error="xray_startup",
                protocol=protocol,
                host=host,
                port=port,
                security=security
            )
        
        # Test latency with multiple samples
        for i in range(CONFIG.LATENCY_SAMPLES):
            try:
                start_time = time.time()
                response = requests.get(
                    CONFIG.CHECK_URLS[i % len(CONFIG.CHECK_URLS)],
                    proxies=session.proxies,
                    timeout=CONFIG.XRAY_TIMEOUT,
                    allow_redirects=False
                )
                
                if response.status_code in [204, 200]:
                    latency = (time.time() - start_time) * 1000
                    latencies.append(latency)
                
            except:
                pass
            
            # Small delay between tests
            if i < CONFIG.LATENCY_SAMPLES - 1:
                time.sleep(0.2)
        
        # Check if we have enough successful latency tests
        if len(latencies) < CONFIG.MIN_LATENCY_SUCCESS:
            return CheckResult(
                key=key,
                alive=False,
                error="latency_test_failed",
                protocol=protocol,
                host=host,
                port=port,
                security=security
            )
        
        # Phase 2: Category tests
        for url, category in CONFIG.CATEGORY_URLS:
            try:
                response = requests.get(
                    url,
                    proxies=session.proxies,
                    timeout=8,
                    allow_redirects=True,
                    headers={'User-Agent': 'Mozilla/5.0'}
                )
                
                if response.status_code < 500:
                    categories_passed += 1
                    if category == "telegram":
                        telegram_works = True
                    elif category == "netflix":
                        netflix_works = True
                        
            except:
                pass
    
    # Phase 3: Reconnection test
    reconnect_success = 0
    
    for i in range(CONFIG.RECONNECT_TESTS):
        time.sleep(0.5)  # Brief pause between reconnects
        
        with XraySession(xray_exe, config, CONFIG.XRAY_STARTUP_QUICK) as session:
            if session.ok:
                try:
                    response = requests.get(
                        CONFIG.CHECK_URLS[0],
                        proxies=session.proxies,
                        timeout=5,
                        allow_redirects=False
                    )
                    
                    if response.status_code in [204, 200]:
                        reconnect_success += 1
                        
                except:
                    pass
    
    # Calculate metrics
    avg_latency = mean(latencies) if latencies else 999
    jitter = stdev(latencies) if len(latencies) > 1 else 0
    
    # Determine if proxy is alive
    alive = reconnect_success >= CONFIG.MIN_RECONNECT_SUCCESS
    
    # Determine quality level
    quality = None
    if alive:
        for q in Quality:
            threshold = QUALITY_THRESHOLDS[q]
            if (avg_latency <= threshold.latency_max and
                jitter <= threshold.jitter_max and
                categories_passed >= threshold.categories_min and
                reconnect_success >= threshold.reconnect_min):
                quality = q
                break
    
    # Update statistics
    with stats_lock:
        if alive:
            stats.xray_passed += 1
            if quality:
                stats.by_quality[quality] += 1
            stats.by_protocol[protocol] += 1
        else:
            stats.xray_failed += 1
    
    return CheckResult(
        key=key,
        alive=alive,
        latency=avg_latency,
        jitter=jitter,
        reconnect_success=reconnect_success,
        categories=categories_passed,
        telegram=telegram_works,
        netflix=netflix_works,
        quality=quality,
        protocol=protocol,
        host=host,
        port=port,
        security=security
    )

# ==================== RESULT HANDLING ====================
def save_results(results: List[CheckResult], region: str = "ALL"):
    """Save results to files with detailed statistics"""
    
    # Group by quality
    by_quality = defaultdict(list)
    for result in results:
        if result.quality:
            by_quality[result.quality].append(result)
    
    # Save each quality level
    for quality in Quality:
        if quality not in by_quality:
            continue
        
        quality_results = by_quality[quality]
        
        # Sort by latency
        quality_results.sort(key=lambda x: x.latency)
        
        # Create filename
        filename = PREMIUM_FOLDER / f"{quality.value}.txt"
        
        # Write to file
        with open(filename, 'w', encoding='utf-8') as f:
            # Header
            f.write(f"# {quality.name} Proxies\n")
            f.write(f"# Region: {region}\n")
            f.write(f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
            f.write(f"# Total: {len(quality_results)} proxies\n")
            f.write(f"# Channel: {MY_CHANNEL}\n")
            f.write("#" + "="*50 + "\n\n")
            
            # Write proxies
            for result in quality_results:
                # Add metadata as comment
                metadata = f"# Latency: {result.latency:.1f}ms | "
                metadata += f"Jitter: {result.jitter:.1f}ms | "
                metadata += f"Categories: {result.categories}/5"
                
                if result.telegram:
                    metadata += " | Telegram: ✓"
                if result.netflix:
                    metadata += " | Netflix: ✓"
                if result.mutation_used:
                    metadata += f" | Mutation: {result.mutation_used}"
                
                f.write(f"{metadata}\n")
                f.write(f"{result.key}\n\n")
        
        log(f"💾 Saved {len(quality_results)} {quality.name} proxies to {filename.name}", "success")
    
        # Generate statistics JSON
    stats_data = {
        "timestamp": datetime.now().isoformat(),
        "region": region,
        "total_checked": stats.tcp_passed,
        "total_working": len(results),
        "by_quality": {q.value: len(by_quality[q]) for q in Quality},
        "by_protocol": dict(stats.by_protocol),
        "mutations": {
            "tried": stats.total_mutations_tried,
            "successful": stats.mutations_success
        },
        "ai": {
            "enabled": ai_engine.enabled,
            "anomalies_detected": stats.ai_anomalies,
            "model_trained": ai_engine.model_risk is not None
        },
        "processing_time": time.time() - stats.start_time
    }

    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats_data, f, indent=2)

    log(f"📊 Statistics saved to {STATS_FILE.name}", "info")

    return stats_data
