# -*- coding: utf-8 -*-
"""
ZCCSA CDN缓存探测引擎
- 获取基线响应（截断版）记录Hash
- 构造变异请求头Fuzzing：内网IP、服务间调用、缓存控制
- 比对响应Hash，检测缓存泄露
- 使用httpx异步并发
"""
import asyncio
import hashlib
import logging
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import httpx

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from core.header_fuzzer import HeaderFuzzer, FuzzPayload

logger = logging.getLogger(__name__)


@dataclass
class FuzzResponse:
    """Fuzz单个请求的结果"""
    payload_name: str
    category: str
    status: int
    length: int
    content_hash: str
    text_preview: str
    headers: Dict[str, str]
    cn_word_count: int = 0
    is_bypass: bool = False
    delta_chars: int = 0


class CDNCacheEngine(BaseEngine):
    """
    CDN缓存探测引擎
    原理：CDN可能因配置错误缓存了会员用户的完整响应，通过特殊请求头
    （如伪装内网IP、CDN节点间通信头）可能命中缓存获取完整内容。
    """

    name = "cdn_cache_engine"
    description = "CDN缓存探测（Header Fuzzing + Hash对比）"
    default_weight = 80

    async def _probe(self, url: str, article_id: Dict,
                     result: EngineResult) -> EngineResult:
        fuzzer = HeaderFuzzer()
        parser = self._get_parser()

        # ========== 1. 获取基线响应（标准请求头，无Cookie） ==========
        self.logger.info("  [1/3] 获取基线响应...")
        baseline = await self._fetch_baseline(url)
        if not baseline:
            result.error = "无法获取基线响应"
            return result

        baseline_hash = self._hash_text(baseline["text"])
        baseline_cn = baseline["cn_word_count"]
        baseline_len = baseline["length"]
        self.logger.info(f"    基线: {baseline_cn}中文字, {baseline_len}字节, hash={baseline_hash[:12]}")

        # ========== 2. 并发Fuzzing ==========
        self.logger.info(f"  [2/3] 开始Fuzzing ({len(fuzzer)}个载荷, 并发={config.CDN_FUZZ_CONCURRENCY})...")
        fuzz_results = await self._fuzz_all(url, baseline_hash, baseline_len, baseline_cn)

        # ========== 3. 分析结果 ==========
        self.logger.info("  [3/3] 分析Fuzzing结果...")
        bypasses = [r for r in fuzz_results if r.is_bypass]
        best = None

        if bypasses:
            self.logger.info(f"  ✓ 发现 {len(bypasses)} 个可能的缓存绕过！")
            # 取内容最长的绕过
            best_bypass = max(bypasses, key=lambda r: r.delta_chars)
            result.bypass_found = True
            result.bypass_method = (
                f"CDN缓存泄露: 载荷 '{best_bypass.payload_name}' "
                f"(分类: {best_bypass.category}), "
                f"中文字数从{baseline_cn}增至{best_bypass.cn_word_count}。"
            )
            # 重新获取该载荷的完整内容用于保存
            try:
                status, full_text, _ = await self._fetch_with_headers(
                    url, fuzzer.get_payloads_by_category(best_bypass.category)
                    [0].headers if best_bypass.category in ["internal_ip", "service", "cache", "vendor", "combo", "referer"]
                    else {}
                )
                if full_text:
                    best = parser.parse_html(full_text, url=url, engine_name=self.name)
                    best.metadata["bypass_payload"] = best_bypass.payload_name
                    best.metadata["bypass_category"] = best_bypass.category
            except Exception:
                pass
        else:
            # 即使没有绕过，检查是否有载荷返回了更多内容
            interesting = [r for r in fuzz_results
                           if r.delta_chars > 200 and r.cn_word_count > baseline_cn]
            if interesting:
                self.logger.info(f"    {len(interesting)} 个载荷返回了更长内容（未达绕过阈值）")

        if best and self._is_significant_content(best):
            result.success = True
            result.content = best
        elif bypasses:
            # 即使解析失败也标记成功发现
            result.success = True

        # 统计
        by_category = {}
        for r in fuzz_results:
            by_category.setdefault(r.category, {"total": 0, "bypass": 0, "avg_length": 0})
            by_category[r.category]["total"] += 1
            by_category[r.category]["bypass"] += 1 if r.is_bypass else 0
            by_category[r.category]["avg_length"] += r.length
        for cat in by_category:
            by_category[cat]["avg_length"] = (
                by_category[cat]["avg_length"] // by_category[cat]["total"]
            )

        result.details = {
            "baseline": {
                "cn_words": baseline_cn,
                "length": baseline_len,
                "hash": baseline_hash[:16],
            },
            "total_payloads": len(fuzzer),
            "fuzzed": len(fuzz_results),
            "bypasses_found": len(bypasses),
            "by_category": by_category,
            "bypass_details": [
                {"name": r.payload_name, "category": r.category,
                 "cn_words": r.cn_word_count, "delta": r.delta_chars}
                for r in bypasses[:10]
            ],
        }
        return result

    async def _fetch_baseline(self, url: str) -> Optional[Dict]:
        """获取基线响应"""
        try:
            sess = self._get_session()
            status, text, meta = await asyncio.to_thread(
                sess.get, url,
                extra_headers=None,
                timeout=config.REQUEST_TIMEOUT,
                verify=False,
            )
            self._increment_requests()
            if status != 200:
                return None
            cn_count = len(re.findall(r'[\u4e00-\u9fff]', text))
            return {
                "status": status, "text": text,
                "length": len(text), "cn_word_count": cn_count,
                "final_url": meta.get("url", url),
            }
        except Exception as e:
            self.logger.debug(f"基线请求失败: {e}")
            return None

    async def _fuzz_all(self, url: str, baseline_hash: str,
                        baseline_len: int, baseline_cn: int) -> List[FuzzResponse]:
        """并发执行所有Fuzzing载荷"""
        fuzzer = HeaderFuzzer()
        semaphore = asyncio.Semaphore(config.CDN_FUZZ_CONCURRENCY)
        results = []

        async def worker(payload: FuzzPayload):
            async with semaphore:
                await asyncio.sleep(random.uniform(
                    config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX))
                try:
                    status, text, meta = await self._fetch_with_headers(
                        url, payload.headers)
                    self._increment_requests()
                    cn_count = len(re.findall(r'[\u4e00-\u9fff]', text or ""))
                    h = self._hash_text(text or "")
                    delta = len(text or "") - baseline_len
                    is_bypass = (
                        status == 200 and
                        h != baseline_hash and
                        cn_count >= config.MIN_CONTENT_LENGTH and
                        cn_count > baseline_cn * 1.3 and
                        delta > 1000
                    )
                    results.append(FuzzResponse(
                        payload_name=payload.name,
                        category=payload.category,
                        status=status,
                        length=len(text or ""),
                        content_hash=h,
                        text_preview=(text or "")[:200],
                        headers=meta.get("headers", {}) if meta else {},
                        cn_word_count=cn_count,
                        is_bypass=is_bypass,
                        delta_chars=delta,
                    ))
                except Exception as e:
                    self.logger.debug(f"Fuzz '{payload.name}' 失败: {str(e)[:60]}")

        tasks = [worker(p) for p in fuzzer.payloads]
        await asyncio.gather(*tasks, return_exceptions=True)
        return results

    async def _fetch_with_headers(self, url: str,
                                   extra_headers: Dict) -> Tuple[int, str, Dict]:
        """使用指定额外请求头发起请求"""
        client = await self._get_async_client()
        headers = dict(config.DEFAULT_HEADERS_DESKTOP)
        headers.update(extra_headers or {})
        resp = await client.get(url, headers=headers,
                                timeout=config.REQUEST_TIMEOUT,
                                follow_redirects=True)
        return resp.status_code, resp.text, {
            "url": str(resp.url),
            "headers": dict(resp.headers),
        }

    async def _get_async_client(self) -> httpx.AsyncClient:
        """获取异步HTTP客户端（复用）"""
        if not hasattr(self, '_async_client') or self._async_client is None:
            self._async_client = httpx.AsyncClient(
                follow_redirects=True,
                timeout=config.REQUEST_TIMEOUT,
                verify=False,
                http2=True,
            )
        return self._async_client

    @staticmethod
    def _hash_text(text: str) -> str:
        normalized = re.sub(r'\s+', '', text or "")
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()
