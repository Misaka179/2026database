"""Launch the local workbench without relying on PowerShell script policies."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
from urllib.error import URLError
from urllib.request import HTTPRedirectHandler, ProxyHandler, build_opener


CORE = Path(__file__).resolve().parent
HOST = '127.0.0.1'
PORT = 8765
HOME_URL = f'http://{HOST}:{PORT}/'
APP_TITLE = '图书馆志愿服务管理核心 API'


class StartupError(RuntimeError):
    pass


class LocalOnlyRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        return None


def existing_application() -> bool:
    """Recognize our application, but never stop or replace another listener."""
    try:
        # Windows can take roughly two seconds to report WSAECONNREFUSED
        # for a closed loopback port. A 0.5 s probe misclassifies normal startup.
        with socket.create_connection((HOST, PORT), timeout=3):
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
                probe.bind((HOST, PORT))
        except OSError as bind_error:
            raise StartupError(f'本机 {PORT} 端口连接超时且无法绑定：{bind_error}。'
                               '请检查是否已有程序占用该端口或本机访问受到限制。') from exc
        return False
    except OSError as exc:
        raise StartupError(f'无法访问本机 {HOST}:{PORT}：{exc}。'
                           '请检查 Python 的本机网络访问权限；此错误不表示需要联网。') from exc
    try:
        opener = build_opener(ProxyHandler({}), LocalOnlyRedirectHandler())
        with opener.open(HOME_URL + 'openapi.json', timeout=2) as response:
            schema = json.loads(response.read(2 * 1024 * 1024).decode('utf-8'))
        if (isinstance(schema, dict)
                and schema.get('info', {}).get('title') == APP_TITLE
                and all(path in schema.get('paths', {})
                        for path in ('/auth/login', '/schedules', '/health'))):
            return True
    except (URLError, OSError, ValueError, AttributeError, TypeError):
        pass
    raise StartupError(f'本机 {PORT} 端口已被其他程序占用，或已有服务尚未就绪。'
                       '请先检查占用情况，再重新运行启动器。')


def run_step(label: str, arguments: list[str]) -> None:
    print(label, flush=True)
    environment = os.environ.copy()
    environment['PYTHONIOENCODING'] = 'utf-8'
    environment['PYTHONUTF8'] = '1'
    result = subprocess.run([sys.executable, *arguments], cwd=CORE,
                            env=environment, check=False)
    if result.returncode:
        raise StartupError(f'此步骤未完成，退出码为 {result.returncode}。请查看上方错误信息。')


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(
        description='启动图书馆志愿服务管理系统。保留已有数据库，无需修改 PowerShell 执行策略。',
        add_help=False,
    )
    parser.add_argument('-h', '--help', action='help', help='显示帮助信息并退出，不启动服务')
    parser.add_argument('--mysql-bin', metavar='目录', help='首次初始化时指定 MySQL 的 bin 目录')
    args = parser.parse_args(argv)
    try:
        if sys.version_info < (3, 10):
            raise StartupError('请使用 Python 3.10 或更新版本运行本系统。')
        missing = [name for name in ('fastapi', 'uvicorn', 'cryptography')
                   if importlib.util.find_spec(name) is None]
        if missing:
            raise StartupError('当前 Python 缺少运行依赖，请在 core 目录执行：'
                               'python -m pip install -r requirements.txt')
        # Check before touching the database, then recheck after initialization
        # in case another launcher has started the application in the meantime.
        existing_application()
        mysql_arguments = [str(CORE / 'scripts' / 'local_mysql.py'), 'start']
        if args.mysql_bin:
            mysql_arguments.extend(['--mysql-bin', args.mysql_bin])
        run_step('【1/3】启动或检查本项目的独立 MySQL 数据库。', mysql_arguments)
        run_step('【2/3】检查数据表及演示账号，保留已有业务数据。', ['-m', 'app.bootstrap'])
        if existing_application():
            print(f'本系统已经运行，请打开：{HOME_URL}', flush=True)
            print(f'中文接口文档：{HOME_URL}docs', flush=True)
            return 0
        print(f'中文工作台：{HOME_URL}', flush=True)
        print(f'中文接口文档：{HOME_URL}docs', flush=True)
        print('请保持此窗口打开；使用结束后按 Ctrl+C 停止网页服务。', flush=True)
        run_step('【3/3】启动网页服务。',
                 ['-m', 'uvicorn', 'app.api:app', '--host', HOST, '--port', str(PORT)])
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
