#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI Proxy Checker v5.0 RF-READY
Адаптация под российские реалии с DPI-детекцией
- XHTTP транспорт для VLESS
- Разделение нейтральных и категорийных проверок
- DPI-детекция по паттернам
- RF-метка качества
- Гибкая работа с SNI
- Определение региона RU/EU
- Prefiltered keys поддержка
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
from urllib.parse import quote, unquote, urlparse
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
RF_FOLDER = RESULTS_FOLDER / "rf_ready"
HISTORY_FILE = RESULTS_FOLDER / "history.jsonl"
STATS_FILE = RESULTS_FOLDER / "stats_latest.json"
LOG_FILE = RESULTS_FOLDER / "checker.log"
CATEGORY_STATS_FILE = RESULTS_FOLDER / "category_stats.json"
DPI_STATS_FILE = RESULTS_FOLDER / "dpi_stats.json"
PREFILTER_FILE = WORK_DIR / "checked" / "latest" / "verified.txt"

for d in [XRAY_FOLDER, RESULTS_FOLDER, PREMIUM_FOLDER, RF_FOLDER]:
    d.mkdir(parents=True, exist_ok=True)


# ==================== UNIVERSAL SOURCE READER ====================
def read_source_text(url: str) -> str:
    """Universal source reader: http/https/file:// or local path"""
    if url.startswith("file://"):
        p = Path(urlparse(url).path)
        return p.read_text(encoding="utf-8", errors="ignore")
    p = Path(url)
    if p.exists():
        return p.read_text(encoding="utf-8", errors="ignore")
    # Обычный HTTP/HTTPS с retry
    for attempt in range(3):
        try:
            r = requests.get(url, timeout=30)
            r.raise_for_status()
            return r.text
        except Exception:
            if attempt == 2:
                raise
            time.sleep(2)


# ==================== PREFILTERED KEYS LOADER ====================
def load_prefiltered_keys() -> List[str]:
    """Load keys from prefilter file (verified.txt)"""
    if not PREFILTER_FILE.exists():
        return []
    text = PREFILTER_FILE.read_text(encoding="utf-8", errors="ignore")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.startswith("#")
    ]


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
    ],
    "Prefiltered": [
        # Поддерживаются форматы:
        #   "results/verified_2026-02-18_12-00-00.txt"   — относительный путь
        #   "/home/user/vpn/results/verified_latest.txt" — абсолютный путь
        #   "file:///home/user/vpn/results/verified.txt" — file:// URI
        "results/verified_latest.txt"
    ]
}

MY_CHANNEL = "@vlesstrojan"


