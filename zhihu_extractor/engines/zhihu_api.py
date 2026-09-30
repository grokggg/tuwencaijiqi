#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知乎API探测引擎 - 尝试多种API端点和参数组合
"""
import re
import json
from typing import List, Dict

from core.http_engine import HTTPEngine
from core.content_parser import ContentParser


class ZhihuAPI:
    """知乎API探测引擎"""

    def __init__(self, http: HTTPEngine, config: dict):
        self.http = http
        self.config = config
        self.parser = ContentParser()
        self.name = "zhihu_api"
        self.results = []

    async def run(self) -> List[Dict]:
        results = []
        article_id = self.config.get("TARGET", {}).get("article_id", "")
        target = self.config.get("TARGET", {})

        # 1. 知乎API端点探测
        print(f"[{self.name}] API端点探测...")
        api_endpoints = [
            f"https://www.zhihu.com/api/v4/answers/{article_id}?include=content",
            f"https://www.zhihu.com/api/v4/answers/{article_id}",
            f"https://zhuanlan.zhihu.com/api/articles/{article_id}",
            f"https://www.zhihu.com/api/v4/columns/items/{article_id}",
        ]

        for url in api_endpoints:
            status, data = self.http.get_json(url, headers={
                "Accept": "application/json",
                "Referer": "https://www.zhihu.com/",
            })
            if data and "error" not in data:
                content = data.get("content", "")
                if content and len(content) > 100:
                    validation = self.parser.validate_content(content, target)
                    if validation["is_valid"]:
                        results.append({
                            "source": "zhihu_api",
                            "url": url,
                            "content": content,
                            "char_count": validation["char_count"],
                            "confidence": validation["confidence"],
                        })
                        print(f"  ✓ API成功: {url[-40:]}")

        # 2. 知乎页面直连（多种UA）
        print(f"[{self.name}] 页面直连（多UA）...")
        page_urls = [
            f"https://zhuanlan.zhihu.com/p/{article_id}",
            f"https://www.zhihu.com/question/582374928/answer/{article_id}",
        ]

        for ua_key in ["desktop_chrome", "mobile_iphone", "bot_baidu", "bot_bing", "bot_google"]:
            ua = self.config.get("USER_AGENTS", {}).get(ua_key, "")
            for url in page_urls:
                status, html, _ = self.http.get(url, ua=ua, timeout=8, retries=1)
                if html and len(html) > 1000:
                    # 检查是否有initialData
                    initial = re.search(r'<script id="js-initialData"[^>]*>(.*?)</script>', html, re.DOTALL)
                    if initial:
                        try:
                            data = json.loads(initial.group(1))
                            entities = data.get("initialState", {}).get("entities", {})

                            # 检查articles
                            for aid, article in entities.get("articles", {}).items():
                                content = article.get("content", "")
                                if content:
                                    validation = self.parser.validate_content(content, target)
                                    if validation["is_valid"]:
                                        results.append({
                                            "source": f"zhihu_page_{ua_key}",
                                            "url": url,
                                            "content": content,
                                            "char_count": validation["char_count"],
                                            "confidence": validation["confidence"],
                                        })
                                        print(f"  ✓ [{ua_key}] 提取文章内容: {validation['char_count']}字")

                            # 检查answers
                            for aid, answer in entities.get("answers", {}).items():
                                content = answer.get("content", "")
                                if content:
                                    validation = self.parser.validate_content(content, target)
                                    if validation["is_valid"]:
                                        results.append({
                                            "source": f"zhihu_page_{ua_key}",
                                            "url": url,
                                            "content": content,
                                            "char_count": validation["char_count"],
                                            "confidence": validation["confidence"],
                                        })
                                        print(f"  ✓ [{ua_key}] 提取回答内容: {validation['char_count']}字")
                        except:
                            pass

                    # 也尝试直接从HTML提取
                    content = self.parser.extract_content(html, url)
                    if self.parser.count_chinese(content) > 200:
                        validation = self.parser.validate_content(content, target)
                        if validation["is_valid"]:
                            results.append({
                                "source": f"zhihu_html_{ua_key}",
                                "url": url,
                                "content": content,
                                "char_count": validation["char_count"],
                                "confidence": validation["confidence"],
                            })

        # 3. 知乎移动端API
        print(f"[{self.name}] 移动端API探测...")
        mobile_endpoints = [
            f"https://api.zhihu.com/answers/{article_id}",
            f"https://api.zhihu.com/articles/{article_id}",
        ]
        for url in mobile_endpoints:
            status, data = self.http.get_json(url, headers={
                "Accept": "application/json",
                "User-Agent": "com.zhihu.android/10.0.0",
            })
            if data and "error" not in data:
                content = data.get("content", "")
                if content:
                    validation = self.parser.validate_content(content, target)
                    if validation["is_valid"]:
                        results.append({
                            "source": "zhihu_mobile_api",
                            "url": url,
                            "content": content,
                            "char_count": validation["char_count"],
                            "confidence": validation["confidence"],
                        })

        self.results = results
        return results
