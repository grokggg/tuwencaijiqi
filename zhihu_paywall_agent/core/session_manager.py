# -*- coding: utf-8 -*-
"""
session_manager.py - HTTP会话管理

基于 curl_cffi 实现TLS指纹伪装的HTTP客户端，
支持Cookie池管理、请求重试、超时、设备指纹绑定。
"""
import asyncio
import logging
import random
import time
import json
import re
from typing import Optional, Dict, List, Tuple, Any
from pathlib import Path
from dataclasses import dataclass, field
from urllib.parse import urlparse, urljoin

import config
from core.fingerprint import Fingerprint, generate_fingerprint

logger = logging.getLogger(__name__)

# 尝试导入可选依赖
try:
    from curl_cffi import requests as curl_requests
    HAS_CURL_CFFI = True
except ImportError:
    HAS_CURL_CFFI = False
    import requests as curl_requests
    logger.warning("curl_cffi 未安装，将使用普通requests（无法伪装TLS指纹）")

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False


@dataclass
class CookieEntry:
    """单个Cookie条目"""
    z_c0: str = ""           # 知乎登录Cookie（核心）
    _xsrf: str = ""          # CSRF Token
    d_c0: str = ""           # 设备标识
    capsion_ticket: str = "" # 验证码ticket
    extra: Dict[str, str] = field(default_factory=dict)
    is_valid: bool = True
    last_check: float = 0.0
    is_member: bool = False   # 是否是盐选会员
    username: str = ""

    def to_cookie_string(self) -> str:
        """转换为Cookie请求头字符串"""
        parts = []
        if self.z_c0:
            parts.append(f"z_c0={self.z_c0}")
        if self._xsrf:
            parts.append(f"_xsrf={self._xsrf}")
        if self.d_c0:
            parts.append(f"d_c0={self.d_c0}")
        if self.capsion_ticket:
            parts.append(f"capsion_ticket={self.capsion_ticket}")
        for k, v in self.extra.items():
            parts.append(f"{k}={v}")
        return "; ".join(parts)

    def to_dict(self) -> Dict[str, str]:
        """转换为字典"""
        d = {}
        if self.z_c0: d["z_c0"] = self.z_c0
        if self._xsrf: d["_xsrf"] = self._xsrf
        if self.d_c0: d["d_c0"] = self.d_c0
        if self.capsion_ticket: d["capsion_ticket"] = self.capsion_ticket
        d.update(self.extra)
        return d

    @classmethod
    def from_string(cls, cookie_str: str) -> "CookieEntry":
        """从Cookie字符串解析"""
        entry = cls()
        for item in cookie_str.split(";"):
            item = item.strip()
            if "=" in item:
                k, v = item.split("=", 1)
                k, v = k.strip(), v.strip()
                if k == "z_c0":
                    entry.z_c0 = v
                elif k == "_xsrf":
                    entry._xsrf = v
                elif k == "d_c0":
                    entry.d_c0 = v
                elif k == "capsion_ticket":
                    entry.capsion_ticket = v
                else:
                    entry.extra[k] = v
        return entry

    @classmethod
    def from_dict(cls, d: Dict[str, str]) -> "CookieEntry":
        """从字典创建"""
        entry = cls()
        for k, v in d.items():
            if k == "z_c0": entry.z_c0 = v
            elif k == "_xsrf": entry._xsrf = v
            elif k == "d_c0": entry.d_c0 = v
            elif k == "capsion_ticket": entry.capsion_ticket = v
            else: entry.extra[k] = v
        return entry