# ==================== CONFIG ====================
@dataclass
class Config:
    # ==================== WORKERS ====================
    TCP_WORKERS: int = 60
    XRAY_WORKERS: int = 8
    # ==================== TIMEOUTS ====================
    TCP_TIMEOUT: int = 6
    TCP_RETRIES: int = 1
    XRAY_TIMEOUT: int = 12
    XRAY_STARTUP: float = 6.5
    XRAY_STARTUP_QUICK: float = 3.5
    QUICK_CHECK_TIMEOUT: int = 7
    CATEGORY_TIMEOUT: int = 6
    # ==================== SAMPLES & TESTS ====================
    LATENCY_SAMPLES: int = 2
    MIN_LATENCY_SUCCESS: int = 1
    RECONNECT_TESTS: int = 1
    MIN_RECONNECT_SUCCESS: int = 1
    # ==================== CATEGORIES ====================
    CATEGORY_URLS: List[Tuple[str, str, str]] = field(default_factory=lambda: [
        ("https://web.telegram.org", "telegram", "critical"),
        ("https://www.youtube.com", "youtube", "critical"),
        ("https://www.google.com", "google", "important"),
        ("https://www.instagram.com", "instagram", "important"),
        ("https://twitter.com", "twitter", "important"),
    ])
    CATEGORY_PARALLEL: int = 4
    # RF-критерии
    RF_MIN_CRITICAL_CATEGORIES: int = 1
    RF_MIN_TOTAL_CATEGORIES: int = 2
    RF_MAX_LATENCY: float = 1000

    # Нейтральные сайты для базовой проверки alive
    NEUTRAL_URLS: List[str] = field(default_factory=lambda: [
        'https://cp.cloudflare.com/generate_204',
        'http://www.gstatic.com/generate_204',
        'https://captive.apple.com/hotspot-detect.html',
    ])

    # SNI configuration
    SNI_LIST: List[str] = field(default_factory=lambda: [
        "www.google.com",
        "www.microsoft.com",
        "www.cloudflare.com",
        "cdn.jsdelivr.net",
    ])
    DEFAULT_SNI: str = "www.google.com"

    # Transport modes
    TRANSPORT_MODE: str = "tcp"
    XHTTP_PATH: str = "/api/v1/updates"

    # DPI detection
    DPI_THRESHOLD: int = 10
    DPI_WINDOW: int = 50

    MAX_SAFE_MUTATIONS: int = 1
    GC_EVERY: int = 50

    # AI scalability
    AI_MAX_HISTORY: int = 15000
    AI_TRAIN_BATCH: int = 5000
    AI_RETRAIN_EVERY: int = 200
    AI_TREND_WINDOW: int = 50

    # Route tagging
    ROUTE_TAG: str = "default"


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
        latency_max=250, jitter_max=100, categories_min=4
    ),
    Quality.PREMIUM: QualityThreshold(
        latency_max=600, jitter_max=200, categories_min=3
    ),
    Quality.GOOD: QualityThreshold(
        latency_max=2000, jitter_max=600, categories_min=2
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
    critical_categories: int = 0
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
    rf_ready: bool = False
    rf_score: float = 0.0
    sni_used: str = ""
    transport_used: str = ""
    route_tag: str = ""
    dpi_suspect: bool = False


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
    rf_ready: int = 0
    by_quality: Dict[Quality, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    by_protocol: Dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    by_transport: Dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    by_sni: Dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    errors: Dict[str, int] = field(
        default_factory=lambda: defaultdict(int)
    )
    dpi_suspects: int = 0
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


# ==================== DPI DETECTOR ====================
class DPIDetector:
    """
    Улучшенный детектор DPI-блокировок по паттернам ошибок.

    DPI обычно проявляется как:
    - quick_fail (нейтральные сайты не отвечают)
    - xray_startup (xray падает сразу при запуске)
    - reconnect_fail (режется при реконнекте)

    НЕ считаем DPI:
    - latency_fail (просто медленно)
    - below_threshold (частично работает)
    - parse_error (мусорный ключ)
    """

    DPI_ERROR_TYPES = {
        'quick_fail',
        'xray_startup',
        'reconnect_fail',
    }

    NON_DPI_ERROR_TYPES = {
        'latency_fail',
        'below_threshold',
        'parse_error',
        'tcp_timeout',
        'tcp_refused',
        'dns_error',
    }

    def __init__(self):
        self.check_history = defaultdict(list)
        self._lock = threading.Lock()
        self.dpi_suspects = set()
        self.false_positives = set()

    def record_check(self, host: str, port: int, error: Optional[str], success: bool):
        if not host or not port:
            return
        key = f"{host}:{port}"
        with self._lock:
            self.check_history[key].append({
                'error': error,
                'success': success,
                'time': time.time(),
                'is_dpi_error': error in self.DPI_ERROR_TYPES if error else False,
                'is_non_dpi_error': error in self.NON_DPI_ERROR_TYPES if error else False,
            })
            if len(self.check_history[key]) > CONFIG.DPI_WINDOW:
                self.check_history[key] = self.check_history[key][-CONFIG.DPI_WINDOW:]
            self._analyze_pattern(key)

    def _analyze_pattern(self, key: str):
        history = self.check_history[key]
        if len(history) < CONFIG.DPI_THRESHOLD:
            return
        recent = history[-CONFIG.DPI_THRESHOLD:]
        dpi_errors = sum(1 for r in recent if r['is_dpi_error'])
        non_dpi_errors = sum(1 for r in recent if r['is_non_dpi_error'])
        successes = sum(1 for r in recent if r['success'])
        if non_dpi_errors > 0:
            if key in self.dpi_suspects:
                self.dpi_suspects.remove(key)
                self.false_positives.add(key)
            return
        if successes > 0:
            return
        dpi_ratio = dpi_errors / len(recent)
        if dpi_errors >= CONFIG.DPI_THRESHOLD * 0.8 and dpi_ratio >= 0.8:
            if key not in self.dpi_suspects and key not in self.false_positives:
                self.dpi_suspects.add(key)
                with stats_lock:
                    stats.dpi_suspects += 1
                error_types = [r['error'] for r in recent if r['error'] in self.DPI_ERROR_TYPES]
                most_common = max(set(error_types), key=error_types.count) if error_types else 'unknown'
                log(f"[DPI] Suspect detected: {key} (pattern: {most_common}, {dpi_errors}/{len(recent)} DPI errors)")

    def is_dpi_suspect(self, host: str, port: int) -> bool:
        if not host or not port:
            return False
        key = f"{host}:{port}"
        return key in self.dpi_suspects

    def get_confidence(self, host: str, port: int) -> float:
        if not host or not port:
            return 0.0
        key = f"{host}:{port}"
        history = self.check_history.get(key, [])
        if not history:
            return 0.0
        dpi_errors = sum(1 for r in history if r['is_dpi_error'])
        non_dpi_errors = sum(1 for r in history if r['is_non_dpi_error'])
        total = len(history)
        if non_dpi_errors > 0:
            return 0.0
        if total == 0:
            return 0.0
        return dpi_errors / total

    def get_stats(self) -> Dict:
        with self._lock:
            high_confidence = []
            medium_confidence = []
            for suspect in self.dpi_suspects:
                host, port = suspect.rsplit(':', 1)
                confidence = self.get_confidence(host, int(port))
                if confidence >= 0.9:
                    high_confidence.append(suspect)
                elif confidence >= 0.7:
                    medium_confidence.append(suspect)
            return {
                'total_suspects': len(self.dpi_suspects),
                'high_confidence': high_confidence,
                'medium_confidence': medium_confidence,
                'false_positives': list(self.false_positives),
                'monitored_endpoints': len(self.check_history)
            }

    def save_stats(self):
        try:
            stats_data = self.get_stats()
            details = {}
            for suspect in self.dpi_suspects:
                host, port = suspect.rsplit(':', 1)
                confidence = self.get_confidence(host, int(port))
                history = self.check_history.get(suspect, [])
                recent_errors = [r['error'] for r in history[-10:] if r['error']]
                details[suspect] = {
                    'confidence': round(confidence, 2),
                    'total_checks': len(history),
                    'recent_errors': recent_errors
                }
            stats_data['suspect_details'] = details
            with open(DPI_STATS_FILE, 'w') as f:
                json.dump(stats_data, f, indent=2)
        except:
            pass


dpi_detector = DPIDetector()


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


# ==================== AI ENGINE (enhanced) ====================
class AIEngine:
    """Enhanced AI engine с поддержкой RF-метрик"""

    def __init__(self):
        self.enabled = AI_AVAILABLE
        self.history: List[Dict] = []
        self.model_anomaly = None
        self.scaler = StandardScaler() if AI_AVAILABLE else None
        self._lock = threading.Lock()
        self._checks_since_retrain = 0

        self.protocol_stats = defaultdict(lambda: {
            'success': 0, 'total': 0,
            'latencies': [],
            'trend': 0.0,
            'last_success_rate': 0.5,
            'rf_ready_count': 0
        })

        self.host_stats = defaultdict(lambda: {
            'success': 0, 'total': 0,
            'avg_latency': 0.0,
            'last_seen': 0,
            'quality_history': [],
            'rf_ready': False
        })

        self.category_weights = defaultdict(lambda: {
            'success': 0, 'total': 0, 'avg_time': 0.0,
            'weight': 1.0,
            'priority': 'optional'
        })

        self.sni_stats = defaultdict(lambda: {
            'success': 0, 'total': 0, 'avg_latency': 0.0
        })

        self.transport_stats = defaultdict(lambda: {
            'success': 0, 'total': 0, 'avg_latency': 0.0
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
        try:
            data = {}
            for name, w in self.category_weights.items():
                data[name] = {
                    'success': w['success'],
                    'total': w['total'],
                    'avg_time': w['avg_time'],
                    'weight': w['weight'],
                    'priority': w['priority']
                }
            with open(CATEGORY_STATS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except:
            pass

    def _update_stats_from_record(self, rec: Dict):
        proto = rec.get('protocol', '')
        ps = self.protocol_stats[proto]
        ps['total'] += 1
        if rec.get('alive'):
            ps['success'] += 1
            if rec.get('rf_ready'):
                ps['rf_ready_count'] += 1
            lat = rec.get('latency', 0)
            if lat > 0:
                ps['latencies'].append(lat)
                if len(ps['latencies']) > CONFIG.AI_TREND_WINDOW * 2:
                    ps['latencies'] = ps['latencies'][-CONFIG.AI_TREND_WINDOW * 2:]

        host_key = rec.get('host_key', '')
        if host_key:
            hs = self.host_stats[host_key]
            hs['total'] += 1
            hs['last_seen'] = rec.get('timestamp', 0)
            if rec.get('alive'):
                hs['success'] += 1
                hs['avg_latency'] = hs['avg_latency'] * 0.8 + rec.get('latency', 0) * 0.2
                hs['rf_ready'] = rec.get('rf_ready', False)
                q = rec.get('quality')
                if q:
                    hs['quality_history'].append(q)
                    if len(hs['quality_history']) > 20:
                        hs['quality_history'] = hs['quality_history'][-20:]

        cat_details = rec.get('category_details', {})
        for cat_name, success in cat_details.items():
            cw = self.category_weights[cat_name]
            cw['total'] += 1
            if success:
                cw['success'] += 1

        sni = rec.get('sni_used', '')
        if sni:
            ss = self.sni_stats[sni]
            ss['total'] += 1
            if rec.get('alive'):
                ss['success'] += 1
                ss['avg_latency'] = ss['avg_latency'] * 0.8 + rec.get('latency', 0) * 0.2

        transport = rec.get('transport_used', '')
        if transport:
            ts = self.transport_stats[transport]
            ts['total'] += 1
            if rec.get('alive'):
                ts['success'] += 1
                ts['avg_latency'] = ts['avg_latency'] * 0.8 + rec.get('latency', 0) * 0.2

    def _compute_trends(self):
        for proto, ps in self.protocol_stats.items():
            lats = ps['latencies']
            if len(lats) < CONFIG.AI_TREND_WINDOW:
                ps['trend'] = 0.0
                continue
            window = CONFIG.AI_TREND_WINDOW
            old_window = lats[-window * 2:-window]
            new_window = lats[-window:]
            if old_window and new_window:
                old_avg = mean(old_window)
                new_avg = mean(new_window)
                if old_avg > 0:
                    ps['trend'] = (old_avg - new_avg) / old_avg
                else:
                    ps['trend'] = 0.0
            if ps['total'] > 0:
                ps['last_success_rate'] = ps['success'] / ps['total']

    def _update_category_weights(self):
        for name, cw in self.category_weights.items():
            for url, cat_name, priority in CONFIG.CATEGORY_URLS:
                if cat_name == name:
                    cw['priority'] = priority
                    break
            if cw['total'] > 10:
                rate = cw['success'] / cw['total']
                if rate > 0.9:
                    base_weight = 0.5
                elif rate > 0.6:
                    base_weight = 1.5
                elif rate > 0.3:
                    base_weight = 1.0
                else:
                    base_weight = 0.3
                priority_bonus = {
                    'critical': 2.0,
                    'important': 1.5,
                    'optional': 1.0
                }.get(cw['priority'], 1.0)
                cw['weight'] = base_weight * priority_bonus

    def _train(self):
        if len(self.history) < 50:
            return
        self._compute_trends()
        self._update_category_weights()
        try:
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
            log(f"[AI] Trained on {len(X)} records (total history: {len(self.history)})")
        except Exception as e:
            log(f"[AI] Training failed: {e}")

    def _extract_features(self, rec: Dict) -> List[float]:
        proto = rec.get('protocol', '')
        ps = self.protocol_stats.get(proto, {})
        return [
            rec.get('latency', 999),
            rec.get('jitter', 100),
            rec.get('reconnect', 0),
            rec.get('categories', 0),
            rec.get('critical_categories', 0),
            1 if proto == 'VLESS' else 0,
            1 if proto == 'VMess' else 0,
            1 if proto == 'Trojan' else 0,
            1 if rec.get('security') == 'reality' else 0,
            1 if rec.get('security') == 'tls' else 0,
            1 if rec.get('transport_used') == 'xhttp' else 0,
            ps.get('last_success_rate', 0.5),
            ps.get('trend', 0.0),
            1 if rec.get('rf_ready') else 0,
        ]

    def _maybe_retrain(self):
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
        if len(self.history) > CONFIG.AI_MAX_HISTORY:
            self.history = self.history[-CONFIG.AI_MAX_HISTORY:]
            try:
                with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
                    for rec in self.history:
                        f.write(json.dumps(rec) + '\n')
                log(f"[AI] Pruned history to {len(self.history)} records")
            except:
                pass

    def prioritize_keys(self, keys: List[str]) -> List[str]:
        if not self.enabled:
            return keys
        self._compute_trends()

        def score(key):
            kl = key.lower()
            if 'vless://' in kl:
                proto, s = 'VLESS', 0.8
            elif 'trojan://' in kl:
                proto, s = 'Trojan', 0.6
            elif 'vmess://' in kl:
                proto, s = 'VMess', 0.4
            else:
                proto, s = 'SS', 0.2
            ps = self.protocol_stats.get(proto)
            if ps and ps['total'] > 10:
                rate = ps['success'] / ps['total']
                rf_rate = ps['rf_ready_count'] / max(ps['success'], 1)
                s = s * 0.2 + rate * 0.4 + rf_rate * 0.3
                trend = ps.get('trend', 0)
                if trend > 0:
                    s += trend * 0.2
                elif trend < -0.1:
                    s -= 0.1
            host, port = extract_host_port(key)
            if host and port:
                host_key = f"{host}:{port}"
                hs = self.host_stats.get(host_key)
                if hs and hs['total'] > 3:
                    host_rate = hs['success'] / hs['total']
                    s += host_rate * 0.15
                    if hs.get('rf_ready'):
                        s += 0.2
                    age = time.time() - hs.get('last_seen', 0)
                    if age < 86400 and host_rate > 0.7:
                        s += 0.1
            if 'security=reality' in kl:
                s += 0.2
            elif 'security=tls' in kl:
                s += 0.05
            return s

        return sorted(keys, key=score, reverse=True)

    def get_adaptive_categories(self) -> List[Tuple[str, str, str, float]]:
        result = []
        for url, name, priority in CONFIG.CATEGORY_URLS:
            cw = self.category_weights.get(name, {})
            weight = cw.get('weight', 1.0)
            result.append((url, name, priority, weight))
        result.sort(key=lambda x: (
            0 if x[2] == 'critical' else 1 if x[2] == 'important' else 2,
            -x[3]
        ))
        return result

    def weighted_category_score(self, category_details: Dict[str, bool]) -> float:
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
        return score / max_score

    def analyze_result(self, result: CheckResult):
        if not self.enabled or not self.model_anomaly or not result.alive:
            return
        try:
            rec = {
                'latency': result.latency,
                'jitter': result.jitter,
                'reconnect': result.reconnect_success,
                'categories': result.categories,
                'critical_categories': result.critical_categories,
                'protocol': result.protocol,
                'security': result.security,
                'transport_used': result.transport_used,
                'rf_ready': result.rf_ready,
            }
            features = [self._extract_features(rec)]
            fs = self.scaler.transform(features)
            if self.model_anomaly.predict(fs)[0] == -1:
                result.is_anomaly = True
                result.ai_verdict = "[ANOMALY]"
                with stats_lock:
                    stats.ai_anomalies += 1
            proto_ps = self.protocol_stats.get(result.protocol, {})
            avg_lats = proto_ps.get('latencies', [])
            if avg_lats:
                historical_avg = mean(avg_lats[-50:])
                if historical_avg > 0:
                    ratio = result.latency / historical_avg
                    result.ai_score = max(0, min(1, 1.5 - ratio))
                else:
                    result.ai_score = 0.5
            else:
                result.ai_score = 0.5
            if result.rf_ready:
                result.ai_score = min(1.0, result.ai_score * 1.2)
        except:
            pass

    def save_result(self, result: CheckResult):
        host_key = f"{result.host}:{result.port}" if result.host else ""
        record = {
            'timestamp': time.time(),
            'alive': result.alive,
            'protocol': result.protocol,
            'latency': result.latency,
            'jitter': result.jitter,
            'reconnect': result.reconnect_success,
            'categories': result.categories,
            'critical_categories': result.critical_categories,
            'category_details': result.category_details,
            'quality': result.quality.value if result.quality else None,
            'security': result.security,
            'error': result.error,
            'mutation': result.mutation_used,
            'host_key': host_key,
            'ai_score': result.ai_score,
            'rf_ready': result.rf_ready,
            'rf_score': result.rf_score,
            'sni_used': result.sni_used,
            'transport_used': result.transport_used,
            'route_tag': result.route_tag,
            'dpi_suspect': result.dpi_suspect,
        }
        try:
            with open(HISTORY_FILE, 'a', encoding='utf-8') as f:
                f.write(json.dumps(record) + '\n')
            self.history.append(record)
            self._update_stats_from_record(record)
        except:
            pass
        self._maybe_retrain()

    def safe_mutate(self, proxy_config: Dict, attempt: int) -> Tuple[Dict, str]:
        mutated = json.loads(json.dumps(proxy_config))
        stream = mutated.get('streamSettings', {})
        name = ""
        if attempt == 1:
            fps = ['chrome', 'firefox', 'safari', 'edge', 'ios', 'android', 'random']
            if 'tlsSettings' in stream:
                old = stream['tlsSettings'].get('fingerprint', 'chrome')
                new = random.choice([f for f in fps if f != old])
                stream['tlsSettings']['fingerprint'] = new
                name = f"FP_{new}"
            elif 'realitySettings' in stream:
                old = stream['realitySettings'].get('fingerprint', 'chrome')
                new = random.choice([f for f in fps if f != old])
                stream['realitySettings']['fingerprint'] = new
                name = f"FP_{new}"
        return mutated, name

    def get_best_sni(self) -> str:
        if not self.sni_stats:
            return CONFIG.DEFAULT_SNI
        best_sni = CONFIG.DEFAULT_SNI
        best_score = 0
        for sni, s in self.sni_stats.items():
            if s['total'] > 5:
                rate = s['success'] / s['total']
                score = rate * 1000 / max(s['avg_latency'], 1)
                if score > best_score:
                    best_score = score
                    best_sni = sni
        return best_sni

    def finalize(self):
        self._save_category_stats()
        self._compute_trends()
        log("[AI] Saved category weights and computed trends")


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

        url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{filename}"
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
        log(f"[WARN] Xray setup failed: {e}")
        return None


# ==================== XRAY SESSION ====================
def wait_for_port(port: int, timeout: float = 5.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
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
    def __init__(self, xray_exe: Path, proxy_config: Dict, startup: float = 5.0):
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
            config = create_xray_config(self.proxy_config, self.port)
            with open(self.config_file, 'w') as f:
                json.dump(config, f)
            self.process = subprocess.Popen(
                [str(self.xray_exe), "run", "-c", str(self.config_file)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            register_process(self.process)
            if wait_for_port(self.port, timeout=self.startup) and self.process.poll() is None:
                self.proxies = {
                    'http': f'http://127.0.0.1:{self.port}',
                    'https': f'http://127.0.0.1:{self.port}'
                }
                self.http_session = requests.Session()
                self.http_session.proxies = self.proxies
                self.http_session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                })
                adapter = requests.adapters.HTTPAdapter(
                    pool_connections=10, pool_maxsize=10, max_retries=0
                )
                self.http_session.mount('http://', adapter)
                self.http_session.mount('https://', adapter)
                self.ok = True
        except:
            pass
        return self

    def get(self, url: str, timeout: int = 10, allow_redirects: bool = True) -> Optional[requests.Response]:
        if not self.ok or not self.http_session:
            return None
        try:
            return self.http_session.get(url, timeout=timeout, allow_redirects=allow_redirects)
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
def extract_host_port(key: str) -> Tuple[Optional[str], Optional[int]]:
    try:
        key = key.strip()
        if key.lower().startswith("vmess://"):
            encoded = key[8:]
            padding = len(encoded) % 4
            if padding:
                encoded += '=' * (4 - padding)
            data = json.loads(base64.b64decode(encoded).decode('utf-8'))
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


def parse_key_to_config(key: str, sni: str = None, transport: str = None) -> Tuple[Optional[Dict], str, str]:
    if sni is None:
        sni = CONFIG.DEFAULT_SNI
    if transport is None:
        transport = CONFIG.TRANSPORT_MODE
    key_lower = key.lower()
    security = "none"
    if "security=reality" in key_lower:
        security = "reality"
    elif "security=tls" in key_lower:
        security = "tls"
    try:
        if key_lower.startswith("vless://"):
            return parse_vless(key, sni, transport), "VLESS", security
        elif key_lower.startswith("vmess://"):
            return parse_vmess(key, sni), "VMess", security
        elif key_lower.startswith("trojan://"):
            return parse_trojan(key, sni), "Trojan", security
        elif key_lower.startswith("ss://"):
            return parse_shadowsocks(key), "SS", security
    except:
        pass
    return None, "", security


def parse_vless(key: str, sni: str, transport: str) -> Optional[Dict]:
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
            for param in rest.split("?")[1].split("#")[0].split("&"):
                if "=" in param:
                    k, v = param.split("=", 1)
                    params[k] = unquote(v)
        network = transport if transport in ["tcp", "xhttp"] else params.get("type", "tcp")
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
                "network": network,
                "security": params.get("security", "none")
            }
        }
        if params.get("security") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": sni,
                "allowInsecure": True,
                "fingerprint": params.get("fp", "chrome")
            }
        elif params.get("security") == "reality":
            config["streamSettings"]["realitySettings"] = {
                "dest": f"{sni}:{port}",
                "serverName": sni,
                "publicKey": params.get("pbk", ""),
                "shortId": params.get("sid", ""),
                "fingerprint": params.get("fp", "chrome")
            }
        if network == "xhttp":
            config["streamSettings"]["xhttpSettings"] = {
                "path": CONFIG.XHTTP_PATH,
                "host": sni
            }
        elif params.get("type") == "ws" or network == "ws":
            config["streamSettings"]["network"] = "ws"
            config["streamSettings"]["wsSettings"] = {
                "path": params.get("path", "/"),
                "headers": {"Host": params.get("host", host)}
            }
        elif params.get("type") == "grpc":
            config["streamSettings"]["grpcSettings"] = {
                "serviceName": params.get("serviceName", "")
            }
        elif params.get("type") == "tcp" and params.get("headerType") == "http":
            config["streamSettings"]["tcpSettings"] = {
                "header": {
                    "type": "http",
                    "request": {
                        "version": "1.1",
                        "method": "GET",
                        "path": [params.get("path", "/")],
                        "headers": {"Host": [params.get("host", host)]}
                    }
                }
            }
        return config
    except:
        return None


def parse_vmess(key: str, sni: str) -> Optional[Dict]:
    try:
        encoded = key[8:]
        padding = len(encoded) % 4
        if padding:
            encoded += '=' * (4 - padding)
        data = json.loads(base64.b64decode(encoded).decode('utf-8'))
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
                "security": data.get("tls", "none") if data.get("tls") else "none"
            }
        }
        if data.get("tls") == "tls":
            config["streamSettings"]["tlsSettings"] = {
                "serverName": sni,
                "allowInsecure": True
            }
        if data.get("net") == "ws":
            config["streamSettings"]["wsSettings"] = {
                "path": data.get("path", "/"),
                "headers": {"Host": data.get("host", host)}
            }
        return config
    except:
        return None


def parse_trojan(key: str, sni: str) -> Optional[Dict]:
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
            for param in rest.split("?")[1].split("#")[0].split("&"):
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
            "serverName": sni,
            "allowInsecure": True,
            "fingerprint": params.get("fp", "chrome")
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
                decoded = base64.b64decode(encoded).decode('utf-8')
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
def download_and_deduplicate(sources: Dict[str, List[str]] = None) -> List[str]:
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
                content = read_source_text(url).strip()
            except Exception as e:
                log(f"    FAIL {url.split('/')[-1]}: {e}")
                continue
            if 'base64' in url:
                try:
                    content = base64.b64decode(content).decode('utf-8')
                except:
                    pass
            count = 0
            for line in content.split('\n'):
                line = html.unescape(line.strip())
                if not line or not line.lower().startswith(("vless://", "vmess://", "trojan://", "ss://")):
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
    
    # Add prefiltered keys
    prefiltered = load_prefiltered_keys()
    if prefiltered:
        log(f"  Region: Prefiltered (from {PREFILTER_FILE})")
        count = 0
        for line in prefiltered:
            normalized = line.split("#")[0].strip()
            if normalized in seen:
                duplicates += 1
                continue
            seen.add(normalized)
            all_keys.append(line)
            count += 1
        stats.total_downloaded += count
        log(f"    verified.txt: {count}")
    
    stats.duplicates = duplicates
    stats.unique = len(all_keys)
    log(f"  Total: {stats.total_downloaded + duplicates} | Dupes: {duplicates} | Unique: {len(all_keys)}")
    return all_keys


# ==================== TCP CHECK ====================
def tcp_check(key: str) -> Optional[str]:
    host, port = extract_host_port(key)
    if not host or not port:
        record_error("parse_error")
        return None
    for attempt in range(CONFIG.TCP_RETRIES + 1):
        try:
            with socket.create_connection((host, port), timeout=CONFIG.TCP_TIMEOUT):
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


# ==================== CATEGORY CHECKS ====================
def check_single_category(session: XraySession, url: str, name: str, priority: str) -> Tuple[str, bool, float, str]:
    t1 = time.time()
    resp = session.get(url, timeout=CONFIG.CATEGORY_TIMEOUT, allow_redirects=True)
    elapsed = (time.time() - t1) * 1000
    if resp and resp.status_code < 500:
        return (name, True, elapsed, priority)
    return (name, False, elapsed, priority)


def check_categories_parallel(session: XraySession) -> Tuple[int, int, bool, Dict[str, bool]]:
    categories_passed = 0
    critical_passed = 0
    telegram_works = False
    details = {}
    adaptive_cats = ai_engine.get_adaptive_categories()
    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.CATEGORY_PARALLEL) as cat_executor:
        futures = {
            cat_executor.submit(check_single_category, session, url, name, priority): name
            for url, name, priority, weight in adaptive_cats
        }
        for future in concurrent.futures.as_completed(futures, timeout=CONFIG.CATEGORY_TIMEOUT + 5):
            try:
                name, success, elapsed, priority = future.result(timeout=1)
                details[name] = success
                if success:
                    categories_passed += 1
                    if priority == "critical":
                        critical_passed += 1
                    if name == "telegram":
                        telegram_works = True
                cw = ai_engine.category_weights[name]
                cw['total'] += 1
                cw['priority'] = priority
                if success:
                    cw['success'] += 1
                cw['avg_time'] = cw['avg_time'] * 0.8 + elapsed * 0.2
            except:
                pass
    return categories_passed, critical_passed, telegram_works, details


