"""Run a private MySQL instance; never read or change an installed service.

Usage: python core/scripts/local_mysql.py start [--mysql-bin PATH] [--port PORT]
       python core/scripts/local_mysql.py status|stop [--port PORT]

All data, logs and credentials are under workspace/.work/mysql-core
(or under $VOLUNTEER_HOME/mysql-core when that variable is set). Passwords are
randomly generated, never accepted on the command line and never printed.
The TCP port defaults to 3308 and can be overridden with --port or the
VOLUNTEER_DB_PORT environment variable.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import string
import subprocess
import sys
import tempfile
import time

CORE = Path(__file__).resolve().parents[1]
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))
try:  # app.paths only uses the standard library, so a bare Python can import it.
    from app.paths import MYSQL_DATA, MYSQL_STATE
except Exception:  # pragma: no cover - defensive fallback for a copied script
    MYSQL_STATE = CORE.parent / ".work" / "mysql-core"
    MYSQL_DATA = MYSQL_STATE / "data"
STATE = MYSQL_STATE
DATA = MYSQL_DATA
HOST = "127.0.0.1"
DEFAULT_PORT = 3308
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
    # utf-8-sig tolerates a BOM if the file was copied or edited on Windows.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(name: str, value: dict) -> None:
    path = confined(STATE / name)
    temporary = confined(path.with_suffix(path.suffix + ".tmp"))
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def executable(bin_directory: Path, name: str) -> Path:
    return bin_directory / (name + (".exe" if os.name == "nt" else ""))


def version_family(version: str | None) -> str | None:
    """Return ``major.minor`` for a MySQL version string, else None."""
    if not version:
        return None
    parts = str(version).split(".")
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else None


def supported_version(version: str) -> bool:
    return version.startswith(("5.7.", "8."))


def windows_service_bins() -> list[Path]:
    """Discover MySQL binaries registered as Windows services (best effort)."""
    if os.name != "nt":
        return []
    import winreg
    found: list[Path] = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Services") as services:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(services, index)
                except OSError:
                    break
                index += 1
                if "mysql" not in name.lower():
                    continue
                try:
                    with winreg.OpenKey(services, name) as service:
                        image = winreg.QueryValueEx(service, "ImagePath")[0]
                except OSError:
                    continue
                if "mysqld" not in image.lower():
                    continue
                match = re.search(r'"([^"]+mysqld\.exe)"', image, re.IGNORECASE)
                if not match:
                    match = re.search(r'([A-Za-z]:\\[^\s"]*mysqld\.exe)', image, re.IGNORECASE)
                if match:
                    found.append(Path(match[1]).parent)
    except OSError:
        pass
    return found


def common_bin_candidates() -> list[Path]:
    """Search the PATH and the usual MySQL install locations on every drive.

    Only shallow directory patterns are probed; no full-drive enumeration.
    """
    found: list[Path] = []
    on_path = shutil.which("mysqld")
    if on_path:
        found.append(Path(on_path).parent)
    if os.name == "nt":
        roots = [Path(f"{letter}:/") for letter in string.ascii_uppercase
                 if Path(f"{letter}:/").exists()]
    else:
        roots = [Path("/usr"), Path("/usr/local/mysql")]
    patterns = [
        "bin/mysqld",                    # /usr/bin, /usr/local/mysql/bin
        "*[Mm]y[Ss][Qq][Ll]*/bin",
        "*[Mm]y[Ss][Qq][Ll]*/*/bin",
        "*[Mm]y[Ss][Qq][Ll]*/Extensions/MySQL*/bin",
        "xampp/mysql/bin",
        "wamp*/bin/mysql/*/bin",
    ]
    for root in roots:
        for pattern in patterns:
            for candidate in root.glob(pattern):
                if candidate.is_file():     # matched "bin/mysqld"
                    candidate = candidate.parent
                if candidate.is_dir():
                    found.append(candidate)
    return found


def unique_directories(candidates: list[Path]) -> list[Path]:
    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def probe_version(bin_directory: Path) -> str | None:
    """Return the MySQL server version when ``bin_directory`` holds usable tools."""
    server = executable(bin_directory, "mysqld")
    if not server.is_file() or not executable(bin_directory, "mysql").is_file():
        return None
    try:
        result = subprocess.run([str(server), "--no-defaults", "--version"],
                                capture_output=True, text=True, creationflags=HIDDEN, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    match = re.search(r"Ver\s+(\d+\.\d+\.\d+)", result.stdout)
    if result.returncode == 0 and match and supported_version(match[1]):
        return match[1]
    return None


def locate_bin(explicit: str | None, family: str | None = None) -> tuple[Path, str]:
    """Find a MySQL 5.7/8.x bin directory, optionally restricted to a version family."""
    if explicit:
        candidates = [Path(explicit)]
    else:
        candidates = unique_directories(common_bin_candidates() + windows_service_bins())
    for candidate in candidates:
        version = probe_version(candidate)
        if version is None:
            continue
        if family and version_family(version) != family:
            continue
        return candidate.resolve(), version
    if family:
        raise LocalMySQLError(
            f"未找到与已初始化数据目录版本族 {family}.x 匹配的 MySQL 二进制，已停止启动以保护数据。"
            "请安装同版本族的 MySQL，或用 --mysql-bin 指定其 bin 目录。")
    raise LocalMySQLError("MySQL 5.7 or 8.x binaries were not found; supply --mysql-bin with the bin directory.")


def resolve_existing_bin(metadata: dict, mysql_bin: str | None) -> tuple[Path, str]:
    """Return (bin directory, version) for an already initialized instance.

    A cached path that no longer exists (for example after moving the project to
    another machine) is re-discovered only within the same version family, so a
    different major version can never silently open an incompatible data
    directory. The data directory itself is never changed here.
    """
    cached = Path(str(metadata.get("bin", "")))
    family = version_family(metadata.get("version"))
    if mysql_bin:
        explicit = Path(mysql_bin).expanduser()
        version = probe_version(explicit)
        if version is None:
            raise LocalMySQLError(
                f"--mysql-bin 指定的目录中没有可用的 MySQL 5.7/8.x 工具：{explicit}")
        if family and version_family(version) != family:
            raise LocalMySQLError(
                f"不能为已初始化的数据目录切换到不同版本族：现有 {family}.x，指定的是 {version}。"
                "不同大版本的 MySQL 数据目录不兼容，请使用相同版本族的二进制。")
        if str(explicit.resolve()) != str(cached.resolve()) or version != metadata.get("version"):
            metadata["bin"] = str(explicit.resolve())
            metadata["version"] = version
            write_json("server.json", metadata)
            print(f"Using MySQL {version} at {explicit.resolve()} for the existing data directory.", flush=True)
        return explicit.resolve(), version
    version = probe_version(cached) if str(cached) else None
    if version is not None:
        if metadata.get("version") != version:
            metadata["version"] = version
            write_json("server.json", metadata)
        return cached.resolve(), version
    relocated, version = locate_bin(None, family=family)
    metadata["bin"] = str(relocated)
    metadata["version"] = version
    write_json("server.json", metadata)
    print(f"缓存中的 MySQL 二进制路径 {cached} 已失效，已自动重新定位到 {relocated}（版本 {version}）。",
          flush=True)
    return relocated, version


def validate_port(port: int) -> int:
    if not isinstance(port, int) or not 1 <= port <= 65535:
        raise LocalMySQLError("端口必须是 1—65535 的整数。")
    return port


def env_port() -> int | None:
    raw = os.environ.get("VOLUNTEER_DB_PORT", "").strip()
    if not raw:
        return None
    try:
        return validate_port(int(raw))
    except ValueError:
        raise LocalMySQLError("环境变量 VOLUNTEER_DB_PORT 必须是 1—65535 的整数。") from None


def resolve_port(explicit: int | None, metadata: dict | None = None) -> int:
    """Port precedence: --port, VOLUNTEER_DB_PORT, cached instance metadata, 3308."""
    if explicit is not None:
        return validate_port(int(explicit))
    from_env = env_port()
    if from_env is not None:
        return from_env
    if metadata and metadata.get("port"):
        try:
            return validate_port(int(metadata["port"]))
        except (TypeError, ValueError):
            pass
    return DEFAULT_PORT


def occupied(port: int) -> bool:
    with socket.socket() as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((HOST, port)) == 0


def client_command(metadata: dict, command: str, sql: str | None = None,
                   port: int | None = None) -> subprocess.CompletedProcess:
    if port is None:
        port = int(metadata.get("port", DEFAULT_PORT))
    admin = read_json("admin.json")
    # Credentials only occur in a temporary option file, never in process args.
    argument, cleanup = client_option_file(
        "[client]\nuser=root\npassword=" + admin["password"] +
        f"\nhost={HOST}\nport={port}\nprotocol=tcp\n")
    try:
        args = [str(executable(Path(metadata["bin"]), command)), f"--defaults-file={argument}"]
        if command == "mysql":
            args += ["--batch", "--raw", "--skip-column-names", "--default-character-set=utf8mb4"]
        else:
            args += ["shutdown"]
        return subprocess.run(args, input=sql, capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=20, creationflags=HIDDEN,
                              cwd=STATE)
    finally:
        for path in cleanup:
            path.unlink(missing_ok=True)


def query(metadata: dict, sql: str, port: int | None = None) -> str:
    result = client_command(metadata, "mysql", sql, port)
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


def decode_path_candidates(value: str) -> list[str]:
    """Decode a HEX() filesystem-path value with every plausible encoding.

    MySQL on Windows may report @@datadir / @@pid_file bytes encoded as UTF-8
    or as the system ANSI codepage (mbcs), and the project path itself contains
    CJK characters. Trying the candidates avoids a false "another instance"
    verdict that would block startup instead of protecting anything.
    """
    raw = bytes.fromhex(value)
    encodings = ["utf-8", "latin-1"]
    if os.name == "nt":
        encodings.insert(1, "mbcs")
    decoded: list[str] = []
    for encoding in encodings:
        try:
            text = raw.decode(encoding)
        except (UnicodeDecodeError, LookupError):
            continue
        if text and text not in decoded:
            decoded.append(text)
    return decoded


def same_path(left: str | Path, right: str | Path) -> bool:
    """Compare two filesystem paths the way Windows/Linux filesystems do."""
    def normalized(value: str | Path) -> str:
        try:
            text = str(Path(value).resolve())
        except OSError:
            text = str(value)
        return os.path.normcase(os.path.normpath(text))
    return normalized(left) == normalized(right)


def verified_server(metadata: dict, port: int | None = None) -> int:
    if port is None:
        port = int(metadata.get("port", DEFAULT_PORT))
    result = query(metadata, "SELECT HEX(@@datadir), HEX(@@pid_file), @@port;", port).split("\t")
    if len(result) != 3:
        raise LocalMySQLError("Unexpected server identity response.")
    data_hex, pid_hex, server_port = result
    data_paths = decode_path_candidates(data_hex)
    pid_paths = decode_path_candidates(pid_hex)
    if int(server_port) != port or not any(same_path(path, DATA) for path in data_paths):
        raise LocalMySQLError(
            f"端口 {port} 属于另一个 MySQL 实例（不是本项目的私用数据目录）；"
            "为避免误操作，已停止。可设置环境变量 VOLUNTEER_DB_PORT=<其他端口> 或加 --port <其他端口> 后重试。")
    expected_pid_file = STATE / "mysqld.pid"
    pid_path = next((path for path in pid_paths if same_path(path, expected_pid_file)), None)
    if pid_path is None:
        raise LocalMySQLError("Unexpected server PID file; refusing to touch it.")
    pid = int(confined(Path(pid_path)).read_text(encoding="ascii").strip())
    if not same_path(process_image(pid), executable(Path(metadata["bin"]), "mysqld")):
        raise LocalMySQLError("Server executable does not match instance metadata.")
    return pid


def config_text(bin_directory: Path, version: str, port: int, datadir: Path) -> str:
    values = {
        "basedir": bin_directory.parent.as_posix(),
        # These must be absolute: mysqld resolves relative option-file paths
        # against basedir, not the working directory. The CJK characters are
        # written via the ANSI codepage (mbcs), which mysqld reads correctly;
        # only command-line arguments get truncated, so the command line below
        # keeps passing relative, pure-ASCII filenames instead.
        "datadir": datadir.as_posix(),
        "port": port,
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


def provision(metadata: dict, port: int) -> None:
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
    query(metadata, "\n".join(statements), port)


def ascii_path(path: Path) -> Path | None:
    """Return the path when it is pure ASCII, else None.

    MySQL on Windows converts command-line arguments through the ANSI codepage;
    an absolute path containing CJK characters is truncated (observed as
    ``D:\\``), so such paths must never appear on the mysqld command line.
    """
    try:
        str(path).encode("ascii")
    except UnicodeEncodeError:
        return None
    return path


def restrict(path: Path) -> None:
    """Best-effort owner-only permissions for files that contain secrets."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def client_option_file(text: str) -> tuple[str, list[Path]]:
    """Write a mysql client option file; prefer an absolute ASCII path.

    Returns the ``--defaults-file`` argument and the files to delete afterwards.
    An absolute ASCII path avoids both Windows ANSI truncation and any ambiguity
    about how a relative option-file name is resolved.
    """
    name = "volunteer-client-" + secrets.token_hex(8) + ".cnf"
    location = ascii_path(Path(tempfile.gettempdir()) / name)
    if location is not None:
        try:
            location.write_text(text, encoding="utf-8")
            restrict(location)
            return str(location), [location]
        except OSError:
            pass
    fallback = confined(STATE / name)
    fallback.write_text(text, encoding="utf-8")
    restrict(fallback)
    return fallback.name, [fallback]


