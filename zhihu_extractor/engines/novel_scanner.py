#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小说站扫描引擎 - 系统性扫描已知小说转载站
"""
import re
import time
from typing import List, Tuple, Dict
from urllib.parse import quote, urljoin

from core.http_engine import HTTPEngine
from core.content_parser import ContentParser


class NovelScanner:
    """小说站扫描引擎"""

    def __init__(self, http: HTTPEngine, config: dict):
        self.http = http
        self.config = config
        self.parser = ContentParser()
        self.name = "novel_scanner"
        self.results = []

    async def run(self) -> List[Dict]:
        """执行扫描"""
        results = []
        target = self.config.get("TARGET", {})

        # 1. 已知kepue.com的5章
        print(f"[{self.name}] 扫描kepue.com已知章节...")
        kepue_chapters = self._scan_kepue()
        results.extend(kepue_chapters)

        # 2. 尝试kepue.com更高章节号（可能隐藏）
        print(f"[{self.name}] 尝试枚举kepue.com隐藏章节 (6-15)...")
        hidden_chapters = self._enumerate_kepue_hidden(6, 15)
        results.extend(hidden_chapters)

        # 3. 搜索其他小说站
        print(f"[{self.name}] 搜索其他小说站...")
        other_results = self._search_other_sites()
        results.extend(other_results)

        self.results = results
        return results

    def _scan_kepue(self) -> List[Dict]:
        """扫描kepue.com的已知章节"""
        results = []
        ua_mobile = self.config.get("USER_AGENTS", {}).get("mobile_iphone",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15")

        for ch_num in range(1, self.config.get("TARGET", {}).get("known_chapters", 5) + 1):
            url = f"https://m.kepue.com/nvpin/38738/{ch_num}/"
            status, html, _ = self.http.get(url, ua=ua_mobile, timeout=10, retries=3)

            if status == 200 and html:
                content = self.parser.extract_content(html, url)
                title = self.parser.extract_title(html)
                validation = self.parser.validate_content(content, self.config.get("TARGET", {}))

                if validation["is_valid"]:
                    results.append({
                        "source": "kepue.com",
                        "chapter": ch_num,
                        "title": title,
                        "url": url,
                        "content": content,
                        "char_count": validation["char_count"],
                        "confidence": validation["confidence"],
                    })
                    print(f"  ✓ 第{ch_num}章: {validation['char_count']}字, 置信度={validation['confidence']:.2f}")
                else:
                    print(f"  ✗ 第{ch_num}章: 内容验证失败")
            else:
                print(f"  ✗ 第{ch_num}章: HTTP {status}")

        return results

    def _enumerate_kepue_hidden(self, start: int, end: int) -> List[Dict]:
        """枚举kepue.com可能隐藏的章节"""
        results = []
        ua_mobile = self.config.get("USER_AGENTS", {}).get("mobile_iphone",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15")

        # 同时尝试多种URL模式
        url_patterns = [
            "https://m.kepue.com/nvpin/38738/{n}/",
        ]

        for ch_num in range(start, end + 1):
            found = False
            for pattern in url_patterns:
                url = pattern.format(n=ch_num)
                status, html, _ = self.http.get(url, ua=ua_mobile, timeout=6, retries=1)

                if status == 200 and html and len(html) > 1000:
                    if '404' in html[:500] or '不存在' in html[:500] or '页面不存在' in html[:500]:
                        continue

                    content = self.parser.extract_content(html, url)
                    if self.parser.count_chinese(content) > 30:
                        validation = self.parser.validate_content(content, self.config.get("TARGET", {}))
                        if validation["confidence"] > 0.3:
                            results.append({
                                "source": "kepue.com_hidden",
                                "chapter": ch_num,
                                "title": self.parser.extract_title(html),
                                "url": url,
                                "content": content,
                                "char_count": validation["char_count"],
                                "confidence": validation["confidence"],
                            })
                            print(f"  ✓ 发现隐藏第{ch_num}章: {validation['char_count']}字")
                            found = True
                            break

            if not found and ch_num <= start + 10:
                print(f"  - 第{ch_num}章: 未找到")

        return results

    def _search_other_sites(self) -> List[Dict]:
        """搜索其他小说站"""
        results = []
        target = self.config.get("TARGET", {})
        search_queries = [
            target.get("title", "娇娇和她的忠犬小狗"),
            target.get("alias_titles", ["婚后一年老公从不碰我"])[0],
        ]

        novel_sites = [
            ("https://www.biqubo.com/search.html?searchtype=novelname&searchkey=", "biqubo", False),
            ("https://www.biquge.lu/search.php?q=", "biquge_lu", False),
            ("https://www.lwxs99.cc/search.php?q=", "lwxs99", False),
            ("https://www.biquwx.la/search.php?q=", "biquwx", False),
            ("https://www.81zw.com/search.php?q=", "81zw", False),
            ("https://www.88dus.com/search.php?q=", "88dus", False),
            ("https://www.bqg5200.com/search.php?q=", "bqg5200", False),
            ("https://www.syzgl.com/search/?q=", "syzgl", False),
            ("https://m.biqubo.com/search.html?searchtype=novelname&searchkey=", "m_biqubo", True),
        ]

        ua_pc = self.config.get("USER_AGENTS", {}).get("desktop_chrome",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        ua_m = self.config.get("USER_AGENTS", {}).get("mobile_iphone",
            "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)")

        for base_url, site_name, need_mobile in novel_sites:
            for query in search_queries:
                url = base_url + quote(query)
                ua = ua_m if need_mobile else ua_pc
                status, html, _ = self.http.get(url, ua=ua, timeout=8, retries=1)

                if status == 200 and html:
                    has_target = any(c in html for c in target.get("characters", ["靳川"]))
                    if has_target:
                        print(f"  ✓ {site_name}: 找到相关内容!")
                        # 尝试提取章节链接
                        from bs4 import BeautifulSoup
                        soup = BeautifulSoup(html, 'html.parser')
                        for a in soup.find_all('a', href=True):
                            text = a.get_text(strip=True)
                            href = a['href']
                            if any(kw in text for kw in ['娇娇', '忠犬', '靳川', '孟娇蕊', '婚后一年']):
                                if href.startswith('/'):
                                    href = urljoin(base_url, href)
                                # 访问该书页面
                                ch_status, ch_html, _ = self.http.get(href, ua=ua, timeout=10, retries=2)
                                if ch_html:
                                    content = self.parser.extract_content(ch_html, href)
                                    validation = self.parser.validate_content(content, target)
                                    if validation["is_valid"]:
                                        results.append({
                                            "source": site_name,
                                            "chapter": 0,
                                            "title": text,
                                            "url": href,
                                            "content": content,
                                            "char_count": validation["char_count"],
                                            "confidence": validation["confidence"],
                                        })
                                        print(f"    提取内容: {validation['char_count']}字")
                    else:
                        if len(html) > 2000:
                            print(f"  - {site_name}: 无目标内容 (len={len(html)})")
                else:
                    print(f"  ✗ {site_name}: HTTP {status}")

        return results
