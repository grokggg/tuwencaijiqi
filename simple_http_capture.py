#!/usr/bin/env python3
"""
simple_http_capture.py — 本地手机网络请求调试工具

功能：
  1. 使用 mitmproxy 在本地启动 HTTPS 代理服务器
  2. 在后台线程中启动证书下载服务，并生成二维码方便手机安装证书
  3. 实时打印所有 HTTP/HTTPS 请求的完整 URL 和 Request Headers

依赖安装：
  pip install mitmproxy "qrcode[pil]"

使用方法：
  python simple_http_capture.py
  python simple_http_capture.py --port 8888

手机配置步骤：
  1. 确保手机和电脑在同一 Wi-Fi 下
  2. 手机 Wi-Fi 设置中配置代理（主机和端口见控制台输出）
  3. 用手机扫描控制台中的二维码，下载并安装根证书
  4. iOS 需在「设置 -> 通用 -> 关于本机 -> 证书信任设置」中启用信任
  5. Android 需在「设置 -> 安全 -> 从存储设备安装」中选择下载的证书
"""

import argparse
import asyncio
import socket
import sys
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional

# ── 第三方库导入 ──
#    如果报 ModuleNotFoundError，请执行：pip install mitmproxy "qrcode[pil]"
from mitmproxy import options, http
from mitmproxy.tools.dump import DumpMaster
import qrcode


# ================================================================
#  第一部分：请求记录器（mitmproxy Addon）
# ================================================================

class RequestLogger:
    """
    mitmproxy 插件。

    当每个 HTTP/HTTPS 请求到达代理时，mitmproxy 会调用 request() 方法。
    我们在这里提取 URL 和 Headers 并格式化打印到控制台。

    对于 HTTPS 请求，mitmproxy 会先完成 TLS 拦截（中间人握手），
    然后才将解密后的请求传给此方法，因此 pretty_url 会显示完整的 https:// URL。
    """

    def __init__(self) -> None:
        self._count: int = 0

    def request(self, flow: http.HTTPFlow) -> None:
        """每个请求触发时由 mitmproxy 调用。"""
        if flow.request is None:
            return

        self._count += 1
        req = flow.request
        ts = time.strftime("%H:%M:%S")

        # ── 格式化输出 ──
        print(f"\n+{'-' * 78}+")
        print(f"| #{self._count:<6}  [{ts}]  {req.method}")
        print(f"| URL: {req.pretty_url}")
        print(f"+{'-' * 78}+")
        print(f"| Headers:")
        for key, value in req.headers.items():
            # 截断过长的 header 值，保持控制台整洁
            display_val = value if len(value) <= 200 else value[:197] + "..."
            print(f"|   {key}: {display_val}")
        print(f"+{'-' * 78}+")
        sys.stdout.flush()


# ================================================================
#  第二部分：工具函数
# ================================================================