# ==================== RF-READY LOGIC ====================
def calculate_rf_readiness(
    alive: bool,
    critical_passed: int,
    categories_passed: int,
    category_details: Dict[str, bool],
    latency: float,
    reconnect_success: int
) -> Tuple[bool, float]:
    if not alive:
        return False, 0.0
    meets_critical = critical_passed >= CONFIG.RF_MIN_CRITICAL_CATEGORIES
    meets_total = categories_passed >= CONFIG.RF_MIN_TOTAL_CATEGORIES
    meets_latency = latency <= CONFIG.RF_MAX_LATENCY
    meets_reconnect = reconnect_success >= CONFIG.MIN_RECONNECT_SUCCESS
    rf_ready = meets_critical and meets_total and meets_latency and meets_reconnect
    if not rf_ready:
        partial_score = 0.0
        if meets_critical:
            partial_score += 0.2
        if meets_total:
            partial_score += 0.1
        if meets_latency:
            partial_score += 0.1
        if meets_reconnect:
            partial_score += 0.1
        return False, min(partial_score, 0.49)
    total_critical = len([c for c in CONFIG.CATEGORY_URLS if c[2] == "critical"])
    critical_ratio = critical_passed / max(total_critical, 1)
    critical_score = min(critical_ratio, 1.0)
    important_passed = sum(
        1 for name, passed in category_details.items()
        if passed and any(
            c[1] == name and c[2] == "important"
            for c in CONFIG.CATEGORY_URLS
        )
    )
    total_important = len([c for c in CONFIG.CATEGORY_URLS if c[2] == "important"])
    important_ratio = important_passed / max(total_important, 1)
    important_score = min(important_ratio, 1.0)
    latency_score = max(0, 1.0 - latency / CONFIG.RF_MAX_LATENCY)
    reconnect_ratio = reconnect_success / max(CONFIG.RECONNECT_TESTS, 1)
    reconnect_score = min(reconnect_ratio, 1.0)
    rf_score = (
        critical_score * 0.4 +
        important_score * 0.2 +
        latency_score * 0.3 +
        reconnect_score * 0.1
    )
    if critical_passed == total_critical and categories_passed >= 5:
        rf_score = min(1.0, rf_score * 1.1)
    return True, min(rf_score, 1.0)


