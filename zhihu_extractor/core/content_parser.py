#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
内容解析器 - HTML清洗、正文提取、标点修正
"""
import re
from bs4 import BeautifulSoup
from typing import Tuple, List, Optional


class ContentParser:
    """HTML内容解析和清洗"""

    # 正文选择器优先级（从高到低）
    CONTENT_SELECTORS = [
        '#pContainer',                    # kepue.com
        '#content',
        '.content',
        '#chaptercontent',
        '.chapter-content',
        '.novel_content',
        '#js_content',                    # 微信
        '.rich_media_content',
        '#bookContent',
        '.read-content',
        '.text-wrap',
        '.txt_tcontent',
        'div.read_bd',
        '#BookText',
        '#nr1',
        'div.nr_nr',
    ]

    # 标题选择器
    TITLE_SELECTORS = [
        'h1', '.chapter-title', '.novel_name',
        'title', '#title', '.article-title',
    ]

    # 需要排除的元素
    EXCLUDE_SELECTORS = [
        'script', 'style', 'nav', 'header', 'footer',
        '.advertisement', '.ad', '.ads', '.banner',
        '.fch_settingBox', '.change_charpeter',
        '.novel_nav', '.ch_header', '.tools',
    ]

    @staticmethod
    def extract_title(html: str) -> str:
        """从HTML中提取标题"""
        soup = BeautifulSoup(html, 'html.parser')
        for selector in ContentParser.TITLE_SELECTORS:
            el = soup.select_one(selector)
            if el:
                title = el.get_text(strip=True)
                if title and len(title) > 1:
                    # 清理标题
                    title = re.sub(r'[-_|].*$', '', title).strip()
                    title = re.sub(r'第\d+章.*?免费阅读.*$', '', title)
                    return title
        return ""

    @staticmethod
    def extract_content(html: str, url: str = "") -> str:
        """
        从HTML中提取正文内容
        返回清洗后的纯文本
        """
        soup = BeautifulSoup(html, 'html.parser')

        # 移除不需要的元素
        for selector in ContentParser.EXCLUDE_SELECTORS:
            for el in soup.select(selector):
                el.decompose()

        # 尝试各种正文选择器
        content_div = None
        for selector in ContentParser.CONTENT_SELECTORS:
            content_div = soup.select_one(selector)
            if content_div:
                text = content_div.get_text(separator='\n', strip=True)
                if len(text) > 50:
                    break
                content_div = None

        if not content_div:
            # 回退：找最大的文本块
            content_div = ContentParser._find_largest_text_block(soup)

        if not content_div:
            return ""

        # 提取段落
        paragraphs = []
        for p in content_div.find_all(['p', 'br']):
            text = p.get_text(strip=True)
            if text:
                paragraphs.append(text)

        if not paragraphs:
            # 如果没有p标签，直接取文本
            text = content_div.get_text(separator='\n', strip=True)
            paragraphs = [p.strip() for p in text.split('\n') if p.strip()]

        content = '\n\n'.join(paragraphs)
        content = ContentParser.clean_text(content)

        return content

    @staticmethod
    def _find_largest_text_block(soup: BeautifulSoup):
        """找到页面上文本量最大的div"""
        best_div = None
        best_len = 0
        for div in soup.find_all('div'):
            text = div.get_text(strip=True)
            cn_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
            if cn_count > best_len:
                best_len = cn_count
                best_div = div
        return best_div if best_len > 100 else None

    @staticmethod
    def clean_text(text: str) -> str:
        """清洗文本：标点修正、空白处理"""
        if not text:
            return ""

        # 英文标点转中文（在中文上下文中）
        text = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]),', r'\1，', text)
        text = re.sub(r',([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])', r'，\1', text)
        text = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])\?', r'\1？', text)
        text = re.sub(r'\?([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])', r'？\1', text)
        text = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])!', r'\1！', text)
        text = re.sub(r'!([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])', r'！\1', text)
        text = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]):', r'\1：', text)

        # 移除多余空白
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        text = text.strip()

        return text

    @staticmethod
    def count_chinese(text: str) -> int:
        """统计中文字数"""
        return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')

    @staticmethod
    def extract_chapters_from_catalog(html: str, base_url: str = "") -> List[Tuple[str, str]]:
        """
        从目录页提取章节列表
        返回: [(章节标题, URL), ...]
        """
        soup = BeautifulSoup(html, 'html.parser')
        chapters = []
        seen_urls = set()

        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            href = a['href']

            # 匹配章节模式
            if re.search(r'第[0-9一二三四五六七八九十百千]+[章节回]', text):
                if href.startswith('/'):
                    href = base_url.rstrip('/') + href if base_url else href
                if href not in seen_urls:
                    seen_urls.add(href)
                    chapters.append((text, href))

        return chapters

    @staticmethod
    def find_next_chapter_link(html: str) -> Optional[str]:
        """在章节页中找到下一章的链接"""
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            if any(kw in text for kw in ['下一章', '下一页', 'next', 'Next', '下章']):
                return a['href']
        return None

    @staticmethod
    def has_paywall_markers(html: str) -> bool:
        """检查是否包含付费墙标记"""
        markers = [
            '付费内容', '盐选会员', 'VIP专享', '开通会员',
            '付费阅读', '订阅后查看', '登录查看', '内容已被删除',
            '404', '页面不存在', '资源未找到',
        ]
        return any(m in html for m in markers)

    @staticmethod
    def validate_content(text: str, target_config: dict) -> dict:
        """
        验证内容是否匹配目标文章
        返回验证结果
        """
        result = {
            "is_valid": False,
            "confidence": 0.0,
            "char_count": 0,
            "character_matches": [],
            "issues": [],
        }

        if not text or len(text) < 50:
            result["issues"].append("内容过短")
            return result

        cn_count = ContentParser.count_chinese(text)
        result["char_count"] = cn_count

        if cn_count < 100:
            result["issues"].append(f"中文字数过少: {cn_count}")
            return result

        # 检查主角名
        characters = target_config.get("characters", [])
        matched = []
        for char in characters:
            if char in text:
                matched.append(char)
        result["character_matches"] = matched

        # 计算置信度
        confidence = 0.0
        if len(matched) >= 2:
            confidence += 0.4
        if len(matched) >= 1:
            confidence += 0.3

        # 检查标题关键词
        title = target_config.get("title", "")
        title_chars = [c for c in title if '\u4e00' <= c <= '\u9fff']
        title_match_count = sum(1 for c in title_chars if c in text)
        if title_chars and title_match_count / len(title_chars) > 0.5:
            confidence += 0.15

        # 检查弹幕特征（本文特有）
        if '弹幕' in text and '【' in text and '】' in text:
            confidence += 0.25

        # 检查弹幕格式
        danmu_count = text.count('【') + text.count('】')
        if danmu_count >= 4:
            confidence += 0.1

        result["confidence"] = min(confidence, 1.0)
        result["is_valid"] = result["confidence"] >= 0.4

        return result