def get_local_ip() -> str:
    """
    获取本机在局域网中的 IP 地址。

    原理：创建一个 UDP socket 并"连接"到一个公网地址，
    操作系统会自动选择合适的网卡，从而获取本机的局域网 IP。
    实际上不会发送任何数据包。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        ip = sock.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        sock.close()
    return ip


def get_mitmproxy_cert_dir() -> Path:
    """返回 mitmproxy 默认的 CA 证书存放目录（~/.mitmproxy/）。"""
    return Path.home() / ".mitmproxy"


def wait_for_certificate(cert_dir: Path, timeout: float = 15.0) -> Optional[Path]:
    """
    等待 mitmproxy 生成 CA 根证书。

    mitmproxy 首次启动时会自动在 ~/.mitmproxy/ 目录下生成：
      - mitmproxy-ca-cert.pem   (PEM 格式证书，适用于 iOS)
      - mitmproxy-ca-cert.cer   (DER 格式证书，适用于 Android)
      - mitmproxy-ca.pem         (PEM 格式私钥+证书，请勿泄露)

    返回证书文件路径，超时则返回 None。
    """
    cert_file = cert_dir / "mitmproxy-ca-cert.pem"
    deadline = time.time() + timeout
    while not cert_file.exists():
        if time.time() > deadline:
            return None
        time.sleep(0.3)
    return cert_file


# ================================================================
#  第三部分：证书下载服务（后台线程）
# ================================================================

def _make_cert_handler(cert_dir: Path):
    """
    创建一个只允许下载 CA 证书文件的 HTTP 请求处理器工厂。

    出于安全考虑，不暴露整个 ~/.mitmproxy/ 目录（其中包含私钥），
    只允许访问证书文件本身。
    """

    class CertDownloadHandler(BaseHTTPRequestHandler):
        # URL 路径 -> (文件名, Content-Type) 映射
        _FILES = {
            "/":          ("mitmproxy-ca-cert.pem", "application/x-pem-file"),
            "/cert.pem":  ("mitmproxy-ca-cert.pem", "application/x-pem-file"),
            "/cert.cer":  ("mitmproxy-ca-cert.cer", "application/x-x509-ca-cert"),
        }

        def do_GET(self) -> None:
            entry = self._FILES.get(self.path)
            if entry is None:
                self.send_error(404, "Not Found")
                return

            filename, content_type = entry
            filepath = cert_dir / filename
            if not filepath.exists():
                self.send_error(404, "Certificate not found")
                return

            data = filepath.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header(
                "Content-Disposition",
                f'attachment; filename="{filename}"',
            )
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args) -> None:
            """静默证书服务器的请求日志，避免干扰主输出。"""
            pass

    return CertDownloadHandler


def start_cert_server_and_qr(
    local_ip: str,
    proxy_port: int,
    cert_port: int,
    ready_event: threading.Event,
) -> None:
    """
    后台线程入口：
      1. 等待 mitmproxy 生成 CA 证书
      2. 在控制台打印二维码和连接说明
      3. 启动 HTTP 服务，供手机下载证书

    参数:
      local_ip     本机局域网 IP
      proxy_port   代理服务器端口
      cert_port    证书下载服务端口
      ready_event  通知主线程证书服务已就绪的事件
    """
    cert_dir = get_mitmproxy_cert_dir()
    cert_file = wait_for_certificate(cert_dir)

    if cert_file is None:
        print("\n[警告] 未能找到 mitmproxy 根证书。")
        print("       请手动检查 ~/.mitmproxy/ 目录是否存在 mitmproxy-ca-cert.pem")
        ready_event.set()
        return

    cert_url = f"http://{local_ip}:{cert_port}/cert.pem"
    proxy_addr = f"{local_ip}:{proxy_port}"

    # ── 打印连接信息 ──
    print("\n" + "=" * 60)
    print("  [OK] 代理服务器已就绪")
    print(f"  代理地址 : {proxy_addr}")
    print(f"  证书下载 : {cert_url}")
    print("=" * 60)

    # ── 生成并打印二维码 ──
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=1,
        border=1,
    )
    qr.add_data(cert_url)
    qr.make(fit=True)

    print("\n  扫描以下二维码下载根证书（或手动访问上方链接）：\n")
    qr.print_ascii(invert=True)

    print(f"""
  ── 手机配置步骤 ──────────────────────────────────────
  1. 确保手机和电脑在同一 Wi-Fi 网络

  2. 手机 Wi-Fi -> 修改网络 -> 代理 -> 手动
       主机: {local_ip}
       端口: {proxy_port}

  3. 用手机浏览器访问以下地址下载证书:
       {cert_url}
       (Android 用户也可访问 /cert.cer 获取 DER 格式证书)

  4. iOS 安装证书:
       设置 -> 已下载描述文件 -> 安装
       设置 -> 通用 -> 关于本机 -> 证书信任设置 -> 启用

  5. Android 安装证书:
       设置 -> 安全 -> 加密与凭据 -> 安装证书 -> CA 证书
  ─────────────────────────────────────────────────────
