"""Create isolated local credentials and a test PostgreSQL container, never overwrite."""
import json
import argparse
import os
from pathlib import Path
import secrets
import subprocess
import time
from werkzeug.security import generate_password_hash

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--context', help='Docker context；默认使用当前 context')
args = parser.parse_args()
docker = ['docker'] + (['--context', args.context] if args.context else [])

root = Path(__file__).resolve().parents[1]
folder = root / ".local"
folder.mkdir(mode=0o700, exist_ok=True)
settings = folder / "settings.json"
if settings.exists():
    raise SystemExit(".local/settings.json 已存在，未覆盖。")
password, login = secrets.token_hex(24), secrets.token_urlsafe(14)
config = {"SECRET_KEY": secrets.token_hex(32), "ADMIN_PASSWORD_HASH": generate_password_hash(login),
          "DATABASE_URL": f"postgresql+psycopg://postgres:{password}@127.0.0.1:55432/englishwords"}
subprocess.run(docker + ["run", "-d", "--name", "englishwords-dev-db", "-p", "127.0.0.1:55432:5432",
                "-e", "POSTGRES_PASSWORD", "-e", "POSTGRES_DB=englishwords", "-v", "englishwords-dev-db:/var/lib/postgresql", "postgres:18.6-bookworm"],
               env={**os.environ, "POSTGRES_PASSWORD": password}, check=True, stdout=subprocess.DEVNULL)
with settings.open("x") as file:
    json.dump(config, file, indent=2)
settings.chmod(0o600)
with (folder / "login.txt").open("x") as file:
    file.write(login + "\n")
(folder / "login.txt").chmod(0o600)
for _ in range(60):
    result = subprocess.run(docker + ["exec", "englishwords-dev-db", "pg_isready", "-U", "postgres", "-d", "englishwords"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        print("本地测试库已就绪；管理密码保存在 .local/login.txt（未输出）。")
        break
    time.sleep(1)
else:
    raise SystemExit("数据库尚未就绪，请查看专用容器日志。")
