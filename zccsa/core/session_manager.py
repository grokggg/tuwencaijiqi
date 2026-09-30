# -*- coding: utf-8 -*-
"""
ZCCSA Session管理器
- 使用curl_cffi伪装TLS指纹为Chrome 120
- 为每个会话绑定独立设备指纹
- 支持Cookie加载、指数退避重试
"""
import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
from curl_cffi import requests as curl_requests

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


@dataclass
class DeviceFingerprint:
    """设备指纹数据"""
    user_agent: str
    accept_language: str
    screen_resolution: str
    platform: str
    color_depth: int = 24
    timezone: str = "Asia/Shanghai"
    session_id: str = field(default_factory=lambda: hashlib.md5(
        f"{time.time()}-{random.random()}".encode()).hexdigest()[:12])


class SessionManager:
    """
    Session管理器：管理HTTP会话生命周期，提供TLS指纹伪装、
    Cookie管理、自动重试等能力。
    """

    # 桌面UA池（Chrome 120 变体）
    _DESKTOP_UAS = [
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    ]

    _MOBILE_UAS = [
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1",
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    ]

    _SCREEN_RESOLUTIONS = [
        "1920x1080", "2560x1440", "1440x900", "1366x768",
        "390x844", "414x896", "360x800",
    ]

    def __init__(self, cookie_file: Optional[str] = None,
                 use_mobile: bool = False,
                 fingerprint: Optional[DeviceFingerprint] = None):
        """
        初始化SessionManager
        :param cookie_file: Cookie文件路径（JSON格式，cookies.txt兼容）
        :param use_mobile: 是否使用移动端UA
        :param fingerprint: 指定设备指纹，不指定则随机生成
        """
        self._cookie_file = cookie_file
        self._use_mobile = use_mobile
        self._fingerprint = fingerprint or self._generate_fingerprint(use_mobile)
        self._cookies: Dict[str, str] = {}
        self._curl_session: Optional[curl_requests.Session] = None
        self._httpx_client: Optional[httpx.AsyncClient] = None

        # 加载Cookie
        if cookie_file:
            self._load_cookies(cookie_file)

    def _generate_fingerprint(self, mobile: bool) -> DeviceFingerprint:
        """生成随机设备指纹"""
        ua_pool = self._MOBILE_UAS if mobile else self._DESKTOP_UAS
        res_pool = self._SCREEN_RESOLUTIONS[-3:] if mobile else self._SCREEN_RESOLUTIONS[:5]
        return DeviceFingerprint(
            user_agent=random.choice(ua_pool),
            accept_language="zh-CN,zh;q=0.9,en;q=0.8" if not mobile
            else "zh-CN,zh-Hans;q=0.9",
            screen_resolution=random.choice(res_pool),
            platform="Mobile" if mobile else "desktop",
        )

    def _load_cookies(self, cookie_file: str) -> None:
        """从文件加载Cookie，支持JSON和Netscape格式"""
        path = Path(cookie_file)
        if not path.exists():
            logger.warning(f"Cookie文件不存在: {cookie_file}")
            return
        try:
            text = path.read_text(encoding="utf-8").strip()
            if text.startswith("[") or text.startswith("{"):
                # JSON格式
                data = json.loads(text)
                if isinstance(data, list):
                    for c in data:
                        name = c.get("name") or c.get("Name")
                        value = c.get("value") or c.get("Value")
                        if name and value is not None:
                            self._cookies[name] = value
                elif isinstance(data, dict):
                    self._cookies.update(data)
            else:
                # Netscape/curl格式
                for line in text.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    parts = line.split("\t")
                    if len(parts) >= 7:
                        self._cookies[parts[5]] = parts[6]
            logger.info(f"加载了 {len(self._cookies)} 个Cookie (fingerprint={self._fingerprint.session_id})")
        except Exception as e:
            logger.error(f"加载Cookie失败: {e}")

    @property
    def fingerprint(self) -> DeviceFingerprint:
        return self._fingerprint

    @property
    def cookies(self) -> Dict[str, str]:
        return self._cookies.copy()

    def _build_headers(self, extra_headers: Optional[Dict] = None) -> Dict[str, str]:
        """构造完整请求头"""
        base = config.DEFAULT_HEADERS_MOBILE if self._use_mobile \
            else config.DEFAULT_HEADERS_DESKTOP
        # 使用当前指纹的UA（可能是随机生成的）
        headers = dict(base)
        headers["User-Agent"] = self._fingerprint.user_agent
        headers["Accept-Language"] = self._fingerprint.accept_language
        if extra_headers:
            headers.update(extra_headers)
        return headers

    def _get_curl_session(self) -> curl_requests.Session:
        """获取或创建curl_cffi会话"""
        if self._curl_session is None:
            self._curl_session = curl_requests.Session(
                impersonate=config.IMPERSONATE_BROWSER
            )
            # 设置Cookie
            if self._cookies:
                for name, value in self._cookies.items():
                    self._curl_session.cookies.set(name, value, domain=".zhihu.com")
        return self._curl_session

    async def get_async_client(self) -> httpx.AsyncClient:
        """获取异步httpx客户端（用于并发请求）"""
        if self._httpx_client is None:
            self._httpx_client = httpx.AsyncClient(
                headers=self._build_headers(),
                cookies=self._cookies,
                follow_redirects=True,
                timeout=config.REQUEST_TIMEOUT,
                verify=False,
                http2=True,
            )
        return self._httpx_client

    def get(self, url: str,
            extra_headers: Optional[Dict] = None,
            timeout: Optional[int] = None,
            allow_redirects: bool = True,
            verify: bool = False,
            referer: Optional[str] = None) -> Tuple[int, str, Dict[str, Any]]:
        """
        同步GET请求（使用curl_cffi，TLS伪装最强）
        返回 (status_code, text, metadata)
        metadata: {"url": final_url, "headers": response_headers, "cookies": cookies}
        """
        headers = self._build_headers(extra_headers)
        if referer:
            headers["Referer"] = referer

        last_exc = None
        for attempt in range(config.MAX_RETRIES):
            try:
                sess = self._get_curl_session()
                resp = sess.get(
                    url,
                    headers=headers,
                    timeout=timeout or config.REQUEST_TIMEOUT,
                    allow_redirects=allow_redirects,
                    verify=verify,
                )
                # 编码处理
                text = self._decode_response(resp)
                return resp.status_code, text, {
                    "url": str(resp.url),
                    "headers": dict(resp.headers),
                    "cookies": dict(resp.cookies),
                    "length": len(text),
                    "attempt": attempt + 1,
                }
            except Exception as e:
                last_exc = e
                if attempt < config.MAX_RETRIES - 1:
                    delay = min(config.RETRY_BACKOFF_BASE ** attempt, config.RETRY_BACKOFF_MAX)
                    delay += random.uniform(0, 0.5)
                    logger.debug(f"请求重试 ({attempt+1}/{config.MAX_RETRIES}) "
                                 f"url={url[:60]}... err={str(e)[:50]} sleep={delay:.1f}s")
                    time.sleep(delay)
                else:
                    logger.warning(f"请求失败 url={url[:60]}... err={str(e)[:80]}")

        raise last_exc if last_exc else RuntimeError("请求失败，未知错误")

    async def async_get(self, url: str,
                        extra_headers: Optional[Dict] = None,
                        timeout: Optional[int] = None,
                        client: Optional[httpx.AsyncClient] = None) -> Tuple[int, str, Dict[str, Any]]:
        """异步GET请求（用于并发Fuzzing）"""
        headers = self._build_headers(extra_headers)
        own_client = client is None
        if own_client:
            client = await self.get_async_client()
        last_exc = None
        for attempt in range(config.MAX_RETRIES):
            try:
                resp = await client.get(
                    url,
                    headers=headers,
                    timeout=timeout or config.REQUEST_TIMEOUT,
                    follow_redirects=True,
                )
                text = resp.text
                return resp.status_code, text, {
                    "url": str(resp.url),
                    "headers": dict(resp.headers),
                    "length": len(text),
                    "attempt": attempt + 1,
                }
            except Exception as e:
                last_exc = e
                if attempt < config.MAX_RETRIES - 1:
                    delay = min(config.RETRY_BACKOFF_BASE ** attempt, config.RETRY_BACKOFF_MAX)
                    await asyncio.sleep(delay)
        raise last_exc if last_exc else RuntimeError("异步请求失败")

    def _decode_response(self, resp) -> str:
        """响应体编码检测与解码"""
        # 先尝试响应声明的编码
        text = resp.text
        if hasattr(resp, 'encoding') and resp.encoding:
            try:
                text = resp.content.decode(resp.encoding, errors='ignore')
            except Exception:
                pass
        # 从meta charset检测
        import re
        meta_match = re.search(
            r'<meta[^>]*charset=["\']?([^"\'>\s;]+)',
            text[:2000], re.I
        )
        if meta_match:
            try:
                text = resp.content.decode(meta_match.group(1), errors='ignore')
            except Exception:
                pass
        return text

    def close(self):
        """关闭所有会话"""
        if self._curl_session:
            try:
                self._curl_session.close()
            except Exception:
                pass
            self._curl_session = None
        if self._httpx_client:
            try:
                asyncio.get_event_loop().create_task(self._httpx_client.aclose())
            except Exception:
                pass
            self._httpx_client = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False


def create_session(cookie_file: Optional[str] = None,
                   mobile: bool = False) -> SessionManager:
    """创建SessionManager的工厂函数"""
    return SessionManager(cookie_file=cookie_file, use_mobile=mobile)
