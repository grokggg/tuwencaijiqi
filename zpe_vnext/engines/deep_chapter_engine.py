# -*- coding: utf-8 -*-
"""
ZPE vNext - 深度章节爬取引擎
基于已发现的信息，专门针对小说站进行深度遍历和章节爬取
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


class DeepChapterEngine(BaseEngine):
    """深度章节爬取引擎 - 针对已知有效路径进行深入爬取"""
    
    name = "deep_chapter"
    description = "深度章节遍历与爬取"
    priority = 95  # 很高优先级，基于已有线索深挖
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.all_titles = [config.TARGET["title"]] + config.TARGET["alternate_titles"]
        self.main_chars = config.TARGET["main_characters"]
        
        # 之前侦察发现的高价值目标模式
        self.known_patterns = [
            # kepue.com 模式
            {
                "name": "kepue_nvpin",
                "discover": [
                    "https://kepue.com/nvpin/38738/",  # 之前发现的
                    "https://kepue.com/search.php?q={q}",
                ],
                "chapter_pattern": r'/nvpin/\d+/\d+\.html',
            },
            # syzgly.com (随意阅读网)
            {
                "name": "syzgly",
                "discover": [
                    "https://www.syzgly.com/search.php?q={q}",
                ],
                "chapter_pattern": r'/\d+/\d+\.html',
            },
        ]
    
    async def run(self, context: Dict[str, Any]) -> EngineResult:
        result = self.create_result()
        
        # 收集已发现的章节和URL
        existing_chapters = context.get("chapters", [])
        discovered_urls = context.get("discovered_urls", [])
        existing_content = context.get("best_content", "")
        
        all_chapters = list(existing_chapters)
        all_contents = []
        best_content = existing_content
        best_word_count = cn_count(best_content) if best_content else 0
        
        # 1. 首先尝试访问kepue.com已知路径 (之前侦察发现的高价值目标)
        self.logger.info("阶段1: 深入爬取kepue.com已知路径...")
        kepue_content, kepue_chapters = await self._crawl_kepue()
        if kepue_chapters:
            all_chapters.extend(kepue_chapters)
        if kepue_content and cn_count(kepue_content) > best_word_count:
            best_content = kepue_content
            best_word_count = cn_count(kepue_content)
            all_contents.append(("kepue_known", kepue_content))
        
        # 2. 爬取syzgly.com (随意阅读网 - 已有前5章)
        self.logger.info("阶段2: 深入爬取syzgly.com...")
        syzgly_content, syzgly_chapters = await self._crawl_syzgly()
        if syzgly_chapters:
            all_chapters.extend(syzgly_chapters)
        if syzgly_content and cn_count(syzgly_content) > best_word_count:
            best_content = syzgly_content
            best_word_count = cn_count(syzgly_content)
            all_contents.append(("syzgly", syzgly_content))
        
        # 3. 爬取已发现URL中的章节
        if discovered_urls:
            self.logger.info(f"阶段3: 爬取 {len(discovered_urls)} 个已发现URL的章节...")
            for url in discovered_urls[:10]:
                try:
                    chapters, content = await self._crawl_url_chapters(url)
                    if chapters and len(chapters) >= 3:
                        all_chapters.extend(chapters)
                    if content and cn_count(content) > 200:
                        all_contents.append((url, content))
                except:
                    pass
        
        # 4. 去重并爬取所有收集到的章节
        if all_chapters:
            # 章节去重
            seen_urls = set()
            unique_chapters = []
            for title, url in all_chapters:
                if url not in seen_urls:
                    seen_urls.add(url)
                    unique_chapters.append((title, url))
            
            self.logger.info(f"共收集到 {len(unique_chapters)} 个唯一章节，开始批量爬取...")
            
            crawled_content = await self._batch_crawl_chapters(unique_chapters)
            if crawled_content:
                all_contents.append(("batch_crawl", crawled_content))
                if cn_count(crawled_content) > best_word_count:
                    best_content = crawled_content
                    best_word_count = cn_count(crawled_content)
        
        # 5. 合并所有内容
        if all_contents:
            merged = self.parser.merge_contents(all_contents)
            if cn_count(merged) > best_word_count:
                best_content = merged
                best_word_count = cn_count(merged)
        
        if best_content and best_word_count > 300:
            result.success = True
            result.content = best_content
            result.word_count = best_word_count
            result.chapters = all_chapters
            result.source_url = "deep_chapter_crawl"
            result.confidence = 0.85 if best_word_count > 5000 else 0.6
            
            if best_word_count >= 5000:
                result.bypass_found = True
                result.bypass_method = f"深度章节爬取获取 {best_word_count} 字内容"
        
        result.details = {
            "chapters_crawled": len(all_chapters),
            "content_sources": len(all_contents),
        }
        
        return result
    
    async def _crawl_kepue(self) -> Tuple[str, List[Tuple[str, str]]]:
        """爬取kepue.com已知路径"""
        base_url = "https://kepue.com/nvpin/38738/"
        chapters = []
        content = ""
        
        headers = {"User-Agent": random_ua()}
        
        # 首先尝试访问已知的目录页
        for try_url in [base_url, base_url + "index.html"]:
            try:
                status, html, _ = await self.http.get(try_url, headers=headers)
                if status == 200 and html:
                    # 检查是否有目标内容
                    if any(c in html for c in self.main_chars[:2]):
                        chs = self.parser.extract_chapter_links(html, base_url)
                        if chs:
                            chapters = chs
                            self.logger.info(f"  kepue: 发现 {len(chapters)} 个章节")
                            break
            except:
                pass
        
        # 如果没找到章节列表，尝试暴力枚举章节号
        if not chapters:
            self.logger.info("  kepue: 未找到章节目录，尝试枚举章节URL...")
            # kepue章节URL模式: /nvpin/38738/{num}.html 或 /nvpin/38738/{num}/
            sem = asyncio.Semaphore(3)
            found_chapters = []
            
            async def try_chapter(num: int):
                async with sem:
                    for suffix in ['.html', '/', '']:
                        url = f"https://kepue.com/nvpin/38738/{num}{suffix}"
                        try:
                            status, html, _ = await self.http.get(url, headers=headers)
                            if status == 200 and html and any(c in html for c in self.main_chars[:2]):
                                _, ch_content = self.parser.extract_main_content(html, url)
                                if ch_content and cn_count(ch_content) > 100:
                                    title = f"第{num}章"
                                    # 尝试从页面提取真实标题
                                    from bs4 import BeautifulSoup
                                    soup = BeautifulSoup(html, 'html.parser')
                                    h1 = soup.find('h1')
                                    if h1:
                                        title = h1.get_text(strip=True)
                                    return (title, url, ch_content)
                        except:
                            pass
                    return None
            
            # 尝试1-100章
            tasks = [try_chapter(n) for n in range(1, 101)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            valid = []
            for r in results:
                if isinstance(r, Exception) or not r:
                    continue
                valid.append(r)
            
            if valid:
                # 按章节号排序（假设URL中数字是章节号）
                def extract_num(item):
                    title, url, _ = item
                    m = re.search(r'/(\d+)(?:\.html|/)?$', url)
                    return int(m.group(1)) if m else 999
                
                valid.sort(key=extract_num)
                chapters = [(t, u) for t, u, _ in valid]
                content_parts = [f"## {t}\n\n{c}" for t, u, c in valid]
                content = "\n\n".join(content_parts)
                self.logger.info(f"  kepue: 枚举找到 {len(valid)} 章")
        
        # 如果有章节目录，爬取所有章节
        if chapters and not content:
            content = await self._batch_crawl_chapters(chapters)
        
        return content, chapters
    
    async def _crawl_syzgly(self) -> Tuple[str, List[Tuple[str, str]]]:
        """爬取syzgly.com (随意阅读网)"""
        chapters = []
        content = ""
        
        # 搜索标题
        for query in self.all_titles[:3]:
            try:
                search_url = f"https://www.syzgly.com/search.php?q={quote(query)}"
                headers = {"User-Agent": random_ua()}
                status, html, _ = await self.http.get(search_url, headers=headers)
                
                if status != 200 or not html:
                    continue
                
                if not any(c in html for c in self.main_chars[:2]):
                    continue
                
                # 找到书籍链接
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(html, 'html.parser')
                book_url = ""
                
                for a in soup.find_all('a', href=True):
                    text = a.get_text(strip=True)
                    href = a['href']
                    if any(t in text for t in self.all_titles) or any(c in text for c in self.main_chars[:2]):
                        if href.startswith('/'):
                            href = urljoin("https://www.syzgly.com/", href)
                        elif not href.startswith('http'):
                            href = urljoin("https://www.syzgly.com/", href)
                        book_url = href
                        break
                
                if book_url:
                    # 访问书籍页
                    status2, html2, _ = await self.http.get(book_url, headers=headers)
                    if status2 == 200 and html2:
                        chs = self.parser.extract_chapter_links(html2, book_url)
                        if chs and len(chs) >= 3:
                            chapters = chs
                            self.logger.info(f"  syzgly: 发现 {len(chapters)} 个章节")
                            break
                            
            except Exception as e:
                self.logger.debug(f"  syzgly搜索失败: {e}")
                continue
        
        if chapters:
            content = await self._batch_crawl_chapters(chapters)
        
        return content, chapters
    
    async def _crawl_url_chapters(self, url: str) -> Tuple[List[Tuple[str, str]], str]:
        """从URL爬取章节"""
        chapters = []
        content = ""
        
        try:
            headers = {"User-Agent": random_ua()}
            status, html, _ = await self.http.get(url, headers=headers)
            if status == 200 and html:
                chs = self.parser.extract_chapter_links(html, url)
                if chs and len(chs) >= 3:
                    chapters = chs
                    content = await self._batch_crawl_chapters(chapters[:50])
        except:
            pass
        
        return chapters, content
    
    async def _batch_crawl_chapters(self, chapters: List[Tuple[str, str]]) -> str:
        """批量爬取章节内容"""
        sem = asyncio.Semaphore(2)
        results = []
        
        async def crawl_one(idx, title, url):
            async with sem:
                try:
                    headers = {"User-Agent": random_ua()}
                    status, html, _ = await self.http.get(url, headers=headers)
                    if status == 200 and html:
                        _, content = self.parser.extract_main_content(html, url)
                        validation = self.parser.validate_content(content)
                        if validation["word_count"] > 50:
                            return (idx, title, content)
                except:
                    pass
                return None
        
        tasks = [crawl_one(i, t, u) for i, (t, u) in enumerate(chapters)]
        crawl_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        valid = []
        for r in crawl_results:
            if isinstance(r, Exception) or not r:
                continue
            valid.append(r)
        
        valid.sort(key=lambda x: x[0])
        
        parts = []
        for idx, title, content in valid:
            parts.append(f"## {title}\n\n{content}")
        
        self.logger.info(f"  批量爬取: {len(valid)}/{len(chapters)} 章成功")
        return "\n\n".join(parts)
