#!/usr/bin/env python3
"""
simple_api_tester.py — 通用 HTTP API 测试工具

功能：
  1. 接受 URL 和 JSON 格式的 Headers 作为命令行参数
  2. 使用 curl_cffi 库伪装成 Chrome 浏览器发送 GET 请求
  3. 打印 HTTP 响应码和响应体

依赖安装：
  pip install curl_cffi

使用示例：
  python simple_api_tester.py --url "https://www.example.com/api/data" --headers '{"Authorization": "Bearer test"}'
  python simple_api_tester.py -u "https://httpbin.org/get" -H '{"X-Custom": "value"}' -v
  python simple_api_tester.py -u "https://httpbin.org/get"  # 不带 headers
"""

import argparse
import json
import logging
import sys
import time
import traceback
from typing import Any, Dict, Optional, Tuple

# ── 第三方库导入 ──
#    如果报 ModuleNotFoundError，请执行：pip install curl_cffi
from curl_cffi import requests as cffi_requests
from curl_cffi.requests.exceptions import (
    RequestException,    # 所有请求异常的基类
    ConnectionError,     # 连接异常
    Timeout,             # 超时异常
    HTTPError,           # HTTP 协议异常
    SSLError,            # SSL/TLS 异常
)


# ================================================================
#  日志配置
# ================================================================

def setup_logger(verbose: bool = False) -> logging.Logger:
    """
    配置并返回一个 Logger 实例。

    参数:
      verbose  若为 True，输出 DEBUG 级别日志（含请求/响应详情）；
               若为 False，仅输出 INFO 及以上级别日志。
    """
    logger = logging.getLogger("simple_api_tester")
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)

    # 避免重复添加 handler
    if logger.handlers:
        logger.handlers.clear()

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)

    # 日志格式：时间 | 级别 | 消息
    fmt = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-7s | %(message)s",
        datefmt="%H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)

    return logger


# ================================================================
#  参数解析
# ================================================================

def parse_headers(headers_json: str, logger: logging.Logger) -> Dict[str, str]:
    """
    将 JSON 字符串解析为 Headers 字典。

    参数:
      headers_json  JSON 格式的字符串，如 '{"Authorization": "Bearer xxx"}'
      logger        日志记录器

    返回:
      Headers 字典

    异常:
      json.JSONDecodeError  JSON 格式错误时抛出，由调用方处理
    """
    if not headers_json:
        return {}

    try:
        parsed = json.loads(headers_json)
    except json.JSONDecodeError as e:
        logger.error(f"Headers JSON 解析失败: {e}")
        logger.error(f"  输入值: {headers_json}")
        raise

    # 确保所有 key 和 value 都是字符串
    if not isinstance(parsed, dict):
        logger.error(f"Headers JSON 必须是一个对象（字典），但得到了: {type(parsed).__name__}")
        raise ValueError(f"Headers 必须是 JSON 对象，得到的是 {type(parsed).__name__}")

    result: Dict[str, str] = {}
    for key, value in parsed.items():
        result[str(key)] = str(value)

    logger.debug(f"解析得到 {len(result)} 个 Header:")
    for k, v in result.items():
        # 日志中截断过长的 header 值
        display = v if len(v) <= 80 else v[:77] + "..."
        logger.debug(f"  {k}: {display}")

    return result


# ================================================================
#  核心请求逻辑
# ================================================================

def send_request(
    url: str,
    headers: Dict[str, str],
    logger: logging.Logger,
    timeout: int = 30,
) -> Tuple[Optional[int], Optional[str], Optional[str]]:
    """
    使用 curl_cffi 伪装成 Chrome 浏览器发送 GET 请求。

    参数:
      url      目标 URL
      headers  请求头字典
      logger   日志记录器
      timeout  超时时间（秒），默认 30

    返回:
      (status_code, response_body, error_message)
      - 成功时 error_message 为 None
      - 失败时 status_code 和 response_body 可能为 None
    """
    logger.info(f"发送 GET 请求 -> {url}")
    logger.debug(f"伪装浏览器: Chrome")
    logger.debug(f"超时设置: {timeout}s")

    try:
        # ── 使用 curl_cffi 发送请求 ──
        #    impersonate="chrome" 会自动设置 TLS 指纹和 JA3 哈希，
        #    使请求在服务器端看起来像真实的 Chrome 浏览器。
        response = cffi_requests.get(
            url,
            headers=headers if headers else None,
            impersonate="chrome",
            timeout=timeout,
            allow_redirects=True,
        )

    except RequestException as e:
        # ── curl_cffi 请求异常（基类，涵盖连接、超时、SSL 等）──
        logger.error(f"请求失败（RequestException）: {type(e).__name__}: {e}")
        logger.debug(traceback.format_exc())
        return None, None, f"{type(e).__name__}: {e}"

    except ConnectionError as e:
        # ── 连接异常（DNS 解析失败、拒绝连接等）──
        logger.error(f"连接失败: {e}")
        logger.debug(traceback.format_exc())
        return None, None, f"ConnectionError: {e}"

    except Timeout as e:
        # ── 请求超时 ──
        logger.error(f"请求超时（{timeout}s）: {e}")
        return None, None, f"Timeout after {timeout}s"

    except SSLError as e:
        # ── SSL/TLS 证书异常 ──
        logger.error(f"SSL 异常: {e}")
        logger.debug(traceback.format_exc())
        return None, None, f"SSLError: {e}"

    except Exception as e:
        # ── 其他未预期的异常 ──
        logger.error(f"未预期的异常: {type(e).__name__}: {e}")
        logger.debug(traceback.format_exc())
        return None, None, str(e)

    # ── 提取响应信息 ──
    status_code = response.status_code
    logger.info(f"响应状态码: {status_code}")

    # 尝试以 UTF-8 解码响应体
    try:
        body = response.text
    except UnicodeDecodeError:
        logger.warning("响应体无法以 UTF-8 解码，尝试用 errors='replace' 模式解码")
        body = response.content.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning(f"读取响应体时出错: {e}")
        body = response.content.decode("utf-8", errors="replace")

    # DEBUG 模式下打印响应头
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("响应头:")
        for k, v in response.headers.items():
            display = v if len(v) <= 80 else v[:77] + "..."
            logger.debug(f"  {k}: {display}")

    return status_code, body, None


