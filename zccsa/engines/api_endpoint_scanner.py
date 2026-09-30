# -*- coding: utf-8 -*-
"""
ZCCSA API端点扫描引擎
- 维护已知知乎API端点列表（v1/v2/v3/v4/old/mobile等版本）
- 支持从 data/extra_api_endpoints.json 加载用户自定义端点
- 对每个端点尝试无Cookie请求
- 对比不同API版本返回内容完整性
- 标记无Cookie仍返回完整数据的端点
"""
import asyncio
import json
import logging
import os
import random
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# 外部端点文件路径（相对于项目根目录）
EXTRA_ENDPOINTS_FILE = Path(__file__).parent.parent / "data" / "extra_api_endpoints.json"


def _load_external_endpoints() -> List[str]:
    """
    从外部JSON文件加载额外的API端点。
    文件格式: ["https://.../{id}", "/api/v1/.../{column_id}/..."]
    如果文件不存在或格式错误，返回空列表。
    """
    if not EXTRA_ENDPOINTS_FILE.exists():
        logger.debug(f"外部端点文件不存在: {EXTRA_ENDPOINTS_FILE}，跳过加载")
        return []
    try:
        text = EXTRA_ENDPOINTS_FILE.read_text(encoding="utf-8").strip()
        if not text:
            return []
        data = json.loads(text)
        if not isinstance(data, list):
            logger.warning(f"外部端点文件格式错误（应为JSON数组）: {EXTRA_ENDPOINTS_FILE}")
            return []
        valid = [str(item).strip() for item in data if isinstance(item, str) and str(item).strip()]
        logger.info(f"从 {EXTRA_ENDPOINTS_FILE.name} 加载了 {len(valid)} 个外部API端点")
        return valid
    except json.JSONDecodeError as e:
        logger.warning(f"外部端点文件JSON解析失败: {e}")
        return []
    except Exception as e:
        logger.warning(f"加载外部端点文件失败: {e}")
        return []


