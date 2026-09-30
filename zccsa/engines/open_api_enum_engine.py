# -*- coding: utf-8 -*-
"""
ZCCSA 开放平台接口枚举引擎（Zero-Cookie引擎）
- 枚举知乎可能遗留的开放平台/公开API路径
- 覆盖RSS、oEmbed、Syndication、Open Graph、SEO预渲染等场景
- 无Cookie直接请求，检测是否返回完整内容
- 权重：75
"""
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlencode

import httpx

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class OpenAPIEnumEngine(BaseEngine):
    """
    开放平台接口枚举引擎
    原理：内容平台通常会为RSS订阅、内容聚合、学术合作、SEO预渲染等场景保留公开接口，
    这些接口可能使用简单API Key鉴权或完全无鉴权，可能返回完整内容。
    """

    name = "open_api_enum_engine"
    description = "开放平台接口枚举（RSS/oEmbed/Syndication/SEO）"
    default_weight = 75

    # 开放平台路径模板，{id} = article_id, {url} = 完整URL编码
    OPEN_API_PATHS = [
        # === oEmbed / 嵌入接口 ===
        ("/api/oembed?url={url}", "oembed", "json"),
        ("/oembed?url={url}", "oembed_html", "json"),

        # === RSS / 订阅 ===
        ("/api/rss/article/{id}", "rss_article", "xml"),
        ("/rss/article/{id}", "rss_article_html", "xml"),
        ("/api/v4/articles/{id}/rss", "rss_v4", "xml"),
        ("/feed/article/{id}", "feed_article", "xml"),

        # === Open / Public API ===
        ("/api/open/v1/articles/{id}", "open_v1", "json"),
        ("/api/open/v2/content/{id}", "open_v2", "json"),
        ("/api/public/v1/articles/{id}", "public_v1", "json"),
        ("/api/public/v2/content/{id}", "public_v2", "json"),
        ("/api/public/articles/{id}?include=content", "public_v1_content", "json"),

        # === Syndication / 内容分发 ===
        ("/api/syndication/v1/post/{id}", "syndication_v1", "json"),
        ("/api/syndication/v1/article/{id}", "syndication_article", "json"),
        ("/api/v4/syndication/sections/{id}?include=content", "syndication_section", "json"),
        ("/syndication/content/{id}", "syndication_content", "json"),

        # === Embed / 嵌入 ===
        ("/api/embed/article/{id}", "embed_api", "json"),
        ("/embed/article/{id}", "embed_html", "html"),
        ("/api/v4/articles/{id}/embed", "embed_v4", "json"),

        # === SEO / 预渲染 ===
        ("/api/seo/content/{id}", "seo_api", "json"),
        ("/seo/paid/{id}", "seo_paid", "html"),
        ("/api/seo/paid/{id}", "seo_paid_api", "json"),
        ("/_next/data/{id}.json", "next_data", "json"),
        ("/api/v4/entries/{id}/content", "entries_content", "json"),

        # === AppCloud / 内部公开API ===
        ("/appcloud/v4/articles/{id}?include=content", "appcloud_v4", "json"),
        ("/appcloud/api/v4/articles/{id}?include=content", "appcloud_api", "json"),

        # === 专栏相关公开接口 ===
        ("/api/v4/posts/{id}?include=content", "posts_v4", "json"),
        ("/api/v3/posts/{id}?include=content", "posts_v3", "json"),
        ("/api/articles/{id}", "articles_api", "json"),

        # === Market/付费内容公开接口 ===
        ("/api/v4/market/sections/{id}?include=content", "market_section", "json"),
        ("/api/v4/market/sections/{id}/content", "market_content", "json"),
        ("/api/market/sections/{id}?include=content", "market_section_no_v4", "json"),
        ("/market/sections/{id}?include=content", "market_section_html", "html"),

        # === Share / 分享接口（通常返回完整内容用于分享页渲染）===
        ("/api/v4/share/articles/{id}", "share_v4", "json"),
        ("/share/article/{id}", "share_html", "html"),
        ("/api/v4/market/sections/{id}/share", "share_market", "json"),

        # === AMP / 移动加速页 ===
        ("/api/v4/amp/article/{id}", "amp_api", "json"),
        ("/amp/p/{id}", "amp_html", "html"),

        # === 打印/阅读模式 ===
        ("/api/v4/articles/{id}/print", "print_api", "json"),
        ("/article/print/{id}", "print_html", "html"),
    ]

    # 多种请求头组合（增加命中率）
    HEADER_PROFILES = [
        {
            "name": "default_json",
            "headers": {
                "Accept": "application/json, text/plain, */*",
                "Referer": "https://www.zhihu.com/",
            },
        },
        {
            "name": "seo_bot",
            "headers": {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            },
        },
        {
            "name": "rss_reader",
            "headers": {
                "Accept": "application/rss+xml, application/xml, text/xml",
                "User-Agent": "Feedly/1.0 (+http://www.feedly.com/fetcher.html)",
            },
        },
        {
            "name": "embed_view",
            "headers": {
                "Accept": "text/html,application/xhtml+xml",
                "Referer": "https://link.zhihu.com/",
                "X-Requested-With": "IFrame",
            },
        },
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._async_client: Optional[httpx.AsyncClient] = None

    async def _probe(self, url: str, article_id: Dict,
                     result: EngineResult) -> EngineResult:
        parser = self._get_parser()
        id_info = article_id if article_id else {}
        if id_info.get("type") == "unknown" or not id_info.get("id"):
            id_info = parser.extract_article_id(url)

        art_id = id_info.get("id")
        col_id = id_info.get("column_id")
        art_type = id_info.get("type", "unknown")

        if not art_id:
            result.error = "无法提取文章ID"
            return result

        self.logger.info(f"  文章类型: {art_type}, id={art_id}")

        # 构建待测试的端点URL列表
        encoded_url = quote(url, safe='')
        endpoints = []
        for path_tmpl, tag, resp_type in self.OPEN_API_PATHS:
            path = path_tmpl.replace("{id}", art_id)
            path = path.replace("{url}", encoded_url)
            if col_id:
                path = path.replace("{column_id}", col_id)
            if "{" in path and "}" in path:
                continue  # 仍有未替换的占位符，跳过
            endpoints.append({
                "url": f"https://www.zhihu.com{path}",
                "tag": tag,
                "resp_type": resp_type,
            })

        # 额外：尝试www.zhihu.com的直接文章路径（如果是专栏/文章类型）
        if art_type in ("post", "article"):
            endpoints.append({
                "url": f"https://zhuanlan.zhihu.com/p/{art_id}?include=content",
                "tag": "zhuanlan_direct",
                "resp_type": "html",
            })

        self.logger.info(f"  准备枚举 {len(endpoints)} 个开放API端点，"
                         f"使用 {len(self.HEADER_PROFILES)} 种请求头Profile...")

        # 并发探测（使用信号量控制并发）
        sem = asyncio.Semaphore(8)
        best_content = None
        found_bypasses = []
        tested = 0

        async def test_endpoint(ep: Dict):
            nonlocal best_content, tested
            async with sem:
                tested += 1
                for hp in self.HEADER_PROFILES:
                    try:
                        resp = await self._request(ep["url"], hp["headers"])
                        if not resp or resp["status"] != 200:
                            continue
                        text = resp.get("text", "")
                        if len(text) < 200:
                            continue

                        parsed = None
                        if ep["resp_type"] == "json" or text.strip().startswith(("{","[")):
                            try:
                                data = json.loads(text)
                                parsed = parser.parse_json_api(data, url=resp.get("url", ep["url"]),
                                                               engine_name=self.name)
                            except (json.JSONDecodeError, Exception):
                                parsed = parser.parse_html(text, url=resp.get("url", ep["url"]),
                                                           engine_name=self.name)
                        else:
                            parsed = parser.parse_html(text, url=resp.get("url", ep["url"]),
                                                       engine_name=self.name)

                        if parsed and self._is_significant_content(parsed):
                            parsed.metadata["endpoint"] = ep["tag"]
                            parsed.metadata["header_profile"] = hp["name"]
                            parsed.metadata["bypass_method"] = f"open_api:{ep['tag']}"
                            found_bypasses.append({
                                "endpoint": ep["tag"],
                                "url": ep["url"][:80],
                                "header": hp["name"],
                                "cn_words": parsed.word_count_cn,
                                "is_complete": not parsed.is_truncated,
                            })
                            if best_content is None or parsed.word_count_cn > best_content.word_count_cn:
                                best_content = parsed
                            if parsed.word_count_cn >= config.COMPLETE_CONTENT_LENGTH and not parsed.is_truncated:
                                return  # 找到完整内容，提前结束该端点
                    except Exception as e:
                        self.logger.debug(f"  端点 {ep['tag']} 测试失败: {str(e)[:50]}")
                    await asyncio.sleep(0.05)

        tasks = [test_endpoint(ep) for ep in endpoints]
        await asyncio.gather(*tasks, return_exceptions=True)

        if best_content:
            result.success = True
            result.content = best_content
            if best_content.word_count_cn >= config.COMPLETE_CONTENT_LENGTH and not best_content.is_truncated:
                result.bypass_found = True
                result.bypass_method = (
                    f"开放接口绕过: {best_content.metadata.get('endpoint', 'unknown')} "
                    f"({best_content.metadata.get('header_profile', '')}) "
                    f"无Cookie返回 {best_content.word_count_cn} 字完整内容"
                )
            else:
                result.bypass_method = (
                    f"开放接口部分内容: {best_content.metadata.get('endpoint', 'unknown')} "
                    f"{best_content.word_count_cn} 字"
                )

        result.details = {
            "article_type": art_type,
            "article_id": art_id,
            "total_endpoints": len(endpoints),
            "tested": tested,
            "header_profiles": [hp["name"] for hp in self.HEADER_PROFILES],
            "bypasses": found_bypasses[:15],
        }
        return result

    async def _request(self, url: str, extra_headers: Dict) -> Optional[Dict]:
        try:
            client = await self._get_client()
            headers = dict(config.DEFAULT_HEADERS_DESKTOP)
            headers.update(extra_headers)
            self._increment_requests()
            resp = await client.get(url, headers=headers, timeout=10, follow_redirects=True)
            return {
                "status": resp.status_code,
                "text": resp.text,
                "headers": dict(resp.headers),
                "url": str(resp.url),
            }
        except Exception as e:
            self.logger.debug(f"请求失败 {url[:60]}: {str(e)[:50]}")
            return None

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._async_client:
            self._async_client = httpx.AsyncClient(
                follow_redirects=True, timeout=config.REQUEST_TIMEOUT, verify=False,
            )
        return self._async_client
