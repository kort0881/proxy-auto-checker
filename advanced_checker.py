#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Proxy Checker v4.2 SMART+
Two-phase check + parallel categories + session pooling
+ Dynamic AI scoring + adaptive categories + scalable training
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
from typing import List, Dict, Optional, Tuple, Set
from dataclasses import dataclass, field
from enum import Enum
from statistics import mean, stdev
from logging.handlers import RotatingFileHandler

# ==================== AI (optional) ====================
AI_AVAILABLE = False
try:
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    AI_AVAILABLE = True
except ImportError:
    print("[INFO] scikit-learn not found, AI disabled")

# ==================== PATHS ====================
WORK_DIR = Path(__file__).parent.absolute()
XRAY_FOLDER = WORK_DIR / "xray"
RESULTS_FOLDER = WORK_DIR / "results"
PREMIUM_FOLDER = RESULTS_FOLDER / "premium"
HISTORY_FILE = RESULTS_FOLDER / "history.jsonl"
STATS_FILE = RESULTS_FOLDER / "stats_latest.json"
LOG_FILE = RESULTS_FOLDER / "checker.log"
CATEGORY_STATS_FILE = RESULTS_FOLDER / "category_stats.json"

for d in [XRAY_FOLDER, RESULTS_FOLDER, PREMIUM_FOLDER]:
    d.mkdir(parents=True, exist_ok=True)

# ==================== SOURCES ====================
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


# ==================== CONFIG ====================
@dataclass
class Config:
    TCP_WORKERS: int = 40
    TCP_TIMEOUT: int = 8
    TCP_RETRIES: int = 1

    XRAY_WORKERS: int = 8
    XRAY_STARTUP: float = 5.0
    XRAY_STARTUP_QUICK: float = 3.0
    XRAY_TIMEOUT: int = 12

    QUICK_CHECK_TIMEOUT: int = 8

    LATENCY_SAMPLES: int = 3
    MIN_LATENCY_SUCCESS: int = 2

    # Categories checked in parallel
    CATEGORY_URLS: List[Tuple[str, str]] = field(default_factory=lambda: [
        ("https://www.google.com", "google"),
        ("https://web.telegram.org", "telegram"),
        ("https://www.youtube.com", "youtube"),
        ("https://vk.com", "vk"),
        ("https://www.instagram.com", "instagram"),
        ("https://twitter.com", "twitter"),
        ("https://www.tiktok.com", "tiktok"),
    ])
    CATEGORY_TIMEOUT: int = 6
    CATEGORY_PARALLEL: int = 4

    RECONNECT_TESTS: int = 1
    MIN_RECONNECT_SUCCESS: int = 1

    CHECK_URLS: List[str] = field(default_factory=lambda: [
        'https://cp.cloudflare.com/generate_204',
        'http://www.gstatic.com/generate_204',
    ])

    MAX_SAFE_MUTATIONS: int = 1
    GC_EVERY: int = 50

    # AI scalability
    AI_MAX_HISTORY: int = 15000
    AI_TRAIN_BATCH: int = 5000
    AI_RETRAIN_EVERY: int = 200
    AI_TREND_WINDOW: int = 50


CONFIG = Config()


# ==================== QUALITY ====================
class Quality(Enum):
    ELITE = "elite"
    PREMIUM = "premium"
    GOOD = "good"


@dataclass
class QualityThreshold:
    latency_max: float
    jitter_max: float
    categories_min: int


QUALITY_THRESHOLDS = {
    Quality.ELITE: QualityThreshold(
        latency_max=200, jitter_max=80, categories_min=4
    ),
    Quality.PREMIUM: QualityThreshold(
        latency_max=500, jitter_max=150, categories_min=3
    ),
    Quality.GOOD: QualityThreshold(
        latency_max=2000, jitter_max=500, categories_min=2
    ),
}


@dataclass
class CheckResult:
    key: str
    alive: bool
    latency: float = 0
    jitter: float = 0
    reconnect_success: int = 0
    categories: int = 0
    category_details: Dict[str, bool] = field(default_factory=dict)
    telegram: bool = False
    quality: Optional[Quality] = None
    protocol: str = ""
    host: str = ""
    port: int = 0
    security: str = ""
    error: Optional[str] = None
    mutation_used: str = ""
    is_anomaly: bool = False
    ai_verdict: str = ""
    ai_score: float = 0.0


