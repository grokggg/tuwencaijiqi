# -*- coding: utf-8 -*-
"""
ZPE vNext - 内容解析器
HTML清理、正文提取、内容验证
"""
import re
import html as html_lib
from typing import Optional, List, Tuple
from bs4 import BeautifulSoup, Comment

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from core.http_client import cn_count


class ContentParser:
    """内容解析和验证器"""
    
    def __init__(self):
        self.title = config.TARGET["title"]
        self.alt_titles = config.TARGET["alternate_titles"]
        self.main_chars = config.TARGET["main_characters"]
    
    def extract_main_content(self, html: str, url: str = "") -> Tuple[str, str]:
        """
        智能提取正文内容
        返回: (title, content)
        """
        soup = BeautifulSoup(html, 'html.parser')
        
        # 移除无用元素
        for elem in soup(['script', 'style', 'nav', 'footer', 'header', 'aside',
                          'iframe', 'noscript', 'form', 'button', 'svg', 'img']):
            elem.decompose()
        
        # 移除注释
        for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
            comment.extract()
        
        # 提取标题
        title = self._extract_title(soup)
        
        # 尝试多种正文选择器
        content = ""
        
        # 常见小说站/文章站正文选择器
        selectors = [
            # 小说站常见
            '#content', '#chaptercontent', '#BookText', '#htmlContent',
            '.content', '.chapter-content', '.read-content', '.article-content',
            '.novel-content', '.txt', '.showtxt', '.article-con', '#booktext',
            '.text', '#text', '.bookcontent', '.article_content',
            # 知乎
            '.Post-RichTextContainer', '.RichText', '.Post-Main',
            '.ContentItem-main', '.RichText.ztext',
            # 通用
            'article', '.article', '.post-content', '.entry-content',
            '#main-content', '.main-content', '.content-wrap',
        ]
        
        for sel in selectors:
            el = soup.select_one(sel)
            if el:
                text = self._clean_text(el.get_text(separator='\n', strip=True))
                if cn_count(text) > 200:  # 至少200字才认为是正文
                    content = text
                    break
        
        # 如果没找到，尝试找最长的p标签集合
        if not content or cn_count(content) < 200:
            content = self._extract_from_paragraphs(soup)
        
        # 如果还是没找到，取body中所有文本
        if not content or cn_count(content) < 200:
            body = soup.body
            if body:
                content = self._clean_text(body.get_text(separator='\n', strip=True))
        
        return title, content
    
    def _extract_title(self, soup: BeautifulSoup) -> str:
        """提取页面标题"""
        # 尝试h1
        h1 = soup.find('h1')
        if h1:
            t = h1.get_text(strip=True)
            if len(t) > 2:
                return t
        
        # 尝试title标签
        if soup.title:
            t = soup.title.get_text(strip=True)
            # 移除站点后缀
            for sep in ['_', '-', '|', '–', '—']:
                if sep in t:
                    t = t.split(sep)[0].strip()
            if len(t) > 2:
                return t
        
        return ""
    
    def _extract_from_paragraphs(self, soup: BeautifulSoup) -> str:
        """从p标签提取正文"""
        paragraphs = soup.find_all('p')
        if not paragraphs:
            return ""
        
        # 过滤短的p标签
        valid_p = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if len(text) > 10:
                valid_p.append(text)
        
        return self._clean_text('\n'.join(valid_p))
    
    def _clean_text(self, text: str) -> str:
        """清理文本"""
        # HTML实体解码
        text = html_lib.unescape(text)
        
        # 移除多余空白
        lines = text.split('\n')
        cleaned = []
        for line in lines:
            line = line.strip()
            # 移除广告和导航文本
            if self._is_noise_line(line):
                continue
            if line:
                cleaned.append(line)
        
        return '\n\n'.join(cleaned)
    
    def _is_noise_line(self, line: str) -> bool:
        """判断是否是噪音行"""
        noise_patterns = [
            r'^第[0-9一二三四五六七八九十百千]+章',  # 重复的章节标题
            r'^手机用户.*?请.*?阅读',
            r'^请记住本书首发域名',
            r'^最新章节.*?免费阅读',
            r'^笔趣阁.*?更新',
            r'^本章未完.*?点击',
            r'^上一章.*?下一章',
            r'^返回目录',
            r'^加入书签',
            r'^Error 404',
            r'^百度',
            r'^登录',
            r'^注册',
            r'^下载APP',
            r'^扫码.*?阅读',
        ]
        for pattern in noise_patterns:
            if re.search(pattern, line):
                return True
        return False
    
    def validate_content(self, content: str) -> dict:
        """
        验证内容是否匹配目标文章
        返回验证结果
        """
        result = {
            "is_match": False,
            "word_count": cn_count(content),
            "has_title": False,
            "has_main_char": False,
            "chars_found": [],
            "is_truncated": False,
            "confidence": 0.0,
        }
        
        # 检查主角
        chars_found = []
        for char in self.main_chars:
            if char in content:
                chars_found.append(char)
        result["chars_found"] = chars_found
        result["has_main_char"] = len(chars_found) >= 2  # 至少有2个主角
        
        # 检查标题/别名
        all_titles = [self.title] + self.alt_titles
        for t in all_titles:
            if t in content:
                result["has_title"] = True
                break
        
        # 检查是否被截断
        truncation_indicators = [
            '余下全文', 'VIP章节', '付费阅读', '登录后查看',
            '展开全文', '查看更多', '本章未完', '...<点击',
            '购买专栏', '盐选会员', '开通会员', '订阅后',
        ]
        for indicator in truncation_indicators:
            if indicator in content[-500:] if len(content) > 500 else indicator in content:
                result["is_truncated"] = True
                break
        
        # 计算置信度
        confidence = 0.0
        if result["has_main_char"]:
            confidence += 0.4
        if result["has_title"]:
            confidence += 0.2
        if result["word_count"] > 1000:
            confidence += 0.2
        if not result["is_truncated"]:
            confidence += 0.2
        if result["word_count"] > 5000:
            confidence += 0.2
        
        result["confidence"] = min(confidence, 1.0)
        result["is_match"] = result["has_main_char"] and result["confidence"] >= 0.4
        
        return result
    
    def extract_chapter_links(self, html: str, base_url: str) -> List[Tuple[str, str]]:
        """
        从目录页提取章节链接
        返回: [(chapter_title, url), ...]
        """
        soup = BeautifulSoup(html, 'html.parser')
        chapters = []
        
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            href = a['href']
            
            if not text or not href:
                continue
            
            # 匹配章节模式
            if re.search(r'第[0-9一二三四五六七八九十百千]+[章节回]', text):
                # 转换相对URL
                if href.startswith('/'):
                    href = base_url.rstrip('/') + href
                elif not href.startswith('http'):
                    href = base_url.rstrip('/') + '/' + href
                chapters.append((text, href))
            # 或者链接路径看起来像章节
            elif re.search(r'/\d+\.html$', href) or re.search(r'/\d+/?$', href):
                if len(text) > 1 and len(text) < 100:
                    if href.startswith('/'):
                        href = base_url.rstrip('/') + href
                    elif not href.startswith('http'):
                        href = base_url.rstrip('/') + '/' + href
                    chapters.append((text, href))
        
        # 去重
        seen = set()
        unique = []
        for title, url in chapters:
            if url not in seen:
                seen.add(url)
                unique.append((title, url))
        
        return unique
    
    def merge_contents(self, contents: List[Tuple[str, str]]) -> str:
        """
        合并多个来源的内容，去重拼接
        contents: [(source_name, content), ...]
        """
        # 按字数排序，长的优先
        sorted_contents = sorted(contents, key=lambda x: cn_count(x[1]), reverse=True)
        
        all_paragraphs = []
        seen_paragraphs = set()
        
        for source, content in sorted_contents:
            paragraphs = content.split('\n\n')
            for p in paragraphs:
                p_stripped = p.strip()
                if not p_stripped:
                    continue
                # 用前50字作为去重key
                key = p_stripped[:50]
                if key not in seen_paragraphs and len(p_stripped) > 5:
                    seen_paragraphs.add(key)
                    all_paragraphs.append(p_stripped)
        
        return '\n\n'.join(all_paragraphs)