class Session:
    """
    封装单个HTTP会话，绑定固定指纹，支持重试、延迟。
    使用curl_cffi实现TLS JA3指纹伪装。
    """

    def __init__(self, fingerprint: Optional[Fingerprint] = None,
                 cookie: Optional[CookieEntry] = None,
                 proxy: Optional[str] = None):
        self.fp = fingerprint or generate_fingerprint()
        self.cookie = cookie
        self.proxy = proxy
        self._session = None
        self._init_session()

    def _init_session(self):
        """初始化底层session"""
        if HAS_CURL_CFFI:
            self._session = curl_requests.Session(
                impersonate=self.fp.tls_impersonate
            )
        else:
            self._session = curl_requests.Session()

        # 设置默认headers
        self._session.headers.update(self.fp.to_headers())
        # 设置Cookie
        if self.cookie:
            self._session.headers["Cookie"] = self.cookie.to_cookie_string()
        # 设置代理
        if self.proxy:
            self._session.proxies = {"http": self.proxy, "https": self.proxy}

    def update_cookie(self, cookie: CookieEntry):
        """更新Cookie"""
        self.cookie = cookie
        self._session.headers["Cookie"] = cookie.to_cookie_string()

    def get(self, url: str, params: Optional[Dict] = None,
            headers: Optional[Dict] = None, timeout: int = None,
            allow_redirects: bool = True, **kwargs) -> Tuple[int, str, Dict[str, str], str]:
        """
        发送GET请求，带重试。

        Returns:
            (status_code, body_text, response_headers, final_url)
        """
        return self._request("GET", url, params=params, headers=headers,
                             timeout=timeout, allow_redirects=allow_redirects, **kwargs)

    def post(self, url: str, data: Any = None, json_data: Any = None,
             headers: Optional[Dict] = None, timeout: int = None,
             allow_redirects: bool = True, **kwargs) -> Tuple[int, str, Dict[str, str], str]:
        """发送POST请求"""
        return self._request("POST", url, data=data, json_data=json_data,
                             headers=headers, timeout=timeout,
                             allow_redirects=allow_redirects, **kwargs)

    def _request(self, method: str, url: str, params: Optional[Dict] = None,
                 data: Any = None, json_data: Any = None,
                 headers: Optional[Dict] = None, timeout: int = None,
                 allow_redirects: bool = True, **kwargs) -> Tuple[int, str, Dict[str, str], str]:
        """
        核心请求方法，带指数退避重试。
        """
        timeout = timeout or config.REQUEST_TIMEOUT
        merged_headers = {}
        if headers:
            merged_headers.update(headers)

        last_error = None
        for attempt in range(config.MAX_RETRIES):
            try:
                # 请求间隔
                if attempt > 0:
                    delay = config.RETRY_BACKOFF_BASE ** attempt + random.uniform(0, 1)
                    logger.debug(f"重试等待 {delay:.1f}s (第{attempt+1}次)")
                    time.sleep(delay)
                elif config.REQUEST_DELAY:
                    time.sleep(random.uniform(*config.REQUEST_DELAY))

                # 发起请求
                if HAS_CURL_CFFI:
                    resp = self._session.request(
                        method, url, params=params, data=data, json=json_data,
                        headers=merged_headers, timeout=timeout,
                        allow_redirects=allow_redirects,
                        impersonate=self.fp.tls_impersonate,
                        **kwargs
                    )
                else:
                    resp = self._session.request(
                        method, url, params=params, data=data, json=json_data,
                        headers=merged_headers, timeout=timeout,
                        allow_redirects=allow_redirects, **kwargs
                    )

                # 自动检测编码
                # curl_cffi的Response没有apparent_encoding，用chardet或Content-Type/meta判断
                if hasattr(resp, 'apparent_encoding') and resp.apparent_encoding:
                    resp.encoding = resp.apparent_encoding
                elif resp.encoding:
                    resp.encoding = resp.encoding
                else:
                    # 从Content-Type头检测
                    ct = resp.headers.get("Content-Type", "")
                    charset_match = re.search(r'charset=([^\s;]+)', ct, re.I)
                    if charset_match:
                        resp.encoding = charset_match.group(1).strip('"\'')
                    else:
                        # 从HTML meta标签检测
                        resp.encoding = "utf-8"  # 默认UTF-8
                        try:
                            raw_text = resp.text[:2000] if hasattr(resp, 'text') else ""
                            meta_charset = re.search(r'<meta[^>]*charset=["\']?([^"\'>\s;]+)', raw_text, re.I)
                            if meta_charset:
                                resp.encoding = meta_charset.group(1)
                        except:
                            pass
                resp_headers = dict(resp.headers)
                return resp.status_code, resp.text, resp_headers, resp.url

            except Exception as e:
                last_error = e
                logger.warning(f"请求失败 (尝试{attempt+1}/{config.MAX_RETRIES}): {url[:80]} - {e}")
                # 429/5xx需要更长等待
                if hasattr(e, 'response') and hasattr(e.response, 'status_code'):
                    if e.response.status_code == 429:
                        time.sleep(config.RETRY_BACKOFF_BASE ** (attempt + 2))

        raise last_error if last_error else RuntimeError(f"请求失败: {url}")

    def close(self):
        if self._session:
            self._session.close()


