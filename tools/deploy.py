"""Deploy custom_components/routeros_ha lên HA qua SSH exec + base64 (host không có sftp-server).

Cần file `.env` (gitignored) ở gốc repo với HA_HOST, HA_USER, HA_PASS — xem `.env.example`.
Dùng: python tools/deploy.py   (sau đó restart HA)
"""

import base64
from pathlib import Path

import paramiko

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "custom_components" / "routeros_ha"
DEST = "/config/custom_components/routeros_ha"
ENV = ROOT / ".env"

env = dict(
    line.strip().split("=", 1)
    for line in ENV.read_text(encoding="utf-8").splitlines()
    if "=" in line and not line.lstrip().startswith("#")
)
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(
    env["HA_HOST"], username=env["HA_USER"], password=env["HA_PASS"], timeout=10
)


def run(cmd: str) -> str:
    _in, out, err = ssh.exec_command(cmd)
    code = out.channel.recv_exit_status()
    if code:
        raise RuntimeError(f"{cmd[:80]}… exit {code}: {err.read().decode()}")
    return out.read().decode()


files = [p for p in SRC.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
dirs = sorted(
    {f"{DEST}/{p.relative_to(SRC).parent.as_posix()}".rstrip("/.") for p in files}
)
run(f"sudo mkdir -p {' '.join(dirs)} && sudo rm -rf {DEST}/__pycache__")
for p in files:
    rel = p.relative_to(SRC).as_posix()
    b64 = base64.b64encode(p.read_bytes()).decode()
    run(f"echo {b64} | sudo sh -c 'base64 -d > {DEST}/{rel}'")
    print("deployed", rel)
print(run(f"sudo ls -la {DEST} {DEST}/translations {DEST}/brand"))
ssh.close()