class APIEndpointScanner(BaseEngine):
    """
    API端点扫描引擎
    原理：知乎历史API版本（v1/v2/v3）可能存在权限校验覆盖不全的问题，
    部分老版本端点可能在无Cookie状态下仍返回完整数据。
    支持从 data/extra_api_endpoints.json 动态加载用户自定义端点。
    """

    name = "api_endpoint_scanner"
    description = "API端点扫描（多版本API权限校验边界测试 + 外部端点扩展）"
    default_weight = 60

    # 额外API端点（代码内置，补充config中的列表）
    _EXTRA_ENDPOINTS = [
        # 付费内容相关
        "/api/v4/market/paid/columns/{id}",
        "/api/v4/paid-columns/{id}/sections",
        "/api/v3/market/paid/sections/{id}",
        # 老版本盐选/Remix
        "/api/v4/remix/essays/{id}",
        "/api/v3/remix/essays/{id}",
        "/remix/api/v2/essay/{id}",
        # 老版article
        "/api/v4/articles/{id}?include=data[*].content",
        "/api/v4/articles/{id}?include=content",
        "/api/v3/articles/{id}?include=content",
        # 专栏/回答
        "/api/v4/answers/{id}?include=content",
        "/api/v4/posts/{id}?include=content",
        "/api/v3/posts/{id}?include=content",
        # App端API
        "/api/v4/market/columns/{column_id}/sections/{section_id}?include=content",
        "/api/v7/articles/{id}",
        "/appview/api/paid/{id}",
        # 微信读书合作API
        "/api/v4/market/partner/weread/sections/{id}",
        # SEO/预渲染
        "/seo/paid/{id}",
        "/_next/data/{article}.json",
    ]

    # 类加载时一次性合并外部端点（避免每次实例化都读文件）
    _EXTERNAL_ENDPOINTS_CACHE: Optional[List[str]] = None

    @classmethod
    def _get_external_endpoints(cls) -> List[str]:
        """获取外部端点列表（带缓存）"""
        if cls._EXTERNAL_ENDPOINTS_CACHE is None:
            cls._EXTERNAL_ENDPOINTS_CACHE = _load_external_endpoints()
        return cls._EXTERNAL_ENDPOINTS_CACHE

    @classmethod
    def reload_external_endpoints(cls) -> int:
        """强制重新加载外部端点文件（用于热更新），返回加载数量"""
        cls._EXTERNAL_ENDPOINTS_CACHE = _load_external_endpoints()
        return len(cls._EXTERNAL_ENDPOINTS_CACHE)

    async def _probe(self, url: str, article_id: Dict,
                     result: EngineResult) -> EngineResult:
        parser = self._get_parser()
        id_info = article_id
        if not id_info or id_info.get("type") == "unknown":
            id_info = parser.extract_article_id(url)

        art_id = id_info.get("id")
        col_id = id_info.get("column_id")
        sec_id = id_info.get("section_id") or art_id
        art_type = id_info.get("type", "unknown")
        self.logger.info(f"  文章类型: {art_type}, id={art_id}, column={col_id}, section={sec_id}")

        if not art_id:
            result.error = "无法提取文章ID"
            return result

        # 构建要测试的端点URL列表
        endpoints = self._build_endpoints(art_type, art_id, col_id, sec_id)
        external_count = len(self._get_external_endpoints())
        self.logger.info(f"  准备测试 {len(endpoints)} 个API端点"
                         f"（含 {external_count} 个外部自定义端点）...")

        # 异步并发测试（无Cookie）
        no_cookie_results = await self._test_endpoints(endpoints, col_id=col_id, art_id=art_id)

        # 筛选出有内容的端点
        valid_no_cookie = [r for r in no_cookie_results if r["cn_words"] > 100]
        self.logger.info(f"  无Cookie有效响应: {len(valid_no_cookie)} / {len(endpoints)}")

        best_content = None
        best_result = None
        bypasses = []

        for nr in valid_no_cookie:
            parsed = None
            data = nr.get("data")
            if isinstance(data, dict):
                parsed = parser.parse_json_api(data, url=nr["url"], engine_name=self.name)
            elif nr.get("text"):
                if nr["text"].strip().startswith("<"):
                    parsed = parser.parse_html(nr["text"], url=nr["url"], engine_name=self.name)
                else:
                    try:
                        jd = json.loads(nr["text"])
                        parsed = parser.parse_json_api(jd, url=nr["url"], engine_name=self.name)
                    except Exception:
                        parsed = parser.parse_html(nr["text"], url=nr["url"], engine_name=self.name)

            if parsed and self._is_significant_content(parsed):
                parsed.metadata["endpoint"] = nr["endpoint"]
                parsed.metadata["status_code"] = nr["status"]
                is_external = nr.get("is_external", False)
                parsed.metadata["is_external_endpoint"] = is_external
                bypasses.append({
                    "endpoint": nr["endpoint"],
                    "url": nr["url"],
                    "cn_words": parsed.word_count_cn,
                    "is_complete": not parsed.is_truncated,
                    "is_external": is_external,
                })
                if best_content is None or parsed.word_count_cn > best_content.word_count_cn:
                    best_content = parsed
                    best_result = nr

        if best_content:
            result.success = True
            result.content = best_content
            if best_content.word_count_cn >= config.COMPLETE_CONTENT_LENGTH:
                result.bypass_found = True
                ext_tag = " (外部自定义端点)" if best_result.get("is_external") else ""
                result.bypass_method = (
                    f"API端点绕过{ext_tag}: {best_result['endpoint']} "
                    f"在无Cookie状态下返回 {best_content.word_count_cn} 字完整内容"
                )

        result.details = {
            "article_type": art_type,
            "article_id": art_id,
            "total_endpoints": len(endpoints),
            "external_endpoints_loaded": external_count,
            "tested": len(no_cookie_results),
            "valid_responses": len(valid_no_cookie),
            "bypasses": bypasses[:15],
            "all_results": [
                {"endpoint": r["endpoint"], "status": r["status"],
                 "cn_words": r["cn_words"], "length": r["length"],
                 "is_external": r.get("is_external", False)}
                for r in no_cookie_results
            ],
        }
        return result

    def _build_endpoints(self, art_type: str, art_id: str,
                          col_id: Optional[str], sec_id: Optional[str]) -> List[Dict]:
        """
        构建待测试的端点列表。
        合并三部分：config内置端点 + 代码内置_EXTRA_ENDPOINTS + 外部文件加载的端点。
        支持占位符: {id}, {article_id}, {section_id}, {column_id}
        支持完整URL（以http开头）和相对路径（以/开头）。
        """
        endpoints = []
        seen = set()  # 去重

        # 合并所有端点模板来源
        all_templates = []
        # 1. config内置
        all_templates.extend(config.API_ENDPOINTS)
        # 2. 代码内置额外端点
        all_templates.extend(self._EXTRA_ENDPOINTS)
        # 3. 外部文件加载的端点
        external_templates = self._get_external_endpoints()
        all_templates.extend(external_templates)
        external_set = set(external_templates)

        for tmpl in all_templates:
            url_path = tmpl
            try:
                # 替换占位符
                url_path = url_path.replace("{id}", art_id)
                url_path = url_path.replace("{article_id}", art_id)
                url_path = url_path.replace("{section_id}", sec_id or art_id)
                if col_id:
                    url_path = url_path.replace("{column_id}", col_id)
                else:
                    # 没有column_id时跳过需要column_id的端点
                    if "{column_id}" in url_path:
                        continue
                # 如果还包含未替换的占位符（如{article}等），跳过
                if "{" in url_path and "}" in url_path:
                    # 检查是否还有未替换的{xxx}
                    remaining = re.findall(r'\{[a-zA-Z_]+\}', url_path)
                    if remaining:
                        continue
                # 去重
                if url_path in seen:
                    continue
                seen.add(url_path)

                # 判断是完整URL还是相对路径
                if url_path.startswith("http://") or url_path.startswith("https://"):
                    full_url = url_path
                else:
                    full_url = f"https://www.zhihu.com{url_path}" if url_path.startswith("/") else f"https://www.zhihu.com/{url_path}"

                endpoints.append({
                    "template": tmpl,
                    "path": url_path,
                    "url": full_url,
                    "is_external": tmpl in external_set,
                })
            except Exception:
                continue
        return endpoints

    async def _test_endpoints(self, endpoints: List[Dict],
                               col_id: Optional[str],
                               art_id: Optional[str]) -> List[Dict]:
        """并发测试多个API端点"""
        semaphore = asyncio.Semaphore(config.API_SCAN_CONCURRENCY)
        results = []

        async def worker(ep: Dict):
            async with semaphore:
                await asyncio.sleep(random.uniform(0.2, 0.6))
                try:
                    client = await self._get_async_client()
                    headers = dict(config.DEFAULT_HEADERS_DESKTOP)
                    headers.update({
                        "Accept": "application/json, text/plain, */*",
                        "X-Requested-With": "fetch",
                        "Referer": f"https://www.zhihu.com/market/paid_column/{col_id}/section/{art_id}"
                                   if col_id else "https://www.zhihu.com/",
                    })
                    self._increment_requests()
                    resp = await client.get(
                        ep["url"], headers=headers,
                        timeout=10, follow_redirects=True,
                    )
                    text = resp.text
                    data = None
                    try:
                        data = resp.json()
                    except Exception:
                        pass
                    cn_words = len(re.findall(r'[\u4e00-\u9fff]', text))
                    results.append({
                        "endpoint": ep["template"],
                        "url": ep["url"],
                        "status": resp.status_code,
                        "length": len(text),
                        "cn_words": cn_words,
                        "text": text[:50000],
                        "data": data,
                        "is_external": ep.get("is_external", False),
                    })
                except Exception as e:
                    results.append({
                        "endpoint": ep["template"],
                        "url": ep["url"],
                        "status": 0,
                        "length": 0,
                        "cn_words": 0,
                        "text": "",
                        "data": None,
                        "is_external": ep.get("is_external", False),
                        "error": str(e)[:100],
                    })

        tasks = [worker(ep) for ep in endpoints]
        await asyncio.gather(*tasks, return_exceptions=True)
        return results

    async def _get_async_client(self) -> httpx.AsyncClient:
        if not hasattr(self, '_async_client') or self._async_client is None:
            self._async_client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=config.REQUEST_TIMEOUT,
                verify=False,
            )
        return self._async_client
