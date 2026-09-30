# -*- coding: utf-8 -*-
"""
ZPE vNext - 搜索引擎OSINT引擎
通过百度、必应、搜狗等搜索引擎发现转载链接
"""
import asyncio
import re
from typing import Dict, List, Any
from urllib.parse import urlparse, parse_qs, unquote

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from core.http_client import cn_count, random_ua


class SearchOSINTEngine(BaseEngine):
    """搜索引擎OSINT发现引擎"""
    
    name = "search_osint"
    description = "通过搜索引擎发现第三方转载链接"
    priority = 100  # 最高优先级，先发现链接
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.all_titles = [config.TARGET["title"]] + config.TARGET["alternate_titles"]
        self.main_chars = config.TARGET["main_characters"]
    
    async def run(self, context: Dict[str, Any]) -> EngineResult:
        result = self.create_result()
        discovered_urls = []
        all_content_pieces = []
        
        # 构建搜索查询词组合
        queries = self._build_queries()
        self.logger.info(f"构建了 {len(queries)} 个搜索查询")
        
        # 并发搜索多个搜索引擎
        tasks = []
        for engine_name, engine_cfg in config.SEARCH_ENGINES.items():
            if not engine_cfg.get("enabled", True):
                continue
            for query in queries[:8]:  # 限制查询数避免请求过多
                tasks.append(self._search_one(engine_name, engine_cfg, query))
        
        search_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 处理搜索结果
        for sr in search_results:
            if isinstance(sr, Exception):
                continue
            if not sr:
                continue
            urls, contents = sr
            for url in urls:
                if url not in discovered_urls and self._is_potential_source(url):
                    discovered_urls.append(url)
            all_content_pieces.extend(contents)
        
        self.logger.info(f"发现 {len(discovered_urls)} 个潜在来源URL")
        
        # 现在并发访问发现的URL，提取内容
        if discovered_urls:
            self.logger.info(f"并发访问 {len(discovered_urls[:20])} 个发现的URL...")
            fetch_tasks = []
            sem = asyncio.Semaphore(3)
            
            async def fetch_one(url):
                async with sem:
                    return await self._fetch_and_extract(url)
            
            for url in discovered_urls[:30]:
                fetch_tasks.append(fetch_one(url))
            
            fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
            
            best_content = ""
            best_confidence = 0.0
            best_source = ""
            
            for fr in fetch_results:
                if isinstance(fr, Exception) or not fr:
                    continue
                url, title, content, validation = fr
                if validation["is_match"] and content:
                    if validation["confidence"] > best_confidence:
                        best_confidence = validation["confidence"]
                        best_content = content
                        best_source = url
                        result.title = title
                    if validation["word_count"] > 1000:
                        all_content_pieces.append((url, content))
                    
                    # 检查是否有章节列表
                    chapters = self.parser.extract_chapter_links(
                        await self._get_raw_html(url), url
                    ) if content else []
                    if chapters and len(chapters) >= 3:
                        result.chapters.extend(chapters)
            
            if best_content:
                result.success = True
                result.content = best_content
                result.source_url = best_source
                result.word_count = cn_count(best_content)
                result.confidence = best_confidence
                if best_confidence >= 0.7 and result.word_count > 3000:
                    result.bypass_found = True
                    result.bypass_method = f"搜索引擎发现第三方转载: {best_source} ({result.word_count}字)"
        
        result.discovered_urls = discovered_urls
        result.details = {
            "queries_used": queries,
            "urls_found": len(discovered_urls),
        }
        
        return result
    
    def _build_queries(self) -> List[str]:
        """构建搜索查询组合"""
        queries = []
        base_queries = []
        
        # 标题组合
        for title in self.all_titles:
            base_queries.append(title)
            base_queries.append(f"{title} 免费阅读")
            base_queries.append(f"{title} 全文")
            base_queries.append(f"{title} 小说")
            base_queries.append(f"{title} 笔趣阁")
        
        # 主角组合
        for char in self.main_chars[:2]:
            base_queries.append(f"{char} 孟娇蕊 小说")
            base_queries.append(f"靳川 {char} 免费阅读")
        
        # 去重
        seen = set()
        for q in base_queries:
            if q not in seen:
                seen.add(q)
                queries.append(q)
        
        return queries
    
    async def _search_one(self, engine_name: str, cfg: Dict, query: str):
        """搜索单个引擎"""
        urls_out = []
        contents_out = []
        
        try:
            for page in range(0, 2):
                url = cfg["url"]
                params = {}
                for k, v in cfg["params"].items():
                    if "{query}" in v:
                        params[k] = v.format(query=query)
                    elif "{page}" in v:
                        offset = page * 10 if engine_name in ["baidu", "sogou", "360"] else page * 10 + 1
                        params[k] = v.format(page=offset)
                    else:
                        params[k] = v
                
                headers = {"User-Agent": random_ua()}
                status, html, resp_headers = await self.http.get(url, headers=headers, params=params)
                
                if status == 200 and html:
                    # 提取搜索结果中的URL
                    found_urls = self._extract_search_urls(html, engine_name)
                    urls_out.extend(found_urls)
                    
                    # 也检查搜索摘要中的内容
                    if any(c in html for c in self.main_chars):
                        contents_out.append(html)
                
                await asyncio.sleep(0.5)
                
        except Exception as e:
            self.logger.debug(f"搜索 {engine_name} 失败: {e}")
        
        return urls_out, contents_out
    
    def _extract_search_urls(self, html: str, engine: str) -> List[str]:
        """从搜索结果页提取URL"""
        urls = []
        
        # 提取所有href
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text(strip=True)
            
            # 跳过搜索引擎自身链接
            if any(skip in href for skip in ['baidu.com/link', 'bing.com/ck', 'sogou.com/link',
                                              'javascript:', '#', 'login', 'register']):
                # 但要提取百度跳转链接
                if 'baidu.com/link' in href or 'sogou.com/link' in href:
                    urls.append(href)
                continue
            
            # 检查是否是相关结果
            if any(t in text for t in self.all_titles + self.main_chars):
                if href.startswith('http'):
                    urls.append(href)
        
        # 也从HTML中直接提取URL模式
        url_pattern = r'https?://[^\s<>"\']+[^\s<>"\'.,;:)]'
        for match in re.findall(url_pattern, html):
            if self._is_potential_source(match):
                urls.append(match)
        
        return list(set(urls))
    
    def _is_potential_source(self, url: str) -> bool:
        """判断URL是否可能是内容来源"""
        if not url.startswith('http'):
            return False
        
        # 跳过明显不是内容的站点
        skip_domains = [
            'baidu.com', 'bing.com', 'sogou.com', 'so.com', 'google.com',
            'zhihu.com', 'weibo.com', 'bilibili.com', 'douyin.com',
            'qq.com', '163.com', 'sina.com.cn', 'sohu.com',
            'facebook.com', 'twitter.com', 'youtube.com',
        ]
        
        domain = urlparse(url).netloc.lower()
        for skip in skip_domains:
            if skip in domain and domain != 'zhuanlan.zhihu.com':
                return False
        
        # 小说站、文章站特征
        novel_indicators = [
            'biquge', 'biqukan', 'xs', 'shuquge', 'txt', 'novel', 'book',
            'read', 'chapter', 'xiaoshuo', 'wenxue', 'kepue', 'syzgly',
            '630', '23usp', 'beqege', 'bqgui', 'ibiquge',
        ]
        
        path = urlparse(url).path.lower()
        for ind in novel_indicators:
            if ind in domain or ind in path:
                return True
        
        # 如果URL中包含文章ID特征（数字较长）
        if re.search(r'/\d{6,}', path):
            return True
        
        return False
    
    async def _get_raw_html(self, url: str) -> str:
        """获取原始HTML（用于章节提取）"""
        try:
            headers = {"User-Agent": random_ua()}
            status, html, _ = await self.http.get(url, headers=headers)
            return html if status == 200 else ""
        except:
            return ""
    
    async def _fetch_and_extract(self, url: str):
        """访问URL并提取内容"""
        try:
            # 处理百度跳转链接
            if 'baidu.com/link' in url or 'sogou.com/link' in url:
                headers = {"User-Agent": random_ua()}
                status, html, resp_headers = await self.http.get(
                    url, headers=headers, follow_redirects=True
                )
                # 获取重定向后的URL
                url = str(resp_headers.get('location', url))
            
            headers = {"User-Agent": random_ua()}
            status, html, _ = await self.http.get(url, headers=headers)
            
            if status != 200 or not html:
                return None
            
            title, content = self.parser.extract_main_content(html, url)
            if not content or cn_count(content) < 50:
                return None
            
            validation = self.parser.validate_content(content)
            return (url, title, content, validation)
            
        except Exception as e:
            self.logger.debug(f"访问失败 {url}: {e}")
            return None