@dataclass
class Stats:
    total_downloaded: int = 0
    duplicates: int = 0
    unique: int = 0
    tcp_passed: int = 0
    tcp_failed: int = 0
    quick_passed: int = 0
    quick_failed: int = 0
    xray_passed: int = 0
    xray_failed: int = 0
    by_quality: Dict[Quality, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    by_protocol: Dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    errors: Dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    ai_anomalies: int = 0
    ai_retrains: int = 0
    mutations_success: int = 0
    mutations_tried: int = 0
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
    handler.setFormatter(
        logging.Formatter('%(asctime)s | %(message)s')
    )
    logger = logging.getLogger('ProxyChecker')
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    return logger


file_logger = setup_logging()


def log(msg: str):
    print(msg)
    file_logger.info(msg)


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
    with _processes_lock:
        for p in list(_active_processes):
            try:
                p.kill()
                p.wait(timeout=1)
            except:
                pass
        _active_processes.clear()


atexit.register(cleanup_all_processes)


def signal_handler(signum, frame):
    print("\n[STOP] Interrupted")
    cleanup_all_processes()
    sys.exit(1)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


def cleanup_memory():
    gc.collect()
    time.sleep(0.1)


# ==================== AI ENGINE (dynamic + scalable) ====================
class AIEngine:
    """
    Dynamic AI engine with:
    - Historical performance tracking per host/protocol
    - Latency trend analysis (improving/degrading)
    - Adaptive category weighting
    - Scalable batch training with data pruning
    """

    def __init__(self):
        self.enabled = AI_AVAILABLE
        self.history: List[Dict] = []
        self.model_anomaly = None
        self.scaler = StandardScaler() if AI_AVAILABLE else None
        self._lock = threading.Lock()
        self._checks_since_retrain = 0

        # Dynamic performance tracking
        self.protocol_stats = defaultdict(lambda: {
            'success': 0, 'total': 0,
            'latencies': [],         # rolling window
            'trend': 0.0,            # positive = improving
            'last_success_rate': 0.5
        })

        # Per-host performance (keyed by host:port)
        self.host_stats = defaultdict(lambda: {
            'success': 0, 'total': 0,
            'avg_latency': 0.0,
            'last_seen': 0,
            'quality_history': []    # last N quality values
        })

        # Dynamic category weights (learned from data)
        self.category_weights = defaultdict(lambda: {
            'success': 0, 'total': 0, 'avg_time': 0.0,
            'weight': 1.0
        })

        self._load_history()
        self._load_category_stats()
        if self.enabled:
            self._train()

    def _load_history(self):
        if not HISTORY_FILE.exists():
            return
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # Scalability: only load last AI_MAX_HISTORY records
                lines = lines[-CONFIG.AI_MAX_HISTORY:]
                for line in lines:
                    try:
                        rec = json.loads(line)
                        self.history.append(rec)
                        self._update_stats_from_record(rec)
                    except:
                        continue
            log(f"[AI] Loaded {len(self.history)} history records")
        except:
            pass

    def _load_category_stats(self):
        """Load learned category weights from disk"""
        if not CATEGORY_STATS_FILE.exists():
            return
        try:
            with open(CATEGORY_STATS_FILE, 'r') as f:
                data = json.load(f)
                for cat_name, cat_data in data.items():
                    self.category_weights[cat_name].update(cat_data)
            log(f"[AI] Loaded category weights for {len(data)} sites")
        except:
            pass

    def _save_category_stats(self):
        """Persist category weights to disk"""
        try:
            data = {}
            for name, w in self.category_weights.items():
                data[name] = {
                    'success': w['success'],
                    'total': w['total'],
                    'avg_time': w['avg_time'],
                    'weight': w['weight']
                }
            with open(CATEGORY_STATS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except:
            pass

    def _update_stats_from_record(self, rec: Dict):
        """Update internal stats from a history record"""
        proto = rec.get('protocol', '')
        ps = self.protocol_stats[proto]
        ps['total'] += 1
        if rec.get('alive'):
            ps['success'] += 1
            lat = rec.get('latency', 0)
            if lat > 0:
                ps['latencies'].append(lat)
                # Keep rolling window
                if len(ps['latencies']) > CONFIG.AI_TREND_WINDOW * 2:
                    ps['latencies'] = ps['latencies'][
                        -CONFIG.AI_TREND_WINDOW * 2:
                    ]

        # Per-host stats
        host_key = rec.get('host_key', '')
        if host_key:
            hs = self.host_stats[host_key]
            hs['total'] += 1
            hs['last_seen'] = rec.get('timestamp', 0)
            if rec.get('alive'):
                hs['success'] += 1
                hs['avg_latency'] = (
                    hs['avg_latency'] * 0.8
                    + rec.get('latency', 0) * 0.2
                )
                q = rec.get('quality')
                if q:
                    hs['quality_history'].append(q)
                    if len(hs['quality_history']) > 20:
                        hs['quality_history'] = hs['quality_history'][-20:]

        # Category stats
        cat_details = rec.get('category_details', {})
        for cat_name, success in cat_details.items():
            cw = self.category_weights[cat_name]
            cw['total'] += 1
            if success:
                cw['success'] += 1

    def _compute_trends(self):
        """Compute latency trends per protocol"""
        for proto, ps in self.protocol_stats.items():
            lats = ps['latencies']
            if len(lats) < CONFIG.AI_TREND_WINDOW:
                ps['trend'] = 0.0
                continue

            # Compare recent window vs older window
            window = CONFIG.AI_TREND_WINDOW
            old_window = lats[-window * 2:-window]
            new_window = lats[-window:]

            if old_window and new_window:
                old_avg = mean(old_window)
                new_avg = mean(new_window)
                if old_avg > 0:
                    # Positive = improving (latency decreased)
                    ps['trend'] = (old_avg - new_avg) / old_avg
                else:
                    ps['trend'] = 0.0

            # Update success rate
            if ps['total'] > 0:
                ps['last_success_rate'] = ps['success'] / ps['total']

    def _update_category_weights(self):
        """Recalculate category weights based on actual success rates"""
        for name, cw in self.category_weights.items():
            if cw['total'] > 10:
                rate = cw['success'] / cw['total']
                # Weight = how reliably this site works via proxy
                # Sites that always fail get low weight
                # Sites that always succeed are "easy" = lower weight
                # Best weight for sites at 50-80% success (discriminating)
                if rate > 0.9:
                    cw['weight'] = 0.5  # too easy, low value
                elif rate > 0.6:
                    cw['weight'] = 1.5  # good discriminator
                elif rate > 0.3:
                    cw['weight'] = 1.0  # moderate
                else:
                    cw['weight'] = 0.3  # mostly fails, low value

    def _train(self):
        """Train anomaly model with scalability controls"""
        if len(self.history) < 50:
            return

        self._compute_trends()
        self._update_category_weights()

        try:
            # Scalability: use last AI_TRAIN_BATCH records
            train_data = self.history[-CONFIG.AI_TRAIN_BATCH:]

            X = []
            for rec in train_data:
                X.append(self._extract_features(rec))

            X = np.array(X)
            X_scaled = self.scaler.fit_transform(X)
            self.model_anomaly = IsolationForest(
                contamination=0.1, random_state=42,
                n_estimators=100, max_samples=min(len(X), 1000)
            ).fit(X_scaled)
            log(
                f"[AI] Trained on {len(X)} records "
                f"(total history: {len(self.history)})"
            )
        except Exception as e:
            log(f"[AI] Training failed: {e}")

    def _extract_features(self, rec: Dict) -> List[float]:
        """Extract feature vector from a record"""
        proto = rec.get('protocol', '')
        ps = self.protocol_stats.get(proto, {})

        return [
            rec.get('latency', 999),
            rec.get('jitter', 100),
            rec.get('reconnect', 0),
            rec.get('categories', 0),
            1 if proto == 'VLESS' else 0,
            1 if proto == 'VMess' else 0,
            1 if proto == 'Trojan' else 0,
            1 if rec.get('security') == 'reality' else 0,
            1 if rec.get('security') == 'tls' else 0,
            # Dynamic features
            ps.get('last_success_rate', 0.5),
            ps.get('trend', 0.0),
        ]

    def _maybe_retrain(self):
        """Retrain model periodically as new data comes in"""
        with self._lock:
            self._checks_since_retrain += 1
            if self._checks_since_retrain >= CONFIG.AI_RETRAIN_EVERY:
                self._checks_since_retrain = 0
                if self.enabled and len(self.history) >= 100:
                    self._train()
                    self._prune_history()
                    with stats_lock:
                        stats.ai_retrains += 1

    def _prune_history(self):
        """Scalability: keep history file from growing forever"""
        if len(self.history) > CONFIG.AI_MAX_HISTORY:
            # Keep only recent records
            self.history = self.history[-CONFIG.AI_MAX_HISTORY:]
            try:
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                    for rec in self.history:
                        f.write(json.dumps(rec) + '\n')
                log(
                    f"[AI] Pruned history to "
                    f"{len(self.history)} records"
                )
            except:
                pass

    def prioritize_keys(self, keys: List[str]) -> List[str]:
        """
        Dynamic prioritization using:
        1. Protocol success rate (historical)
        2. Latency trend (improving protocols first)
        3. Host reputation (if seen before)
        4. Security type bonus
        """
        if not self.enabled:
            return keys

        self._compute_trends()

        def score(key):
            kl = key.lower()

            # Base protocol score
            if 'vless://' in kl:
                proto, s = 'VLESS', 0.7
            elif 'trojan://' in kl:
                proto, s = 'Trojan', 0.6
            elif 'vmess://' in kl:
                proto, s = 'VMess', 0.5
            else:
                proto, s = 'SS', 0.4

            ps = self.protocol_stats.get(proto)
            if ps and ps['total'] > 10:
                # Weight by historical success rate
                rate = ps['success'] / ps['total']
                s = s * 0.2 + rate * 0.5

                # Bonus for improving trend
                trend = ps.get('trend', 0)
                if trend > 0:
                    s += trend * 0.2  # up to +0.2 for improving
                elif trend < -0.1:
                    s -= 0.1  # penalty for degrading

            # Host reputation
            host, port = extract_host_port(key)
            if host and port:
                host_key = f"{host}:{port}"
                hs = self.host_stats.get(host_key)
                if hs and hs['total'] > 3:
                    host_rate = hs['success'] / hs['total']
                    s += host_rate * 0.15

                    # Bonus for recently successful hosts
                    age = time.time() - hs.get('last_seen', 0)
                    if age < 86400 and host_rate > 0.7:  # 24h
                        s += 0.1

                    # Bonus for consistently high quality
                    qh = hs.get('quality_history', [])
                    if qh:
                        elite_ratio = qh.count('elite') / len(qh)
                        s += elite_ratio * 0.1

            # Security type bonus
            if 'security=reality' in kl:
                s += 0.15
            elif 'security=tls' in kl:
                s += 0.05

            return s

        return sorted(keys, key=score, reverse=True)

    def get_adaptive_categories(self) -> List[Tuple[str, str, float]]:
        """
        Return categories sorted by discrimination value.
        Format: (url, name, weight)
        Categories that are too easy or always fail get lower priority.
        """
        result = []
        for url, name in CONFIG.CATEGORY_URLS:
            cw = self.category_weights.get(name, {})
            weight = cw.get('weight', 1.0)
            result.append((url, name, weight))

        # Sort: best discriminators first
        result.sort(key=lambda x: x[2], reverse=True)
        return result

    def weighted_category_score(
        self, category_details: Dict[str, bool]
    ) -> float:
        """
        Calculate weighted category score instead of simple count.
        Sites that are better discriminators count more.
        """
        score = 0.0
        max_score = 0.0
        for name, passed in category_details.items():
            cw = self.category_weights.get(name, {})
            weight = cw.get('weight', 1.0)
            max_score += weight
            if passed:
                score += weight
        if max_score == 0:
            return 0
        return score / max_score  # normalized 0..1

    def analyze_result(self, result: CheckResult):
        if not self.enabled or not self.model_anomaly or not result.alive:
            return
        try:
            rec = {
                'latency': result.latency,
                'jitter': result.jitter,
                'reconnect': result.reconnect_success,
                'categories': result.categories,
                'protocol': result.protocol,
                'security': result.security,
            }
            features = [self._extract_features(rec)]
            fs = self.scaler.transform(features)

            if self.model_anomaly.predict(fs)[0] == -1:
                result.is_anomaly = True
                result.ai_verdict = "[ANOMALY]"
                with stats_lock:
                    stats.ai_anomalies += 1

            # Compute dynamic AI score (0..1)
            # Based on how this result compares to historical norms
            proto_ps = self.protocol_stats.get(result.protocol, {})
            avg_lats = proto_ps.get('latencies', [])
            if avg_lats:
                historical_avg = mean(avg_lats[-50:])
                if historical_avg > 0:
                    # Lower latency than average = higher score
                    ratio = result.latency / historical_avg
                    result.ai_score = max(0, min(1, 1.5 - ratio))
                else:
                    result.ai_score = 0.5
            else:
                result.ai_score = 0.5

        except:
            pass

    def save_result(self, result: CheckResult):
        host_key = (
            f"{result.host}:{result.port}" if result.host else ""
        )
        record = {
            'timestamp': time.time(),
            'alive': result.alive,
            'protocol': result.protocol,
            'latency': result.latency,
            'jitter': result.jitter,
            'reconnect': result.reconnect_success,
            'categories': result.categories,
            'category_details': result.category_details,
            'quality': (
                result.quality.value if result.quality else None
            ),
            'security': result.security,
            'error': result.error,
            'mutation': result.mutation_used,
            'host_key': host_key,
            'ai_score': result.ai_score,
        }
        try:
            with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record) + '\n')
            self.history.append(record)
            self._update_stats_from_record(record)
        except:
            pass

        # Periodic retrain check
        self._maybe_retrain()

    def safe_mutate(
        self, proxy_config: Dict, attempt: int
    ) -> Tuple[Dict, str]:
        mutated = json.loads(json.dumps(proxy_config))
        stream = mutated.get('streamSettings', {})
        name = ""
        if attempt == 1:
            fps = [
                'chrome', 'firefox', 'safari',
                'edge', 'ios', 'android', 'random'
            ]
            if 'tlsSettings' in stream:
                old = stream['tlsSettings'].get(
                    'fingerprint', 'chrome'
                )
                new = random.choice([f for f in fps if f != old])
                stream['tlsSettings']['fingerprint'] = new
                name = f"FP_{new}"
            elif 'realitySettings' in stream:
                old = stream['realitySettings'].get(
                    'fingerprint', 'chrome'
                )
                new = random.choice([f for f in fps if f != old])
                stream['realitySettings']['fingerprint'] = new
                name = f"FP_{new}"
        return mutated, name

    def finalize(self):
        """Save learned data at end of run"""
        self._save_category_stats()
        self._compute_trends()
        log(
            "[AI] Saved category weights and computed trends"
        )