""")
    print("=" * 60)
    print("  等待手机请求...\n")
    sys.stdout.flush()

    # ── 启动证书下载 HTTP 服务 ──
    handler_cls = _make_cert_handler(cert_dir)
    httpd = HTTPServer(("0.0.0.0", cert_port), handler_cls)
    ready_event.set()

    try:
        httpd.serve_forever()
    except Exception as e:
        print(f"\n[证书服务错误] {e}")


# ================================================================
#  第四部分：mitmproxy 代理服务器
# ================================================================

async def run_mitmproxy(host: str, port: int) -> None:
    """
    启动 mitmproxy 代理服务器（主协程）。

    使用 DumpMaster 但关闭自带的终端日志和 dumper，
    仅保留我们的 RequestLogger 插件输出。

    参数:
      host  监听地址
      port  监听端口
    """
    opts = options.Options(
        listen_host=host,
        listen_port=port,
    )

    master = DumpMaster(
        opts,
        with_termlog=False,   # 关闭 mitmproxy 自带的终端彩色日志
        with_dumper=False,    # 关闭自带的请求/响应 dumper
    )

    # 注册我们的请求记录插件
    master.addons.add(RequestLogger())

    print(f"\n  [mitmproxy] 监听 {host}:{port} ...")
    sys.stdout.flush()

    # 运行直到用户按 Ctrl+C
    await master.run()


# ================================================================
#  第五部分：程序入口
# ================================================================

def main() -> None:
    """解析命令行参数，启动后台线程和代理服务器。"""
    parser = argparse.ArgumentParser(
        description="本地手机网络请求调试工具 — 实时打印 URL 和 Headers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python simple_http_capture.py
  python simple_http_capture.py --port 8888
  python simple_http_capture.py --host 0.0.0.0 --port 8080 --cert-port 8081

依赖:
  pip install mitmproxy "qrcode[pil]"
        """,
    )
    parser.add_argument(
        "--host", default="0.0.0.0",
        help="代理监听地址（默认 0.0.0.0，允许局域网内手机连接）",
    )
    parser.add_argument(
        "--port", type=int, default=8080,
        help="代理监听端口（默认 8080）",
    )
    parser.add_argument(
        "--cert-port", type=int, default=8081,
        help="证书下载服务端口（默认 8081）",
    )
    args = parser.parse_args()

    local_ip = get_local_ip()

    # ── 打印启动横幅 ──
    print("\n" + "=" * 60)
    print("  simple_http_capture — 手机网络请求调试工具")
    print("=" * 60)
    print(f"  本机 IP   : {local_ip}")
    print(f"  代理端口   : {args.port}")
    print(f"  证书端口   : {args.cert_port}")

    # ── 启动后台线程：证书服务 + 二维码 ──
    #    daemon=True 表示主线程退出时自动结束
    ready_event = threading.Event()
    cert_thread = threading.Thread(
        target=start_cert_server_and_qr,
        args=(local_ip, args.port, args.cert_port, ready_event),
        daemon=True,
        name="cert-server",
    )
    cert_thread.start()

    # ── 等待证书线程完成二维码和说明的打印 ──
    #    避免代理启动信息与二维码输出交错
    ready_event.wait(timeout=20.0)

    # ── 启动 mitmproxy 代理（主线程 asyncio 事件循环）──
    try:
        asyncio.run(run_mitmproxy(args.host, args.port))
    except OSError as e:
        # 端口被占用时的友好提示
        if "Address already in use" in str(e) or "98" in str(e):
            print(f"\n  [错误] 端口 {args.port} 已被占用，请尝试其他端口:")
            print(f"         python simple_http_capture.py --port {args.port + 1}")
        else:
            raise
    except KeyboardInterrupt:
        print("\n\n  [退出] 代理服务器已停止，再见！\n")
        sys.exit(0)


if __name__ == "__main__":
    main()
