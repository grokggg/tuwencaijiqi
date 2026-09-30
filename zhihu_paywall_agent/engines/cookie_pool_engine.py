# -*- coding: utf-8 -*-
"""
cookie_pool_engine.py - Cookie池+WebAPI引擎 (P1)

使用Cookie池中有效（会员）Cookie，直接请求知乎API获取付费内容。
实时验证Cookie有效性，失效自动移除。
"""
import json
import logging
import re
import time
from typing import Optional, Dict, List
from urllib.parse import quote

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from core.parser import ContentParser, ParsedContent, extract_article_id
from core.session_manager import SessionManager, Session, CookieEntry

logger = logging.getLogger(__name__)


class CookiePoolEngine:
    """
    Cookie池引擎。
    遍历池中有效Cookie，请求文章API，直到获取完整内容。
    """

    name = "cookie_pool_engine"

    def __init__(self, session_manager: SessionManager):
        self.sm = session_manager
        self.parser = ContentParser()

    async def fetch(self, url: str) -> Optional[ParsedContent]:
        """
        使用Cookie池尝试获取文章内容。
        """
        start_time = time.time()
        ids = extract_article_id(url)

        # 先验证Cookie池
        await self.sm.verify_cookies()

        # 确定可用的会员Cookie
        member_cookies = [c for c in self.sm.cookies if c.is_valid and c.is_member and c.z_c0]
        if not member_cookies:
            logger.info("无可用会员Cookie，Cookie池引擎跳过")
            # 尝试普通Cookie（可能获取到部分内容或试读）
            normal_cookies = [c for c in self.sm.cookies if c.is_valid and c.z_c0]
            if not normal_cookies:
                logger.info("无可用Cookie")
                return None
            cookies_to_try = normal_cookies
        else:
            cookies_to_try = member_cookies

        # 确定请求的API端点列表
        api_endpoints = self._build_api_endpoints(ids, url)
        if not api_endpoints:
            logger.warning("无法从URL确定API端点")
            return None

        # 逐个Cookie尝试
        for cookie in cookies_to_try:
            session = self.sm.get_session(require_member=False)
            session.update_cookie(cookie)

            for api_url, api_headers in api_endpoints:
                try:
                    logger.debug(f"尝试API: {api_url[:80]} (Cookie={cookie.username or 'unknown'})")

                    headers = {
                        "Referer": url,
                        "Accept": "application/json, text/plain, */*",
                        "x-requested-with": "fetch",
                    }
                    if cookie._xsrf:
                        headers["x-xsrftoken"] = cookie._xsrf
                    headers.update(api_headers)

                    status, body, resp_headers, final_url = session.get(
                        api_url,
                        headers=headers,
                        timeout=config.REQUEST_TIMEOUT,
                    )

                    if status == 401 or status == 403:
                        logger.debug(f"Cookie失效 (HTTP {status})")
                        cookie.is_valid = False
                        break

                    if status != 200:
                        logger.debug(f"API返回 {status}")
                        continue

                    # 尝试解析JSON
                    if body.strip().startswith("{") or body.strip().startswith("["):
                        try:
                            data = json.loads(body)
                        except json.JSONDecodeError:
                            # 可能是HTML
                            pc = self.parser.parse_html(body, final_url)
                            if pc and self.parser.is_content_complete(pc):
                                return pc
                            continue

                        pc = self.parser.parse_api_json(data, final_url)
                        if pc:
                            pc.platform = "zhihu"
                            if self.parser.is_content_complete(pc):
                                elapsed = time.time() - start_time
                                logger.info(f"Cookie池引擎成功: {pc.title} ({pc.content_length}字)")
                                return pc
                            else:
                                logger.debug(f"内容不完整 (截断={pc.is_truncated}, 长度={pc.content_length})")
                    else:
                        # HTML响应
                        pc = self.parser.parse_html(body, final_url)
                        if pc and self.parser.is_content_complete(pc):
                            return pc

                except Exception as e:
                    logger.debug(f"API请求失败: {e}")
                    continue

        logger.info("Cookie池引擎未能获取完整内容")
        return None

    def _build_api_endpoints(self, ids: Dict[str, str], original_url: str) -> List[tuple]:
        """
        构建要尝试的API端点列表。
        返回 [(url, extra_headers), ...]
        """
        endpoints = []

        article_id = ids.get("article_id") or ids.get("section_id")
        column_id = ids.get("column_id")
        answer_id = ids.get("answer_id")
        post_id = ids.get("post_id")
        share_code = ids.get("share_code")
        km_pst = ids.get("km_pst")

        # 1. 付费专栏文章内容API
        if article_id:
            endpoints.append((
                config.ARTICLE_CONTENT_API_TEMPLATE.format(article_id=article_id),
                {}
            ))
            endpoints.append((
                config.ARTICLE_DETAIL_API_TEMPLATE.format(article_id=article_id),
                {}
            ))

        # 2. 专栏/章节API
        if column_id and article_id:
            endpoints.append((
                f"{config.ZHIHU_MARKET_API}/{column_id}/section/{article_id}",
                {}
            ))

        # 3. 普通文章API
        if article_id:
            endpoints.append((
                f"{config.ZHIHU_API_BASE}/articles/{article_id}",
                {}
            ))

        # 4. 回答API
        if answer_id:
            endpoints.append((
                f"{config.ZHIHU_API_BASE}/answers/{answer_id}",
                {}
            ))

        # 5. 想法/帖子API
        if post_id:
            endpoints.append((
                f"{config.ZHIHU_API_BASE}/posts/{post_id}",
                {}
            ))

        # 6. oia付费分享API
        if share_code and km_pst:
            endpoints.append((
                f"{config.ZHIHU_OIA_URL}?km_pst={quote(km_pst)}&share_code={share_code}",
                {"Accept": "text/html,*/*"}
            ))

        # 7. 直接请求原始URL（可能在有Cookie时返回完整HTML）
        if "zhihu.com" in original_url:
            endpoints.append((
                original_url,
                {"Accept": "text/html,application/xhtml+xml,*/*"}
            ))

        return endpoints