# ==================== XRAY CHECK WITH RF LOGIC ====================
def xray_full_check(key: str, xray_exe: Path, sni: str = None, transport: str = None) -> CheckResult:
    if sni is None:
        sni = ai_engine.get_best_sni()
    if transport is None:
        transport = CONFIG.TRANSPORT_MODE
    proxy_config, protocol, security = parse_key_to_config(key, sni, transport)
    if not proxy_config:
        return CheckResult(key=key, alive=False, error="parse_error", route_tag=CONFIG.ROUTE_TAG)
    host, port = extract_host_port(key)
    dpi_suspect = dpi_detector.is_dpi_suspect(host, port) if host and port else False
    result = _two_phase_test(key, proxy_config, protocol, security, xray_exe, host, port, sni, transport)
    if host and port:
        dpi_detector.record_check(host, port, result.error, result.alive)
    result.dpi_suspect = dpi_suspect
    result.route_tag = CONFIG.ROUTE_TAG
    if result.alive:
        return result
    if CONFIG.MAX_SAFE_MUTATIONS >= 1 and result.error != "quick_fail" and not dpi_suspect:
        mutated_config, mutation_name = ai_engine.safe_mutate(proxy_config, 1)
        if mutation_name:
            with stats_lock:
                stats.mutations_tried += 1
            mut_result = _two_phase_test(key, mutated_config, protocol, security, xray_exe, host, port, sni, transport)
            if mut_result.alive:
                mut_result.mutation_used = mutation_name
                mut_result.dpi_suspect = dpi_suspect
                mut_result.route_tag = CONFIG.ROUTE_TAG
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
    port: int,
    sni: str,
    transport: str
) -> CheckResult:
    latencies = []
    categories_passed = 0
    critical_passed = 0
    telegram_works = False
    category_details = {}

    with XraySession(xray_exe, proxy_config, CONFIG.XRAY_STARTUP) as session:
        if not session.ok:
            return CheckResult(
                key=key, alive=False, error="xray_startup",
                protocol=protocol, host=host, port=port,
                security=security, sni_used=sni, transport_used=transport
            )
        quick_ok = False
        for neutral_url in CONFIG.NEUTRAL_URLS:
            try:
                t1 = time.time()
                resp = session.get(neutral_url, timeout=CONFIG.QUICK_CHECK_TIMEOUT, allow_redirects=False)
                if resp and resp.status_code in [200, 204]:
                    latencies.append((time.time() - t1) * 1000)
                    quick_ok = True
                    with stats_lock:
                        stats.quick_passed += 1
                    break
            except:
                pass
        if not quick_ok:
            with stats_lock:
                stats.quick_failed += 1
            return CheckResult(
                key=key, alive=False, error="quick_fail",
                protocol=protocol, host=host, port=port,
                security=security, sni_used=sni, transport_used=transport
            )
        for i in range(CONFIG.LATENCY_SAMPLES - 1):
            url = CONFIG.NEUTRAL_URLS[(i + 1) % len(CONFIG.NEUTRAL_URLS)]
            try:
                t1 = time.time()
                resp = session.get(url, timeout=CONFIG.XRAY_TIMEOUT, allow_redirects=False)
                if resp and resp.status_code in [200, 204]:
                    latencies.append((time.time() - t1) * 1000)
            except:
                pass
            time.sleep(0.1)
        if len(latencies) < CONFIG.MIN_LATENCY_SUCCESS:
            return CheckResult(
                key=key, alive=False, error="latency_fail",
                protocol=protocol, host=host, port=port,
                security=security, sni_used=sni, transport_used=transport
            )
        categories_passed, critical_passed, telegram_works, category_details = check_categories_parallel(session)

    avg_latency = mean(latencies)
    jitter = stdev(latencies) if len(latencies) > 1 else 0

    reconnect_success = 0
    for _ in range(CONFIG.RECONNECT_TESTS):
        time.sleep(0.3)
        with XraySession(xray_exe, proxy_config, CONFIG.XRAY_STARTUP_QUICK) as session:
            if not session.ok:
                continue
            resp = session.get(random.choice(CONFIG.NEUTRAL_URLS), timeout=8, allow_redirects=False)
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
            critical_categories=critical_passed,
            category_details=category_details,
            sni_used=sni,
            transport_used=transport
        )

    rf_ready, rf_score = calculate_rf_readiness(
        alive=True,
        critical_passed=critical_passed,
        categories_passed=categories_passed,
        category_details=category_details,
        latency=avg_latency,
        reconnect_success=reconnect_success
    )

    quality = None
    weighted_score = ai_engine.weighted_category_score(category_details)

    for q in [Quality.ELITE, Quality.PREMIUM, Quality.GOOD]:
        thresh = QUALITY_THRESHOLDS[q]
        if (
            avg_latency <= thresh.latency_max
            and jitter <= thresh.jitter_max
            and categories_passed >= thresh.categories_min
        ):
            quality = q
            break

    if quality == Quality.GOOD and weighted_score > 0.7:
        quality = Quality.PREMIUM
    elif quality == Quality.PREMIUM and weighted_score > 0.85:
        quality = Quality.ELITE

    if rf_ready and quality == Quality.GOOD:
        quality = Quality.PREMIUM

    if quality is None and reconnect_success >= CONFIG.MIN_RECONNECT_SUCCESS:
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
            critical_categories=critical_passed,
            category_details=category_details,
            sni_used=sni,
            transport_used=transport
        )

    with stats_lock:
        stats.xray_passed += 1
        stats.by_quality[quality] += 1
        stats.by_protocol[protocol] += 1
        stats.by_sni[sni] += 1
        stats.by_transport[transport] += 1
        if rf_ready:
            stats.rf_ready += 1

    return CheckResult(
        key=key, alive=True,
        latency=round(avg_latency, 1),
        jitter=round(jitter, 1),
        reconnect_success=reconnect_success,
        categories=categories_passed,
        critical_categories=critical_passed,
        category_details=category_details,
        telegram=telegram_works,
        quality=quality,
        protocol=protocol, host=host, port=port,
        security=security,
        rf_ready=rf_ready,
        rf_score=round(rf_score, 2),
        sni_used=sni,
        transport_used=transport
    )