def prepare_init_file(root_secret: str) -> tuple[str, list[Path]]:
    """Write the SQL that (re)sets the root credential on every startup.

    Returns the ``--init-file`` argument plus files to clean up afterwards.
    MySQL may resolve a relative init-file name against the data directory
    rather than the process working directory, and absolute CJK paths are
    truncated on Windows. Prefer a short absolute ASCII path in the system temp
    directory; if that path is not ASCII, write the file under both the state
    and data directories and pass the bare ASCII name so either resolution
    finds it.
    """
    statements = "\n".join([
        f"ALTER USER 'root'@'localhost' IDENTIFIED BY '{root_secret}';",
        f"CREATE USER IF NOT EXISTS 'root'@'127.0.0.1' IDENTIFIED BY '{root_secret}';",
        f"ALTER USER 'root'@'127.0.0.1' IDENTIFIED BY '{root_secret}';",
        "GRANT ALL PRIVILEGES ON *.* TO 'root'@'127.0.0.1' WITH GRANT OPTION;",
    ]) + "\n"
    location = ascii_path(Path(tempfile.gettempdir()) /
                          ("volunteer-bootstrap-" + secrets.token_hex(6) + ".sql"))
    if location is not None:
        try:
            location.write_text(statements, encoding="ascii")
            restrict(location)
            return str(location), [location]
        except OSError:
            pass
    cleanup: list[Path] = []
    for candidate in (STATE / "bootstrap.sql", DATA / "bootstrap.sql"):
        candidate.parent.mkdir(parents=True, exist_ok=True)
        candidate.write_text(statements, encoding="ascii")
        restrict(candidate)
        cleanup.append(candidate)
    return "bootstrap.sql", cleanup