ai_engine = AIEngine()


# ==================== XRAY SETUP ====================
def setup_xray() -> Optional[Path]:
    exe_name = "xray.exe" if os.name == 'nt' else "xray"
    exe_path = XRAY_FOLDER / exe_name

    if exe_path.exists():
        log("[OK] Xray found")
        return exe_path

    log("[DL] Downloading xray-core...")
    try:
        import platform
        system = platform.system().lower()
        machine = platform.machine().lower()

        if system == "windows":
            arch = "64" if "64" in machine else "32"
            filename = f"Xray-windows-{arch}.zip"
        elif system == "linux":
            if "aarch64" in machine or "arm64" in machine:
                arch = "arm64-v8a"
            else:
                arch = "64"
            filename = f"Xray-linux-{arch}.zip"
        elif system == "darwin":
            arch = "arm64-v8a" if "arm" in machine else "64"
            filename = f"Xray-macos-{arch}.zip"
        else:
            return None

        url = (
            "https://github.com/XTLS/Xray-core/releases"
            f"/latest/download/{filename}"
        )
        r = requests.get(url, stream=True, timeout=120)
        zip_path = XRAY_FOLDER / "xray.zip"
        with open(zip_path, 'wb') as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)

        import zipfile
        with zipfile.ZipFile(zip_path, 'r') as zf:
            zf.extractall(XRAY_FOLDER)
        zip_path.unlink()

        if system != "windows":
            exe_path.chmod(0o755)

        log("[OK] Xray installed")
        return exe_path
    except Exception as e:
        log(f"[ERR] Xray setup: {e}")
        return None


