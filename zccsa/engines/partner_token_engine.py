# -*- coding: utf-8 -*-
"""
ZCCSA 第三方合作平台信任链分析引擎
- 分析知乎与微信读书等合作平台的接口调用模式
- 探测是否存在非用户级的平台Token可用于内容拉取
"""
import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class PartnerTokenEngine(BaseEngine):
    """
    第三方平台信任链分析引擎
    原理：内容平台通常会与第三方（微信读书、百度、今日头条等）签订内容分发协议，
    这些合作方通过平台级Token拉取内容，可能存在信任链脆弱点。
    """

    name = "partner_token_engine"
    description = "第三方平台信任链分析"
    default_weight = 50

    # 合作平台标识与对应请求头
    PARTNER_PROFILES = {
        "wechat_read": {
            "name": "微信读书",
            "headers": {
                "Referer": "https://weread.qq.com/",
                "Origin": "https://weread.qq.com",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                              "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                              "Mobile/15E148 Safari/604.1",
                "X-Weread-Client": "weread-ios",
                "X-Requested-With": "com.tencent.weread",
            },
            "trust_headers": [
                {"X-Partner-Id": "weread"},
                {"X-Channel": "wechat_read"},
                {"X-Distribution-Channel": "weread"},
            ],
        },
        "baidu": {
            "name": "百度搜索/小程序",
            "headers": {
                "Referer": "https://www.baidu.com/",
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                              "AppleWebKit/605.1.15 Mobile/15E148 Safari/604.1 "
                              "baiduboxapp/13.0",
                "X-Requested-With": "com.baidu.searchbox",
            },
            "trust_headers": [
                {"X-Partner-Id": "baidu"},
                {"X-From-Baidu": "1"},
                {"X-Baidu-App": "1"},
            ],
        },
        "toutiao": {
            "name": "今日头条",
            "headers": {
                "Referer": "https://www.toutiao.com/",
                "User-Agent": "Mozilla/5.0 (Linux; Android 13) AppleWebKit/537.36 "
                              "Chrome/120.0.0.0 Mobile Safari/537.36",
            },
            "trust_headers": [
                {"X-Partner-Id": "toutiao"},
                {"X-Channel": "toutiao"},
            ],
        },
        "sogou": {
            "name": "搜狗搜索（微信内容搜索）",
            "headers": {
                "Referer": "https://weixin.sogou.com/",
                "User-Agent": "Sogou web spider/4.0(+http://www.sogou.com/docs/help/webmasters.htm#07)",
            },
            "trust_headers": [
                {"X-Partner-Id": "sogou"},
                {"X-Crawler": "sogou"},
            ],
        },
        "search_bot": {
            "name": "搜索引擎爬虫",
            "headers": {
                "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
                "Accept": "text/html,application/xhtml+xml",
            },
            "trust_headers": [
                {"X-Crawler": "googlebot"},
            ],
        },
    }

    # 合作方API端点猜测
    PARTNER_API_PATHS = [
        "/api/v4/market/partner/{partner}/sections/{id}",
        "/api/v4/market/partner/content/{id}",
        "/api/v4/partner/{partner}/content/{id}",
        "/api/partner/content/{id}",
        "/partner/content/{id}",
        "/api/v4/market/distribution/{id}",
        "/dist/content/{id}",
    ]

    async def _probe(self, url: str, article_id: Dict,
                     result: EngineResult) -> EngineResult:
        parser = self._get_parser()
        art_id = article_id.get("id")
        col_id = article_id.get("column_id")
        if not art_id:
            id_info = parser.extract_article_id(url)
            art_id = id_info.get("id")
            col_id = id_info.get("column_id")

        if not art_id:
            result.error = "无法提取文章ID"
            return result

        # 1. 基线响应（标准浏览器头，无合作标识）
        self.logger.info("  [1/2] 获取基线响应...")
        baseline = await self._make_request(url, config.DEFAULT_HEADERS_DESKTOP)
        baseline_cn = len(re.findall(r'[\u4e00-\u9fff]', baseline.get("text", ""))) if baseline else 0

        # 2. 逐个尝试合作平台Profile
        self.logger.info(f"  [2/2] 测试 {len(self.PARTNER_PROFILES)} 个合作平台Profile...")
        best = None
        found_bypasses = []

        for partner_key, profile in self.PARTNER_PROFILES.items():
            # 2.1 用平台UA访问原URL
            try:
                resp = await self._make_request(url, profile["headers"])
                if resp and resp["status"] == 200:
                    cn = len(re.findall(r'[\u4e00-\u9fff]', resp["text"]))
                    parsed = parser.parse_html(resp["text"], url=url, engine_name=self.name)
                    parsed.metadata["partner"] = profile["name"]
                    parsed.metadata["bypass_method"] = f"partner_ua:{partner_key}"

                    if cn > baseline_cn * 1.5 and self._is_significant_content(parsed):
                        found_bypasses.append({
                            "partner": profile["name"],
                            "method": "user_agent_spoof",
                            "cn_words": cn,
                        })
                        if best is None or cn > best.word_count_cn:
                            best = parsed

                # 2.2 注入信任头
                for trust_h in profile.get("trust_headers", []):
                    h = dict(profile["headers"])
                    h.update(trust_h)
                    resp2 = await self._make_request(url, h)
                    if resp2 and resp2["status"] == 200:
                        cn2 = len(re.findall(r'[\u4e00-\u9fff]', resp2["text"]))
                        parsed2 = parser.parse_html(resp2["text"], url=url, engine_name=self.name)
                        parsed2.metadata["partner"] = profile["name"]
                        parsed2.metadata["bypass_method"] = f"trust_header:{trust_h}"
                        if cn2 > baseline_cn * 1.5 and self._is_significant_content(parsed2):
                            found_bypasses.append({
                                "partner": profile["name"],
                                "method": f"trust_header: {list(trust_h.keys())[0]}",
                                "cn_words": cn2,
                            })
                            if best is None or cn2 > best.word_count_cn:
                                best = parsed2
            except Exception as e:
                self.logger.debug(f"  {profile['name']}测试失败: {e}")

            # 2.3 尝试合作方API路径
            for path_tmpl in self.PARTNER_API_PATHS[:3]:
                api_path = path_tmpl.replace("{id}", art_id)
                api_path = api_path.replace("{partner}", partner_key)
                if col_id:
                    api_path = api_path.replace("{column_id}", col_id)
                if "{" in api_path:
                    continue
                api_url = f"https://www.zhihu.com{api_path}"
                try:
                    api_h = dict(profile["headers"])
                    api_h["Accept"] = "application/json"
                    resp3 = await self._make_request(api_url, api_h)
                    if resp3 and resp3["status"] == 200 and len(resp3["text"]) > 100:
                        try:
                            data = json.loads(resp3["text"])
                            parsed3 = parser.parse_json_api(data, url=api_url, engine_name=self.name)
                            if self._is_significant_content(parsed3):
                                found_bypasses.append({
                                    "partner": profile["name"],
                                    "method": f"api_endpoint: {api_path[:60]}",
                                    "cn_words": parsed3.word_count_cn,
                                })
                                if best is None or parsed3.word_count_cn > best.word_count_cn:
                                    best = parsed3
                        except Exception:
                            pass
                except Exception:
                    pass

            await asyncio.sleep(0.3)

        if best:
            result.success = True
            result.content = best
            if best.word_count_cn >= config.COMPLETE_CONTENT_LENGTH:
                result.bypass_found = True
                result.bypass_method = (
                    f"第三方信任链绕过: {best.metadata.get('partner', 'unknown')} "
                    f"via {best.metadata.get('bypass_method', 'unknown')}"
                )

        result.details = {
            "baseline_cn_words": baseline_cn,
            "partners_tested": list(self.PARTNER_PROFILES.keys()),
            "bypasses_found": found_bypasses,
        }
        return result

    async def _make_request(self, url: str, headers: Dict) -> Optional[Dict]:
        """发起单个HTTP请求"""
        try:
            client = await self._get_async_client()
            self._increment_requests()
            resp = await client.get(url, headers=dict(headers), timeout=10,
                                    follow_redirects=True)
            return {
                "status": resp.status_code,
                "text": resp.text,
                "headers": dict(resp.headers),
                "url": str(resp.url),
            }
        except Exception as e:
            self.logger.debug(f"请求失败 {url[:50]}: {e}")
            return None

    async def _get_async_client(self) -> httpx.AsyncClient:
        if not hasattr(self, '_async_client') or self._async_client is None:
            self._async_client = httpx.AsyncClient(
                follow_redirects=True, timeout=config.REQUEST_TIMEOUT,
                verify=False, http2=True,
            )
        return self._async_client
