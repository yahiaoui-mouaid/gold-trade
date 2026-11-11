"""Create the private development PostgreSQL cluster in .dev/ (port 5433).

Does not touch any other PostgreSQL service on the machine. Safe to re-run:
an existing cluster is reused and simply started.
"""
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEV = ROOT / ".dev"
PGDATA = DEV / "pgdata"
CONFIG = DEV / "config.json"
BIN = Path(os.environ.get("GOLDVOLT_PG_BIN", r"C:\Program Files\PostgreSQL\18\bin"))
PORT = 5433


def run(*args, **kwargs):
    return subprocess.run([str(a) for a in args], check=True, **kwargs)


def init_cluster(cfg):
    pwfile = DEV / "pw.tmp"
    pwfile.write_text(cfg["postgres_password"], encoding="utf-8")
    try:
        run(BIN / "initdb", "-D", PGDATA, "-U", "postgres", f"--pwfile={pwfile}",
            "--auth=scram-sha-256", "--encoding=UTF8", "--locale=C", "--data-checksums")
    finally:
        pwfile.unlink()
    with (PGDATA / "postgresql.conf").open("a", encoding="utf-8") as f:
        f.write(
            "\nlisten_addresses = '127.0.0.1'\n"
            f"port = {PORT}\n"
            "password_encryption = 'scram-sha-256'\n"
            "log_connections = on\n"
            "timezone = 'UTC'\n"
        )
    (PGDATA / "pg_hba.conf").write_text(
        "host all goldvolt_app 127.0.0.1/32 scram-sha-256\n"
        "host all goldvolt_owner 127.0.0.1/32 scram-sha-256\n"
        "host all postgres 127.0.0.1/32 scram-sha-256\n",
        encoding="utf-8",
    )


def is_running():
    return subprocess.run([str(BIN / "pg_ctl"), "status", "-D", str(PGDATA)],
                          capture_output=True).returncode == 0


def start():
    if not is_running():
        # Detached so the server outlives this script's console.
        subprocess.Popen(
            [str(BIN / "pg_ctl"), "start", "-w", "-D", str(PGDATA), "-l", str(DEV / "pg.log")],
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ).wait(timeout=60)


def create_roles(cfg):
    sql = f"""
    CREATE ROLE goldvolt_owner LOGIN CREATEDB PASSWORD '{cfg["owner_password"]}';
    CREATE ROLE goldvolt_app LOGIN PASSWORD '{cfg["app_password"]}';
    GRANT goldvolt_app TO goldvolt_owner;
    CREATE DATABASE goldvolt OWNER goldvolt_owner;
    REVOKE ALL ON DATABASE goldvolt FROM PUBLIC;
    GRANT CONNECT ON DATABASE goldvolt TO goldvolt_app;
    """
    env = {**os.environ, "PGPASSWORD": cfg["postgres_password"]}
    for statement in filter(str.strip, sql.split(";")):
        run(BIN / "psql", "-h", "127.0.0.1", "-p", PORT, "-U", "postgres", "-d", "postgres",
            "-v", "ON_ERROR_STOP=1", "-q", "-c", statement, env=env)


def main():
    DEV.mkdir(exist_ok=True)
    fresh = not PGDATA.exists()
    if CONFIG.exists():
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    else:
        cfg = {
            "secret_key": secrets.token_urlsafe(64),
            "postgres_password": secrets.token_hex(24),
            "owner_password": secrets.token_hex(24),
            "app_password": secrets.token_hex(24),
            "db_host": "127.0.0.1",
            "db_port": PORT,
            "db_name": "goldvolt",
            "media_root": str(DEV / "media"),
            "log_dir": str(DEV / "logs"),
        }
        CONFIG.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    if fresh:
        init_cluster(cfg)
    start()
    if not is_running():
        sys.exit("PostgreSQL did not start; see .dev/pg.log")
    if fresh:
        create_roles(cfg)
    print("Development database ready on 127.0.0.1:%d" % PORT)


if __name__ == "__main__":
    main()
