# -*- coding: utf-8 -*-
"""
basic_http_engine.py - 基础HTTP页面抓取引擎

作为最基础的 fallback 引擎，直接请求页面HTML，
提取标题、作者、免费预览内容等可见信息。
"""
import asyncio
import logging
import re
import time
import json
from typing import Optional, Dict, Any
from urllib.parse import urlparse

from core.parser import ContentParser, ParsedContent, extract_article_id
from core.session_manager import SessionManager

logger = logging.getLogger(__name__)


class BasicHttpEngine:
    """基础HTTP页面抓取引擎"""

    def __init__(self, session_mgr: SessionManager):
        self.session_mgr = session_mgr
        self.parser = ContentParser()
        self.name = "basic_http_engine"

    async def fetch(self, url: str) -> Optional[ParsedContent]:
        """直接请求页面HTML并提取可见内容"""
        start_time = time.time()
        ids = extract_article_id(url)

        try:
            session = self.session_mgr.get_session()
            logger.info(f"基础HTTP引擎: 直接请求页面...")

            # 发送GET请求
            status, html, headers, final_url = await asyncio.to_thread(
                session.get, url,
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "Cache-Control": "no-cache",
                    "Pragma": "no-cache",
                }
            )

            logger.info(f"基础HTTP引擎: 状态码={status}, HTML长度={len(html)}")

            if status != 200:
                logger.warning(f"基础HTTP引擎: 请求失败，状态码={status}")
                return None

            # 解析页面内容
            content = self._parse_html(html, url, ids)

            elapsed = time.time() - start_time
            if content:
                logger.info(f"基础HTTP引擎: 获取到内容 - {content.title} ({content.content_length}字)")
            else:
                logger.warning(f"基础HTTP引擎: 未能解析到有效内容")

            return content

        except Exception as e:
            logger.error(f"基础HTTP引擎异常: {e}")
            import traceback
            logger.debug(traceback.format_exc())
            return None

    def _parse_html(self, html: str, url: str, ids: Dict[str, str]) -> Optional[ParsedContent]:
        """解析HTML页面提取内容"""
        content = ParsedContent()
        content.original_url = url
        content.platform = "zhihu_salt" if "paid_column" in url else "zhihu"

        # 1. 提取标题
        title = self._extract_title(html)
        if title:
            content.title = title

        # 2. 尝试从JSON数据中提取
        json_data = self._extract_json_data(html)
        if json_data:
            self._extract_from_json(content, json_data, ids)

        # 3. 提取作者
        if not content.author:
            author = self._extract_author(html)
            if author:
                content.author = author

        # 4. 提取正文预览
        if not content.content_html:
            preview = self._extract_content_preview(html)
            if preview:
                content.content_html = preview
                content.is_truncated = True  # 标记为截断（免费预览）
                content.content_markdown = self.parser.html_to_markdown(preview)

        # 5. 提取专栏信息
        if "column_id" in ids:
            content.column_id = ids["column_id"]
        if "section_id" in ids:
            content.section_id = ids["section_id"]
        if "article_id" in ids:
            content.article_id = ids["article_id"]

        # 判断是否有有效内容
        if content.title or content.content_html:
            return content
        return None

    def _extract_title(self, html: str) -> str:
        """提取页面标题"""
        # 从 <title> 标签
        m = re.search(r'<title[^>]*>([^<]+)</title>', html, re.I)
        if m:
            title = m.group(1).strip()
            # 移除知乎后缀
            title = re.sub(r'[-_|]\s*知乎\s*$', '', title).strip()
            if title and len(title) > 2:
                return title

        # 从 og:title
        m = re.search(r'<meta[^>]*property=["\']og:title["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
        if m:
            return m.group(1).strip()

        # 从 h1 标签
        m = re.search(r'<h1[^>]*class="[^"]*title[^"]*"[^>]*>([^<]+)</h1>', html, re.I)
        if m:
            return m.group(1).strip()

        return ""

    def _extract_author(self, html: str) -> str:
        """提取作者"""
        # 从 meta author
        m = re.search(r'<meta[^>]*name=["\']author["\'][^>]*content=["\']([^"\']+)["\']', html, re.I)
        if m:
            return m.group(1).strip()

        # 从常见作者class
        m = re.search(r'class="[^"]*author[^"]*"[^>]*>([^<]+)<', html, re.I)
        if m:
            author = m.group(1).strip()
            if author and len(author) < 50:
                return author

        # 从用户名链接
        m = re.search(r'/people/[^>]+>([^<]{2,20})</a>', html)
        if m:
            return m.group(1).strip()

        return ""

    def _extract_json_data(self, html: str) -> Optional[Dict]:
        """提取页面中的JSON数据"""
        # 查找初始数据 script
        patterns = [
            r'<script[^>]*id="js-initialData"[^>]*>(.*?)</script>',
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
            r'<script[^>]*data-zop-initial[^>]*>(.*?)</script>',
            r'window\.INITIAL_DATA\s*=\s*({.*?});',
        ]

        for pattern in patterns:
            m = re.search(pattern, html, re.S | re.I)
            if m:
                try:
                    json_str = m.group(1).strip()
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    continue
        return None

    def _extract_from_json(self, content: ParsedContent, data: Dict, ids: Dict[str, str]):
        """从JSON数据中提取内容"""
        try:
            # 遍历查找可能包含文章内容的节点
            self._walk_json(data, content, ids, depth=0, max_depth=8)
        except Exception as e:
            logger.debug(f"JSON解析异常: {e}")

    def _walk_json(self, obj: Any, content: ParsedContent, ids: Dict, depth: int, max_depth: int):
        """递归遍历JSON查找内容"""
        if depth > max_depth:
            return

        if isinstance(obj, dict):
            # 检查是否是文章节点
            if "title" in obj and isinstance(obj["title"], str) and len(obj["title"]) > 2:
                if not content.title or len(obj["title"]) > len(content.title):
                    title = obj["title"].strip()
                    if "知乎" not in title and len(title) > 2:
                        content.title = title

            if "author" in obj and isinstance(obj["author"], dict):
                if "name" in obj["author"] and not content.author:
                    content.author = obj["author"]["name"]

            if "content" in obj and isinstance(obj["content"], str) and len(obj["content"]) > 50:
                html_content = obj["content"]
                # 判断是否是付费内容标记
                if "盐选" in html_content or "会员" in html_content or len(html_content) > 200:
                    if not content.content_html or len(html_content) > len(content.content_html):
                        content.content_html = html_content
                        content.content_markdown = self.parser.html_to_markdown(html_content)
                        # 检查是否被截断
                        if "付费" in html_content[:500] or "剩余" in html_content[:500] or "查看全文" in html_content:
                            content.is_truncated = True

            if "excerpt" in obj and isinstance(obj["excerpt"], str) and not content.excerpt:
                content.excerpt = obj["excerpt"][:500]

            if "voteupCount" in obj and isinstance(obj["voteupCount"], int):
                content.voteup_count = obj["voteupCount"]

            if "commentCount" in obj and isinstance(obj["commentCount"], int):
                content.comment_count = obj["commentCount"]

            # 递归遍历子节点
            for key, value in obj.items():
                if key in ("entities", "payload", "data", "section", "article", "column", "node"):
                    self._walk_json(value, content, ids, depth + 1, max_depth)
                elif isinstance(value, (dict, list)):
                    self._walk_json(value, content, ids, depth + 1, max_depth)

        elif isinstance(obj, list):
            for item in obj[:20]:  # 限制列表长度
                self._walk_json(item, content, ids, depth + 1, max_depth)

    def _extract_content_preview(self, html: str) -> str:
        """提取正文预览内容"""
        # 尝试查找文章内容区域
        content_patterns = [
            r'<div[^>]*class="[^"]*RichContent[^"]*"[^>]*>(.*?)</div>\s*<div[^>]*class="[^"]*ContentItem',
            r'<div[^>]*class="[^"]*Post-RichText[^"]*"[^>]*>(.*?)</div>',
            r'<div[^>]*class="[^"]*RichText[^"]*"[^>]*>(.*?)</div>',
            r'<article[^>]*>(.*?)</article>',
            r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>',
        ]

        for pattern in content_patterns:
            m = re.search(pattern, html, re.S | re.I)
            if m:
                content_html = m.group(1).strip()
                # 移除script和style标签
                content_html = re.sub(r'<script[^>]*>.*?</script>', '', content_html, flags=re.S | re.I)
                content_html = re.sub(r'<style[^>]*>.*?</style>', '', content_html, flags=re.S | re.I)
                if len(content_html) > 50:
                    return content_html

        # 查找付费提示前的内容
        paywall_patterns = [
            r'(.*?)<div[^>]*class="[^"]*(?:Paywall|paid|salt|member)[^"]*"',
            r'(.*?)<a[^>]*class="[^"]*SaltCard[^"]*"',
            r'(.*?)开通盐选会员',
            r'(.*?)查看全文',
            r'(.*?)<div[^>]*class="[^"]*Reward[^"]*"',
        ]

        for pattern in paywall_patterns:
            m = re.search(pattern, html, re.S | re.I)
            if m:
                preview = m.group(1).strip()
                # 找到最后一个完整的段落
                preview = re.sub(r'<script[^>]*>.*?</script>', '', preview, flags=re.S | re.I)
                preview = re.sub(r'<style[^>]*>.*?</style>', '', preview, flags=re.S | re.I)
                paragraphs = re.findall(r'<p[^>]*>.*?</p>', preview, re.S | re.I)
                if paragraphs:
                    return '\n'.join(paragraphs[-5:])  # 最后5段
                if len(preview) > 100:
                    return preview[-2000:]

        return ""
