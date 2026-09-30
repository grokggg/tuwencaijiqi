# -*- coding: utf-8 -*-
"""
ZPE vNext - HTTP客户端
封装httpx，支持自动重试、会话保持、随机UA、请求延迟等
"""
import asyncio
import logging
import random
import time
from typing import Dict, Optional, Tuple, Any
from urllib.parse import urljoin

import httpx

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class HttpClient:
    def __init__(self):
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._cookie_jar = httpx.Cookies()
        self._last_request_time = 0
        
    def _get_client(self, headers: Optional[Dict] = None, **kwargs) -> httpx.AsyncClient:
        """获取或创建带有指定配置的client"""
        key = str(headers) + str(kwargs.get("follow_redirects", True))
        if key not in self._clients:
            client_kwargs = {
                "follow_redirects": kwargs.get("follow_redirects", True),
                "timeout": httpx.Timeout(config.REQUEST_CONFIG["timeout"]),
                "verify": False,
                "cookies": self._cookie_jar,
            }
            if headers:
                client_kwargs["headers"] = headers
            self._clients[key] = httpx.AsyncClient(**client_kwargs)
        return self._clients[key]
    
    async def _rate_limit(self):
        """请求限速"""
        now = time.time()
        min_delay, max_delay = config.REQUEST_CONFIG["request_delay"]
        elapsed = now - self._last_request_time
        delay = random.uniform(min_delay, max_delay)
        if elapsed < delay:
            await asyncio.sleep(delay - elapsed)
        self._last_request_time = time.time()
    
    async def get(self, url: str, headers: Optional[Dict] = None, 
                  params: Optional[Dict] = None, **kwargs) -> Tuple[int, str, Dict]:
        """
        发送GET请求
        返回: (status_code, text, response_headers)
        """
        await self._rate_limit()
        
        request_headers = dict(config.DEFAULT_HEADERS_DESKTOP)
        if headers:
            request_headers.update(headers)
        
        for attempt in range(config.REQUEST_CONFIG["max_retries"]):
            try:
                client = self._get_client(headers=request_headers, **kwargs)
                resp = await client.get(url, params=params, headers=request_headers)
                
                # 保存cookies
                for name, value in resp.cookies.items():
                    self._cookie_jar.set(name, value, domain=resp.url.host)
                
                return resp.status_code, resp.text, dict(resp.headers)
                
            except Exception as e:
                logger.debug(f"  请求失败 (尝试 {attempt+1}/{config.REQUEST_CONFIG['max_retries']}): {url} - {e}")
                if attempt < config.REQUEST_CONFIG["max_retries"] - 1:
                    await asyncio.sleep(config.REQUEST_CONFIG["retry_delay"] * (attempt + 1))
                else:
                    logger.warning(f"  请求最终失败: {url} - {e}")
                    return 0, str(e), {}
    
    async def post(self, url: str, headers: Optional[Dict] = None,
                   data: Optional[Dict] = None, json: Optional[Dict] = None,
                   **kwargs) -> Tuple[int, str, Dict]:
        """发送POST请求"""
        await self._rate_limit()
        
        request_headers = dict(config.DEFAULT_HEADERS_DESKTOP)
        if headers:
            request_headers.update(headers)
        
        for attempt in range(config.REQUEST_CONFIG["max_retries"]):
            try:
                client = self._get_client(headers=request_headers, **kwargs)
                resp = await client.post(url, data=data, json=json, headers=request_headers)
                return resp.status_code, resp.text, dict(resp.headers)
            except Exception as e:
                if attempt < config.REQUEST_CONFIG["max_retries"] - 1:
                    await asyncio.sleep(config.REQUEST_CONFIG["retry_delay"] * (attempt + 1))
                else:
                    return 0, str(e), {}
    
    async def close(self):
        """关闭所有client"""
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()


def cn_count(text: str) -> int:
    """统计中文字数"""
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')


def random_ua() -> str:
    """随机获取一个User-Agent"""
    return random.choice(list(config.USER_AGENTS.values()))


def with_referer(url: str) -> Dict[str, str]:
    """生成带Referer的headers"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    origin = f"{parsed.scheme}://{parsed.netloc}"
    return {
        "Referer": origin + "/",
        "Origin": origin,
    }
