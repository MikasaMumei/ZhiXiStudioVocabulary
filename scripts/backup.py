"""Explicit operator-run backup; uses pg_dump in the project's Compose database."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--container", help="仅供明确指定的本地隔离容器；默认使用项目 Compose")
parser.add_argument("--context", default=None)
args = parser.parse_args()

root = Path(__file__).resolve().parents[1]
folder = root / "backups"
folder.mkdir(mode=0o700, exist_ok=True)
target = folder / ("englishwords-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ") + ".dump")
with target.open("xb") as output:
    command = ["docker"] + (["--context", args.context] if args.context else [])
    command += ["exec", args.container] if args.container else ["compose", "exec", "-T", "db"]
    # All application objects are public tables; include indexes, constraints and data.
    # -t avoids re-creating the pre-existing public schema on a fresh restore target.
    command += ["pg_dump", "-U", "postgres", "-d", "englishwords", "-t", "public.*", "-Fc", "--no-owner", "--no-acl"]
    result = subprocess.run(command, cwd=root, stdout=output)
target.chmod(0o600)
if result.returncode:
    raise SystemExit(f"备份失败，不可使用该文件：{target.name}")
print(f"备份已生成：{target.name}。请按运维文档在隔离库验证恢复。")
