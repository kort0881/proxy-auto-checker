#!/usr/bin/env bash
# advanced_checker.sh — обёртка для advanced_checker.py
# FIX: убрана любая арифметика, только чтение JSON и echo

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHON="${PYTHON:-python3}"
CHECKER="$SCRIPT_DIR/advanced_checker.py"
STATS_FILE="$SCRIPT_DIR/results/stats_latest.json"
REGION="${1:-ALL}"
TRANSPORT="${2:-tcp}"
ROUTE_TAG="${3:-default}"

echo "============================================================"
echo "  AI Proxy Checker — bash wrapper"
echo "  Region: $REGION | Transport: $TRANSPORT | Route: $ROUTE_TAG"
echo "============================================================"

"$PYTHON" "$CHECKER" \
    --region "$REGION" \
    --transport "$TRANSPORT" \
    --route-tag "$ROUTE_TAG"

EXIT_CODE=$?

# Читаем статистику из JSON (без expr/let/$(( )))
if [ -f "$STATS_FILE" ] && command -v python3 &>/dev/null; then
    TOTAL=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('total_working', 0))" 2>/dev/null || echo "0")
    ELITE=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('by_quality',{}).get('elite',0))" 2>/dev/null || echo "0")
    PREMIUM=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('by_quality',{}).get('premium',0))" 2>/dev/null || echo "0")
    GOOD=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('by_quality',{}).get('good',0))" 2>/dev/null || echo "0")
    RF=$(python3 -c "import json; d=json.load(open('$STATS_FILE')); print(d.get('rf_ready', 0))" 2>/dev/null || echo "0")

    echo ""
    echo "📊 Found: Total=$TOTAL, Elite=$ELITE, Premium=$PREMIUM, Good=$GOOD, RF=$RF"
else
    echo "📊 Stats file not found or python3 unavailable"
fi

echo "============================================================"
echo "  Done. Exit code: $EXIT_CODE"
echo "============================================================"

exit $EXIT_CODE
