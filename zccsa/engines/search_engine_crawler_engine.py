# -*- coding: utf-8 -*-
"""
ZCCSA 搜索引擎爬虫模拟引擎（Zero-Cookie引擎）
- 模拟Googlebot/Bingbot/Baiduspider等搜索引擎爬虫
- 伪造X-Forwarded-For为爬虫IP段
- 直接请求文章URL，检测是否返回完整内容（SEO配置不当）
- 权重：80
"""
import asyncio
import logging
import random
import re
from typing import Any, Dict, List, Optional

import httpx

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class SearchEngineCrawlerEngine(BaseEngine):
    """
    搜索引擎爬虫模拟引擎
    原理：搜索引擎爬虫为索引内容被服务端特殊对待，若配置不当可能直接返回全文。
    通过伪装爬虫UA + 伪造爬虫来源IP（X-Forwarded-For）来探测SEO配置漏洞。
    """

    name = "search_engine_crawler_engine"
    description = "搜索引擎爬虫模拟（Googlebot/Bingbot/Baiduspider等）"
    default_weight = 80

    # 爬虫UA配置列表：名称、UA字符串、IP段（用于伪造X-Forwarded-For）
    CRAWLER_PROFILES = [
        {
            "name": "Googlebot-Desktop",
            "user_agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            # Googlebot 已知IP段
            "ip_ranges": [
                "66.249.{}.{}",    # Googlebot主要段
                "66.102.{}.{}",
                "74.125.{}.{}",
                "209.85.{}.{}",
                "216.239.{}.{}",
            ],
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        {
            "name": "Googlebot-Smartphone",
            "user_agent": "Mozilla/5.0 (Linux; Android 6.0.1; Nexus 5X Build/MMB29P) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.6099.130 "
                          "Mobile Safari/537.36 (compatible; Googlebot/2.1; "
                          "+http://www.google.com/bot.html)",
            "ip_ranges": ["66.249.{}.{}", "66.102.{}.{}"],
            "accept": "text/html,application/xhtml+xml",
        },
        {
            "name": "Bingbot",
            "user_agent": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
            # Bingbot IP段
            "ip_ranges": [
                "157.55.{}.{}",
                "207.46.{}.{}",
                "13.66.{}.{}",
                "40.77.{}.{}",
                "52.168.{}.{}",
            ],
            "accept": "text/html,application/xhtml+xml",
        },
        {
            "name": "Bingbot-Mobile",
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                          "Mobile/15E148 Safari/604.1 (compatible; bingbot/2.0; "
                          "+http://www.bing.com/bingbot.htm)",
            "ip_ranges": ["207.46.{}.{}", "157.55.{}.{}"],
            "accept": "text/html,application/xhtml+xml",
        },
        {
            "name": "Baiduspider",
            "user_agent": "Mozilla/5.0 (compatible; Baiduspider/2.0; "
                          "+http://www.baidu.com/search/spider.html)",
            # 百度爬虫IP段
            "ip_ranges": [
                "123.125.{}.{}",
                "220.181.{}.{}",
                "111.206.{}.{}",
                "180.149.{}.{}",
                "110.242.{}.{}",
            ],
            "accept": "text/html,application/xhtml+xml",
        },
        {
            "name": "Baiduspider-render",
            "user_agent": "Mozilla/5.0 (compatible; Baiduspider-render/2.0; "
                          "+http://www.baidu.com/search/spider.html)",
            "ip_ranges": ["123.125.{}.{}", "220.181.{}.{}"],
            "accept": "text/html,application/xhtml+xml",
        },
        {
            "name": "YandexBot",
            "user_agent": "Mozilla/5.0 (compatible; YandexBot/3.0; +http://yandex.com/bots)",
            # Yandex IP段
            "ip_ranges": [
                "77.88.{}.{}",
                "5.255.{}.{}",
                "178.154.{}.{}",
            ],
            "accept": "text/html,application/xhtml+xml",
        },
        {
            "name": "Sogou-spider",
            "user_agent": "Sogou web spider/4.0(+http://www.sogou.com/docs/help/webmasters.htm#07)",
            # 搜狗爬虫IP段
            "ip_ranges": [
                "123.126.{}.{}",
                "220.181.{}.{}",
                "183.232.{}.{}",
            ],
            "accept": "text/html,application/xhtml+xml",
        },
        {
            "name": "360Spider",
            "user_agent": "Mozilla/5.0 (compatible; 360Spider/2.0; +http://www.so.com/help/help_3_2.html)",
            "ip_ranges": [
                "180.153.{}.{}",
                "101.226.{}.{}",
            ],
            "accept": "text/html",
        },
        {
            "name": "Bytespider-头条",
            "user_agent": "Mozilla/5.0 (compatible; Bytespider; spider-feedback@bytedance.com) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            # 字节爬虫
            "ip_ranges": [
                "110.249.{}.{}",
                "220.243.{}.{}",
            ],
            "accept": "text/html",
        },
        {
            "name": "DuckDuckBot",
            "user_agent": "DuckDuckBot/1.1; (+http://duckduckgo.com/duckduckbot.html)",
            "ip_ranges": ["23.21.{}.{}", "50.16.{}.{}", "54.208.{}.{}"],
            "accept": "text/html",
        },
        {
            "name": "Yahoo!-Slurp",
            "user_agent": "Mozilla/5.0 (compatible; Yahoo! Slurp; http://help.yahoo.com/help/us/ysearch/slurp)",
            "ip_ranges": ["72.30.{}.{}", "98.136.{}.{}"],
            "accept": "text/html",
        },
    ]

    # 额外的爬虫信任头组合
    EXTRA_TRUST_HEADERS = [
        {},  # 无额外头（仅UA+IP）
        {"X-Crawler": "1"},
        {"X-Forwarded-For": None},  # 占位，实际在循环中填充
        {"X-Real-IP": None},
        {"Via": "HTTP/1.1 Google", "X-Forwarded-Host": "www.google.com"},
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
        art_type = id_info.get("type", "unknown")

        if not art_id:
            result.error = "无法提取文章ID"
            return result

        self.logger.info(f"  文章类型: {art_type}, id={art_id}")

        # 1. 基线响应（标准浏览器UA，非爬虫）
        baseline = await self._request(url, dict(config.DEFAULT_HEADERS_DESKTOP))
        baseline_cn = self._count_cn(baseline.get("text", "")) if baseline else 0
        baseline_status = baseline["status"] if baseline else 0
        self.logger.info(f"  基线状态: {baseline_status}, 中文字数: {baseline_cn}")

        # 2. 并发测试所有爬虫Profile
        self.logger.info(f"  并发模拟 {len(self.CRAWLER_PROFILES)} 种搜索引擎爬虫...")
        best_content = None
        found_bypasses = []
        sem = asyncio.Semaphore(6)

        async def test_crawler(profile: Dict):
            nonlocal best_content
            async with sem:
                # 生成伪造IP
                fake_ip = self._generate_crawler_ip(profile["ip_ranges"])
                headers = {
                    "User-Agent": profile["user_agent"],
                    "Accept": profile["accept"],
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                    "X-Forwarded-For": fake_ip,
                    "X-Real-IP": fake_ip,
                    "Referer": "https://www.google.com/",
                }

                # a) 基础爬虫请求（UA+XFF）
                resp = await self._request(url, headers)
                if resp and resp["status"] == 200:
                    text = resp["text"]
                    cn = self._count_cn(text)
                    if cn > baseline_cn * 1.3 or cn > 500:
                        parsed = parser.parse_html(text, url=resp.get("url", url),
                                                   engine_name=self.name)
                        if self._is_significant_content(parsed):
                            parsed.metadata["crawler"] = profile["name"]
                            parsed.metadata["bypass_method"] = f"crawler_ua:{profile['name']}"
                            parsed.metadata["fake_ip"] = fake_ip
                            bypass_info = {
                                "crawler": profile["name"],
                                "method": "crawler_spoof",
                                "fake_ip": fake_ip,
                                "cn_words": parsed.word_count_cn,
                                "url": resp.get("url", url)[:80],
                            }
                            found_bypasses.append(bypass_info)
                            if best_content is None or parsed.word_count_cn > best_content.word_count_cn:
                                best_content = parsed
                            if parsed.word_count_cn >= config.COMPLETE_CONTENT_LENGTH and not parsed.is_truncated:
                                return  # 找到完整内容

                # b) 添加额外信任头的变体
                for extra in self.EXTRA_TRUST_HEADERS[1:3]:  # 只测试X-Crawler和Via两个变体，避免过多请求
                    h = dict(headers)
                    h.update(extra)
                    resp2 = await self._request(url, h)
                    if resp2 and resp2["status"] == 200:
                        text2 = resp2["text"]
                        cn2 = self._count_cn(text2)
                        if cn2 > baseline_cn * 1.3 and cn2 > 300:
                            parsed2 = parser.parse_html(text2, url=resp2.get("url", url),
                                                        engine_name=self.name)
                            if self._is_significant_content(parsed2):
                                parsed2.metadata["crawler"] = profile["name"]
                                parsed2.metadata["bypass_method"] = f"crawler_ua_headers:{profile['name']}"
                                found_bypasses.append({
                                    "crawler": profile["name"],
                                    "method": "crawler_headers",
                                    "cn_words": parsed2.word_count_cn,
                                })
                                if best_content is None or parsed2.word_count_cn > best_content.word_count_cn:
                                    best_content = parsed2

        tasks = [test_crawler(p) for p in self.CRAWLER_PROFILES]
        await asyncio.gather(*tasks, return_exceptions=True)

        if best_content:
            result.success = True
            result.content = best_content
            if best_content.word_count_cn >= config.COMPLETE_CONTENT_LENGTH and not best_content.is_truncated:
                result.bypass_found = True
                crawler_name = best_content.metadata.get("crawler", "unknown")
                result.bypass_method = (
                    f"搜索引擎爬虫绕过: 模拟{crawler_name} "
                    f"（UA+IP伪造）零Cookie获取 {best_content.word_count_cn} 字完整内容"
                )
            else:
                result.bypass_method = (
                    f"爬虫模式部分内容: {best_content.metadata.get('crawler', 'unknown')} "
                    f"{best_content.word_count_cn} 字"
                )

        result.details = {
            "baseline_status": baseline_status,
            "baseline_cn_words": baseline_cn,
            "crawlers_tested": len(self.CRAWLER_PROFILES),
            "bypasses": found_bypasses[:15],
        }
        return result

    @staticmethod
    def _generate_crawler_ip(ip_ranges: List[str]) -> str:
        """从爬虫IP段模板生成随机IP"""
        template = random.choice(ip_ranges)
        parts = template.format(random.randint(0, 255), random.randint(0, 255))
        return parts

    async def _request(self, url: str, headers: Dict) -> Optional[Dict]:
        try:
            client = await self._get_client()
            self._increment_requests()
            resp = await client.get(url, headers=dict(headers), timeout=10, follow_redirects=True)
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

    @staticmethod
    def _count_cn(text: str) -> int:
        return len(re.findall(r'[\u4e00-\u9fff]', text))