def start(mysql_bin: str | None, port_override: int | None) -> None:
    STATE.mkdir(parents=True, exist_ok=True)
    # The runtime data directory is private runtime data, never source material.
    confined(STATE / ".gitignore").write_text("*\n!.gitignore\n", encoding="ascii")
    has_metadata = (STATE / "server.json").is_file()
    metadata = read_json("server.json") if has_metadata else None
    port = resolve_port(port_override, metadata)
    if metadata is not None:
        old_port = metadata.get("port")
        if (old_port and int(old_port) != port and occupied(int(old_port))):
            old_pid = verified_server(metadata, int(old_port))
            raise LocalMySQLError(
                f"私用 MySQL 已在端口 {old_port} 运行（PID {old_pid}）。"
                f"如需改用端口 {port}，请先执行 python scripts/local_mysql.py stop 停止旧实例。")
    if occupied(port):
        if metadata is None:
            raise LocalMySQLError(
                f"端口 {port} 已被其他程序占用，无法启动私用 MySQL。"
                "可设置环境变量 VOLUNTEER_DB_PORT=<其他端口> 或加 --port <其他端口> 后重试。")
        try:
            pid = verified_server(metadata, port)
        except LocalMySQLError:
            raise LocalMySQLError(
                f"端口 {port} 已被其他程序占用（不是本项目的私用 MySQL），不会覆盖它。"
                "可设置环境变量 VOLUNTEER_DB_PORT=<其他端口> 或加 --port <其他端口> 后重试。") from None
        print(f"Private MySQL already running: {HOST}:{port}, PID {pid}, version {metadata['version']}.")
        return
    if metadata is not None:
        bin_directory, version = resolve_existing_bin(metadata, mysql_bin)
        metadata = read_json("server.json")
        if metadata.get("port") != port:
            metadata["port"] = port
            write_json("server.json", metadata)
            # Keep the application credentials in sync with a changed port.
            for name in ("admin.json", "runtime.json"):
                try:
                    entry = read_json(name)
                except LocalMySQLError:
                    continue
                if entry.get("port") != port:
                    entry["port"] = port
                    write_json(name, entry)
            print(f"私用 MySQL 端口已改为 {port}，数据目录保持不变。", flush=True)
    else:
        if DATA.exists() and any(DATA.iterdir()):
            raise LocalMySQLError("Unrecognized nonempty data directory; refusing to initialize.")
        bin_directory, version = locate_bin(mysql_bin)
        metadata = {"bin": str(bin_directory), "version": version, "host": HOST, "port": port,
                    "datadir": str(DATA), "initialized": False}
        write_json("server.json", metadata)
        write_json("admin.json", {"host": HOST, "port": port, "user": "root",
                                  "password": secrets.token_hex(32), "database": "volunteer_core"})
        write_json("runtime.json", {"host": HOST, "port": port, "user": "volunteer_app",
                                    "password": secrets.token_hex(32), "database": "volunteer_core"})
    server = executable(bin_directory, "mysqld")
    config = confined(STATE / "my.cnf")
    # Windows MySQL reads option files in the system ANSI codepage; Python's
    # "mbcs" codec maps to exactly that codepage. If the codepage cannot even
    # represent the project path, explain the fix instead of raising a bare
    # UnicodeEncodeError.
    try:
        config.write_text(config_text(bin_directory, version, port, DATA),
                          encoding="mbcs" if os.name == "nt" else "utf-8")
    except UnicodeEncodeError:
        raise LocalMySQLError(
            "当前 Windows 系统 ANSI 编码无法表示项目路径中的非英文字符，私用 MySQL 读不到配置。"
            "请把项目移动到纯英文（ASCII）路径，或在“区域设置”中启用 UTF-8 支持后重试。") from None
    if not metadata.get("initialized"):
        if not DATA.exists():
            DATA.mkdir()
        result = subprocess.run([str(server), f"--defaults-file={config.name}", "--initialize-insecure"],
                                capture_output=True, timeout=120, creationflags=HIDDEN, cwd=STATE)
        if result.returncode:
            confined(STATE / "initialize.log").write_bytes(result.stdout + result.stderr)
            raise LocalMySQLError("Private data initialization failed. Review .work/mysql-core/mysql-error.log.")
        metadata["initialized"] = True
        write_json("server.json", metadata)
    admin = read_json("admin.json")
    # Every startup sets the same secret before accepting connections. This also
    # safely recovers an interrupted first startup with an initialized data dir.
    init_argument, init_cleanup = prepare_init_file(admin["password"])
    output = confined(STATE / "console.log")
    try:
        with output.open("ab") as log:
            process = subprocess.Popen([str(server), f"--defaults-file={config.name}",
                                        f"--init-file={init_argument}"],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       creationflags=HIDDEN | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
                                       close_fds=True, cwd=STATE)
        metadata["pid"] = process.pid
        write_json("server.json", metadata)
        deadline = time.monotonic() + 70
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise LocalMySQLError("Private server exited. Review .work/mysql-core/mysql-error.log.")
            if occupied(port):
                try:
                    pid = verified_server(metadata, port)
                    provision(metadata, port)
                    print(f"Private MySQL running: {HOST}:{port}, PID {pid}, version {version}.")
                    print("Application credentials saved in .work/mysql-core/runtime.json (password not displayed).")
                    return
                except LocalMySQLError:
                    pass
            time.sleep(0.4)
        raise LocalMySQLError(
            f"Private server startup timed out on port {port}; inspect its error log and run status. "
            "If the port was busy before, set VOLUNTEER_DB_PORT or pass --port with a free port.")
    finally:
        for path in init_cleanup:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass


