name: Xray selftest

on:
  workflow_dispatch:  # запуск руками из вкладки Actions

jobs:
  selftest:
    runs-on: ubuntu-latest

    steps:
      - name: Checkout repo
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          python -m pip install requests

      - name: Xray self test
        run: |
          cat > xray_selftest.py << 'EOF'
          #!/usr/bin/env python3
          import json, random, socket, subprocess, time
          from pathlib import Path
          import requests

          WORKDIR = Path(__file__).parent.absolute()
          XRAYFOLDER = WORKDIR / "xray_selftest"

          def wait_for_port(port: int, timeout: float = 5.0) -> bool:
              deadline = time.time() + timeout
              while time.time() < deadline:
                  try:
                      with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                          return True
                  except OSError:
                      time.sleep(0.1)
              return False

          def setup_xray() -> Path:
              XRAYFOLDER.mkdir(parents=True, exist_ok=True)
              import platform
              system = platform.system().lower()
              machine = platform.machine().lower()
              if system != "linux":
                  raise RuntimeError(f"Unsupported system for selftest: {system}")
              arch = "arm64-v8a" if "aarch64" in machine or "arm64" in machine else "64"
              filename = f"Xray-linux-{arch}.zip"
              url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{filename}"
              print(f"[DL] {url}")
              r = requests.get(url, stream=True, timeout=120)
              r.raise_for_status()
              zippath = XRAYFOLDER / "xray.zip"
              with open(zippath, "wb") as f:
                  for chunk in r.itercontent(8192):
                      if chunk:
                          f.write(chunk)
              import zipfile
              with zipfile.ZipFile(zippath, "r") as zf:
                  zf.extractall(XRAYFOLDER)
              zippath.unlink()
              exepath = XRAYFOLDER / "xray"
              exepath.chmod(0o755)
              print(f"[OK] Xray installed at {exepath}")
              return exepath

          def main() -> int:
              xrayexe = setup_xray()
              port = random.randint(20000, 50000)
              cfg = {
                  "log": {"loglevel": "info"},
                  "inbounds": [{
                      "listen": "127.0.0.1",
                      "port": port,
                      "protocol": "http",
                      "settings": {"timeout": 30}
                  }],
                  "outbounds": [{
                      "protocol": "freedom",
                      "tag": "direct"
                  }]
              }
              cfg_path = XRAYFOLDER / f"selftest_{port}.json"
              cfg_path.write_text(json.dumps(cfg), encoding="utf-8")
              print(f"[CFG] {cfg_path}")

              proc = subprocess.Popen(
                  [str(xrayexe), "run", "-c", str(cfg_path)],
                  stdout=subprocess.PIPE,
                  stderr=subprocess.STDOUT,
                  text=True,
              )
              try:
                  if not wait_for_port(port, timeout=10):
                      print("[FAIL] xray_startup: port did not open in time")
                      try:
                          for _ in range(20):
                              line = proc.stdout.readline()
                              if not line:
                                  break
                              print("[XRAY]", line.rstrip())
                      except Exception:
                          pass
                      return 1
                  proxies = {
                      "http": f"http://127.0.0.1:{port}",
                      "https": f"http://127.0.0.1:{port}",
                  }
                  try:
                      resp = requests.get("https://www.google.com", proxies=proxies, timeout=10)
                      print(f"[OK] Xray selftest, status={resp.status_code}")
                      return 0
                  except Exception as e:
                      print(f"[FAIL] HTTP through Xray failed: {e}")
                      return 1
              finally:
                  try:
                      proc.terminate()
                      proc.wait(timeout=2)
                  except Exception:
                      try:
                          proc.kill()
                          proc.wait(timeout=1)
                      except Exception:
                          pass
                  try:
                      cfg_path.unlink()
                  except OSError:
                      pass

          if __name__ == "__main__":
              raise SystemExit(main())
          EOF

          python xray_selftest.py

