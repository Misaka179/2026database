"""Launch the local workbench without relying on PowerShell script policies.

Portable launcher: when the Python that started it is too old or lacks the
runtime dependencies (for example a PATH-wide Python without FastAPI), the
project's bundled environment is located and this script re-runs itself with
that interpreter. Set VOLUNTEER_PYTHON to force a specific interpreter.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


CORE = Path(__file__).resolve().parent
HOST = '127.0.0.1'
PORT = 8765
DEFAULT_DB_PORT = 3308
APP_TITLE = '图书馆志愿服务管理核心 API'
MIN_VERSION = (3, 10)
REQUIRED_MODULES = ('fastapi', 'uvicorn', 'pymysql', 'cryptography', 'openpyxl', 'PIL')
REEXEC_FLAG = 'VOLUNTEER_LAUNCHER_REEXEC'


class StartupError(RuntimeError):
    pass


class LocalOnlyRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


# ---------------------------------------------------------------- interpreter --
def environment_python(environment: Path) -> Path | None:
    """Return the Python executable inside a virtual/conda environment directory."""
    if not environment.is_dir():
        return None
    candidates = [environment / 'python.exe', environment / 'Scripts' / 'python.exe'] if os.name == 'nt' else []
    candidates += [environment / 'bin' / 'python', environment / 'bin' / 'python3']
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def python_from_override(value: str) -> Path | None:
    path = Path(value).expanduser()
    if path.is_file():
        return path
    if path.is_dir():
        return environment_python(path)
    found = shutil.which(value)
    return Path(found) if found else None


def bundled_python_candidates() -> list[Path]:
    """Project-bundled interpreters, most specific first."""
    candidates: list[Path] = []
    override = os.environ.get('VOLUNTEER_PYTHON', '').strip()
    if override:
        found = python_from_override(override)
        if found:
            candidates.append(found)
    for environment in (CORE / '.conda' / 'envs' / 'volunteer-core',
                        CORE / '.venv', CORE.parent / '.venv'):
        found = environment_python(environment)
        if found:
            candidates.append(found)
    envs = CORE / '.conda' / 'envs'
    if envs.is_dir():
        for environment in sorted(envs.iterdir()):
            found = environment_python(environment)
            if found:
                candidates.append(found)
    return candidates


PROBE_SCRIPT = (
    'import importlib.util as u, sys\n'
    'if sys.version_info < {minimum!r}: raise SystemExit(3)\n'
    'missing=[m for m in {modules!r} if u.find_spec(m) is None]\n'
    'raise SystemExit(0 if not missing else 4)\n'
).format(minimum=MIN_VERSION, modules=REQUIRED_MODULES)


def interpreter_ready(python: Path) -> bool:
    try:
        result = subprocess.run([str(python), '-c', PROBE_SCRIPT],
                                capture_output=True, text=True, timeout=120,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def current_interpreter_ready() -> bool:
    if sys.version_info < MIN_VERSION:
        return False
    for name in REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(name) is None:
                return False
        except (ImportError, ValueError):
            return False
    return True


def ensure_runtime(arguments: list[str]) -> int | None:
    """Re-run with a project interpreter when the current one is unusable.

    Returns the child exit code when a switch happened, else None.
    """
    if current_interpreter_ready():
        return None
    try:
        current = str(Path(sys.executable).resolve()).lower() if sys.executable else ''
    except OSError:
        current = ''
    tried: set[str] = set()
    for candidate in bundled_python_candidates():
        try:
            key = str(candidate.resolve()).lower()
        except OSError:
            continue
        if key == current or key in tried:
            continue
        tried.add(key)
        if not interpreter_ready(candidate):
            continue
        print(f'当前 Python（{sys.executable}）缺少运行依赖或版本过低，'
              f'已自动切换到项目自带环境：{candidate}', flush=True)
        environment = os.environ.copy()
        environment[REEXEC_FLAG] = '1'
        environment['PYTHONUTF8'] = '1'
        environment['PYTHONIOENCODING'] = 'utf-8'
        result = subprocess.run([str(candidate), '-X', 'utf8',
                                 str(Path(__file__).resolve()), *arguments],
                                cwd=CORE, env=environment, check=False)
        return result.returncode
    install_hint = ('python -m pip install -r requirements.txt')
    if os.environ.get(REEXEC_FLAG) == '1':
        raise StartupError(
            f'项目自带 Python 环境仍缺少运行依赖（需要 {", ".join(REQUIRED_MODULES)}）。'
            f'请在该环境执行：{install_hint}，或用 VOLUNTEER_PYTHON 指定正确的解释器。')
    raise StartupError(
        f'当前 Python 为 {sys.executable}（版本 {sys.version.split()[0]}），缺少运行依赖或版本过低，'
        f'且未找到项目自带环境（2026database/.conda/envs/volunteer-core 或 .venv）。'
        f'请设置环境变量 VOLUNTEER_PYTHON 指向 Python 3.10+ 且已安装依赖的解释器，'
        f'或在该解释器中执行：{install_hint}')


# ---------------------------------------------------------------------- ports --
def valid_port(value: int, source: str) -> int:
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise StartupError(f'{source} 必须是 1—65535 的整数。') from None
    if not 1 <= port <= 65535:
        raise StartupError(f'{source} 必须是 1—65535 的整数。')
    return port


def resolve_api_port(explicit: int | None) -> int:
    """API port precedence: --port, VOLUNTEER_PORT, default 8765."""
    if explicit is not None:
        return valid_port(explicit, '--port')
    raw = os.environ.get('VOLUNTEER_PORT', '').strip()
    if raw:
        try:
            return valid_port(int(raw), '环境变量 VOLUNTEER_PORT')
        except ValueError:
            raise StartupError('环境变量 VOLUNTEER_PORT 必须是 1—65535 的整数。') from None
    return PORT


def home_url(port: int) -> str:
    return f'http://{HOST}:{port}/'


# ------------------------------------------------------------------ listening --
def existing_application(host: str | None = None, port: int | None = None) -> bool:
    """Recognize our application, but never stop or replace another listener."""
    host = host or HOST
    port = port or PORT
    try:
        # Windows can take roughly two seconds to report WSAECONNREFUSED
        # for a closed loopback port. A 0.5 s probe misclassifies normal startup.
        with socket.create_connection((host, port), timeout=3):
            pass
    except ConnectionRefusedError:
        return False
    except TimeoutError as exc:
        # A slow refusal is not evidence of an existing listener. On Windows,
        # exclusive bind safely distinguishes a free port without port sharing.
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                if os.name == 'nt':
                    probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                probe.bind((host, port))
        except OSError as bind_error:
            raise StartupError(f'本机 {port} 端口连接超时且无法绑定：{bind_error}。'
                               '请检查是否已有程序占用该端口或本机访问受到限制。'
                               '要改用其他端口，可设置环境变量 VOLUNTEER_PORT 或运行 '
                               f'python start.py --port <端口>。') from exc
        return False
    except OSError as exc:
        raise StartupError(f'无法访问本机 {host}:{port}：{exc}。'
                           '请检查 Python 的本机网络访问权限；此错误不表示需要联网。') from exc
    try:
        opener = build_opener(ProxyHandler({}), LocalOnlyRedirectHandler())
        with opener.open(home_url(port) + 'openapi.json', timeout=2) as response:
            schema = json.loads(response.read(2 * 1024 * 1024).decode('utf-8'))
        if (isinstance(schema, dict)
                and schema.get('info', {}).get('title') == APP_TITLE
                and all(path in schema.get('paths', {})
                        for path in ('/auth/login', '/schedules', '/health'))):
            return True
    except (URLError, OSError, ValueError, AttributeError, TypeError):
        pass
    raise StartupError(f'本机 {port} 端口已被其他程序占用，或已有服务尚未就绪。'
                       '请先检查占用情况，再重新运行启动器；'
                       '要改用其他端口，可设置环境变量 VOLUNTEER_PORT 或运行 '
                       f'python start.py --port <端口>。')


def run_step(label: str, arguments: list[str]) -> None:
    print(label, flush=True)
    environment = os.environ.copy()
    environment['PYTHONIOENCODING'] = 'utf-8'
    environment['PYTHONUTF8'] = '1'
    result = subprocess.run([sys.executable, *arguments], cwd=CORE,
                            env=environment, check=False)
    if result.returncode:
        raise StartupError(f'此步骤未完成，退出码为 {result.returncode}。请查看上方错误信息。')


def report_running(port: int) -> None:
    print(f'本系统已经运行，无需重复启动。请直接打开：{home_url(port)}', flush=True)
    print(f'中文接口文档：{home_url(port)}docs', flush=True)
    print(f'找回密码（忘记密码）：{home_url(port)}password', flush=True)


def wait_for_close() -> None:
    """Keep a double-clicked console window readable after a short-lived run."""
    try:
        if sys.stdin is not None and sys.stdin.isatty():
            input('按回车键关闭此窗口。')
    except (EOFError, OSError, KeyboardInterrupt):
        pass


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    arguments = list(sys.argv[1:] if argv is None else argv)
    try:
        switched = ensure_runtime(arguments)
        if switched is not None:
            return switched
        parser = argparse.ArgumentParser(
            description='启动图书馆志愿服务管理系统。保留已有数据库，无需修改 PowerShell 执行策略。',
            add_help=False,
        )
        parser.add_argument('-h', '--help', action='help', help='显示帮助信息并退出，不启动服务')
        parser.add_argument('--mysql-bin', metavar='目录', help='首次初始化或缓存的 MySQL 路径失效时，指定 MySQL 的 bin 目录')
        parser.add_argument('--port', type=int, metavar='端口',
                            help='网页服务端口，默认 8765（也可设置 VOLUNTEER_PORT）')
        parser.add_argument('--db-port', type=int, metavar='端口',
                            help=f'私用 MySQL 端口，默认 {DEFAULT_DB_PORT}（也可设置 VOLUNTEER_DB_PORT）')
        args = parser.parse_args(arguments)
        api_port = resolve_api_port(args.port)
        if sys.version_info < MIN_VERSION:
            raise StartupError('请使用 Python 3.10 或更新版本运行本系统。')
        # Check before touching the database, then recheck after initialization
        # in case another launcher has started the application in the meantime.
        if existing_application(HOST, api_port):
            report_running(api_port)
            wait_for_close()
            return 0
        mysql_arguments = [str(CORE / 'scripts' / 'local_mysql.py'), 'start']
        if args.mysql_bin:
            mysql_arguments.extend(['--mysql-bin', args.mysql_bin])
        if args.db_port is not None:
            mysql_arguments.extend(['--port', str(valid_port(args.db_port, '--db-port'))])
        run_step('【1/3】启动或检查本项目的独立 MySQL 数据库。', mysql_arguments)
        run_step('【2/3】检查数据表及演示账号，保留已有业务数据。', ['-m', 'app.bootstrap'])
        if existing_application(HOST, api_port):
            report_running(api_port)
            wait_for_close()
            return 0
        print(f'中文工作台：{home_url(api_port)}', flush=True)
        print(f'中文接口文档：{home_url(api_port)}docs', flush=True)
        print(f'找回密码（忘记密码）：{home_url(api_port)}password', flush=True)
        print('请保持此窗口打开；使用结束后按 Ctrl+C 停止网页服务。', flush=True)
        run_step('【3/3】启动网页服务。',
                 ['-m', 'uvicorn', 'app.api:app', '--host', HOST, '--port', str(api_port)])
        return 0
    except StartupError as exc:
        print(f'启动失败：{exc}', file=sys.stderr, flush=True)
        return 1
    except OSError:
        print('启动失败：无法运行 Python 子进程，请检查安装路径和文件权限。',
              file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print('\n已停止启动器或网页服务，数据库文件会保留。', flush=True)
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