# ================================================================
#  结果输出
# ================================================================

def print_result(
    status_code: Optional[int],
    body: Optional[str],
    error: Optional[str],
    verbose: bool,
) -> None:
    """
    格式化打印请求结果。

    参数:
      status_code  HTTP 状态码（失败时为 None）
      body         响应体（失败时为 None）
      error        错误信息（成功时为 None）
      verbose      是否输出响应体
    """
    print("\n" + "=" * 60)

    if error is not None:
        # ── 请求失败 ──
        print("  结果: 失败")
        print(f"  错误: {error}")
        print("=" * 60)
        return

    # ── 请求成功 ──
    print(f"  状态码: {status_code}")

    # 根据 status code 给出简要提示
    if status_code is not None:
        if 200 <= status_code < 300:
            print(f"  状态: 成功 (2xx)")
        elif 300 <= status_code < 400:
            print(f"  状态: 重定向 (3xx)")
        elif 400 <= status_code < 500:
            print(f"  状态: 客户端错误 (4xx)")
        elif 500 <= status_code < 600:
            print(f"  状态: 服务器错误 (5xx)")
        else:
            print(f"  状态: 未知")

    print("=" * 60)

    # 响应体输出
    if body is not None:
        if verbose:
            print("\n── 响应体 ──────────────────────────────────────\n")
            print(body)
            print("\n── 响应体结束 ──────────────────────────────────")
        else:
            # 非 verbose 模式下截断过长的响应体
            max_len = 500
            if len(body) <= max_len:
                print(f"\n响应体:\n{body}")
            else:
                print(f"\n响应体 (前 {max_len} 字符，使用 -v 查看完整内容):")
                print(body[:max_len] + "...")
    else:
        print("\n响应体: (空)")


# ================================================================
#  程序入口
# ================================================================

def main() -> int:
    """
    主函数：解析参数、发送请求、打印结果。

    返回值:
      0  请求成功（HTTP 2xx）
      1  请求成功但 HTTP 非 2xx
      2  请求失败（网络异常等）
      3  参数错误
    """
    parser = argparse.ArgumentParser(
        description="通用 HTTP API 测试工具 — 使用 curl_cffi 伪装 Chrome 发送 GET 请求",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 基本用法
  python simple_api_tester.py -u "https://httpbin.org/get"

  # 带 Headers
  python simple_api_tester.py -u "https://api.example.com/data" -H '{"Authorization": "Bearer test"}'

  # 详细模式（打印完整响应体和响应头）
  python simple_api_tester.py -u "https://httpbin.org/get" -v

  # 设置超时
  python simple_api_tester.py -u "https://slow-api.example.com" --timeout 60

依赖:
  pip install curl_cffi
        """,
    )
    parser.add_argument(
        "-u", "--url",
        required=True,
        help="目标 API URL（必须包含 http:// 或 https://）",
    )
    parser.add_argument(
        "-H", "--headers",
        default="",
        help='JSON 格式的请求头，如 \'{"Authorization": "Bearer test"}\'',
    )
    parser.add_argument(
        "-t", "--timeout",
        type=int,
        default=30,
        help="请求超时时间（秒，默认 30）",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="详细模式：打印完整响应体、响应头和调试日志",
    )
    args = parser.parse_args()

    # ── 初始化日志 ──
    logger = setup_logger(verbose=args.verbose)

    logger.info("=" * 60)
    logger.info("simple_api_tester — 通用 API 测试工具")
    logger.info("=" * 60)

    # ── 验证 URL ──
    url: str = args.url.strip()
    if not url:
        logger.error("URL 不能为空")
        return 3
    if not url.startswith(("http://", "https://")):
        logger.error(f"URL 必须以 http:// 或 https:// 开头，得到: {url}")
        return 3
    logger.debug(f"目标 URL: {url}")

    # ── 解析 Headers ──
    try:
        headers = parse_headers(args.headers, logger)
    except (json.JSONDecodeError, ValueError):
        return 3

    # ── 发送请求 ──
    start_time = time.time()
    status_code, body, error = send_request(url, headers, logger, timeout=args.timeout)
    elapsed = time.time() - start_time

    logger.info(f"耗时: {elapsed:.3f}s")

    # ── 打印结果 ──
    print_result(status_code, body, error, args.verbose)

    # ── 返回退出码 ──
    if error is not None:
        return 2
    if status_code is not None and 200 <= status_code < 300:
        return 0
    return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n\n[中断] 用户取消了操作\n")
        sys.exit(130)
    except Exception as e:
        print(f"\n[致命错误] {type(e).__name__}: {e}")
        traceback.print_exc()
        sys.exit(1)