# ==================== XRAY SESSION ====================
def wait_for_port(port: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(
                ("127.0.0.1", port), timeout=0.3
            ):
                return True
        except:
            time.sleep(0.1)
    return False


def create_xray_config(proxy_config: Dict, http_port: int) -> Dict:
    return {
        "log": {"loglevel": "none"},
        "inbounds": [{
            "port": http_port,
            "listen": "127.0.0.1",
            "protocol": "http",
            "settings": {"timeout": 30}
        }],
        "outbounds": [proxy_config]
    }


class XraySession:
    def __init__(self, xray_exe: Path, proxy_config: Dict,
                 startup: float = 5.0):
        self.xray_exe = xray_exe
        self.proxy_config = proxy_config
        self.startup = startup
        self.process = None
        self.port = random.randint(20000, 50000)
        self.config_file = XRAY_FOLDER / f"config_{self.port}.json"
        self.proxies = None
        self.ok = False
        self.http_session = None

    def __enter__(self):
        try:
            config = create_xray_config(
                self.proxy_config, self.port
            )
            with open(self.config_file, 'w') as f:
                json.dump(config, f)

            self.process = subprocess.Popen(
                [
                    str(self.xray_exe), "run",
                    "-c", str(self.config_file)
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            register_process(self.process)

            if (wait_for_port(self.port, timeout=self.startup)
                    and self.process.poll() is None):
                self.proxies = {
                    'http': f'http://127.0.0.1:{self.port}',
                    'https': f'http://127.0.0.1:{self.port}'
                }
                self.http_session = requests.Session()
                self.http_session.proxies = self.proxies
                self.http_session.headers.update({
                    'User-Agent': (
                        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                        'AppleWebKit/537.36'
                    )
                })
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=10,
                    pool_maxsize=10,
                    max_retries=0
                )
                self.http_session.mount('http://', adapter)
                self.http_session.mount('https://', adapter)
                self.ok = True
        except:
            pass
        return self

    def get(self, url: str, timeout: int = 10,
            allow_redirects: bool = True
            ) -> Optional[requests.Response]:
        if not self.ok or not self.http_session:
            return None
        try:
            return self.http_session.get(
                url, timeout=timeout,
                allow_redirects=allow_redirects
            )
        except:
            return None

    def __exit__(self, *args):
        if self.http_session:
            try:
                self.http_session.close()
            except:
                pass
        if self.process:
            unregister_process(self.process)
            try:
                self.process.terminate()
                self.process.wait(timeout=2)
            except:
                try:
                    self.process.kill()
                    self.process.wait(timeout=1)
                except:
                    pass
        try:
            self.config_file.unlink()
        except:
            pass


# ==================== PARSERS ====================
def extract_host_port(
    key: str
) -> Tuple[Optional[str], Optional[int]]:
    try:
        key = key.strip()
        if key.lower().startswith("vmess://"):
            encoded = key[8:]
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            data = json.loads(
                base64.b64decode(encoded).decode('utf-8')
            )
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


def parse_key_to_config(
    key: str
) -> Tuple[Optional[Dict], str, str]:
    key_lower = key.lower()
    security = "none"
    if "security=reality" in key_lower:
        security = "reality"
    elif "security=tls" in key_lower:
        security = "tls"

    try:
        if key_lower.startswith("vless://"):
            return parse_vless(key), "VLESS", security
        elif key_lower.startswith("vmess://"):
            return parse_vmess(key), "VMess", security
        elif key_lower.startswith("trojan://"):
            return parse_trojan(key), "Trojan", security
        elif key_lower.startswith("ss://"):
            return parse_shadowsocks(key), "SS", security
    except:
        pass
    return None, "", security


def parse_vless(key: str) -> Optional[Dict]:
    try:
        key = key[8:]
        if "@" not in key:
            return None
        uuid_part, rest = key.split("@", 1)
        server_part = rest.split("?")[0].split("#")[0]
        if ":" not in server_part:
            return None
        host, port = server_part.rsplit(":", 1)
        host = host.strip("[]")

        params = {}
        if "?" in rest:
            for param in (
                rest.split("?")[1].split("#")[0].split("&")
            ):
                if "=" in param:
                    k, v = param.split("=", 1)
                    params[k] = unquote(v)

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

        if params.get("security") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": params.get("sni", host),
                "allowInsecure": True,
                "fingerprint": params.get("fp", "chrome")
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
                "serviceName": params.get("serviceName", "")
            }
        elif (params.get("type") == "tcp"
              and params.get("headerType") == "http"):
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
        elif params.get("type") == "kcp":
            config["streamSettings"]["kcpSettings"] = {
                "header": {
                    "type": params.get("headerType", "none")
                },
                "seed": params.get("seed")
            }
        elif params.get("type") == "h2":
            config["streamSettings"]["httpSettings"] = {
                "host": [params.get("host", host)],
                "path": params.get("path", "/")
            }

        return config
    except:
        return None


def parse_vmess(key: str) -> Optional[Dict]:
    try:
        encoded = key[8:]
        padding = len(encoded) % 4
        if padding:
            encoded += '=' * (4 - padding)
        data = json.loads(
            base64.b64decode(encoded).decode('utf-8')
        )
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
                        "security": "auto"
                    }]
                }]
            },
            "streamSettings": {
                "network": data.get("net", "tcp"),
                "security": (
                    data.get("tls", "none")
                    if data.get("tls") else "none"
                )
            }
        }

        if data.get("tls") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": data.get("sni", host),
                "allowInsecure": True
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
        elif (
            data.get("net") == "tcp"
            and data.get("type") == "http"
        ):
            config["streamSettings"]["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "path": [data.get("path", "/")],
                        "headers": {
                            "Host": [data.get("host", host)]
                        }
                    }
                }
            }
        elif data.get("net") == "h2":
            config["streamSettings"]["httpSettings"] = {
                "host": [data.get("host", host)],
                "path": data.get("path", "/")
            }

        return config
    except:
        return None


