#!/bin/bash
set -e

cd /opt/proxy-auto-checker

# активируем venv, если им пользуешься
source venv/bin/activate

# запускаем чекер
python advanced_checker.py

# игнорируем venv, чтобы оно не лезло в git
echo "venv/" >> .gitignore

# добавляем только результаты и .gitignore
git add results .gitignore

# коммитим, только если реально есть изменения
if ! git diff --cached --quiet; then
  git commit -m "Auto update proxy results $(date '+%Y-%m-%d %H:%M')"
  git push origin main
fi
