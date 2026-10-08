"""Run a private MySQL instance; never read or change an installed service.

Usage: python core/scripts/local_mysql.py start [--mysql-bin PATH]
       python core/scripts/local_mysql.py status|stop

All data, logs and credentials are under workspace/.work/mysql-core. Passwords
are randomly generated, never accepted on the command line and never printed.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import time

WORKSPACE = Path(__file__).resolve().parents[2]
STATE = WORKSPACE / ".work" / "mysql-core"
DATA = STATE / "data"
PORT = 3308
HOST = "127.0.0.1"
HIDDEN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class LocalMySQLError(RuntimeError):
    pass


def confined(path: Path) -> Path:
    path = path.resolve()
    if not path.is_relative_to(STATE.resolve()):
        raise LocalMySQLError("Refusing a file operation outside the private instance directory.")
    return path


def read_json(name: str) -> dict:
    path = confined(STATE / name)
    if not path.is_file():
        raise LocalMySQLError(f"Private instance metadata is missing: {name}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(name: str, value: dict) -> None:
    path = confined(STATE / name)
    temporary = confined(path.with_suffix(path.suffix + ".tmp"))
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def executable(bin_directory: Path, name: str) -> Path:
    return bin_directory / (name + (".exe" if os.name == "nt" else ""))


def locate_bin(explicit: str | None) -> tuple[Path, str]:
    candidates = [Path(explicit)] if explicit else [
        Path("D:/MySQL/mysql-8.0.43-winx64/bin"),
        Path("C:/Program Files/MySQL/MySQL Server 8.0/bin"),
        Path("F:/mysql5/bin"),
        Path("D:/phpstudy_pro/Extensions/MySQL5.7.26/bin"),
    ]
    for candidate in candidates:
        server = executable(candidate, "mysqld")
        if not server.is_file() or not executable(candidate, "mysql").is_file():
            continue
        result = subprocess.run([str(server), "--no-defaults", "--version"],
                                capture_output=True, text=True, creationflags=HIDDEN, timeout=30)
        match = re.search(r"Ver\s+(\d+\.\d+\.\d+)", result.stdout)
        if result.returncode == 0 and match and (match[1].startswith("8.") or match[1].startswith("5.7.")):
            return candidate.resolve(), match[1]
    raise LocalMySQLError("MySQL 5.7 or 8.x binaries were not found; supply --mysql-bin with the bin directory.")


def occupied() -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, PORT)) == 0


def client_command(metadata: dict, command: str, sql: str | None = None) -> subprocess.CompletedProcess:
    admin = read_json("admin.json")
    config = confined(STATE / ("client-" + secrets.token_hex(8) + ".cnf"))
    # Credentials only occur in a temporary option file, never in process args.
    config.write_text("[client]\nuser=root\npassword=" + admin["password"] +
                      f"\nhost={HOST}\nport={PORT}\nprotocol=tcp\n", encoding="utf-8")
    try:
        args = [str(executable(Path(metadata["bin"]), command)), f"--defaults-file={config.name}"]
        if command == "mysql":
            args += ["--batch", "--raw", "--skip-column-names", "--default-character-set=utf8mb4"]
        else:
            args += ["shutdown"]
        return subprocess.run(args, input=sql, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20, creationflags=HIDDEN,
                              cwd=STATE)
    finally:
        confined(config).unlink(missing_ok=True)


def query(metadata: dict, sql: str) -> str:
    result = client_command(metadata, "mysql", sql)
    if result.returncode:
        # MySQL errors can echo SQL containing credentials. Do not print SQL/errors.
        raise LocalMySQLError("Private MySQL authentication or SQL operation failed; see the private server log.")
    return result.stdout.strip()


def process_image(pid: int) -> Path:
    if os.name != "nt":
        return Path(f"/proc/{pid}/exe").resolve(strict=True)
    from ctypes import wintypes
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel.OpenProcess.restype = wintypes.HANDLE
    kernel.QueryFullProcessImageNameW.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                ctypes.POINTER(wintypes.DWORD))
    kernel.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        raise LocalMySQLError("Cannot verify the private server PID; no process was stopped.")
    try:
        buffer = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(buffer))
        if not kernel.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(length)):
            raise LocalMySQLError("Cannot verify the private server executable path.")
        return Path(buffer.value).resolve()
    finally:
        kernel.CloseHandle(handle)


def verified_server(metadata: dict) -> int:
    result = query(metadata, "SELECT HEX(@@datadir), HEX(@@pid_file), @@port;").split("\t")
    if len(result) != 3:
        raise LocalMySQLError("Unexpected server identity response.")
    data_hex, pid_hex, port = result
    path_encoding = "mbcs" if os.name == "nt" else "utf-8"
    server_data = bytes.fromhex(data_hex).decode(path_encoding)
    pid_file = bytes.fromhex(pid_hex).decode(path_encoding)
    if Path(server_data).resolve() != DATA.resolve() or int(port) != PORT:
        raise LocalMySQLError("Port belongs to a different MySQL instance; refusing to touch it.")
    if Path(pid_file).resolve() != (STATE / "mysqld.pid").resolve():
        raise LocalMySQLError("Unexpected server PID file; refusing to touch it.")
    pid = int(confined(Path(pid_file)).read_text(encoding="ascii").strip())
    if process_image(pid) != executable(Path(metadata["bin"]), "mysqld").resolve():
        raise LocalMySQLError("Server executable does not match instance metadata.")
    return pid


def config_text(bin_directory: Path, version: str) -> str:
    values = {
        "basedir": bin_directory.parent.as_posix(),
        "datadir": DATA.as_posix(),
        "port": PORT,
        "bind-address": HOST,
        "pid-file": (STATE / "mysqld.pid").as_posix(),
        "log-error": (STATE / "mysql-error.log").as_posix(),
        "character-set-server": "utf8mb4",
        "collation-server": "utf8mb4_unicode_ci",
        "default-time-zone": "+08:00",
        "explicit-defaults-for-timestamp": "ON",
        "local-infile": "OFF",
        "skip-name-resolve": "ON",
    }
    # loose prefix disables MySQL X when installed, remains valid on MySQL 5.7.
    values["loose-mysqlx"] = "OFF"
    if version.startswith("5.7."):
        values["log-syslog"] = "OFF"
        values["tls-version"] = "TLSv1.2"
    lines = ["[mysqld]"]
    for key, value in values.items():
        lines.append(f'{key}="{value}"')
    return "\n".join(lines) + "\n"


def provision(metadata: dict) -> None:
    runtime = read_json("runtime.json")
    password = runtime["password"]  # token_hex: no SQL escaping ambiguity
    statements = [
        "CREATE DATABASE IF NOT EXISTS volunteer_core CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        "CREATE DATABASE IF NOT EXISTS volunteer_core_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;",
        f"CREATE USER IF NOT EXISTS 'volunteer_app'@'127.0.0.1' IDENTIFIED BY '{password}';",
        f"ALTER USER 'volunteer_app'@'127.0.0.1' IDENTIFIED BY '{password}';",
        "REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'volunteer_app'@'127.0.0.1';",
        # Database-level grants treat _ as a wildcard unless explicitly escaped.
        "GRANT SELECT, INSERT, UPDATE, DELETE ON `volunteer\\_core`.* TO 'volunteer_app'@'127.0.0.1';",
        "GRANT SELECT, INSERT, UPDATE, DELETE ON `volunteer\\_core\\_test`.* TO 'volunteer_app'@'127.0.0.1';",
    ]
    query(metadata, "\n".join(statements))


def start(mysql_bin: str | None) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    # The root .work directory is private runtime data, never source material.
    confined(STATE / ".gitignore").write_text("*\n!.gitignore\n", encoding="ascii")
    if occupied():
        metadata = read_json("server.json")
        pid = verified_server(metadata)
        print(f"Private MySQL already running: {HOST}:{PORT}, PID {pid}, version {metadata['version']}.")
        return
    if (STATE / "server.json").exists():
        metadata = read_json("server.json")
        bin_directory = Path(metadata["bin"])
        version = metadata["version"]
        if mysql_bin and Path(mysql_bin).resolve() != bin_directory.resolve():
            raise LocalMySQLError("Cannot switch binaries for an existing private data directory.")
    else:
        if DATA.exists() and any(DATA.iterdir()):
            raise LocalMySQLError("Unrecognized nonempty data directory; refusing to initialize.")
        bin_directory, version = locate_bin(mysql_bin)
        metadata = {"bin": str(bin_directory), "version": version, "host": HOST, "port": PORT,
                    "datadir": str(DATA), "initialized": False}
        write_json("server.json", metadata)
        write_json("admin.json", {"host": HOST, "port": PORT, "user": "root",
                                  "password": secrets.token_hex(32), "database": "volunteer_core"})
        write_json("runtime.json", {"host": HOST, "port": PORT, "user": "volunteer_app",
                                    "password": secrets.token_hex(32), "database": "volunteer_core"})
    server = executable(bin_directory, "mysqld")
    config = confined(STATE / "my.cnf")
    # Windows MySQL 5.7 consumes option-file paths in the system ANSI codepage.
    # This matters when the workspace contains Chinese characters.
    config.write_text(config_text(bin_directory, version),
                      encoding="mbcs" if os.name == "nt" else "utf-8")
    if not metadata.get("initialized"):
        if not DATA.exists():
            DATA.mkdir()
        result = subprocess.run([str(server), f"--defaults-file={config.as_posix()}", "--initialize-insecure"],
                                capture_output=True, timeout=120, creationflags=HIDDEN)
        if result.returncode:
            confined(STATE / "initialize.log").write_bytes(result.stdout + result.stderr)
            raise LocalMySQLError("Private data initialization failed. Review .work/mysql-core/mysql-error.log.")
        metadata["initialized"] = True
        write_json("server.json", metadata)
    admin = read_json("admin.json")
    # Every startup sets the same secret before accepting connections. This also
    # safely recovers an interrupted first startup with an initialized data dir.
    init_file = confined(STATE / "bootstrap.sql")
    root_secret = admin["password"]
    init_file.write_text("\n".join([
        f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{root_secret}';",
        f"CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED BY '{root_secret}';",
        f"ALTER USER 'root'@'127.0.0.1' IDENTIFIED BY '{root_secret}';",
        "GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION;",
    ]) + "\n", encoding="ascii")
    output = confined(STATE / "console.log")
    with output.open("ab") as log:
        process = subprocess.Popen([str(server), f"--defaults-file={config.as_posix()}",
                                    f"--init-file={init_file.as_posix()}"],
                                   stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                   creationflags=HIDDEN | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                                   close_fds=True)
    metadata["pid"] = process.pid
    write_json("server.json", metadata)
    deadline = time.monotonic() + 70
    while time.monotonic() < deadline:
        if process.poll() is not None:
            init_file.unlink(missing_ok=True)
            raise LocalMySQLError("Private server exited. Review .work/mysql-core/mysql-error.log.")
        if occupied():
            try:
                pid = verified_server(metadata)
                init_file.unlink(missing_ok=True)
                provision(metadata)
                print(f"Private MySQL running: {HOST}:{PORT}, PID {pid}, version {version}.")
                print("Application credentials saved in .work/mysql-core/runtime.json (password not displayed).")
                return
            except LocalMySQLError:
                pass
        time.sleep(0.4)
    raise LocalMySQLError("Private server startup timed out; inspect its error log and run status.")


def status() -> None:
    if not occupied():
        print("Private MySQL is stopped.")
        return
    metadata = read_json("server.json")
    pid = verified_server(metadata)
    print(f"Private MySQL running: {HOST}:{PORT}, PID {pid}, version {metadata['version']}.")


def stop() -> None:
    if not occupied():
        print("Private MySQL is already stopped.")
        return
    metadata = read_json("server.json")
    pid = verified_server(metadata)
    result = client_command(metadata, "mysqladmin")
    if result.returncode:
        raise LocalMySQLError("Graceful shutdown failed; no process was forcibly terminated.")
    for _ in range(100):
        if not occupied():
            print(f"Private MySQL stopped gracefully (PID {pid}).")
            return
        time.sleep(0.1)
    raise LocalMySQLError("Shutdown requested; listener is still present. No process was forcibly terminated.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--mysql-bin", help="MySQL bin directory; applies only to first initialization")
    args = parser.parse_args()
    try:
        if args.action == "start":
            start(args.mysql_bin)
        elif args.action == "stop":
            stop()
        else:
            status()
    except (LocalMySQLError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