def parse_trojan(key: str) -> Optional[Dict]:
    try:
        key = key[9:]
        if "@" not in key:
            return None
        password, rest = key.split("@", 1)
        password = unquote(password)
        server_part = rest.split("?")[0].split("#")[0]
        if ":" not in server_part:
            return None
        host, port = server_part.rsplit(":", 1)
        host = host.strip("[]")

        params = {}
        if "?" in rest:
            for param in (
                rest.split("?")[1].split("#")[0].split("&")
            ):
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
                "security": "tls"
            }
        }
        config["streamSettings"]["tlsSettings"] = {
            "serverName": params.get("sni", host),
            "allowInsecure": True,
            "fingerprint": params.get("fp", "chrome")
        }
        if params.get("type") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {
                    "Host": params.get("host", host)
                }
            }
        return config
    except:
        return None


def parse_shadowsocks(key: str) -> Optional[Dict]:
    try:
        key = key[5:].split("#")[0]
        if "@" in key:
            encoded, server = key.split("@", 1)
            host, port = server.rsplit(":", 1)
            host = host.strip("[]")
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            try:
                decoded = base64.b64decode(
                    encoded
                ).decode('utf-8')
                method, password = decoded.split(":", 1)
            except:
                method, password = encoded.split(":", 1)
        else:
            padding = len(key) % 4
            if padding:
                key += '=' * (4 - padding)
            decoded = base64.b64decode(key).decode('utf-8')
            creds, server = decoded.rsplit("@", 1)
            method, password = creds.split(":", 1)
            host, port = server.rsplit(":", 1)
            host = host.strip("[]")
        return {
            "protocol": "shadowsocks",
            "settings": {
                "servers": [{
                    "address": host,
                    "port": int(port),
                    "method": method,
                    "password": password
                }]
            },
            "streamSettings": {"network": "tcp"}
        }
    except:
        return None


# ==================== DOWNLOAD ====================
def download_and_deduplicate(
    sources: Dict[str, List[str]] = None
) -> List[str]:
    if sources is None:
        sources = KEY_SOURCES

    all_keys = []
    seen = set()
    duplicates = 0

    log("[DL] Downloading keys...")

    for region, urls in sources.items():
        log(f"  Region: {region}")
        for url in urls:
            try:
                for attempt in range(3):
                    try:
                        r = requests.get(url, timeout=30)
                        r.raise_for_status()
                        break
                    except:
                        if attempt == 2:
                            raise
                        time.sleep(2)

                content = r.text.strip()
                if 'base64' in url:
                    try:
                        content = base64.b64decode(
                            content
                        ).decode('utf-8')
                    except:
                        pass

                count = 0
                for line in content.split('\n'):
                    line = html.unescape(line.strip())
                    if not line or not line.lower().startswith(
                        (
                            "vless://", "vmess://",
                            "trojan://", "ss://"
                        )
                    ):
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
            except Exception as e:
                log(f"    FAIL {url.split('/')[-1]}: {e}")

    stats.duplicates = duplicates
    stats.unique = len(all_keys)
    log(
        f"  Total: {stats.total_downloaded + duplicates} | "
        f"Dupes: {duplicates} | Unique: {len(all_keys)}"
    )
    return all_keys


# ==================== TCP CHECK ====================
def tcp_check(key: str) -> Optional[str]:
    host, port = extract_host_port(key)
    if not host or not port:
        record_error("parse_error")
        return None

    for attempt in range(CONFIG.TCP_RETRIES + 1):
        try:
            with socket.create_connection(
                (host, port), timeout=CONFIG.TCP_TIMEOUT
            ):
                return key
        except socket.timeout:
            record_error("tcp_timeout")
        except ConnectionRefusedError:
            record_error("tcp_refused")
            break
        except socket.gaierror:
            record_error("dns_error")
            break
        except:
            record_error("tcp_other")
            break
        if attempt < CONFIG.TCP_RETRIES:
            time.sleep(0.3)
    return None


# ==================== PARALLEL CATEGORY CHECK ====================
def check_single_category(
    session: XraySession, url: str, name: str
) -> Tuple[str, bool, float]:
    """Returns (name, success, response_time_ms)"""
    t1 = time.time()
    resp = session.get(
        url, timeout=CONFIG.CATEGORY_TIMEOUT,
        allow_redirects=True
    )
    elapsed = (time.time() - t1) * 1000
    if resp and resp.status_code < 500:
        return (name, True, elapsed)
    return (name, False, elapsed)


def check_categories_parallel(
    session: XraySession
) -> Tuple[int, bool, Dict[str, bool]]:
    """
    Check categories in parallel, using adaptive ordering.
    Returns (count, telegram, details_dict)
    """
    categories_passed = 0
    telegram_works = False
    details = {}

    # Get adaptively ordered categories
    adaptive_cats = ai_engine.get_adaptive_categories()

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=CONFIG.CATEGORY_PARALLEL
    ) as cat_executor:
        futures = {
            cat_executor.submit(
                check_single_category, session, url, name
            ): name
            for url, name, weight in adaptive_cats
        }

        for future in concurrent.futures.as_completed(
            futures, timeout=CONFIG.CATEGORY_TIMEOUT + 5
        ):
            try:
                name, success, elapsed = future.result(
                    timeout=1
                )
                details[name] = success
                if success:
                    categories_passed += 1
                    if name == "telegram":
                        telegram_works = True

                # Update category stats for AI learning
                cw = ai_engine.category_weights[name]
                cw['total'] += 1
                if success:
                    cw['success'] += 1
                # Rolling average response time
                cw['avg_time'] = (
                    cw['avg_time'] * 0.8 + elapsed * 0.2
                )
            except:
                pass

    return categories_passed, telegram_works, details