def status(port_override: int | None) -> None:
    metadata = read_json("server.json") if (STATE / "server.json").is_file() else None
    port = resolve_port(port_override, metadata)
    if not occupied(port):
        print(f"Private MySQL is stopped (port {port}).")
        return
    if metadata is None:
        raise LocalMySQLError(
            f"端口 {port} 上运行的不是本项目的私用 MySQL；不会连接或停止它。"
            "可设置 VOLUNTEER_DB_PORT 或加 --port 指定私用实例端口。")
    pid = verified_server(metadata, port)
    print(f"Private MySQL running: {HOST}:{port}, PID {pid}, version {metadata['version']}.")


def stop(port_override: int | None) -> None:
    metadata = read_json("server.json") if (STATE / "server.json").is_file() else None
    port = resolve_port(port_override, metadata)
    if not occupied(port):
        print("Private MySQL is already stopped.")
        return
    if metadata is None:
        raise LocalMySQLError(
            f"端口 {port} 上运行的不是本项目的私用 MySQL；不会停止它。"
            "可设置 VOLUNTEER_DB_PORT 或加 --port 指定私用实例端口。")
    pid = verified_server(metadata, port)
    result = client_command(metadata, "mysqladmin", port=port)
    if result.returncode:
        raise LocalMySQLError("Graceful shutdown failed; no process was forcibly terminated.")
    for _ in range(100):
        if not occupied(port):
            print(f"Private MySQL stopped gracefully (PID {pid}).")
            return
        time.sleep(0.1)
    raise LocalMySQLError("Shutdown requested; listener is still present. No process was forcibly terminated.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--mysql-bin",
                        help="MySQL bin directory; applies to first initialization and to "
                             "re-locating a vanished cached path")
    parser.add_argument("--port", type=int,
                        help="private MySQL TCP port (default 3308 or the VOLUNTEER_DB_PORT variable)")
    args = parser.parse_args()
    try:
        if args.action == "start":
            start(args.mysql_bin, args.port)
        elif args.action == "stop":
            stop(args.port)
        else:
            status(args.port)
    except (LocalMySQLError, OSError, ValueError, subprocess.TimeoutExpired) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