# ==================== SAVE RESULTS ====================
def save_results(results: List[CheckResult], region: str = "ALL"):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    by_quality = defaultdict(list)
    rf_ready_results = []

    for r in results:
        if r.alive and r.quality:
            by_quality[r.quality].append(r)
            if r.rf_ready:
                rf_ready_results.append(r)

    for quality in Quality:
        items = by_quality.get(quality, [])
        if not items:
            continue
        items.sort(key=lambda x: x.latency)
        filename = PREMIUM_FOLDER / f"{quality.value}.txt"
        with open(filename, 'w', encoding='utf-8') as f:
            f.write(f"# {quality.value.upper()}\n")
            f.write(f"# {MY_CHANNEL}\n")
            f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M')}\n")
            f.write(f"# Route: {CONFIG.ROUTE_TAG}\n")
            f.write(f"# Keys: {len(items)}\n\n")
            for r in items:
                tg = " TG" if r.telegram else ""
                is_ru = any(x in r.host.lower() for x in ['.ru', 'russia', 'moscow', 'm9', 'msk'])
                reg = "RU" if is_ru else "EU"
                mut = f" {r.mutation_used}" if r.mutation_used else ""
                ai = f" {r.ai_verdict}" if r.ai_verdict else ""
                score_tag = f" ai{r.ai_score:.1f}" if r.ai_score > 0 else ""
                rf = f" RF{r.rf_score:.1f}" if r.rf_ready else ""
                dpi = " DPI?" if r.dpi_suspect else ""
                comment = f"[{r.latency:.0f}ms|{reg}|j{r.jitter:.0f}|rc{r.reconnect_success}/{CONFIG.RECONNECT_TESTS}|{r.categories}cat|crit{r.critical_categories}{tg}|{r.protocol}|{r.transport_used}|sni:{r.sni_used}{mut}{ai}{score_tag}{rf}{dpi}{MY_CHANNEL}]"
                base_key = r.key.split('#')[0]
                f.write(f"{base_key}#{quote(comment)}\n")
        log(f"[SAVE] {quality.value.upper()}: {len(items)} -> {filename.name}")

    if rf_ready_results:
        rf_ready_results.sort(key=lambda x: -x.rf_score)
        rf_filename = RF_FOLDER / f"rf_ready_{timestamp}.txt"
        with open(rf_filename, 'w', encoding='utf-8') as f:
            f.write(f"# RF-READY KEYS\n")
            f.write(f"# {MY_CHANNEL}\n")
            f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"# Route: {CONFIG.ROUTE_TAG}\n")
            f.write(f"# Keys: {len(rf_ready_results)}\n\n")
            for r in rf_ready_results:
                tg = "TG+" if r.telegram else ""
                is_ru = any(x in r.host.lower() for x in ['.ru', 'russia', 'moscow', 'm9', 'msk'])
                reg = "RU" if is_ru else "EU"
                comment = (
                    f"RF{r.rf_score:.1f} {reg} {r.quality.value.upper()} "
                    f"{r.latency:.0f}ms {r.protocol} {r.transport_used} "
                    f"crit{r.critical_categories} {tg} {MY_CHANNEL}"
                )
                f.write(f"{r.key.split('#')[0]}#{quote(comment)}\n")
        log(f"[SAVE] RF-READY: {len(rf_ready_results)} -> {rf_filename.name}")

    all_results = [r for r in results if r.alive]
    all_results.sort(key=lambda x: x.latency)
    verified_file = RESULTS_FOLDER / f"verified_{timestamp}.txt"
    with open(verified_file, 'w', encoding='utf-8') as f:
        f.write(f"# {MY_CHANNEL}\n")
        f.write(f"# {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"# Route: {CONFIG.ROUTE_TAG}\n")
        f.write(f"# Working: {len(all_results)}\n")
        f.write(f"# RF-Ready: {len(rf_ready_results)}\n\n")
        for r in all_results:
            rf_tag = " RF" if r.rf_ready else ""
            is_ru = any(x in r.host.lower() for x in ['.ru', 'russia', 'moscow', 'm9', 'msk'])
            reg = "RU" if is_ru else "EU"
            comment = f"{reg} {r.quality.value.upper()}{rf_tag} {r.latency:.0f}ms {r.protocol} {MY_CHANNEL}"
            f.write(f"{r.key.split('#')[0]}#{quote(comment)}\n")
    log(f"[SAVE] All: {len(all_results)} -> {verified_file.name}")

    trend_summary = {}
    for proto, ps in ai_engine.protocol_stats.items():
        if ps['total'] > 0:
            trend_summary[proto] = {
                'success_rate': round(ps['success'] / ps['total'], 3),
                'rf_rate': round(ps['rf_ready_count'] / max(ps['success'], 1), 3),
                'trend': round(ps.get('trend', 0), 3),
                'total': ps['total']
            }

    cat_summary = {}
    for name, cw in ai_engine.category_weights.items():
        if cw['total'] > 0:
            cat_summary[name] = {
                'success_rate': round(cw['success'] / cw['total'], 3),
                'weight': round(cw['weight'], 2),
                'avg_time_ms': round(cw['avg_time'], 1),
                'priority': cw.get('priority', 'optional')
            }

    sni_summary = {}
    for sni, ss in ai_engine.sni_stats.items():
        if ss['total'] > 0:
            sni_summary[sni] = {
                'success_rate': round(ss['success'] / ss['total'], 3),
                'avg_latency': round(ss['avg_latency'], 1),
                'total': ss['total']
            }

    transport_summary = {}
    for transport, ts in ai_engine.transport_stats.items():
        if ts['total'] > 0:
            transport_summary[transport] = {
                'success_rate': round(ts['success'] / ts['total'], 3),
                'avg_latency': round(ts['avg_latency'], 1),
                'total': ts['total']
            }

    stats_data = {
        "timestamp": datetime.now().isoformat(),
        "region": region,
        "route_tag": CONFIG.ROUTE_TAG,
        "total_checked": stats.tcp_passed,
        "total_working": len(all_results),
        "rf_ready": len(rf_ready_results),
        "rf_ready_percent": round(len(rf_ready_results) * 100 / max(len(all_results), 1), 1),
        "quick_check": {
            "passed": stats.quick_passed,
            "failed": stats.quick_failed,
        },
        "by_quality": {q.value: len(by_quality.get(q, [])) for q in Quality},
        "by_protocol": dict(stats.by_protocol),
        "by_transport": dict(stats.by_transport),
        "by_sni": dict(stats.by_sni),
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
            "sni_performance": sni_summary,
            "transport_performance": transport_summary,
        },
        "dpi": dpi_detector.get_stats(),
        "processing_time": time.time() - stats.start_time
    }
    with open(STATS_FILE, 'w', encoding='utf-8') as f:
        json.dump(stats_data, f, indent=2)
    log(f"[SAVE] Stats -> {STATS_FILE.name}")
    dpi_detector.save_stats()
    return stats_data