# ==================== TWO-PHASE XRAY CHECK ====================
def xray_full_check(
    key: str, xray_exe: Path
) -> CheckResult:
    proxy_config, protocol, security = parse_key_to_config(key)
    if not proxy_config:
        return CheckResult(
            key=key, alive=False, error="parse_error"
        )

    host, port = extract_host_port(key)

    result = _two_phase_test(
        key, proxy_config, protocol, security,
        xray_exe, host, port
    )

    if result.alive:
        return result

    if (CONFIG.MAX_SAFE_MUTATIONS >= 1
            and result.error != "quick_fail"):
        mutated_config, mutation_name = ai_engine.safe_mutate(
            proxy_config, 1
        )
        if mutation_name:
            with stats_lock:
                stats.mutations_tried += 1
            mut_result = _two_phase_test(
                key, mutated_config, protocol, security,
                xray_exe, host, port
            )
            if mut_result.alive:
                mut_result.mutation_used = mutation_name
                with stats_lock:
                    stats.mutations_success += 1
                return mut_result

    return result


def _two_phase_test(
    key: str,
    proxy_config: Dict,
    protocol: str,
    security: str,
    xray_exe: Path,
    host: str,
    port: int
) -> CheckResult:
    latencies = []
    categories_passed = 0
    telegram_works = False
    category_details = {}

    with XraySession(
        xray_exe, proxy_config, CONFIG.XRAY_STARTUP
    ) as session:
        if not session.ok:
            return CheckResult(
                key=key, alive=False, error="xray_startup",
                protocol=protocol, host=host, port=port,
                security=security
            )

        # --- PHASE A: Quick check ---
        quick_ok = False
        try:
            t1 = time.time()
            resp = session.get(
                CONFIG.CHECK_URLS[0],
                timeout=CONFIG.QUICK_CHECK_TIMEOUT,
                allow_redirects=False
            )
            if resp and resp.status_code in [200, 204]:
                latencies.append((time.time() - t1) * 1000)
                quick_ok = True
                with stats_lock:
                    stats.quick_passed += 1
        except:
            pass

        if not quick_ok:
            with stats_lock:
                stats.quick_failed += 1
            return CheckResult(
                key=key, alive=False, error="quick_fail",
                protocol=protocol, host=host, port=port,
                security=security
            )

        # --- PHASE B: Full test ---
        for i in range(CONFIG.LATENCY_SAMPLES - 1):
            url = CONFIG.CHECK_URLS[
                (i + 1) % len(CONFIG.CHECK_URLS)
            ]
            try:
                t1 = time.time()
                resp = session.get(
                    url, timeout=CONFIG.XRAY_TIMEOUT,
                    allow_redirects=False
                )
                if resp and resp.status_code in [200, 204]:
                    latencies.append(
                        (time.time() - t1) * 1000
                    )
            except:
                pass
            time.sleep(0.1)

        if len(latencies) < CONFIG.MIN_LATENCY_SUCCESS:
            return CheckResult(
                key=key, alive=False, error="latency_fail",
                protocol=protocol, host=host, port=port,
                security=security
            )

        # Parallel categories with adaptive ordering
        (
            categories_passed,
            telegram_works,
            category_details
        ) = check_categories_parallel(session)

    avg_latency = mean(latencies)
    jitter = stdev(latencies) if len(latencies) > 1 else 0

    # === RECONNECT ===
    reconnect_success = 0
    for _ in range(CONFIG.RECONNECT_TESTS):
        time.sleep(0.3)
        with XraySession(
            xray_exe, proxy_config, CONFIG.XRAY_STARTUP_QUICK
        ) as session:
            if not session.ok:
                continue
            resp = session.get(
                random.choice(CONFIG.CHECK_URLS),
                timeout=8, allow_redirects=False
            )
            if resp and resp.status_code in [200, 204]:
                reconnect_success += 1

    if reconnect_success < CONFIG.MIN_RECONNECT_SUCCESS:
        return CheckResult(
            key=key, alive=False, error="reconnect_fail",
            protocol=protocol, host=host, port=port,
            security=security,
            latency=round(avg_latency, 1),
            jitter=round(jitter, 1),
            reconnect_success=reconnect_success,
            categories=categories_passed,
            category_details=category_details
        )

    # === QUALITY ===
    quality = None

    # Use weighted category score for smarter evaluation
    weighted_score = ai_engine.weighted_category_score(
        category_details
    )

    for q in [Quality.ELITE, Quality.PREMIUM, Quality.GOOD]:
        thresh = QUALITY_THRESHOLDS[q]
        if (avg_latency <= thresh.latency_max
                and jitter <= thresh.jitter_max
                and categories_passed >= thresh.categories_min):
            quality = q
            break

    # Weighted bonus: if weighted score is high, upgrade quality
    if quality == Quality.GOOD and weighted_score > 0.7:
        quality = Quality.PREMIUM
    elif quality == Quality.PREMIUM and weighted_score > 0.85:
        quality = Quality.ELITE

    # Fallback
    if (quality is None
            and reconnect_success >= CONFIG.MIN_RECONNECT_SUCCESS):
        quality = Quality.GOOD

    if quality is None:
        return CheckResult(
            key=key, alive=False, error="below_threshold",
            protocol=protocol, host=host, port=port,
            security=security,
            latency=round(avg_latency, 1),
            jitter=round(jitter, 1),
            reconnect_success=reconnect_success,
            categories=categories_passed,
            category_details=category_details
        )

    with stats_lock:
        stats.xray_passed += 1
        stats.by_quality[quality] += 1
        stats.by_protocol[protocol] += 1

    return CheckResult(
        key=key, alive=True,
        latency=round(avg_latency, 1),
        jitter=round(jitter, 1),
        reconnect_success=reconnect_success,
        categories=categories_passed,
        category_details=category_details,
        telegram=telegram_works,
        quality=quality,
        protocol=protocol, host=host, port=port,
        security=security
    )


