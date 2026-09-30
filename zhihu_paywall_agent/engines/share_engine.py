# -*- coding: utf-8 -*-
"""
share_engine.py - 分享免费读引擎 (P0 最高优先级)

技术路径：
1. 若URL中没有share参数，先用会员Cookie调用API生成分享链接
2. 用Playwright打开分享页，拦截网络请求获取临时授权token
3. 用token请求完整文章内容
4. 解析并返回正文
"""
import asyncio
import json
import logging
import re
import time
from typing import Optional, Dict, Any
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, quote

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from core.parser import ContentParser, ParsedContent, extract_article_id
from core.session_manager import SessionManager, Session
from core.fingerprint import get_playwright_stealth_script
from core.browser_utils import get_browser_launch_args

logger = logging.getLogger(__name__)

# Playwright懒加载（启动慢，按需导入）
_playwright = None
_browser_type = None
_browser_instance = None


async def _get_playwright():
    """懒加载Playwright"""
    global _playwright, _browser_type, _browser_instance
    if _playwright is None:
        try:
            from playwright.async_api import async_playwright
            _playwright = await async_playwright().start()
            _browser_type = _playwright.chromium
            launch_args = get_browser_launch_args(headless=config.PLAYWRIGHT_HEADLESS)
            _browser_instance = await _browser_type.launch(**launch_args)
            logger.info("Playwright浏览器已启动")
        except ImportError:
            logger.error("Playwright未安装，请运行: pip install playwright && playwright install chromium")
            return None, None
        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            return None, None
    return _playwright, _browser_instance


async def _close_browser():
    """关闭浏览器实例"""
    global _playwright, _browser_instance
    if _browser_instance:
        await _browser_instance.close()
    if _playwright:
        await _playwright.stop()
    _playwright = None
    _browser_instance = None