# ==================== SELFHOST CONFIG GENERATOR ====================
def generate_selfhost_config(sni: str = None, port: int = 443):
    if sni is None:
        sni = CONFIG.DEFAULT_SNI
    import uuid
    user_id = str(uuid.uuid4())
    short_id = os.urandom(8).hex()
    public_key = "PLACEHOLDER_PUBLIC_KEY"
    server_config = {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "port": port,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": user_id, "flow": ""}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "xhttp",
                "security": "reality",
                "realitySettings": {
                    "show": False,
                    "dest": f"{sni}:{port}",
                    "serverNames": [sni],
                    "privateKey": "PLACEHOLDER_PRIVATE_KEY",
                    "shortIds": [short_id]
                },
                "xhttpSettings": {"path": CONFIG.XHTTP_PATH}
            }
        }],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}]
    }
    client_url = (
        f"vless://{user_id}@YOUR_SERVER_IP:{port}"
        f"?type=xhttp&security=reality&pbk={public_key}"
        f"&fp=chrome&sni={sni}&sid={short_id}"
        f"&path={CONFIG.XHTTP_PATH}#RF-Selfhost"
    )
    return server_config, client_url


# ==================== HELPERS ====================
def _flush_history_and_stats(results: List[CheckResult], region: str):
    """Guaranteed flush of history and stats to disk"""
    ai_engine.finalize()
    dpi_detector.save_stats()
    if results:
        save_results(results, region)
    else:
        stats_data = {
            "timestamp": datetime.now().isoformat(),
            "region": region,
            "route_tag": CONFIG.ROUTE_TAG,
            "total_checked": stats.tcp_passed,
            "total_working": 0,
            "rf_ready": 0,
            "rf_ready_percent": 0.0,
            "quick_check": {
                "passed": stats.quick_passed,
                "failed": stats.quick_failed,
            },
            "by_quality": {q.value: 0 for q in Quality},
            "by_protocol": dict(stats.by_protocol),
            "by_transport": dict(stats.by_transport),
            "by_sni": dict(stats.by_sni),
            "mutations": {
                "tried": stats.mutations_tried,
                "successful": stats.mutations_success,
            },
            "ai": {
                "enabled": ai_engine.enabled,
                "anomalies": stats.ai_anomalies,
                "retrains": stats.ai_retrains,
                "history_size": len(ai_engine.history),
            },
            "dpi": dpi_detector.get_stats(),
            "processing_time": time.time() - stats.start_time,
        }
        try:
            with open(STATS_FILE, 'w', encoding='utf-8') as f:
                json.dump(stats_data, f, indent=2)
            log(f"[SAVE] Stats (empty run) -> {STATS_FILE.name}")
        except Exception as e:
            log(f"[WARN] Could not write stats: {e}")


