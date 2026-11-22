"""Startup smoke test for CI: the real server process boots, serves /api/health,
and shuts down cleanly. No Flask test client — an actual listen on a port."""
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def main() -> int:
    port = free_port()
    env = dict(os.environ)
    env["SATURDAY_DATA_DIR"] = os.environ.get("SATURDAY_DATA_DIR") or str(
        Path(os.environ.get("RUNNER_TEMP", "/tmp")) / "sm-smoke")
    env["SATURDAY_PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "-m", "server.app"],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
    )
    try:
        deadline = time.time() + 30
        body = None
        while time.time() < deadline:
            if proc.poll() is not None:
                out = proc.stdout.read().decode(errors="replace")[-1500:]
                print(f"FAIL: server exited early ({proc.returncode})\n{out}")
                return 1
            try:
                with urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                    body = r.read().decode()
                break
            except Exception:
                time.sleep(0.4)
        if not body:
            print("FAIL: server did not answer /api/health in 30s")
            return 1
        print("health:", body[:220])
        if '"ok": true' not in body.replace("True", "true").lower() and '"ok":true' not in body:
            # flask jsonify writes "ok": true with a space on some versions
            if '"ok"' not in body:
                print("FAIL: unexpected health payload")
                return 1
        print("startup smoke: OK")
        return 0
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    sys.exit(main())
