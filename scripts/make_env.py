"""Prepare .env locally; does not connect to Docker or deploy anything."""
from pathlib import Path
from getpass import getpass
import secrets
from werkzeug.security import generate_password_hash

root = Path(__file__).resolve().parents[1]
password = getpass("设置网页管理密码（至少 12 字符）：")
if len(password) < 12:
    raise SystemExit("密码至少需要 12 字符。")
if password != getpass("再次输入："):
    raise SystemExit("两次密码不一致。")
values = {"POSTGRES_ADMIN_PASSWORD": secrets.token_hex(32), "DB_PASSWORD": secrets.token_hex(32),
          "SECRET_KEY": secrets.token_hex(32), "ADMIN_PASSWORD_HASH": generate_password_hash(password),
          "WEB_BIND_IP": "127.0.0.1", "WEB_PORT": "8088", "COOKIE_SECURE": "0"}
with (root / ".env").open("x") as file:
    for key, value in values.items():
        file.write(f"{key}='{value}'\n")
(root / ".env").chmod(0o600)
print("已生成 .env，未输出任何凭据。默认仅绑定本机。")