# ==================== MAIN ====================
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="AI Proxy Checker v5.0 RF-READY"
    )
    parser.add_argument('--region', choices=['ALL', 'RU', 'EU', 'Prefiltered'], default='ALL')
    parser.add_argument('--workers', type=int, default=CONFIG.XRAY_WORKERS)
    parser.add_argument('--tcp-workers', type=int, default=CONFIG.TCP_WORKERS)
    parser.add_argument('--no-ai', action='store_true')
    parser.add_argument('--no-mutations', action='store_true')
    parser.add_argument('--transport', choices=['tcp', 'xhttp'], default='tcp')
    parser.add_argument('--sni', type=str, help='Custom SNI to use')
    parser.add_argument('--route-tag', type=str, default='default', help='Route tag (MTS, Tele2, etc)')
    parser.add_argument('--generate-selfhost', action='store_true', help='Generate selfhost config')
    return parser.parse_args()


def main():
    args = parse_arguments()

    # Generate selfhost mode
    if args.generate_selfhost:
        print("\n=== SELFHOST CONFIG GENERATOR ===\n")
        sni = input(f"SNI (default: {CONFIG.DEFAULT_SNI}): ").strip() or CONFIG.DEFAULT_SNI
        port = input("Port (default: 443): ").strip() or "443"
        port = int(port)
        server_config, client_url = generate_selfhost_config(sni, port)
        output_dir = WORK_DIR / "selfhost_configs"
        output_dir.mkdir(exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        server_file = output_dir / f"server_{timestamp}.json"
        client_file = output_dir / f"client_{timestamp}.txt"
        with open(server_file, 'w') as f:
            json.dump(server_config, f, indent=2)
        with open(client_file, 'w') as f:
            f.write(f"# VLESS+Reality+XHTTP Config for RF\n")
            f.write(f"# Generated: {datetime.now()}\n")
            f.write(f"# SNI: {sni}\n")
            f.write(f"# Port: {port}\n\n")
            f.write("SERVER CONFIG:\n")
            f.write(f"File: {server_file}\n\n")
            f.write("CLIENT URL:\n")
            f.write(f"{client_url}\n\n")
            f.write("IMPORTANT: Replace PLACEHOLDER values with real keys!\n")
            f.write("Generate keys with: xray x25519\n")
        print(f"\n[OK] Server config: {server_file}")
        print(f"[OK] Client URL: {client_file}")
        print("\nIMPORTANT: Replace PLACEHOLDER values with real keys!")
        print("Generate keys with: xray x25519\n")
        return 0

    # Normal checker mode
    CONFIG.XRAY_WORKERS = args.workers
    CONFIG.TCP_WORKERS = args.tcp_workers
    CONFIG.TRANSPORT_MODE = args.transport
    CONFIG.ROUTE_TAG = args.route_tag

    if args.sni:
        CONFIG.DEFAULT_SNI = args.sni
    if args.no_ai:
        ai_engine.enabled = False
    if args.no_mutations:
        CONFIG.MAX_SAFE_MUTATIONS = 0

    print("\n" + "=" * 60)
    print("  AI Proxy Checker v5.0 RF-READY")
    print("  Адаптация под российские реалии")
    print(f"  Channel: {MY_CHANNEL}")
    print("=" * 60)
    print(f"\n  Settings:")
    print(f"    Region: {args.region}")
    print(f"    Route tag: {CONFIG.ROUTE_TAG}")
    print(f"    Transport: {CONFIG.TRANSPORT_MODE}")
    print(f"    Default SNI: {CONFIG.DEFAULT_SNI}")
    print(f"    TCP: {CONFIG.TCP_WORKERS} workers, {CONFIG.TCP_TIMEOUT}s timeout")
    print(f"    XRAY: {CONFIG.XRAY_WORKERS} workers, {CONFIG.XRAY_TIMEOUT}s timeout")
    print(f"    XRAY startup: {CONFIG.XRAY_STARTUP}s")
    print(f"    Quick check: {CONFIG.QUICK_CHECK_TIMEOUT}s")
    print(f"    Neutral sites: {len(CONFIG.NEUTRAL_URLS)}")
    print(f"    Categories: {len(CONFIG.CATEGORY_URLS)} (parallel x{CONFIG.CATEGORY_PARALLEL})")
    print(f"    Reconnect: {CONFIG.RECONNECT_TESTS} test(s)")
    print(f"    DPI threshold: {CONFIG.DPI_THRESHOLD} errors")
    print(f"    AI: {'ON' if ai_engine.enabled else 'OFF'} (history: {len(ai_engine.history)})")
    print()
    print(f"  RF-Ready criteria:")
    print(f"    Min critical categories: {CONFIG.RF_MIN_CRITICAL_CATEGORIES}")
    print(f"    Min total categories: {CONFIG.RF_MIN_TOTAL_CATEGORIES}")
    print(f"    Max latency: {CONFIG.RF_MAX_LATENCY}ms")
    print(f"    Min reconnects: {CONFIG.MIN_RECONNECT_SUCCESS}/{CONFIG.RECONNECT_TESTS}")
    print()

    if ai_engine.enabled:
        for proto, ps in ai_engine.protocol_stats.items():
            if ps['total'] > 10:
                rate = ps['success'] / ps['total']
                rf_rate = ps['rf_ready_count'] / max(ps['success'], 1)
                trend = ps.get('trend', 0)
                arrow = "^" if trend > 0.05 else "v" if trend < -0.05 else "="
                print(f"    {proto}: {rate:.0%} success, {rf_rate:.0%} RF {arrow}")
        print()

    for q in Quality:
        t = QUALITY_THRESHOLDS[q]
        print(f"    {q.value.upper():>7}: lat<={t.latency_max}ms  jit<={t.jitter_max}ms  cat>={t.categories_min}")
    print()

    xray_exe = setup_xray()
    if not xray_exe:
        log("[WARN] Xray unavailable — skipping Xray-level checks (exit 0)")
        _flush_history_and_stats([], args.region)
        return 0

    if args.region != 'ALL':
        sources = {args.region: KEY_SOURCES.get(args.region, [])}
    else:
        sources = KEY_SOURCES

    all_keys = download_and_deduplicate(sources)
    if not all_keys:
        log("[ERR] No keys found")
        _flush_history_and_stats([], args.region)
        return 1

    if ai_engine.enabled:
        log("[AI] Prioritizing keys...")
        all_keys = ai_engine.prioritize_keys(all_keys)

    # === TCP ===
    print("\n" + "=" * 60)
    log(f"[TCP] Phase 1: {CONFIG.TCP_WORKERS} workers")
    print("=" * 60 + "\n")

    tcp_start = time.time()
    tcp_passed = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.TCP_WORKERS) as executor:
        futures = {executor.submit(tcp_check, key): key for key in all_keys}
        done = 0
        for future in concurrent.futures.as_completed(futures):
            done += 1
            if done % CONFIG.GC_EVERY == 0:
                cleanup_memory()
                log(f"  [{done}/{len(all_keys)}] TCP alive: {len(tcp_passed)}")
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
    log(f"\n  TCP: {len(tcp_passed)}/{len(all_keys)} in {tcp_time:.1f}s")

    if not tcp_passed:
        log("[ERR] No TCP connections")
        _flush_history_and_stats([], args.region)
        return 1

    # === XRAY ===
    print("\n" + "=" * 60)
    log(f"[XRAY] Phase 2: {CONFIG.XRAY_WORKERS} workers")
    log(f"  Mode: {CONFIG.TRANSPORT_MODE.upper()}")
    log(f"  Neutral -> Categories(parallel) -> Reconnect -> RF check")
    print("=" * 60 + "\n")

    xray_start = time.time()
    results = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=CONFIG.XRAY_WORKERS) as executor:
        futures = {
            executor.submit(xray_full_check, key, xray_exe, args.sni, args.transport): key
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
                    rf = f" RF{result.rf_score:.1f}" if result.rf_ready else ""
                    dpi = " DPI?" if result.dpi_suspect else ""
                    mut = f" [{result.mutation_used}]" if result.mutation_used else ""
                    ai = f" {result.ai_verdict}" if result.ai_verdict else ""
                    log(
                        f"  [{done}/{len(tcp_passed)}] OK "
                        f"{result.quality.value.upper():>7} | "
                        f"{result.latency:>6.0f}ms j{result.jitter:>4.0f} | "
                        f"rc:{result.reconnect_success}/{CONFIG.RECONNECT_TESTS} | "
                        f"{result.categories}cat(crit{result.critical_categories}){tg} | "
                        f"{result.protocol}/{result.transport_used}{rf}{mut}{ai}{dpi}"
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

    _flush_history_and_stats(results, args.region)

    # === SUMMARY ===
    print("\n" + "=" * 60)
    print("  RESULTS")
    print("=" * 60)
    print(f"  Unique: {stats.unique} (dupes: {stats.duplicates})")
    print(f"  TCP: {stats.tcp_passed} ({stats.tcp_passed * 100 // max(stats.unique, 1)}%)")
    print(f"  Quick: {stats.quick_passed} passed, {stats.quick_failed} killed early")
    print(f"  XRAY: {stats.xray_passed} ({stats.xray_passed * 100 // max(stats.tcp_passed, 1)}%)")
    print(f"  RF-Ready: {stats.rf_ready} ({stats.rf_ready * 100 // max(stats.xray_passed, 1)}%)")
    print()

    for q in Quality:
        count = stats.by_quality.get(q, 0)
        if count > 0:
            print(f"    {q.value.upper()}: {count}")
    print()

    if stats.mutations_tried > 0:
        print(f"  Mutations: {stats.mutations_success}/{stats.mutations_tried}")
    if stats.dpi_suspects > 0:
        print(f"  DPI suspects: {stats.dpi_suspects}")
    if stats.ai_anomalies > 0:
        print(f"  AI anomalies: {stats.ai_anomalies}")
    print()

    for proto, count in sorted(stats.by_protocol.items(), key=lambda x: -x[1]):
        ps = ai_engine.protocol_stats.get(proto, {})
        trend = ps.get('trend', 0)
        rf_count = ps.get('rf_ready_count', 0)
        arrow = "^" if trend > 0.05 else "v" if trend < -0.05 else "="
        print(f"    {proto}: {count} (RF: {rf_count}) {arrow}")
    print()

    if stats.by_transport:
        print("  By transport:")
        for transport, count in stats.by_transport.items():
            print(f"    {transport}: {count}")
        print()

    if stats.by_sni:
        print("  By SNI:")
        for sni, count in sorted(stats.by_sni.items(), key=lambda x: -x[1])[:5]:
            ss = ai_engine.sni_stats.get(sni, {})
            rate = ss.get('success', 0) / max(ss.get('total', 1), 1)
            lat = ss.get('avg_latency', 0)
            print(f"    {sni[:30]}: {count} ({rate:.0%}, {lat:.0f}ms)")
        print()

    if ai_engine.category_weights:
        print("  Category effectiveness:")
        for name, cw in sorted(
            ai_engine.category_weights.items(),
            key=lambda x: x[1].get('weight', 0),
            reverse=True
        ):
            if cw['total'] > 0:
                rate = cw['success'] / cw['total']
                priority = cw.get('priority', 'optional')
                print(f"    {name:>12} ({priority:>8}): {rate:.0%}, w={cw['weight']:.1f}")
        print()

    print(f"  TCP={tcp_time:.1f}s  XRAY={xray_time:.1f}s  TOTAL={total_time / 60:.1f}min")

    if stats.errors:
        print("\n  Error breakdown:")
        for error, count in sorted(stats.errors.items(), key=lambda x: -x[1])[:8]:
            print(f"    {error}: {count}")

    print("=" * 60)

    if not results:
        log("[WARN] NO ALIVE KEYS (Xray-level) — all keys failed at Xray stage")
        return 0

    return 0 if stats.xray_passed > 0 else 0


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