class ShareEngine:
    """
    分享免费读引擎。
    利用知乎"分享免费读"机制：通过分享链接，非会员可获得临时token阅读全文。
    """

    name = "share_engine"

    def __init__(self, session_manager: SessionManager):
        self.sm = session_manager
        self.parser = ContentParser()

    async def fetch(self, url: str) -> Optional[ParsedContent]:
        """
        执行分享免费读链路。

        Args:
            url: 知乎文章URL
        Returns:
            ParsedContent 或 None
        """
        start_time = time.time()
        ids = extract_article_id(url)

        try:
            # 1. 确定分享URL
            share_url = url
            if "share=" not in url and "share_code" not in url and "oia.zhihu.com" not in url:
                share_url = await self._create_share_link(url, ids)
                if not share_url:
                    logger.warning("无法生成分享链接")
                    return None
                logger.info(f"生成分享链接: {share_url[:80]}...")

            # 2. 用Playwright打开分享页，拦截token
            content = await self._fetch_via_browser(share_url, ids)
            if content and self.parser.is_content_complete(content):
                elapsed = time.time() - start_time
                logger.info(f"分享引擎成功获取内容: {content.title} ({content.content_length}字)")
                return content

            # 3. 浏览器方式失败，尝试直接用HTTP请求模拟
            content = await self._fetch_via_http(share_url, ids)
            if content and self.parser.is_content_complete(content):
                elapsed = time.time() - start_time
                logger.info(f"分享引擎(HTTP)成功: {content.title} ({content.content_length}字)")
                return content

            logger.warning("分享引擎未能获取完整内容")
            return None

        except Exception as e:
            logger.error(f"分享引擎异常: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    async def _create_share_link(self, url: str, ids: Dict[str, str]) -> Optional[str]:
        """调用API生成分享链接"""
        # 需要会员Cookie
        session = self.sm.get_session(require_member=True, mobile=True)

        # 确定要分享的内容类型和ID
        article_id = ids.get("article_id") or ids.get("section_id") or ids.get("answer_id") or ids.get("post_id")
        column_id = ids.get("column_id")

        if not article_id and not column_id:
            # 尝试从oia链接生成
            if "oia.zhihu.com" in url:
                return url
            return None

        try:
            # 先获取_xsrf token
            if not session.cookie or not session.cookie._xsrf:
                status, body, headers, _ = session.get(
                    "https://www.zhihu.com/",
                    headers={"Referer": "https://www.zhihu.com/"},
                    timeout=10
                )
                # 从响应中提取_xsrf
                xsrf_match = re.search(r'_xsrf=([^;]+)', headers.get("Set-Cookie", ""))
                if xsrf_match and session.cookie:
                    session.cookie._xsrf = xsrf_match.group(1)

            # 构建分享API请求
            share_api = config.SHARE_CREATE_API
            payload = {}
            if column_id:
                payload["column_id"] = column_id
            if article_id:
                payload["content_id"] = article_id
                payload["content_type"] = "paid_column_section"

            extra_headers = {
                "Referer": url,
                "Content-Type": "application/json",
                "x-requested-with": "fetch",
            }
            if session.cookie and session.cookie._xsrf:
                extra_headers["x-xsrftoken"] = session.cookie._xsrf

            status, body, headers, _ = session.post(
                share_api,
                json_data=payload,
                headers=extra_headers,
                timeout=15,
            )

            if status == 200:
                try:
                    data = json.loads(body)
                    share_url = data.get("share_url") or data.get("url") or data.get("data", {}).get("share_url")
                    share_id = data.get("share_id") or data.get("id") or data.get("data", {}).get("share_id")
                    if share_url:
                        return share_url
                    if share_id:
                        return f"{url}?share={share_id}"
                except json.JSONDecodeError:
                    logger.debug(f"分享API响应非JSON: {body[:200]}")

            logger.warning(f"分享API返回 {status}: {body[:200]}")
            return None

        except Exception as e:
            logger.warning(f"生成分享链接失败: {e}")
            return None

    async def _fetch_via_browser(self, share_url: str, ids: Dict[str, str]) -> Optional[ParsedContent]:
        """使用Playwright打开分享页，拦截网络响应获取内容"""
        pw, browser = await _get_playwright()
        if not browser:
            return None

        context = None
        page = None
        captured_content = None
        captured_token = None

        try:
            # 创建上下文（移动端UA模拟知乎App WebView）
            from core.fingerprint import ZHIHU_APP_IOS_UA
            context = await browser.new_context(
                user_agent=ZHIHU_APP_IOS_UA,
                viewport=config.PLAYWRIGHT_VIEWPORT,
                device_scale_factor=config.PLAYWRIGHT_DEVICE_SCALE,
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
                is_mobile=True,
                has_touch=True,
            )

            # 注入stealth脚本
            await context.add_init_script(get_playwright_stealth_script())

            page = await context.new_page()

            # 拦截API响应
            async def handle_response(response):
                nonlocal captured_content, captured_token
                try:
                    url = response.url
                    # 监听内容相关API
                    if any(kw in url for kw in [
                        "/api/v4/market/paid_column",
                        "/api/v4/paid_contents",
                        "/api/v4/articles",
                        "/api/v4/posts",
                        "/km_paid_content/api",
                    ]):
                        if "grant" in url or "share" in url or "content" in url:
                            ct = response.headers.get("content-type", "")
                            if "json" in ct:
                                try:
                                    data = await response.json()
                                    # 检查是否是授权响应
                                    if "access_token" in str(data) or "ticket" in str(data):
                                        captured_token = data
                                        logger.info(f"拦截到授权token响应: {url[:80]}")
                                    # 检查是否包含正文
                                    pc = self.parser.parse_api_json(data, url)
                                    if pc and pc.content_length > config.MIN_CONTENT_LENGTH:
                                        captured_content = pc
                                        logger.info(f"拦截到完整内容: {pc.title} ({pc.content_length}字)")
                                except Exception:
                                    pass
                except Exception:
                    pass

            page.on("response", handle_response)

            # 导航到分享页
            logger.info(f"浏览器打开: {share_url[:80]}")
            try:
                await page.goto(share_url, wait_until="domcontentloaded",
                              timeout=config.PLAYWRIGHT_TIMEOUT)
            except Exception as e:
                logger.warning(f"页面导航超时: {e}")

            # 等待页面加载和网络请求
            await asyncio.sleep(5)

            # 尝试滚动页面触发懒加载
            for _ in range(3):
                await page.evaluate("window.scrollBy(0, window.innerHeight)")
                await asyncio.sleep(1)

            # 如果捕获到token，用token请求完整内容
            if captured_token and not captured_content:
                token = None
                if isinstance(captured_token, dict):
                    token = (captured_token.get("access_token") or
                            captured_token.get("ticket") or
                            captured_token.get("token") or
                            captured_token.get("data", {}).get("access_token"))
                if token:
                    article_id = ids.get("article_id") or ids.get("section_id")
                    if article_id:
                        content_url = config.ARTICLE_CONTENT_API_TEMPLATE.format(article_id=article_id)
                        try:
                            # 在浏览器中用token请求
                            result = await page.evaluate(f"""
                                async () => {{
                                    const resp = await fetch("{content_url}?access_token={token}", {{
                                        credentials: 'include'
                                    }});
                                    return await resp.text();
                                }}
                            """)
                            try:
                                data = json.loads(result)
                                captured_content = self.parser.parse_api_json(data, content_url)
                            except:
                                pass
                        except Exception as e:
                            logger.debug(f"Token请求失败: {e}")

            # 如果还没内容，尝试直接从页面DOM提取
            if not captured_content or not self.parser.is_content_complete(captured_content):
                try:
                    html = await page.content()
                    pc = self.parser.parse_html(
                        html, share_url,
                        content_selectors=[
                            ".RichContent-inner", ".Post-RichTextContainer",
                            ".manuscript", ".PostContent", ".Article-content",
                            ".content", "article",
                        ]
                    )
                    if pc and pc.content_length > (captured_content.content_length if captured_content else 0):
                        captured_content = pc
                except Exception as e:
                    logger.debug(f"DOM提取失败: {e}")

            return captured_content

        except Exception as e:
            logger.error(f"浏览器获取失败: {e}")
            return None
        finally:
            if page:
                try: await page.close()
                except: pass
            if context:
                try: await context.close()
                except: pass

    async def _fetch_via_http(self, share_url: str, ids: Dict[str, str]) -> Optional[ParsedContent]:
        """HTTP方式直接请求分享页内容"""
        # 使用移动端/知乎App UA
        session = self.sm.get_session(mobile=True, zhihu_app=True)

        try:
            # 直接请求分享页
            status, body, headers, final_url = session.get(
                share_url,
                headers={"Referer": "https://www.zhihu.com/"},
                timeout=config.REQUEST_TIMEOUT,
                allow_redirects=True,
            )

            if status != 200:
                logger.warning(f"分享页HTTP {status}")
                return None

            # 如果返回的是JSON，直接解析
            if body.strip().startswith("{"):
                try:
                    data = json.loads(body)
                    pc = self.parser.parse_api_json(data, final_url)
                    if pc and self.parser.is_content_complete(pc):
                        return pc
                except json.JSONDecodeError:
                    pass

            # 解析HTML
            content_selectors = [
                ".RichContent-inner", ".Post-RichTextContainer",
                ".manuscript", ".PostContent", ".RichText",
                'div[class*="RichText"]', 'div[class*="content"]',
            ]
            pc = self.parser.parse_html(body, final_url, content_selectors=content_selectors)
            return pc

        except Exception as e:
            logger.warning(f"HTTP获取分享页失败: {e}")
            return None


async def cleanup():
    """清理浏览器资源"""
    await _close_browser()
