# -*- coding: utf-8 -*-
"""
ZPE vNext - 已知小说站直接扫描引擎
直接访问已知的小说转载站搜索目标文章
"""
import asyncio
import re
from typing import Dict, List, Any, Tuple
from urllib.parse import urljoin, quote

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from core.http_client import cn_count, random_ua


class NovelSiteEngine(BaseEngine):
    """已知小说站直接扫描引擎"""
    
    name = "novel_site"
    description = "直接扫描已知小说转载站"
    priority = 90  # 高优先级
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.all_titles = [config.TARGET["title"]] + config.TARGET["alternate_titles"]
        self.main_chars = config.TARGET["main_characters"]
        
        # 扩展更多小说站（基于经验和常见站）
        self.sites = [
            # 已验证有效的
            {"name": "kepue.com", "search": "https://kepue.com/search.php?q={q}", "base": "https://kepue.com/"},
            {"name": "syzgly.com", "search": "https://www.syzgly.com/search.php?q={q}", "base": "https://www.syzgly.com/"},
            # 常见笔趣阁变种
            {"name": "biquge5200", "search": "https://www.biquge5200.com/search.php?q={q}", "base": "https://www.biquge5200.com/"},
            {"name": "biqukan", "search": "https://www.biqukan.la/search.php?q={q}", "base": "https://www.biqukan.la/"},
            {"name": "xsbiquge", "search": "https://www.xsbiquge.com/search.php?q={q}", "base": "https://www.xsbiquge.com/"},
            {"name": "shuquge", "search": "https://www.shuquge.com/search.php?q={q}", "base": "https://www.shuquge.com/"},
            {"name": "beqege", "search": "https://www.beqege.cc/search.php?q={q}", "base": "https://www.beqege.cc/"},
            {"name": "bqgui", "search": "https://www.bqgui.cc/search.php?q={q}", "base": "https://www.bqgui.cc/"},
            {"name": "630la", "search": "https://www.630la.com/search.php?q={q}", "base": "https://www.630la.com/"},
            {"name": "23usp", "search": "https://www.23usp.com/search.php?q={q}", "base": "https://www.23usp.com/"},
            {"name": "ibiquges", "search": "https://www.ibiquges.info/search.php?q={q}", "base": "https://www.ibiquges.info/"},
            {"name": "biqugexx", "search": "https://www.biqugexx.com/search.php?q={q}", "base": "https://www.biqugexx.com/"},
            {"name": "txt99", "search": "https://www.txt99.org/search.php?q={q}", "base": "https://www.txt99.org/"},
            # 更多小说站
            {"name": "xbiquge", "search": "https://www.xbiquge.bz/search.php?q={q}", "base": "https://www.xbiquge.bz/"},
            {"name": "biqugex", "search": "https://www.biqugex.com/search.php?q={q}", "base": "https://www.biqugex.com/"},
            {"name": "qb5", "search": "https://www.qb5.tw/search.php?q={q}", "base": "https://www.qb5.tw/"},
            {"name": "2ks", "search": "https://www.2ks.cc/search.php?q={q}", "base": "https://www.2ks.cc/"},
            {"name": "pxbook", "search": "https://www.pxbook.net/search.php?q={q}", "base": "https://www.pxbook.net/"},
            {"name": "shubaow", "search": "https://www.shubaow.net/search.php?q={q}", "base": "https://www.shubaow.net/"},
            {"name": "uuks", "search": "https://www.uuks.org/search.php?q={q}", "base": "https://www.uuks.org/"},
        ]
    
    async def run(self, context: Dict[str, Any]) -> EngineResult:
        result = self.create_result()
        
        # 优先使用其他引擎发现的URL
        existing_urls = context.get("discovered_urls", [])
        existing_chapters = context.get("chapters", [])
        
        best_content = ""
        best_source = ""
        best_confidence = 0.0
        best_word_count = 0
        all_chapters = list(existing_chapters)
        all_contents = []
        found_urls = []
        
        # 1. 首先尝试访问之前发现的已知有效站点
        self.logger.info("阶段1: 扫描已知小说站...")
        sem = asyncio.Semaphore(3)
        
        async def scan_site(site):
            async with sem:
                return await self._scan_single_site(site)
        
        tasks = [scan_site(site) for site in self.sites[:15]]
        site_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for sr in site_results:
            if isinstance(sr, Exception) or not sr:
                continue
            book_url, chapters, content = sr
            if book_url:
                found_urls.append(book_url)
            if chapters and len(chapters) >= 3:
                all_chapters.extend(chapters)
            if content:
                validation = self.parser.validate_content(content)
                all_contents.append((book_url or "novel_site", content))
                if validation["is_match"] and validation["confidence"] > best_confidence:
                    best_confidence = validation["confidence"]
                    best_content = content
                    best_source = book_url
                    best_word_count = validation["word_count"]
        
        # 2. 如果找到了章节列表，批量爬取章节
        if all_chapters and len(all_chapters) >= 3:
            self.logger.info(f"发现 {len(all_chapters)} 个章节链接，开始爬取章节内容...")
            chapter_content = await self._crawl_chapters(all_chapters)
            if chapter_content and cn_count(chapter_content) > cn_count(best_content):
                best_content = chapter_content
                best_word_count = cn_count(chapter_content)
                best_confidence = 0.9
                best_source = "chapter_crawl"
                all_contents.append(("chapter_crawl", chapter_content))
        
        # 3. 合并所有内容
        if all_contents:
            merged = self.parser.merge_contents(all_contents)
            if cn_count(merged) > best_word_count:
                best_content = merged
                best_word_count = cn_count(merged)
        
        if best_content and best_word_count > 500:
            result.success = True
            result.content = best_content
            result.source_url = best_source
            result.word_count = best_word_count
            result.confidence = best_confidence
            result.chapters = all_chapters
            result.discovered_urls = found_urls
            
            if best_word_count >= 3000 and best_confidence >= 0.6:
                result.bypass_found = True
                result.bypass_method = f"小说站爬取: {best_source} ({best_word_count}字)"
        
        result.details = {
            "sites_scanned": len(self.sites),
            "chapters_found": len(all_chapters),
        }
        
        return result
    
    async def _scan_single_site(self, site: Dict) -> Tuple[str, List[Tuple[str, str]], str]:
        """扫描单个小说站"""
        name = site["name"]
        search_tpl = site["search"]
        base = site["base"]
        
        chapters = []
        book_url = ""
        content = ""
        
        # 用不同标题搜索
        for query in self.all_titles[:3]:
            try:
                search_url = search_tpl.format(q=quote(query))
                headers = {"User-Agent": random_ua()}
                status, html, _ = await self.http.get(search_url, headers=headers)
                
                if status != 200 or not html:
                    continue
                
                # 检查搜索结果是否有匹配
                if not any(c in html for c in self.main_chars) and not any(t in html for t in self.all_titles[:2]):
                    continue
                
                # 提取书籍详情页链接
                soup_link = self._find_book_link(html, base, query)
                if soup_link:
                    book_url = soup_link
                    # 访问书籍页
                    status2, html2, _ = await self.http.get(book_url, headers=headers)
                    if status2 == 200 and html2:
                        # 提取章节列表
                        chs = self.parser.extract_chapter_links(html2, book_url)
                        if chs and len(chs) >= 3:
                            chapters = chs
                            # 尝试提取简介页内容
                            _, page_content = self.parser.extract_main_content(html2, book_url)
                            content = page_content
                            
                            # 访问第一章看看
                            if chs:
                                first_ch_title, first_ch_url = chs[0]
                                status3, html3, _ = await self.http.get(first_ch_url, headers=headers)
                                if status3 == 200 and html3:
                                    _, ch_content = self.parser.extract_main_content(html3, first_ch_url)
                                    if ch_content and self.parser.validate_content(ch_content)["is_match"]:
                                        content = ch_content  # 至少有第一章内容
                        
                        break  # 找到就不用试其他标题了
                        
            except Exception as e:
                self.logger.debug(f"  {name} 扫描失败: {e}")
                continue
        
        return book_url, chapters, content
    
    def _find_book_link(self, html: str, base_url: str, query: str) -> str:
        """从搜索结果页找到书籍链接"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            href = a['href']
            
            if not text or not href:
                continue
            
            # 检查是否包含标题或主角
            if (any(t in text for t in self.all_titles) or 
                any(c in text for c in self.main_chars[:2])):
                if href.startswith('/'):
                    href = urljoin(base_url, href)
                elif not href.startswith('http'):
                    href = urljoin(base_url, href)
                return href
        
        return ""
    
    async def _crawl_chapters(self, chapters: List[Tuple[str, str]]) -> str:
        """批量爬取章节内容"""
        self.logger.info(f"  开始爬取 {len(chapters)} 个章节...")
        
        sem = asyncio.Semaphore(2)
        all_contents = []
        
        async def crawl_one(idx: int, title: str, url: str):
            async with sem:
                try:
                    headers = {"User-Agent": random_ua()}
                    status, html, _ = await self.http.get(url, headers=headers)
                    if status != 200 or not html:
                        return None
                    
                    _, content = self.parser.extract_main_content(html, url)
                    validation = self.parser.validate_content(content)
                    if validation["is_match"] or validation["word_count"] > 100:
                        return (idx, title, content)
                except Exception as e:
                    self.logger.debug(f"  章节爬取失败 {title}: {e}")
                return None
        
        tasks = []
        for idx, (title, url) in enumerate(chapters):
            tasks.append(crawl_one(idx, title, url))
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid_chapters = []
        for r in results:
            if isinstance(r, Exception) or not r:
                continue
            valid_chapters.append(r)
        
        # 按原始顺序排序
        valid_chapters.sort(key=lambda x: x[0])
        
        self.logger.info(f"  成功爬取 {len(valid_chapters)}/{len(chapters)} 个章节")
        
        # 组装
        assembled = []
        for idx, title, content in valid_chapters:
            assembled.append(f"## {title}\n\n{content}")
        
        return "\n\n".join(assembled)
