# -*- coding: utf-8 -*-
"""
ZCCSA 历史快照检索引擎
- 调用Wayback Machine API查询历史快照
- 使用搜索引擎缓存查询文章历史版本
- 检查是否存在付费墙上线前的完整内容存档
"""
import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import httpx

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class SnapshotEngine(BaseEngine):
    """
    历史快照检索引擎
    原理：很多付费内容在上线前曾是免费内容，或被搜索引擎/存档网站缓存了完整版本。
    Wayback Machine、Google Cache、百度快照等可能保留完整内容。
    """

    name = "snapshot_engine"
    description = "历史快照检索（Wayback Machine + 搜索引擎缓存）"
    default_weight = 60

    # Wayback CDX API
    WAYBACK_CDX = "https://web.archive.org/cdx/search/cdx"
    WAYBACK_RAW = "https://web.archive.org/web/{timestamp}id_/{url}"
    # 搜索引擎缓存
    GOOGLE_CACHE = "https://webcache.googleusercontent.com/search?q=cache:{url}"
    # 其他存档服务
    ARCHIVE_TODAY = "https://archive.ph/newest/{url}"

    async def _probe(self, url: str, article_id: Dict,
                     result: EngineResult) -> EngineResult:
        parser = self._get_parser()
        best_content = None
        snapshots_found = []
        sources_checked = 0

        # ========== 1. Wayback Machine 查询 ==========
        self.logger.info("  [1/3] 查询Wayback Machine...")
        try:
            wb_snapshots = await self._query_wayback(url)
            sources_checked += 1
            self.logger.info(f"    发现 {len(wb_snapshots)} 个快照")

            # 只尝试最近的几个快照（按时间倒序）
            for snap in wb_snapshots[:5]:
                ts = snap["timestamp"]
                snap_url = self.WAYBACK_RAW.format(timestamp=ts, url=quote(url, safe=''))
                try:
                    content = await self._fetch_snapshot(snap_url, "wayback")
                    if content and self._is_significant_content(content):
                        content.metadata["snapshot_timestamp"] = ts
                        content.metadata["source"] = "wayback_machine"
                        snapshots_found.append({
                            "source": "wayback",
                            "timestamp": ts,
                            "url": snap_url,
                            "cn_words": content.word_count_cn,
                        })
                        if best_content is None or content.word_count_cn > best_content.word_count_cn:
                            best_content = content
                        # 找到完整内容就停止
                        if not content.is_truncated and content.word_count_cn >= 1000:
                            break
                except Exception as e:
                    self.logger.debug(f"    快照获取失败: {e}")
                await asyncio.sleep(0.5)
        except Exception as e:
            self.logger.warning(f"    Wayback查询失败: {e}")

        # ========== 2. Archive.ph 查询 ==========
        self.logger.info("  [2/3] 查询Archive.ph...")
        try:
            sources_checked += 1
            archive_url = self.ARCHIVE_TODAY.format(url=quote(url, safe=''))
            content = await self._fetch_snapshot(archive_url, "archive.ph")
            if content and self._is_significant_content(content):
                content.metadata["source"] = "archive.ph"
                snapshots_found.append({
                    "source": "archive.ph",
                    "url": archive_url,
                    "cn_words": content.word_count_cn,
                })
                if best_content is None or content.word_count_cn > best_content.word_count_cn:
                    best_content = content
        except Exception as e:
            self.logger.debug(f"    Archive.ph查询失败: {e}")

        # ========== 3. 搜索引擎缓存（Google Cache / Bing搜索存档） ==========
        self.logger.info("  [3/3] 查询搜索引擎缓存...")
        try:
            sources_checked += 1
            # 搜索标题关键词找缓存
            title_hint = article_id.get("title", "")
            if not title_hint:
                parsed = urlparse(url)
                title_hint = parsed.path.strip("/").replace("/", " ")
            search_queries = [
                f"site:zhihu.com {title_hint}",
                f"site:web.archive.org zhihu {title_hint}",
                f"cache:{url}",
            ]
            for q in search_queries[:2]:
                try:
                    search_results = await self._search_bing(q)
                    for sr in search_results[:3]:
                        sr_url = sr.get("url", "")
                        if "zhihu.com" in sr_url or "archive" in sr_url:
                            try:
                                c = await self._fetch_snapshot(sr_url, "search_result")
                                if c and self._is_significant_content(c):
                                    c.metadata["source"] = "search_result"
                                    snapshots_found.append({
                                        "source": "search",
                                        "url": sr_url,
                                        "cn_words": c.word_count_cn,
                                    })
                                    if best_content is None or c.word_count_cn > best_content.word_count_cn:
                                        best_content = c
                            except Exception:
                                pass
                        await asyncio.sleep(0.3)
                except Exception as e:
                    self.logger.debug(f"    搜索失败: {e}")
        except Exception as e:
            self.logger.debug(f"    搜索引擎查询失败: {e}")

        if best_content:
            result.success = True
            result.content = best_content
            if best_content.word_count_cn >= config.COMPLETE_CONTENT_LENGTH:
                result.bypass_found = True
                result.bypass_method = (
                    f"历史快照绕过: 通过{best_content.metadata.get('source', 'unknown')}"
                    f"获取到付费墙上线前的完整内容存档({best_content.word_count_cn}字)"
                )

        result.details = {
            "sources_checked": sources_checked,
            "snapshots_found": len(snapshots_found),
            "snapshots": snapshots_found[:10],
        }
        return result

    async def _query_wayback(self, url: str) -> List[Dict]:
        """查询Wayback Machine CDX API获取快照列表"""
        client = await self._get_async_client()
        params = {
            "url": url,
            "output": "json",
            "fl": "timestamp,original,statuscode,mimetype",
            "filter": ["statuscode:200", "mimetype:text/html"],
            "limit": 20,
            "collapse": "timestamp:8",  # 按天去重
            "from": "2020",
        }
        self._increment_requests()
        resp = await client.get(self.WAYBACK_CDX, params=params, timeout=15)
        if resp.status_code != 200:
            return []
        try:
            data = resp.json()
        except Exception:
            return []
        if not data or len(data) < 2:
            return []
        # 第一行是字段名
        headers = data[0]
        rows = data[1:]
        results = []
        for row in rows:
            item = dict(zip(headers, row))
            results.append(item)
        # 按时间倒序（最新在前）
        results.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
        return results

    async def _fetch_snapshot(self, url: str, source: str) -> Optional[Any]:
        """获取快照页面内容"""
        client = await self._get_async_client()
        headers = dict(config.DEFAULT_HEADERS_DESKTOP)
        headers["Accept"] = "text/html,application/xhtml+xml"
        if "archive.org" in url:
            headers["Referer"] = "https://web.archive.org/"
        self._increment_requests()
        resp = await client.get(url, headers=headers, timeout=20, follow_redirects=True)
        if resp.status_code != 200 or len(resp.text) < 500:
            return None
        # 移除Wayback工具栏
        text = resp.text
        text = re.sub(r'<!-- BEGIN WAYBACK TOOLBAR INSERT.*?END WAYBACK TOOLBAR INSERT -->',
                      '', text, flags=re.DOTALL)
        text = re.sub(r'<script[^>]*src="[^"]*archive\.org[^"]*"[^>]*></script>', '', text)
        text = re.sub(r'<div id="wm-ipp-base".*?</div>', '', text, flags=re.DOTALL)
        parser = self._get_parser()
        content = parser.parse_html(text, url=url, engine_name=self.name)
        return content

    async def _search_bing(self, query: str) -> List[Dict]:
        """Bing搜索（找存档/缓存链接）"""
        client = await self._get_async_client()
        headers = dict(config.DEFAULT_HEADERS_DESKTOP)
        self._increment_requests()
        resp = await client.get(
            "https://www.bing.com/search",
            params={"q": query, "setlang": "zh-CN"},
            headers=headers, timeout=10, follow_redirects=True,
        )
        if resp.status_code != 200:
            return []
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(resp.text, "lxml")
        results = []
        for a in soup.select("li.b_algo h2 a, li.b_algo a"):
            href = a.get("href", "")
            if href.startswith("http"):
                results.append({"url": href, "title": a.get_text(strip=True)})
        return results[:10]

    async def _get_async_client(self) -> httpx.AsyncClient:
        if not hasattr(self, '_async_client') or self._async_client is None:
            self._async_client = httpx.AsyncClient(
                follow_redirects=True, timeout=20, verify=False, http2=True,
            )
        return self._async_client
