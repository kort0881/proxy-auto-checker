#!/usr/bin/env python3
"""
apply_patches.py — применяет два патча к advanced_checker.py
Запуск: python3 apply_patches.py advanced_checker.py
"""
import sys, re
from pathlib import Path

target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("advanced_checker.py")
if not target.exists():
    print(f"[ERR] File not found: {target}")
    sys.exit(1)

text = target.read_text(encoding="utf-8")
original = text

# ── PATCH 1: убираем if/else в _flush_history_and_stats ──────────────────────
OLD1 = (
    '    ai_engine.finalize()\n'
    '    dpi_detector.save_stats()\n'
    '    if results:\n'
    '        save_results(results, region)\n'
    '    else:\n'
    '        stats_data = {'
)
NEW1 = (
    '    ai_engine.finalize()\n'
    '    dpi_detector.save_stats()\n'
    '    # FIX: всегда вызываем save_results — FALLBACK внутри разберётся с пустым xray-списком\n'
    '    save_results(results, region)\n'
    '    return\n'
    '    stats_data = {  # unreachable, kept for reference\n'
)

if OLD1 in text:
    text = text.replace(OLD1, NEW1, 1)
    print("[OK] Patch 1 applied: _flush_history_and_stats guard removed")
else:
    print("[SKIP] Patch 1 anchor not found")

# ── PATCH 2: FALLBACK в main() перед _flush_history_and_stats ────────────────
OLD2 = '    _flush_history_and_stats(results, args.region)\n\n    # === SUMMARY ==='
NEW2 = (
    '    # ── FIX PATCH 2: FALLBACK — если xray не дал ни одного живого ключа,\n'
    '    # строим минимальные CheckResult из TCP-прошедших ключей.\n'
    '    if not results and tcp_passed:\n'
    '        log(f"[FALLBACK] Xray gave 0 results — building CheckResult list from {len(tcp_passed)} TCP-passed keys")\n'
    '        for _key in tcp_passed:\n'
    '            _host, _port = extract_host_port(_key)\n'
    '            _, _proto, _sec = parse_key_to_config(_key)\n'
    '            results.append(CheckResult(\n'
    '                key=_key,\n'
    '                alive=True,\n'
    '                protocol=_proto or "Unknown",\n'
    '                host=_host or "",\n'
    '                port=_port or 0,\n'
    '                security=_sec or "none",\n'
    '                latency=0.0,\n'
    '                jitter=0.0,\n'
    '                route_tag=CONFIG.ROUTE_TAG,\n'
    '            ))\n'
    '        log(f"[FALLBACK] Built {len(results)} CheckResult objects from TCP keys")\n\n'
    '    _flush_history_and_stats(results, args.region)\n\n'
    '    # === SUMMARY ==='
)

if OLD2 in text:
    text = text.replace(OLD2, NEW2, 1)
    print("[OK] Patch 2 applied: FALLBACK block added in main()")
else:
    # Try relaxed anchor
    OLD2b = '    _flush_history_and_stats(results, args.region)\n\n    # === SUMMARY'
    if OLD2b in text:
        text = text.replace(OLD2b, NEW2.replace('    # === SUMMARY ===', '    # === SUMMARY'), 1)
        print("[OK] Patch 2 applied (relaxed anchor)")
    else:
        print("[SKIP] Patch 2 anchor not found")

if text == original:
    print("[WARN] No changes made")
    sys.exit(1)

backup = target.with_suffix(".py.bak")
backup.write_text(original, encoding="utf-8")
target.write_text(text, encoding="utf-8")
print(f"[OK] Saved to {target}  (backup: {backup})")
