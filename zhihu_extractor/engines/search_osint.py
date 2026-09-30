#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搜索引擎OSINT引擎 - 多引擎搜索、结果分析、URL发现
"""
import re
import json
from typing import List, Dict
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup

from core.http_engine import HTTPEngine
from core.content_parser import ContentParser


class SearchOSINT:
    """搜索引擎OSINT引擎"""

    def __init__(self, http: HTTPEngine, config: dict):
        self.http = http
        self.config = config
        self.parser = ContentParser()
        self.name = "search_osint"
        self.results = []
        self.discovered_urls = []

    async def run(self) -> List[Dict]:
        """执行搜索"""
        results = []
        target = self.config.get("TARGET", {})

        # 1. 必应搜索
        print(f"[{self.name}] 必应搜索...")
        bing_results = self._search_bing()
        results.extend(bing_results)

        # 2. 搜狗搜索（Web + 微信）
        print(f"[{self.name}] 搜狗搜索...")
        sogou_results = self._search_sogou()
        results.extend(sogou_results)

        # 3. 360搜索
        print(f"[{self.name}] 360搜索...")
        results_360 = self._search_360()
        results.extend(results_360)

        # 4. 访问发现的高价值URL
        print(f"[{self.name}] 访问发现的URL ({len(self.discovered_urls)}个)...")
        visited_results = self._visit_discovered_urls()
        results.extend(visited_results)

        self.results = results
        return results

    def _search_bing(self) -> List[Dict]:
        """必应搜索"""
        results = []
        target = self.config.get("TARGET", {})
        ua = self.config.get("USER_AGENTS", {}).get("desktop_chrome", "")

        queries = [
            f'"{target.get("title", "娇娇和她的忠犬小狗")}" 全文 阅读',
            f'{" ".join(target.get("characters", ["靳川", "孟娇蕊"]))} 小说 全文',
            f'site:mp.weixin.qq.com "{target.get("title", "")}"',
            f'"{target.get("title", "")}" 大结局 番外',
            f'"{target.get("alias_titles", ["婚后一年老公从不碰我"])[0]}" 全文 完整版',
        ]

        for q in queries:
            url = f'https://cn.bing.com/search?q={quote(q)}'
            status, html, _ = self.http.get(url, ua=ua, timeout=10, retries=2)

            if not html:
                continue

            soup = BeautifulSoup(html, 'html.parser')
            for li in soup.select('li.b_algo'):
                a = li.find('a', href=True)
                if not a:
                    continue

                href = a['href']
                text = a.get_text(strip=True)
                snippet_div = li.find('div', class_='b_caption')
                snippet = snippet_div.get_text(strip=True) if snippet_div else ''

                # 检查相关性
                combined = text + snippet
                is_relevant = any(kw in combined for kw in
                    ['娇娇', '忠犬', '靳川', '孟娇蕊', '傅柏文', '婚后一年', '边月', '弹幕'])

                if is_relevant and href.startswith('http'):
                    self.discovered_urls.append({
                        "url": href,
                        "title": text[:60],
                        "snippet": snippet[:100],
                        "source": "bing",
                        "query": q[:30],
                    })

        return results

    def _search_sogou(self) -> List[Dict]:
        """搜狗搜索"""
        results = []
        target = self.config.get("TARGET", {})
        ua = self.config.get("USER_AGENTS", {}).get("mobile_iphone", "")

        queries = [
            f'{target.get("title", "娇娇和她的忠犬小狗")} 靳川',
            f'{" ".join(target.get("characters", ["孟娇蕊", "靳川"]))} 小说',
            f'{target.get("title", "")} 大结局 番外',
        ]

        for q in queries:
            # 搜狗微信
            url = f'https://weixin.sogou.com/weixin?type=2&query={quote(q)}'
            status, html, _ = self.http.get(url, ua=ua, timeout=10, retries=2)

            if not html or len(html) < 500:
                continue

            soup = BeautifulSoup(html, 'html.parser')
            for item in soup.select('div.txt-box, div.news-box'):
                a = item.find('a', href=True)
                if a:
                    href = a['href']
                    text = a.get_text(strip=True)
                    p = item.find('p', class_='txt-info')
                    snippet = p.get_text(strip=True) if p else ''

                    if any(kw in text + snippet for kw in
                        ['娇娇', '忠犬', '靳川', '孟娇蕊', '婚后一年', '大结局', '番外']):
                        full_url = urljoin('https://weixin.sogou.com', href) if href.startswith('/') else href
                        self.discovered_urls.append({
                            "url": full_url,
                            "title": text[:60],
                            "snippet": snippet[:100],
                            "source": "sogou_wx",
                            "query": q[:30],
                        })

            # 搜狗网页
            url2 = f'https://www.sogou.com/web?query={quote(q)}'
            status2, html2, _ = self.http.get(url2, ua=ua, timeout=8, retries=1)
            if html2:
                soup2 = BeautifulSoup(html2, 'html.parser')
                for item in soup2.select('div.vrwrap, div.rb'):
                    a = item.find('a', href=True)
                    if a:
                        href = a['href']
                        text = a.get_text(strip=True)
                        if any(kw in text for kw in
                            ['娇娇', '忠犬', '靳川', '孟娇蕊', '婚后一年']):
                            self.discovered_urls.append({
                                "url": href if href.startswith('http') else urljoin('https://www.sogou.com', href),
                                "title": text[:60],
                                "snippet": "",
                                "source": "sogou_web",
                                "query": q[:30],
                            })

        return results

    def _search_360(self) -> List[Dict]:
        """360搜索"""
        results = []
        target = self.config.get("TARGET", {})
        ua = self.config.get("USER_AGENTS", {}).get("desktop_chrome", "")

        queries = [
            f'{target.get("title", "娇娇和她的忠犬小狗")} 全文',
            f'{target.get("alias_titles", ["婚后一年老公从不碰我"])[0]} 全文 阅读',
        ]

        for q in queries:
            url = f'https://www.so.com/s?q={quote(q)}'
            status, html, _ = self.http.get(url, ua=ua, timeout=8, retries=1)

            if not html:
                continue

            soup = BeautifulSoup(html, 'html.parser')
            for li in soup.select('li.res-list, div.res-item'):
                a = li.find('a', href=True)
                if a:
                    href = a['href']
                    text = a.get_text(strip=True)
                    if any(kw in text for kw in
                        ['娇娇', '忠犬', '靳川', '孟娇蕊', '婚后一年']):
                        self.discovered_urls.append({
                            "url": href,
                            "title": text[:60],
                            "snippet": "",
                            "source": "360",
                            "query": q[:30],
                        })

        return results

    def _visit_discovered_urls(self) -> List[Dict]:
        """访问发现的URL，提取内容"""
        results = []
        target = self.config.get("TARGET", {})
        seen_urls = set()

        for item in self.discovered_urls:
            url = item["url"]
            if url in seen_urls:
                continue
            seen_urls.add(url)

            # 跳过知乎自身（已知付费墙）
            if 'zhihu.com' in url:
                continue
            # 跳过搜狗跳转链接（需要JS）
            if 'weixin.sogou.com/link' in url:
                continue

            status, html, _ = self.http.get(url, timeout=10, retries=2)

            if not html or len(html) < 500:
                continue

            content = self.parser.extract_content(html, url)
            if not content or self.parser.count_chinese(content) < 50:
                continue

            validation = self.parser.validate_content(content, target)
            if validation["is_valid"]:
                results.append({
                    "source": item["source"],
                    "title": item["title"],
                    "url": url,
                    "content": content,
                    "char_count": validation["char_count"],
                    "confidence": validation["confidence"],
                    "chapter": 0,
                })
                print(f"  ✓ [{item['source']}] {item['title'][:30]}: {validation['char_count']}字 (置信度={validation['confidence']:.2f})")

        return results