class SessionManager:
    """
    会话管理器：管理Cookie池、Session池、指纹分配。
    """

    def __init__(self, cookie_file: Optional[str] = None,
                 proxy_pool: Optional[List[str]] = None):
        self.cookie_file = Path(cookie_file) if cookie_file else config.COOKIE_FILE
        self.proxy_pool = proxy_pool or []
        self.cookies: List[CookieEntry] = []
        self.sessions: Dict[str, Session] = {}  # cookie_id -> Session
        self._next_cookie_idx = 0
        self._lock = asyncio.Lock()
        self._load_cookies()

    def _load_cookies(self):
        """从文件加载Cookie池"""
        if not self.cookie_file.exists():
            logger.info(f"Cookie文件不存在: {self.cookie_file}，将使用无Cookie模式")
            # 创建一个空Cookie条目（游客模式）
            entry = CookieEntry()
            self.cookies.append(entry)
            return

        try:
            content = self.cookie_file.read_text(encoding="utf-8").strip()
            if not content:
                self.cookies.append(CookieEntry())
                return

            for line in content.splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                # 支持JSON格式和纯Cookie字符串格式
                if line.startswith("{"):
                    try:
                        d = json.loads(line)
                        entry = CookieEntry.from_dict(d)
                    except json.JSONDecodeError:
                        entry = CookieEntry.from_string(line)
                else:
                    entry = CookieEntry.from_string(line)
                if entry.z_c0 or entry.d_c0:  # 至少有标识信息
                    self.cookies.append(entry)

            if not self.cookies:
                self.cookies.append(CookieEntry())

            logger.info(f"从 {self.cookie_file} 加载了 {len(self.cookies)} 个Cookie")
        except Exception as e:
            logger.error(f"加载Cookie失败: {e}")
            self.cookies.append(CookieEntry())

    def save_cookies(self):
        """保存Cookie池到文件"""
        try:
            lines = []
            for c in self.cookies:
                if c.z_c0:
                    d = c.to_dict()
                    if c.is_member:
                        d["_is_member"] = "1"
                    lines.append(json.dumps(d, ensure_ascii=False))
            self.cookie_file.write_text("\n".join(lines), encoding="utf-8")
        except Exception as e:
            logger.error(f"保存Cookie失败: {e}")

    def add_cookie(self, cookie: CookieEntry):
        """添加Cookie到池中"""
        self.cookies.append(cookie)
        self.sessions.pop(id(cookie), None)

    def get_session(self, require_member: bool = False,
                    mobile: bool = False,
                    zhihu_app: bool = False) -> Session:
        """
        获取一个可用Session。

        Args:
            require_member: 是否要求盐选会员Cookie
            mobile: 是否使用移动端指纹
            zhihu_app: 是否使用知乎App指纹
        """
        # 筛选有效Cookie
        valid = []
        member_cookies = []
        for c in self.cookies:
            if not c.is_valid:
                continue
            if c.z_c0:
                if c.is_member:
                    member_cookies.append(c)
                else:
                    valid.append(c)
            else:
                valid.append(c)  # 游客

        if require_member and member_cookies:
            cookie = random.choice(member_cookies)
        elif require_member and not member_cookies:
            logger.warning("无可用会员Cookie，降级为普通Cookie")
            pool = valid if valid else self.cookies
            cookie = random.choice(pool) if pool else CookieEntry()
        else:
            pool = valid if valid else self.cookies
            cookie = random.choice(pool) if pool else CookieEntry()

        # 生成或复用Session
        sess_id = str(id(cookie))
        if sess_id not in self.sessions:
            fp = generate_fingerprint(mobile=mobile, zhihu_app=zhihu_app)
            proxy = random.choice(self.proxy_pool) if self.proxy_pool else None
            self.sessions[sess_id] = Session(fingerprint=fp, cookie=cookie, proxy=proxy)
        else:
            # 更新Cookie（可能验证后更新了状态）
            self.sessions[sess_id].update_cookie(cookie)

        return self.sessions[sess_id]

    async def verify_cookies(self, force: bool = False):
        """
        验证池中所有Cookie的有效性。
        调用 /api/v4/me 检查登录状态和会员状态。
        """
        now = time.time()
        verified = 0
        invalid = 0

        for cookie in self.cookies:
            if not cookie.z_c0:
                continue  # 游客Cookie不需要验证
            if not force and (now - cookie.last_check) < config.COOKIE_CHECK_INTERVAL:
                continue

            try:
                sess = self.get_session()
                # 临时绑定这个cookie
                sess.update_cookie(cookie)
                status, body, headers, _ = sess.get(
                    config.ME_API,
                    headers={"Referer": "https://www.zhihu.com/"},
                    timeout=10
                )
                if status == 200:
                    try:
                        data = json.loads(body)
                        cookie.username = data.get("name", "")
                        # 检查会员状态
                        cookie.is_member = bool(
                            data.get("is_org_member") or
                            data.get("is_vip") or
                            (data.get("vip_info", {}) or {}).get("is_vip", False)
                        )
                        cookie.is_valid = True
                        verified += 1
                        logger.debug(f"Cookie有效: {cookie.username} 会员={cookie.is_member}")
                    except json.JSONDecodeError:
                        cookie.is_valid = False
                        invalid += 1
                elif status == 401:
                    cookie.is_valid = False
                    invalid += 1
                    logger.info(f"Cookie已失效，将移除")
                else:
                    cookie.is_valid = True  # 暂时保留
                    verified += 1

                cookie.last_check = now
            except Exception as e:
                logger.warning(f"验证Cookie失败: {e}")
                cookie.last_check = now  # 避免频繁重试

        # 移除失效Cookie
        before = len(self.cookies)
        self.cookies = [c for c in self.cookies if c.is_valid or not c.z_c0]
        removed = before - len(self.cookies)
        if removed > 0:
            logger.info(f"移除了 {removed} 个失效Cookie")

        logger.info(f"Cookie验证完成: {verified}有效, {invalid}失效")
        return verified, invalid

    def close_all(self):
        """关闭所有会话"""
        for s in self.sessions.values():
            s.close()
        self.sessions.clear()
