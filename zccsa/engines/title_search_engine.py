# -*- coding: utf-8 -*-
"""
ZCCSA 标题直搜引擎
- 接收文章标题，通过知乎搜索API / Bing搜索引擎定位文章URL和ID
- search(title) -> dict: 返回 {"article_id", "column_id", "section_id", "url"} 或 {}
- 不继承BaseEngine（定位型工具，非探测引擎），独立模块
"""
import asyncio
import json
import logging
import random
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from core.parser import ContentParser
from core.session_manager import SessionManager

logger = logging.getLogger(__name__)


class TitleSearchEngine:
    """
    标题直搜引擎
    构造器仅接收 SessionManager 实例（parser内部创建，轻量无状态）。

    搜索策略两阶段：
    1. 知乎站内API搜索（4个端点，无需Cookie）
    2. Bing搜索引擎兜底（site:zhihu.com + 标题）
    """

    # 知乎站内搜索API端点列表（按优先级尝试）
    ZHIHU_APIS = [
        # API 1: v3通用搜索
        {
            "url": "https://www.zhihu.com/api/v4/search_v3",
            "params": {"t": "general", "limit": "5", "offset": "0",
                       "filter_fields": "", "q": None},
        },
        # API 2: v3文章搜索
        {
            "url": "https://www.zhihu.com/api/v4/search_v3",
            "params": {"t": "article", "limit": "5", "offset": "0",
                       "filter_fields": "", "q": None},
        },
        # API 3: v3盐选专栏搜索
        {
            "url": "https://www.zhihu.com/api/v4/search_v3",
            "params": {"t": "paid_column", "limit": "5", "offset": "0",
                       "filter_fields": "", "q": None},
        },
        # API 4: 老版v4搜索（兜底）
        {
            "url": "https://www.zhihu.com/api/v4/search",
            "params": {"t": "article", "limit": "5", "q": None},
        },
    ]

    # Bing搜索兜底
    BING_URL = "https://www.bing.com/search"

    def __init__(self, session: SessionManager):
        """
        :param session: 全局SessionManager实例（复用TLS指纹/Cookie/代理池）
        """
        self._session = session
        self._parser = ContentParser()
        self._request_count = 0

    # ============================================================
    # 核心接口
    # ============================================================
    async def search(self, title: str) -> Dict[str, str]:
        """
        通过标题搜索文章，返回最佳匹配的ID信息。
        :param title: 文章标题
        :return: 成功返回 {"article_id", "column_id", "section_id", "url",
                          "matched_title", "match_score", "source"}
                 失败返回空字典 {}
        """
        self._request_count = 0
        logger.info(f"[title_search] 开始搜索标题: {title[:60]}")

        try:
            # 阶段1：知乎站内API
            result = await self._search_zhihu_apis(title)
            if result:
                logger.info(f"[title_search] 知乎API匹配成功: {result.get('url', '')[:80]}")
                return result

            # 阶段2：Bing兜底
            result = await self._search_bing(title)
            if result:
                logger.info(f"[title_search] Bing匹配成功: {result.get('url', '')[:80]}")
                return result

        except Exception as e:
            logger.error(f"[title_search] 搜索过程异常: {type(e).__name__}: {str(e)[:200]}",
                         exc_info=True)

        logger.info("[title_search] 未找到匹配结果")
        return {}

    # ============================================================
    # 阶段1：知乎站内API搜索
    # ============================================================
    async def _search_zhihu_apis(self, title: str) -> Dict[str, str]:
        """依次尝试4个知乎搜索API，返回最佳匹配"""
        best_candidate: Dict[str, Any] = {}
        best_score = 0.0

        for api in self.ZHIHU_APIS:
            try:
                params = dict(api["params"])
                params["q"] = title

                headers = {
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://www.zhihu.com/search?type=content&q=" + quote(title),
                    "X-Requested-With": "fetch",
                }

                status, text = await asyncio.to_thread(
                    self._http_get_retry,
                    api["url"], params, headers, max_retries=3
                )

                if status != 200 or not text:
                    logger.debug(f"  API {api['url']} status={status}")
                    continue

                try:
                    data = json.loads(text)
                except json.JSONDecodeError:
                    logger.debug("  API返回非JSON，跳过")
                    continue

                # 解析结果
                candidates = self._parse_zhihu_response(data, title)
                for c in candidates:
                    if c["match_score"] > best_score:
                        best_score = c["match_score"]
                        best_candidate = c
                        c["source"] = "zhihu_api"

                # 高置信度匹配提前返回
                if best_score >= 0.8:
                    break

            except Exception as e:
                logger.debug(f"  API搜索失败: {str(e)[:80]}")
                continue

            await asyncio.sleep(0.3)

        if best_score >= 0.6 and best_candidate.get("url"):
            return self._normalize_result(best_candidate)
        return {}

    def _parse_zhihu_response(self, data: Dict, query_title: str) -> List[Dict]:
        """解析知乎API返回的JSON，提取候选结果"""
        candidates = []
        items = data.get("data", [])
        if not isinstance(items, list):
            return candidates

        for wrapper in items:
            try:
                obj = wrapper.get("object", wrapper) if isinstance(wrapper, dict) else wrapper
                if not isinstance(obj, dict):
                    continue

                obj_type = obj.get("type", "")
                entry: Dict[str, Any] = {
                    "title": "",
                    "url": "",
                    "article_id": "",
                    "column_id": "",
                    "section_id": "",
                    "match_score": 0.0,
                }

                if obj_type == "article":
                    entry["title"] = self._clean_text(obj.get("title", ""))
                    entry["url"] = obj.get("url", "")
                    entry["article_id"] = str(obj.get("id", ""))
                    if not entry["url"] and entry["article_id"]:
                        entry["url"] = f"https://zhuanlan.zhihu.com/p/{entry['article_id']}"

                elif obj_type == "answer":
                    entry["title"] = self._clean_text(
                        (obj.get("question") or {}).get("title", "") or obj.get("title", "")
                    )
                    aid = str(obj.get("id", ""))
                    qid = str((obj.get("question") or {}).get("id", ""))
                    entry["article_id"] = aid
                    if aid and qid:
                        entry["url"] = f"https://www.zhihu.com/question/{qid}/answer/{aid}"

                elif obj_type == "paid_column":
                    entry["title"] = self._clean_text(obj.get("title", ""))
                    entry["column_id"] = str(obj.get("id", ""))
                    entry["url"] = obj.get("url", "")
                    # 尝试从sections里取第一个章节
                    sections = obj.get("sections") or []
                    if sections:
                        sec = sections[0]
                        entry["section_id"] = str(sec.get("id", ""))
                        if entry["column_id"] and entry["section_id"]:
                            entry["url"] = (f"https://www.zhihu.com/market/paid_column/"
                                            f"{entry['column_id']}/section/{entry['section_id']}")
                    elif not entry["url"] and entry["column_id"]:
                        entry["url"] = f"https://www.zhihu.com/column/{entry['column_id']}"

                elif obj_type == "remix_essay":
                    entry["title"] = self._clean_text(obj.get("title", ""))
                    entry["article_id"] = str(obj.get("id", ""))
                    entry["url"] = obj.get("url", "") or (
                        f"https://www.zhihu.com/remix/essay/{entry['article_id']}"
                        if entry["article_id"] else "")

                elif "section" in obj_type.lower():
                    entry["title"] = self._clean_text(obj.get("title", ""))
                    entry["section_id"] = str(obj.get("id", ""))
                    col = obj.get("column") or obj.get("paid_column") or {}
                    if col:
                        entry["column_id"] = str(col.get("id", ""))
                    entry["url"] = obj.get("url", "")
                    if entry["column_id"] and entry["section_id"] and not entry["url"]:
                        entry["url"] = (f"https://www.zhihu.com/market/paid_column/"
                                        f"{entry['column_id']}/section/{entry['section_id']}")

                else:
                    # 通用兜底
                    entry["title"] = self._clean_text(obj.get("title", ""))
                    entry["url"] = obj.get("url", "")
                    entry["article_id"] = str(obj.get("id", ""))

                if entry["title"] and entry["url"]:
                    entry["match_score"] = self._calc_similarity(query_title, entry["title"])
                    # URL加分：含/section/的直接文章链接加分
                    if "/section/" in entry["url"]:
                        entry["match_score"] = min(1.0, entry["match_score"] + 0.1)
                    elif "/remix/essay/" in entry["url"] or "zhuanlan.zhihu.com/p/" in entry["url"]:
                        entry["match_score"] = min(1.0, entry["match_score"] + 0.05)
                    candidates.append(entry)

            except Exception as e:
                logger.debug(f"  解析结果项失败: {e}")
                continue

        candidates.sort(key=lambda x: x["match_score"], reverse=True)
        return candidates

    # ============================================================
    # 阶段2：Bing搜索引擎兜底
    # ============================================================
    async def _search_bing(self, title: str) -> Dict[str, str]:
        """Bing搜索 site:zhihu.com + 标题"""
        try:
            query = f"site:zhihu.com {title}"
            params = {"q": query, "setlang": "zh-CN", "cc": "CN"}
            headers = {
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Referer": "https://www.bing.com/",
            }

            status, html = await asyncio.to_thread(
                self._http_get_retry,
                self.BING_URL, params, headers, max_retries=2
            )

            if status != 200 or not html:
                return {}

            # 解析Bing结果页，提取第一个zhihu.com链接
            zhihu_url = self._parse_bing_html(html)
            if not zhihu_url:
                return {}

            # 用parser解析URL获取ID
            id_info = self._parser.extract_article_id(zhihu_url)
            result = {
                "url": zhihu_url,
                "article_id": str(id_info.get("id", "")),
                "column_id": str(id_info.get("column_id", "")),
                "section_id": str(id_info.get("section_id", "")),
                "matched_title": title,
                "match_score": 0.55,  # Bing兜底置信度稍低
                "source": "bing",
            }
            return self._normalize_result(result)

        except Exception as e:
            logger.debug(f"  Bing搜索失败: {str(e)[:80]}")
            return {}

    def _parse_bing_html(self, html: str) -> str:
        """从Bing搜索结果HTML中提取第一个知乎URL，优先选择含/section/的文章链接"""
        from bs4 import BeautifulSoup
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        candidates = []
        # 优先 li.b_algo > h2 > a
        for li in soup.select("li.b_algo"):
            h2 = li.find("h2")
            if not h2:
                continue
            a = h2.find("a")
            if not a:
                continue
            href = a.get("href", "")
            if "zhihu.com" in href:
                candidates.append(href)

        # 正则兜底
        if not candidates:
            for m in re.finditer(r'href="(https?://(?:www\.)?zhihu\.com/[^"]+)"', html):
                candidates.append(m.group(1))

        if not candidates:
            return ""

        # 排序：优先含/section/的（直接文章）> 含/remix/的 > /p/（专栏文章）> 其他
        def url_priority(u: str) -> int:
            if "/section/" in u:
                return 0  # 最高优先级
            if "/remix/essay/" in u:
                return 1
            if "/xen/market/remix/paid_column/" in u and "/section/" not in u:
                return 2  # remix专栏入口（无section）
            if "zhuanlan.zhihu.com/p/" in u:
                return 3
            if "/answer/" in u or "/question/" in u:
                return 4
            return 5

        candidates.sort(key=url_priority)
        return candidates[0]

    # ============================================================
    # HTTP请求（带重试）
    # ============================================================
    def _http_get_retry(self, url: str, params: Dict, headers: Dict,
                         max_retries: int = 3):
        """同步HTTP GET，指数退避重试，返回 (status_code, text)"""
        from curl_cffi import requests as curl_requests

        last_exc = None
        for attempt in range(max_retries):
            try:
                sess = curl_requests.Session(impersonate=config.IMPERSONATE_BROWSER)
                try:
                    full_headers = dict(config.DEFAULT_HEADERS_DESKTOP)
                    full_headers.update(headers)
                    resp = sess.get(
                        url, params=params, headers=full_headers,
                        timeout=config.REQUEST_TIMEOUT,
                        allow_redirects=True, verify=False,
                    )
                    self._request_count += 1
                    text = resp.text
                    if resp.encoding:
                        try:
                            text = resp.content.decode(resp.encoding, errors='ignore')
                        except Exception:
                            pass
                    return resp.status_code, text
                finally:
                    try:
                        sess.close()
                    except Exception:
                        pass
            except Exception as e:
                last_exc = e
                if attempt < max_retries - 1:
                    delay = config.RETRY_BACKOFF_BASE ** attempt + random.uniform(0, 0.5)
                    time.sleep(delay)

        if last_exc:
            raise last_exc
        return 0, ""

    # ============================================================
    # 工具方法
    # ============================================================
    def _normalize_result(self, c: Dict) -> Dict[str, str]:
        """统一结果格式，用parser二次校验ID"""
        url = c.get("url", "")
        # 用parser重新解析URL以确保ID准确
        id_info = {}
        if url:
            try:
                id_info = self._parser.extract_article_id(url)
            except Exception:
                pass

        return {
            "article_id": str(id_info.get("id") or c.get("article_id", "")),
            "column_id": str(id_info.get("column_id") or c.get("column_id", "")),
            "section_id": str(id_info.get("section_id") or c.get("section_id", "")),
            "url": url,
            "matched_title": c.get("title", c.get("matched_title", "")),
            "match_score": round(c.get("match_score", 0.0), 3),
            "source": c.get("source", ""),
        }

    @staticmethod
    def _clean_text(val: Any) -> str:
        """清理文本：移除知乎搜索结果中的<em>高亮标签"""
        if not val:
            return ""
        if isinstance(val, str):
            return re.sub(r'</?em[^>]*>', '', val).strip()
        if isinstance(val, dict):
            return TitleSearchEngine._clean_text(val.get("text", val.get("title", "")))
        return str(val).strip()

    @staticmethod
    def _calc_similarity(query: str, candidate: str) -> float:
        """
        计算标题相似度 0-1。
        综合 Jaccard字符相似度 + 2-gram Dice系数 + 3-gram精确匹配。
        """
        if not query or not candidate:
            return 0.0

        # 清洗：移除标点/空白，转小写
        def normalize(s: str) -> str:
            return re.sub(r'[《》""''【】\[\]「」()（）\s<>《》·\-\—\-]+', '', s.lower())

        q = normalize(query)
        c = normalize(candidate)
        if not q or not c:
            return 0.0

        # 子串包含：完全包含时给高基础分
        if q in c or c in q:
            ratio = min(len(q), len(c)) / max(len(q), len(c))
            return 0.8 + 0.2 * ratio

        # Jaccard字符相似度
        q_chars = set(q)
        c_chars = set(c)
        char_jaccard = len(q_chars & c_chars) / len(q_chars | c_chars) if (q_chars | c_chars) else 0

        # 2-gram Dice系数
        def ngrams(s: str, n: int):
            return set(s[i:i+n] for i in range(len(s)-n+1))

        q2, c2 = ngrams(q, 2), ngrams(c, 2)
        dice2 = (2 * len(q2 & c2) / (len(q2) + len(c2))) if (q2 and c2) else 0

        # 3-gram 命中率（更严格的子序列匹配）
        q3, c3 = ngrams(q, 3), ngrams(c, 3)
        trigram_hit = len(q3 & c3) / len(q3) if q3 else 0

        score = char_jaccard * 0.3 + dice2 * 0.4 + trigram_hit * 0.3
        return min(1.0, score)

    @property
    def request_count(self) -> int:
        return self._request_count