# ==================== SAVE ====================
def save_results(
    results: List[CheckResult], region: str = "ALL"
):
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
            f.write(
                f"# {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
            )
            f.write(f"# Keys: {len(items)}\n\n")

            for r in items:
                tg = "TG+" if r.telegram else ""
                mut = (
                    f"|{r.mutation_used}"
                    if r.mutation_used else ""
                )
                ai = (
                    f"|{r.ai_verdict}"
                    if r.ai_verdict else ""
                )
                score_tag = (
                    f"|s{r.ai_score:.1f}"
                    if r.ai_score > 0 else ""
                )
                comment = (
                    f"[{r.latency:.0f}ms|j{r.jitter:.0f}|"
                    f"rc{r.reconnect_success}/"
                    f"{CONFIG.RECONNECT_TESTS}|"
                    f"{r.categories}cat|{tg}{r.protocol}"
                    f"{mut}{ai}{score_tag}|{MY_CHANNEL}]"
                )
                base_key = r.key.split('#')[0]
                f.write(f"{base_key}#{quote(comment)}\n")

        log(
            f"[SAVE] {quality.value.upper()}: "
            f"{len(items)} -> {filename.name}"
        )

    all_results = [r for r in results if r.alive]
    all_results.sort(key=lambda x: x.latency)

    verified_file = RESULTS_FOLDER / f"verified_{timestamp}.txt"
    with open(verified_file, 'w', encoding='utf-8') as f:
        f.write(f"# {MY_CHANNEL}\n")
        f.write(
            f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        )
        f.write(f"# Working: {len(all_results)}\n\n")
        for r in all_results:
            comment = (
                f"{r.quality.value.upper()} {r.latency:.0f}ms "
                f"{r.protocol} {MY_CHANNEL}"
            )
            f.write(
                f"{r.key.split('#')[0]}#{quote(comment)}\n"
            )

    log(f"[SAVE] All: {len(all_results)} -> {verified_file.name}")

    # Stats JSON
    # Compute trend summary
    trend_summary = {}
    for proto, ps in ai_engine.protocol_stats.items():
        if ps['total'] > 0:
            trend_summary[proto] = {
                'success_rate': round(
                    ps['success'] / ps['total'], 3
                ),
                'trend': round(ps.get('trend', 0), 3),
                'total': ps['total']
            }

    # Category effectiveness
    cat_summary = {}
    for name, cw in ai_engine.category_weights.items():
        if cw['total'] > 0:
            cat_summary[name] = {
                'success_rate': round(
                    cw['success'] / cw['total'], 3
                ),
                'weight': round(cw['weight'], 2),
                'avg_time_ms': round(cw['avg_time'], 1)
            }

    stats_data = {
        "timestamp": datetime.now().isoformat(),
        "region": region,
        "total_checked": stats.tcp_passed,
        "total_working": len(all_results),
        "quick_check": {
            "passed": stats.quick_passed,
            "failed": stats.quick_failed,
        },
        "by_quality": {
            q.value: len(by_quality.get(q, []))
            for q in Quality
        },
        "by_protocol": dict(stats.by_protocol),
        "mutations": {
            "tried": stats.mutations_tried,
            "successful": stats.mutations_success
        },
        "ai": {
            "enabled": ai_engine.enabled,
            "anomalies": stats.ai_anomalies,
            "retrains": stats.ai_retrains,
            "history_size": len(ai_engine.history),
            "protocol_trends": trend_summary,
            "category_effectiveness": cat_summary,
        },
        "processing_time": time.time() - stats.start_time
    }
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats_data, f, indent=2)

    log(f"[SAVE] Stats -> {STATS_FILE.name}")
    return stats_data


# ==================== MAIN ====================
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="AI Proxy Checker v4.2 Smart+"
    )
    parser.add_argument(
        '--region', choices=['ALL', 'RU', 'EU'], default='ALL'
    )
    parser.add_argument(
        '--workers', type=int, default=CONFIG.XRAY_WORKERS
    )
    parser.add_argument(
        '--tcp-workers', type=int, default=CONFIG.TCP_WORKERS
    )
    parser.add_argument('--no-ai', action='store_true')
    parser.add_argument('--no-mutations', action='store_true')
    return parser.parse_args()


