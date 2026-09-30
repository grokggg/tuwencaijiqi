# -*- coding: utf-8 -*-
"""
internal_api_engine.py - 内部API降级引擎 (P1)

维护一组已知的旧版/非官方API端点列表，逐一尝试获取内容。
支持从配置文件动态加载新发现的端点。
"""
import json
import logging
import re
import time
from typing import Optional, Dict, List
from urllib.parse import quote

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from core.parser import ContentParser, ParsedContent, extract_article_id
from core.session_manager import SessionManager

logger = logging.getLogger(__name__)


class InternalApiEngine:
    """
    内部API降级引擎。
    尝试多种已知的API端点组合，寻找能返回完整内容的版本。
    """

    name = "internal_api_engine"

    # 额外发现的API端点模式（可从配置文件扩展）
    EXTRA_ENDPOINTS_FILE = Path(__file__).parent.parent / "data" / "extra_endpoints.json"

    def __init__(self, session_manager: SessionManager):
        self.sm = session_manager
        self.parser = ContentParser()
        self._extra_endpoints = self._load_extra_endpoints()

    def _load_extra_endpoints(self) -> List[str]:
        """加载额外API端点配置"""
        endpoints = []
        if self.EXTRA_ENDPOINTS_FILE.exists():
            try:
                data = json.loads(self.EXTRA_ENDPOINTS_FILE.read_text(encoding="utf-8"))
                endpoints = data.get("endpoints", [])
                logger.info(f"加载了 {len(endpoints)} 个额外API端点")
            except Exception as e:
                logger.warning(f"加载额外端点失败: {e}")
        return endpoints

    async def fetch(self, url: str) -> Optional[ParsedContent]:
        """尝试多个内部API端点"""
        start_time = time.time()
        ids = extract_article_id(url)

        article_id = ids.get("article_id") or ids.get("section_id") or ids.get("answer_id") or ids.get("post_id")
        column_id = ids.get("column_id")
        answer_id = ids.get("answer_id")

        # 构建所有要尝试的端点
        endpoints = self._build_all_endpoints(ids)

        session = self.sm.get_session(mobile=False)  # 桌面端

        for api_url, method, params_or_data in endpoints:
            try:
                headers = {
                    "Referer": url,
                    "Accept": "application/json, text/plain, */*",
                    "x-requested-with": "fetch",
                }

                if method.upper() == "GET":
                    status, body, resp_headers, final_url = session.get(
                        api_url, params=params_or_data, headers=headers, timeout=15
                    )
                else:
                    status, body, resp_headers, final_url = session.post(
                        api_url, json_data=params_or_data, headers=headers, timeout=15
                    )

                if status != 200:
                    continue

                # 解析JSON
                if body.strip().startswith("{"):
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError:
                        continue

                    pc = self.parser.parse_api_json(data, final_url)
                    if pc and self.parser.is_content_complete(pc):
                        pc.platform = "zhihu"
                        elapsed = time.time() - start_time
                        logger.info(f"内部API引擎成功 ({api_url[:60]}): {pc.title} ({pc.content_length}字)")
                        return pc

                # 解析HTML
                elif "<html" in body.lower() or "<!doctype" in body.lower():
                    pc = self.parser.parse_html(body, final_url)
                    if pc and self.parser.is_content_complete(pc):
                        return pc

            except Exception as e:
                logger.debug(f"端点 {api_url[:60]} 失败: {e}")
                continue

        logger.info("内部API引擎未能获取内容")
        return None

    def _build_all_endpoints(self, ids: Dict[str, str]) -> List[tuple]:
        """构建所有待尝试的端点列表 [(url, method, params), ...]"""
        endpoints = []
        article_id = ids.get("article_id") or ids.get("section_id")
        column_id = ids.get("column_id")
        answer_id = ids.get("answer_id")
        post_id = ids.get("post_id")
        share_code = ids.get("share_code")
        km_pst = ids.get("km_pst")
        answer_id2 = ids.get("answer_id")

        any_id = article_id or answer_id or post_id

        # 1. 旧版API v2
        if column_id and any_id:
            endpoints.append((
                config.ZHIHU_API_V2 + f"/columns/{column_id}/posts/{any_id}",
                "GET", {}
            ))

        # 2. API v1
        if any_id:
            endpoints.append((
                config.ZHIHU_API_V1 + f"/article/{any_id}",
                "GET", {}
            ))
            endpoints.append((
                config.ZHIHU_API_V1 + f"/answers/{any_id}",
                "GET", {}
            ))

        # 3. 标准API v4（多种变体）
        if any_id:
            # 文章
            endpoints.append((
                f"{config.ZHIHU_API_BASE}/articles/{any_id}",
                "GET", {"include": "data[*].content,author.name"}
            ))
            # 回答
            endpoints.append((
                f"{config.ZHIHU_API_BASE}/answers/{any_id}",
                "GET", {"include": "data[*].content,author.name"}
            ))
            # 帖子
            endpoints.append((
                f"{config.ZHIHU_API_BASE}/posts/{any_id}",
                "GET", {}
            ))

        # 4. 付费内容（不通过market前缀）
        if any_id:
            endpoints.append((
                f"https://www.zhihu.com/api/v4/paid_contents/{any_id}",
                "GET", {}
            ))
            endpoints.append((
                f"https://www.zhihu.com/api/v4/remix_paid_contents/{any_id}",
                "GET", {}
            ))

        # 5. oia API
        if share_code and km_pst:
            endpoints.append((
                "https://oia.zhihu.com/km_paid_content/api/content",
                "GET", {"km_pst": km_pst, "share_code": share_code}
            ))

        # 6. m.zhihu.com 移动端页面（有时返回更多内容）
        if any_id:
            endpoints.append((
                f"https://m.zhihu.com/question/{column_id}/answer/{answer_id2}" if column_id and answer_id2 else f"https://m.zhihu.com/p/{any_id}",
                "GET", {}
            ))

        # 7. www.zhihu.com 桌面端页面
        if any_id:
            # 问答
            if answer_id2:
                qid = ids.get("question_id", "")
                if qid:
                    endpoints.append((
                        f"https://www.zhihu.com/question/{qid}/answer/{answer_id2}",
                        "GET", {}
                    ))
                else:
                    endpoints.append((f"https://www.zhihu.com/p/{any_id}", "GET", {}))
            else:
                endpoints.append((f"https://www.zhihu.com/p/{any_id}", "GET", {}))

        # 8. 加载额外端点
        for ep_tmpl in self._extra_endpoints:
            try:
                url = ep_tmpl
                for k, v in ids.items():
                    url = url.replace("{" + k + "}", v or "")
                if "{" not in url:  # 所有占位符都已替换
                    endpoints.append((url, "GET", {}))
            except:
                pass

        return endpoints

    def add_endpoint(self, endpoint_template: str):
        """动态添加新发现的API端点"""
        self._extra_endpoints.append(endpoint_template)
        try:
            self.EXTRA_ENDPOINTS_FILE.write_text(
                json.dumps({"endpoints": self._extra_endpoints}, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"保存端点失败: {e}")
