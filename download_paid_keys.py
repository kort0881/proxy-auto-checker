#!/usr/bin/env python3
import os
import requests
import zipfile
import io
from pathlib import Path

REPO = "kort0881/paid-keys-fetcher"
ARTIFACT_NAME = "paid-keys"
OUTPUT_DIR = Path("results")
OUTPUT_FILE = OUTPUT_DIR / "paid.txt"

def main():
    token = os.environ.get("GH_TOKEN")
    if not token:
        print("No GH_TOKEN, skipping paid keys")
        return

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    # 1. Получаем список запусков workflow (последний успешный)
    runs_url = f"https://api.github.com/repos/{REPO}/actions/runs?status=success&per_page=1"
    resp = requests.get(runs_url, headers=headers)
    if resp.status_code != 200:
        print(f"Failed to get runs: {resp.status_code}")
        return
    runs = resp.json().get("workflow_runs", [])
    if not runs:
        print("No successful runs found")
        return
    run_id = runs[0]["id"]

    # 2. Получаем список артефактов этого запуска
    artifacts_url = f"https://api.github.com/repos/{REPO}/actions/runs/{run_id}/artifacts"
    resp = requests.get(artifacts_url, headers=headers)
    if resp.status_code != 200:
        print(f"Failed to get artifacts: {resp.status_code}")
        return
    artifacts = resp.json().get("artifacts", [])
    for art in artifacts:
        if art["name"] == ARTIFACT_NAME:
            download_url = art["archive_download_url"]
            # 3. Скачиваем архив
            resp = requests.get(download_url, headers=headers)
            if resp.status_code == 200:
                with zipfile.ZipFile(io.BytesIO(resp.content)) as z:
                    # В архиве ожидается файл results/paid.txt
                    # Извлекаем в OUTPUT_DIR
                    for file_info in z.infolist():
                        if file_info.filename.endswith("paid.txt"):
                            content = z.read(file_info.filename)
                            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                            with open(OUTPUT_FILE, "wb") as f:
                                f.write(content)
                            print(f"✅ Downloaded paid keys to {OUTPUT_FILE}")
                            return
            else:
                print(f"Failed to download artifact: {resp.status_code}")
            break
    else:
        print(f"Artifact {ARTIFACT_NAME} not found")

if __name__ == "__main__":
    main()
