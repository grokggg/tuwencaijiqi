# -*- coding: utf-8 -*-
"""
browser_utils.py - 浏览器启动工具

自动检测系统中可用的Chrome/Chromium浏览器，
支持Playwright自带浏览器和系统安装的Chrome。
"""
import os
import logging
from typing import Optional, List

logger = logging.getLogger(__name__)

# 系统Chrome路径候选
SYSTEM_CHROME_PATHS = [
    "/opt/google/chrome/chrome",
    "/usr/bin/google-chrome",
    "/usr/bin/google-chrome-stable",
    "/usr/bin/chromium-browser",
    "/usr/bin/chromium",
    "/snap/bin/chromium",
]


def find_system_chrome() -> Optional[str]:
    """查找系统中可用的Chrome/Chromium可执行文件"""
    # 1. 检查环境变量
    env_path = os.environ.get("CHROME_PATH") or os.environ.get("CHROMIUM_PATH")
    if env_path and os.path.exists(env_path):
        logger.info(f"使用环境变量指定的Chrome: {env_path}")
        return env_path

    # 2. 检查常见路径
    for path in SYSTEM_CHROME_PATHS:
        if os.path.exists(path):
            # 验证是否是真正的可执行文件（不是snap包装器）
            try:
                import subprocess
                result = subprocess.run(
                    [path, "--version"],
                    capture_output=True,
                    timeout=10,
                    env={**os.environ, "DISPLAY": ""}
                )
                if result.returncode == 0:
                    version = result.stdout.decode().strip()
                    logger.info(f"找到系统Chrome: {path} ({version})")
                    return path
            except Exception:
                continue

    return None


def get_browser_launch_args(headless: bool = True) -> dict:
    """获取浏览器启动参数"""
    args = {
        "headless": headless,
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-web-security",
            "--disable-gpu",
            "--disable-features=IsolateOrigins,site-per-process",
        ]
    }

    # 尝试使用系统Chrome
    chrome_path = find_system_chrome()
    if chrome_path:
        args["executable_path"] = chrome_path

    return args