def main():
    args = parse_arguments()
    CONFIG.XRAY_WORKERS = args.workers
    CONFIG.TCP_WORKERS = args.tcp_workers
    if args.no_ai:
        ai_engine.enabled = False
    if args.no_mutations:
        CONFIG.MAX_SAFE_MUTATIONS = 0

    print("\n" + "=" * 60)
    print("  AI Proxy Checker v4.2 SMART+")
    print("  Dynamic AI + adaptive categories + trends")
    print(f"  Channel: {MY_CHANNEL}")
    print("=" * 60)

    print(f"\n  Settings:")
    print(f"    Region: {args.region}")
    print(
        f"    TCP: {CONFIG.TCP_WORKERS} workers, "
        f"{CONFIG.TCP_TIMEOUT}s timeout"
    )
    print(
        f"    XRAY: {CONFIG.XRAY_WORKERS} workers, "
        f"{CONFIG.XRAY_TIMEOUT}s timeout"
    )
    print(
        f"    Quick check: {CONFIG.QUICK_CHECK_TIMEOUT}s"
    )
    print(
        f"    Latency: {CONFIG.LATENCY_SAMPLES} samples "
        f"(min {CONFIG.MIN_LATENCY_SUCCESS})"
    )
    print(
        f"    Categories: {len(CONFIG.CATEGORY_URLS)} sites "
        f"(parallel x{CONFIG.CATEGORY_PARALLEL})"
    )
    print(
        f"    Reconnect: {CONFIG.RECONNECT_TESTS} test(s)"
    )
    print(
        f"    AI: {'ON' if ai_engine.enabled else 'OFF'} "
        f"(history: {len(ai_engine.history)}, "
        f"retrain every {CONFIG.AI_RETRAIN_EVERY})"
    )
    print()

    # Show protocol trends if available
    if ai_engine.enabled:
        for proto, ps in ai_engine.protocol_stats.items():
            if ps['total'] > 10:
                rate = ps['success'] / ps['total']
                trend = ps.get('trend', 0)
                arrow = (
                    "^" if trend > 0.05
                    else "v" if trend < -0.05
                    else "="
                )
                print(
                    f"    {proto}: {rate:.0%} success "
                    f"{arrow} (trend: {trend:+.2f})"
                )
        print()

    # Show category weights
    if ai_engine.category_weights:
        high_value = [
            n for n, cw
            in ai_engine.category_weights.items()
            if cw.get('weight', 1) > 1.0
        ]
        if high_value:
            print(
                f"    Best discriminators: "
                f"{', '.join(high_value)}"
            )
            print()

    for q in Quality:
        t = QUALITY_THRESHOLDS[q]
        print(
            f"    {q.value.upper():>7}: "
            f"lat<={t.latency_max}ms  "
            f"jit<={t.jitter_max}ms  "
            f"cat>={t.categories_min}"
        )
    print()

    xray_exe = setup_xray()
    if not xray_exe:
        return 1

    if args.region != 'ALL':
        sources = {args.region: KEY_SOURCES.get(args.region, [])}
    else:
        sources = KEY_SOURCES

    all_keys = download_and_deduplicate(sources)
    if not all_keys:
        log("[ERR] No keys found")
        return 1

    if ai_engine.enabled:
        log("[AI] Prioritizing keys (dynamic scoring)...")
        all_keys = ai_engine.prioritize_keys(all_keys)

    # === TCP ===
    print("\n" + "=" * 60)
    log(f"[TCP] Phase 1: {CONFIG.TCP_WORKERS} workers")
    print("=" * 60 + "\n")

    tcp_start = time.time()
    tcp_passed = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=CONFIG.TCP_WORKERS
    ) as executor:
        futures = {
            executor.submit(tcp_check, key): key
            for key in all_keys
        }
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            if done % CONFIG.GC_EVERY == 0:
                cleanup_memory()
                log(
                    f"  [{done}/{len(all_keys)}] "
                    f"TCP alive: {len(tcp_passed)}"
                )
            try:
                result = future.result(timeout=30)
                if result:
                    tcp_passed.append(result)
                    stats.tcp_passed += 1
                else:
                    stats.tcp_failed += 1
            except:
                stats.tcp_failed += 1

    tcp_time = time.time() - tcp_start
    log(
        f"\n  TCP: {len(tcp_passed)}/{len(all_keys)} "
        f"in {tcp_time:.1f}s"
    )

    if not tcp_passed:
        log("[ERR] No TCP connections")
        return 1

    # === XRAY ===
    print("\n" + "=" * 60)
    log(f"[XRAY] Phase 2: {CONFIG.XRAY_WORKERS} workers")
    log(
        f"  Quick -> Latency({CONFIG.LATENCY_SAMPLES}) "
        f"+ Categories(parallel) -> Reconnect"
    )
    print("=" * 60 + "\n")

    xray_start = time.time()
    results = []

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=CONFIG.XRAY_WORKERS
    ) as executor:
        futures = {
            executor.submit(xray_full_check, key, xray_exe): key
            for key in tcp_passed
        }
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            if done % 10 == 0:
                cleanup_memory()
            try:
                result = future.result(timeout=120)

                if ai_engine.enabled:
                    ai_engine.analyze_result(result)
                ai_engine.save_result(result)

                if result.alive:
                    results.append(result)
                    tg = " TG" if result.telegram else ""
                    mut = (
                        f" [{result.mutation_used}]"
                        if result.mutation_used else ""
                    )
                    ai = (
                        f" {result.ai_verdict}"
                        if result.ai_verdict else ""
                    )
                    sc = (
                        f" s{result.ai_score:.1f}"
                        if result.ai_score > 0 else ""
                    )
                    log(
                        f"  [{done}/{len(tcp_passed)}] OK "
                        f"{result.quality.value.upper():>7} | "
                        f"{result.latency:>6.0f}ms "
                        f"j{result.jitter:>4.0f} | "
                        f"rc:{result.reconnect_success}/"
                        f"{CONFIG.RECONNECT_TESTS} | "
                        f"{result.categories}cat{tg} | "
                        f"{result.protocol}{mut}{ai}{sc}"
                    )
                else:
                    stats.xray_failed += 1
                    if result.error:
                        record_error(result.error)
            except:
                stats.xray_failed += 1
                record_error("future_exception")

    xray_time = time.time() - xray_start
    total_time = time.time() - stats.start_time

    # Finalize AI (save learned data)
    ai_engine.finalize()

    if results:
        save_results(results, args.region)

    # === SUMMARY ===
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(
        f"  Unique: {stats.unique} "
        f"(dupes: {stats.duplicates})"
    )
    print(
        f"  TCP: {stats.tcp_passed} "
        f"({stats.tcp_passed * 100 // max(stats.unique, 1)}%)"
    )
    print(
        f"  Quick: {stats.quick_passed} passed, "
        f"{stats.quick_failed} killed early"
    )
    print(
        f"  XRAY: {stats.xray_passed} "
        f"({stats.xray_passed * 100 // max(stats.tcp_passed, 1)}%)"
    )
    print()

    for q in Quality:
        count = stats.by_quality.get(q, 0)
        if count > 0:
            print(f"    {q.value.upper()}: {count}")
    print()

    if stats.mutations_tried > 0:
        print(
            f"  Mutations: {stats.mutations_success}/"
            f"{stats.mutations_tried}"
        )
    if stats.ai_anomalies > 0:
        print(f"  AI anomalies: {stats.ai_anomalies}")
    if stats.ai_retrains > 0:
        print(f"  AI retrains: {stats.ai_retrains}")
    print()

    for proto, count in sorted(
        stats.by_protocol.items(), key=lambda x: -x[1]
    ):
        ps = ai_engine.protocol_stats.get(proto, {})
        trend = ps.get('trend', 0)
        arrow = (
            "^" if trend > 0.05
            else "v" if trend < -0.05
            else "="
        )
        print(f"    {proto}: {count} {arrow}")
    print()

    # Category effectiveness report
    if ai_engine.category_weights:
        print("  Category effectiveness:")
        for name, cw in sorted(
            ai_engine.category_weights.items(),
            key=lambda x: x[1].get('weight', 0),
            reverse=True
        ):
            if cw['total'] > 0:
                rate = cw['success'] / cw['total']
                print(
                    f"    {name:>12}: "
                    f"{rate:.0%} success, "
                    f"weight={cw['weight']:.1f}, "
                    f"avg={cw['avg_time']:.0f}ms"
                )
        print()

    print(
        f"  TCP={tcp_time:.1f}s  XRAY={xray_time:.1f}s  "
        f"TOTAL={total_time / 60:.1f}min"
    )

    if stats.errors:
        print("\n  Error breakdown:")
        for error, count in sorted(
            stats.errors.items(), key=lambda x: -x[1]
        )[:8]:
            print(f"    {error}: {count}")

    print("=" * 60)

    return 0 if stats.xray_passed > 0 else 1


if __name__ == "__main__":
    try:
        exit_code = main()
    except KeyboardInterrupt:
        print("\n[STOP] Interrupted")
        cleanup_all_processes()
        exit_code = 1
    except Exception as e:
        print(f"\n[ERR] {e}")
        import traceback
        traceback.print_exc()
        cleanup_all_processes()
        exit_code = 1

    sys.exit(exit_code)
