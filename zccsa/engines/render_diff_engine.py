# -*- coding: utf-8 -*-
"""
ZCCSA 多端渲染差异分析引擎
- 对比Web端、移动H5、App端对同一内容的响应差异
- 尝试不同端的API路径和请求头，检测是否存在端间权限差异
"""
import asyncio
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

import httpx

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class RenderDiffEngine(BaseEngine):
    """
    多端渲染差异分析引擎
    原理：内容平台通常对不同端（PC Web、移动H5、App、小程序）使用不同的渲染逻辑
    和API接口，可能存在某一端的权限校验较弱或返回完整内容的情况。
    """

    name = "render_diff_engine"
    description = "多端渲染差异分析（Web/H5/App/M端对比）"
    default_weight = 70

    # 各端配置
    PROFILES = {
        "desktop": {
            "name": "PC Web端",
            "headers": dict(config.DEFAULT_HEADERS_DESKTOP),
            "url_transform": lambda u: u,
        },
        "mobile_h5": {
            "name": "移动H5端",
            "headers": dict(config.DEFAULT_HEADERS_MOBILE),
            # 知乎移动H5通常使用 zhihu.com/market/... 或 m.zhihu.com
            "url_transform": lambda u: RenderDiffEngine._to_mobile_url(u),
        },
        "app_ios": {
            "name": "iOS App端",
            "headers": {
                "User-Agent": "ZhihuHybrid-iOS/8.10.0 (com.zhihu.ios; build:2400; iOS 16.0.0) "
                              "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                              "AppleWebKit/605.1.15 Mobile/15E148",
                "Accept": "*/*",
                "Accept-Language": "zh-Hans-CN;q=1",
                "X-App-Version": "8.10.0",
                "X-App-Build": "2400",
                "X-App-Code": "100",
                "X-Platform": "ios",
                "X-Api-Version": "3.0.40",
                "X-App-Device": "iPhone14,5",
                "X-Network-Type": "WIFI",
            },
            "url_transform": lambda u: RenderDiffEngine._to_app_url(u),
        },
        "app_android": {
            "name": "Android App端",
            "headers": {
                "User-Agent": "ZhihuHybrid-Android/8.10.0 (com.zhihu.android; build:2400; Android 13) "
                              "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 "
                              "Chrome/120.0.0.0 Mobile Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "X-App-Version": "8.10.0",
                "X-App-Build": "2400",
                "X-App-Code": "100",
                "X-Platform": "android",
                "X-Api-Version": "3.0.40",
                "X-App-Device": "Pixel7",
                "X-Network-Type": "WIFI",
            },
            "url_transform": lambda u: RenderDiffEngine._to_app_url(u),
        },
        "m_dot": {
            "name": "m.zhihu.com M站",
            "headers": {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                              "AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh-Hans;q=0.9",
            },
            "url_transform": lambda u: RenderDiffEngine._to_m_dot_url(u),
        },
    }

    @staticmethod
    def _to_mobile_url(url: str) -> str:
        """转换为移动H5 URL"""
        parsed = urlparse(url)
        if parsed.netloc == "www.zhihu.com":
            # market/paid_column -> 移动页
            if "/market/" in parsed.path:
                return urlunparse(parsed._replace(netloc="www.zhihu.com"))
        return url

    @staticmethod
    def _to_m_dot_url(url: str) -> str:
        """转换为m.zhihu.com"""
        parsed = urlparse(url)
        if "zhihu.com" in parsed.netloc:
            return urlunparse(parsed._replace(netloc="m.zhihu.com"))
        return url

    @staticmethod
    def _to_app_url(url: str) -> str:
        """转换为App API URL"""
        parsed = urlparse(url)
        # 尝试App端API
        path = parsed.path
        if "/paid_column/" in path or "/market/paid_column/" in path:
            # 提取section id
            m = re.search(r'/section/(\d+)', path)
            col_m = re.search(r'/paid_column/(\d+)', path)
            if m and col_m:
                return f"https://api.zhihu.com/market/paid_column/{col_m.group(1)}/section/{m.group(1)}"
            if m:
                return f"https://api.zhihu.com/remix/essay/{m.group(1)}"
        if m := re.search(r'/p/(\d+)', path):
            return f"https://api.zhihu.com/articles/{m.group(1)}"
        if m := re.search(r'/answer/(\d+)', path):
            return f"https://api.zhihu.com/answers/{m.group(1)}"
        return url

    async def _probe(self, url: str, article_id: Dict,
                     result: EngineResult) -> EngineResult:
        parser = self._get_parser()
        results_by_profile = {}
        best_content = None
        profile_results = []

        # 并发测试所有端Profile
        self.logger.info(f"  对比测试 {len(self.PROFILES)} 个端Profile...")
        tasks = []
        profile_keys = list(self.PROFILES.keys())
        for key in profile_keys:
            tasks.append(self._test_profile(key, url))
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for key, resp in zip(profile_keys, responses):
            profile = self.PROFILES[key]
            if isinstance(resp, Exception):
                profile_results.append({
                    "profile": key, "name": profile["name"],
                    "error": str(resp)[:100], "cn_words": 0,
                })
                continue
            if not resp:
                profile_results.append({
                    "profile": key, "name": profile["name"],
                    "error": "无响应", "cn_words": 0,
                })
                continue

            status, text, final_url = resp
            cn_words = len(re.findall(r'[\u4e00-\u9fff]', text))

            # 解析内容
            parsed = None
            if text.strip().startswith("{") or text.strip().startswith("["):
                try:
                    import json
                    data = json.loads(text)
                    parsed = parser.parse_json_api(data, url=final_url, engine_name=self.name)
                except Exception:
                    parsed = parser.parse_html(text, url=final_url, engine_name=self.name)
            else:
                parsed = parser.parse_html(text, url=final_url, engine_name=self.name)

            parsed.metadata["profile"] = key
            parsed.metadata["profile_name"] = profile["name"]
            results_by_profile[key] = parsed

            profile_results.append({
                "profile": key,
                "name": profile["name"],
                "status": status,
                "cn_words": cn_words,
                "truncated": parsed.is_truncated if parsed else True,
                "final_url": final_url[:80],
            })

            self.logger.info(f"    {profile['name']}: {cn_words} 中文字, "
                             f"截断={parsed.is_truncated if parsed else 'N/A'}")

            if parsed and self._is_significant_content(parsed):
                if best_content is None or parsed.word_count_cn > best_content.word_count_cn:
                    best_content = parsed

        # 分析差异：是否某端返回了完整内容而其他端截断
        desktop_cn = 0
        if "desktop" in results_by_profile:
            desktop_cn = results_by_profile["desktop"].word_count_cn

        if best_content and best_content.word_count_cn > desktop_cn * 1.5:
            profile_name = best_content.metadata.get("profile_name", "unknown")
            if best_content.word_count_cn >= config.COMPLETE_CONTENT_LENGTH:
                result.bypass_found = True
                result.bypass_method = (
                    f"多端差异绕过: {profile_name}返回 {best_content.word_count_cn} 字完整内容，"
                    f"而PC Web端仅返回 {desktop_cn} 字"
                )

        if best_content:
            result.success = True
            result.content = best_content

        result.details = {
            "profiles_tested": len(self.PROFILES),
            "profile_results": profile_results,
            "desktop_cn_words": desktop_cn,
            "best_profile": best_content.metadata.get("profile") if best_content else None,
        }
        return result

    async def _test_profile(self, key: str, url: str) -> Optional[Tuple[int, str, str]]:
        """测试单个端Profile"""
        profile = self.PROFILES[key]
        target_url = profile["url_transform"](url)
        client = await self._get_async_client()
        headers = dict(profile["headers"])
        if "api.zhihu.com" in target_url:
            headers["Host"] = "api.zhihu.com"
            headers["Accept"] = "application/json"
        try:
            self._increment_requests()
            resp = await client.get(target_url, headers=headers, timeout=12,
                                    follow_redirects=True)
            return resp.status_code, resp.text, str(resp.url)
        except Exception as e:
            self.logger.debug(f"  {profile['name']}请求失败: {e}")
            return None

    async def _get_async_client(self) -> httpx.AsyncClient:
        if not hasattr(self, '_async_client') or self._async_client is None:
            self._async_client = httpx.AsyncClient(
                follow_redirects=True, timeout=15, verify=False, http2=True,
            )
        return self._async_client
