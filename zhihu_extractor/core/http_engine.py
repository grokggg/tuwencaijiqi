#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP引擎 - 多UA轮换、自动重试、会话管理
"""
import subprocess
import time
import random
import json
from typing import Optional, Tuple, Dict
from urllib.parse import urlparse


class HTTPEngine:
    """基于curl的HTTP客户端，支持多UA轮换和自动重试"""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.timeout = self.config.get("timeout", 12)
        self.max_retries = self.config.get("max_retries", 3)
        self.retry_delay = self.config.get("retry_delay", 1.0)
        self.rate_limit = self.config.get("rate_limit", 0.3)
        self._last_request_time = 0
        self._ua_pool = [
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
            "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        ]
        self._ua_index = 0
        self.stats = {"total": 0, "success": 0, "fail": 0, "retries": 0}

    def _get_next_ua(self) -> str:
        """轮换UA"""
        ua = self._ua_pool[self._ua_index % len(self._ua_pool)]
        self._ua_index += 1
        return ua

    def _rate_limit_wait(self):
        """速率限制"""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit:
            time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.time()

    def get(self, url: str, ua: str = None, headers: dict = None,
            timeout: int = None, retries: int = None) -> Tuple[int, str, dict]:
        """
        GET请求
        返回: (status_code, body, response_headers)
        """
        self._rate_limit_wait()
        ua = ua or self._get_next_ua()
        timeout = timeout or self.timeout
        retries = retries if retries is not None else self.max_retries
        self.stats["total"] += 1

        for attempt in range(retries + 1):
            cmd = [
                'curl', '-s', '-L',
                '--max-time', str(timeout),
                '--compressed',
                '-w', '\n__HTTP_STATUS__:%{http_code}',
                '-A', ua,
            ]
            if headers:
                for k, v in headers.items():
                    cmd.extend(['-H', f'{k}: {v}'])
            cmd.append(url)

            try:
                result = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=timeout + 5
                )
                output = result.stdout

                # 解析状态码
                status_match = output.rfind('__HTTP_STATUS__:')
                if status_match > 0:
                    status_str = output[status_match + 16:].strip()
                    body = output[:status_match].rstrip('\n').rstrip()
                    try:
                        status_code = int(status_str)
                    except:
                        status_code = 0
                else:
                    body = output
                    status_code = 200 if body and len(body) > 100 else 0

                if status_code == 200 and body and len(body) > 100:
                    self.stats["success"] += 1
                    return status_code, body, {}

                if attempt < retries:
                    self.stats["retries"] += 1
                    time.sleep(self.retry_delay * (attempt + 1))
                    ua = self._get_next_ua()  # 换UA重试
                else:
                    self.stats["fail"] += 1
                    return status_code, body if body else '', {}

            except subprocess.TimeoutExpired:
                if attempt < retries:
                    self.stats["retries"] += 1
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    self.stats["fail"] += 1
                    return 0, '', {}
            except Exception as e:
                if attempt < retries:
                    self.stats["retries"] += 1
                    time.sleep(self.retry_delay * (attempt + 1))
                else:
                    self.stats["fail"] += 1
                    return 0, '', {}

        return 0, '', {}

    def get_json(self, url: str, ua: str = None, headers: dict = None) -> Tuple[int, dict]:
        """GET请求，返回JSON"""
        h = headers or {}
        h['Accept'] = 'application/json'
        status, body, _ = self.get(url, ua=ua, headers=h)
        if body:
            try:
                return status, json.loads(body)
            except:
                return status, {}
        return status, {}

    def get_stats(self) -> dict:
        return self.stats.copy()
