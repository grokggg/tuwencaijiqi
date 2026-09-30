# -*- coding: utf-8 -*-
"""
ZCCSA 内容提取与对比分析
- 从HTML/JSON响应中提取正文内容
- 对比不同引擎返回内容的完整度
- 输出Markdown格式
"""
import hashlib
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)

# 尝试导入selectolax（高性能解析），失败则使用BeautifulSoup
try:
    from selectolax.parser import HTMLParser as SelectolaxParser
    HAS_SELECTOLAX = True
except ImportError:
    HAS_SELECTOLAX = False

from bs4 import BeautifulSoup, NavigableString, Tag

try:
    import html2text
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False


@dataclass
class ExtractedContent:
    """提取后的内容对象"""
    url: str = ""
    title: str = ""
    author: str = ""
    content_html: str = ""
    content_text: str = ""
    content_markdown: str = ""
    images: List[str] = field(default_factory=list)
    paragraphs: int = 0
    char_count: int = 0  # 中文字符+有效字符数
    word_count_cn: int = 0  # 中文字数
    is_truncated: bool = True  # 是否疑似截断
    truncation_indicators: List[str] = field(default_factory=list)  # 截断标记
    source_engine: str = ""  # 来源引擎
    content_hash: str = ""  # 内容Hash（去重用）
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "url": self.url,
            "title": self.title,
            "author": self.author,
            "char_count": self.char_count,
            "word_count_cn": self.word_count_cn,
            "paragraphs": self.paragraphs,
            "is_truncated": self.is_truncated,
            "truncation_indicators": self.truncation_indicators,
            "source_engine": self.source_engine,
            "content_hash": self.content_hash,
        }


@dataclass
class CompareResult:
    """内容对比结果"""
    baseline_chars: int = 0
    candidate_chars: int = 0
    ratio: float = 0.0  # candidate / baseline
    delta_chars: int = 0
    is_bypass: bool = False  # 是否绕过付费墙
    new_content_found: bool = False
    missing_in_candidate: List[str] = field(default_factory=list)


class ContentParser:
    """
    统一内容解析器：支持HTML/JSON，多策略正文提取。
    优先使用selectolax（性能更好），回退BeautifulSoup。
    """

    # 截断标记词（在内容末尾出现表示被截断）
    TRUNCATION_MARKERS = [
        "购买专栏", "查看全文", "展开全文", "解锁全文", "继续阅读",
        "阅读全文", "开通会员", "Salt", "盐选", "订阅", "付费后",
        "查看剩余", "下一段", "vip", "VIP", "会员", "购买",
        "未完待续", "本章未完", "加载中", "剩余.*?字",
    ]

    def __init__(self):
        self._h2t = None
        if HAS_HTML2TEXT:
            self._h2t = html2text.HTML2Text()
            self._h2t.body_width = 0
            self._h2t.ignore_links = False
            self._h2t.ignore_images = False
            self._h2t.ignore_emphasis = False

    def parse_html(self, html: str, url: str = "",
                   engine_name: str = "") -> ExtractedContent:
        """
        从HTML中提取正文内容（多策略尝试）
        """
        content = ExtractedContent(url=url, source_engine=engine_name)
        if not html or len(html) < 100:
            return content

        # 选择解析器
        if HAS_SELECTOLAX:
            content = self._parse_with_selectolax(html, url, engine_name)
        else:
            content = self._parse_with_bs4(html, url, engine_name)

        # 计算Hash
        content.content_hash = self._compute_hash(content.content_text)
        content.char_count = len(content.content_text)
        content.word_count_cn = len(re.findall(r'[\u4e00-\u9fff]', content.content_text))

        # 截断检测
        self._detect_truncation(content, html)

        # Markdown转换
        if self._h2t and content.content_html:
            try:
                content.content_markdown = self._h2t.handle(content.content_html)
            except Exception:
                content.content_markdown = content.content_text
        else:
            content.content_markdown = content.content_text

        return content

    def _parse_with_selectolax(self, html: str, url: str,
                                engine_name: str) -> ExtractedContent:
        """使用selectolax高性能解析"""
        content = ExtractedContent(url=url, source_engine=engine_name)
        try:
            tree = SelectolaxParser(html)

            # 提取标题
            for sel in ["h1.Post-Title", "h1.article-title", "h1", "title"]:
                node = tree.css_first(sel)
                if node:
                    content.title = node.text(strip=True)
                    break

            # 移除噪声标签
            for sel in config.NOISE_SELECTORS:
                for node in tree.css(sel):
                    node.decompose()

            # 尝试正文选择器
            best_node = None
            best_score = 0
            for sel in config.CONTENT_SELECTORS:
                for node in tree.css(sel):
                    text = node.text(separator="\n", strip=True)
                    score = self._score_text(text)
                    if score > best_score:
                        best_score = score
                        best_node = node

            # 若选择器未找到，使用文本密度启发式
            if not best_node or best_score < 100:
                best_node = self._find_densest_node_selectolax(tree)

            if best_node:
                content.content_html = best_node.html
                content.content_text = best_node.text(separator="\n", strip=True)
                content.content_text = self._clean_text(content.content_text)
                content.paragraphs = len([p for p in content.content_text.split('\n') if p.strip()])
                # 提取图片
                content.images = [img.attributes.get("src", "")
                                  for img in best_node.css("img")
                                  if img.attributes.get("src")]
        except Exception as e:
            logger.debug(f"selectolax解析失败: {e}")
        return content

    def _parse_with_bs4(self, html: str, url: str,
                        engine_name: str) -> ExtractedContent:
        """使用BeautifulSoup解析（回退方案）"""
        content = ExtractedContent(url=url, source_engine=engine_name)
        try:
            soup = BeautifulSoup(html, "lxml")

            # 标题
            t = soup.find("title")
            if t:
                content.title = t.get_text(strip=True)
            for sel in ["h1.Post-Title", "h1.article-title", "h1"]:
                el = soup.select_one(sel)
                if el:
                    content.title = el.get_text(strip=True)
                    break

            # 移除噪声
            for sel in config.NOISE_SELECTORS:
                for el in soup.select(sel):
                    el.decompose()

            # 正文选择器
            best_el = None
            best_score = 0
            for sel in config.CONTENT_SELECTORS:
                for el in soup.select(sel):
                    text = el.get_text(separator="\n", strip=True)
                    score = self._score_text(text)
                    if score > best_score:
                        best_score = score
                        best_el = el

            if not best_el or best_score < 100:
                best_el = self._find_densest_node_bs4(soup)

            if best_el:
                content.content_html = str(best_el)
                content.content_text = best_el.get_text(separator="\n", strip=True)
                content.content_text = self._clean_text(content.content_text)
                content.paragraphs = len([p for p in content.content_text.split('\n') if p.strip()])
                content.images = [img.get("src", "") for img in best_el.find_all("img")
                                  if img.get("src")]
        except Exception as e:
            logger.debug(f"BS4解析失败: {e}")
        return content

    def parse_json_api(self, data: Any, url: str = "",
                       engine_name: str = "") -> ExtractedContent:
        """从知乎API JSON响应中提取内容"""
        content = ExtractedContent(url=url, source_engine=engine_name)
        if not data:
            return content

        # 递归查找内容字段
        text_fields = ["content", "excerpt", "body", "text", "html", "answer_content"]
        title_fields = ["title", "question_title", "name"]
        author_fields = ["author", "author_name", "user_name"]

        def search_dict(obj, depth=0):
            if depth > 8 or obj is None:
                return
            if isinstance(obj, dict):
                # 标题
                for tf in title_fields:
                    if tf in obj and isinstance(obj[tf], str) and not content.title:
                        content.title = obj[tf].strip()
                # 作者
                for af in author_fields:
                    if af in obj:
                        val = obj[af]
                        if isinstance(val, str):
                            content.author = val.strip()
                        elif isinstance(val, dict) and "name" in val:
                            content.author = val["name"].strip()
                # 内容（优先长文本）
                for tf in text_fields:
                    if tf in obj and isinstance(obj[tf], str) and len(obj[tf]) > 50:
                        candidate = obj[tf]
                        if len(candidate) > len(content.content_html):
                            content.content_html = candidate
                # 图片
                if "images" in obj and isinstance(obj["images"], list):
                    content.images.extend([str(i) for i in obj["images"] if isinstance(i, str)])
                # 递归
                for v in obj.values():
                    search_dict(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    search_dict(item, depth + 1)

        search_dict(data)

        # HTML内容转文本
        if content.content_html:
            if content.content_html.strip().startswith("<"):
                try:
                    soup = BeautifulSoup(content.content_html, "lxml")
                    content.content_text = self._clean_text(
                        soup.get_text(separator="\n", strip=True))
                except Exception:
                    content.content_text = self._clean_text(content.content_html)
            else:
                content.content_text = self._clean_text(content.content_html)

            if self._h2t:
                try:
                    content.content_markdown = self._h2t.handle(content.content_html)
                except Exception:
                    content.content_markdown = content.content_text

        content.content_hash = self._compute_hash(content.content_text)
        content.char_count = len(content.content_text)
        content.word_count_cn = len(re.findall(r'[\u4e00-\u9fff]', content.content_text))
        content.paragraphs = len([p for p in content.content_text.split('\n') if p.strip()])
        self._detect_truncation(content, content.content_text)
        return content

    def compare(self, baseline: ExtractedContent,
                candidate: ExtractedContent) -> CompareResult:
        """
        对比候选内容相对基线内容的差异
        基线通常是无Cookie的截断响应，候选是变异请求后的响应
        """
        result = CompareResult(
            baseline_chars=baseline.char_count,
            candidate_chars=candidate.char_count,
        )
        if baseline.char_count > 0:
            result.ratio = candidate.char_count / baseline.char_count
        result.delta_chars = candidate.char_count - baseline.char_count

        # 判定绕过：字数显著增加，且超过阈值
        if (candidate.char_count >= config.COMPLETE_CONTENT_LENGTH and
                result.ratio > 1.5):
            result.is_bypass = True
        elif (candidate.char_count >= config.MIN_CONTENT_LENGTH and
              baseline.char_count < config.MIN_CONTENT_LENGTH and
              candidate.char_count > baseline.char_count * 2):
            result.is_bypass = True

        # 检测是否有新内容（基线中不存在的段落）
        if candidate.char_count > baseline.char_count + 100:
            result.new_content_found = True

        return result

    def to_markdown_report(self, content: ExtractedContent,
                           include_meta: bool = True) -> str:
        """将提取的内容输出为Markdown格式报告"""
        lines = []
        if content.title:
            lines.append(f"# {content.title}")
            lines.append("")

        if include_meta:
            lines.append(f"- **来源引擎**: {content.source_engine or 'unknown'}")
            lines.append(f"- **原文URL**: {content.url}")
            lines.append(f"- **字数统计**: {content.word_count_cn} 中文字 / {content.char_count} 字符")
            lines.append(f"- **段落数**: {content.paragraphs}")
            lines.append(f"- **是否截断**: {'是' if content.is_truncated else '否'}")
            if content.truncation_indicators:
                lines.append(f"- **截断标记**: {', '.join(content.truncation_indicators)}")
            lines.append(f"- **内容Hash**: `{content.content_hash[:16]}`")
            lines.append("")
            lines.append("---")
            lines.append("")

        if content.content_markdown:
            lines.append(content.content_markdown.strip())
        elif content.content_text:
            # 纯文本转简易Markdown
            for para in content.content_text.split('\n'):
                para = para.strip()
                if para:
                    lines.append(para)
                    lines.append("")

        return '\n'.join(lines)

    def _score_text(self, text: str) -> int:
        """对正文文本打分，分数越高越可能是正文"""
        if not text:
            return 0
        cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        lines = [l for l in text.split('\n') if l.strip()]
        avg_line_len = cn_chars / max(len(lines), 1)
        # 中文密度 + 长度 + 段落平均长度
        score = cn_chars
        if avg_line_len > 20:
            score += cn_chars // 2  # 段落较长，加分
        if len(lines) > 3:
            score += cn_chars // 4
        # 排除明显是列表/导航的短行密集区
        short_lines = sum(1 for l in lines if len(l) < 5)
        if short_lines > len(lines) * 0.5:
            score = score // 3
        return score

    def _find_densest_node_selectolax(self, tree) -> Optional[Any]:
        """selectolax版本：寻找文本密度最高的节点"""
        best_node = None
        best_score = 0
        for node in tree.css("div, article, section, main"):
            text = node.text(separator="\n", strip=True)
            score = self._score_text(text)
            if score > best_score:
                best_score = score
                best_node = node
        return best_node

    def _find_densest_node_bs4(self, soup: BeautifulSoup) -> Optional[Tag]:
        """BS4版本：寻找文本密度最高的节点"""
        best_el = None
        best_score = 0
        for tag in ["div", "article", "section", "main"]:
            for el in soup.find_all(tag):
                text = el.get_text(separator="\n", strip=True)
                score = self._score_text(text)
                if score > best_score:
                    best_score = score
                    best_el = el
        return best_el

    def _clean_text(self, text: str) -> str:
        """清理提取后的文本"""
        if not text:
            return ""
        # 去除零宽字符
        text = re.sub(r'[\u200b-\u200f\u2028-\u202f\ufeff]', '', text)
        # 合并多余空行
        text = re.sub(r'\n{3,}', '\n\n', text)
        # 去除每行首尾空白
        lines = [l.rstrip() for l in text.split('\n')]
        # 去除连续重复行（导航/广告重复）
        cleaned = []
        prev = None
        for l in lines:
            if l != prev or (l == '' and (not cleaned or cleaned[-1] != '')):
                cleaned.append(l)
            prev = l
        return '\n'.join(cleaned).strip()

    def _detect_truncation(self, content: ExtractedContent, raw_html: str) -> None:
        """检测内容是否被截断"""
        indicators = []
        check_text = (content.content_text or "") + " " + (raw_html or "")[-3000:]
        for marker in self.TRUNCATION_MARKERS:
            if re.search(marker, check_text, re.I):
                indicators.append(marker)
        content.truncation_indicators = list(set(indicators))
        # 判断是否截断：有截断标记，或字数低于最小阈值
        if indicators or content.char_count < config.MIN_CONTENT_LENGTH:
            content.is_truncated = True
        elif content.char_count >= config.COMPLETE_CONTENT_LENGTH:
            content.is_truncated = False

    def _compute_hash(self, text: str) -> str:
        """计算内容Hash（去除空白后）"""
        normalized = re.sub(r'\s+', '', text or "")
        return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

    @staticmethod
    def is_zhihu_url(url: str) -> bool:
        """判断是否为知乎URL"""
        try:
            parsed = urlparse(url)
            return "zhihu.com" in parsed.netloc
        except Exception:
            return False

    @staticmethod
    def extract_article_id(url: str) -> Dict[str, Optional[str]]:
        """
        从知乎URL中提取文章/回答/专栏ID
        返回 {"type": "article|answer|paid_section|post|unknown", "id": ...}
        """
        result = {"type": "unknown", "id": None, "column_id": None, "section_id": None}
        patterns = [
            (r"/paid_column/(\d+)/section/(\d+)", "paid_section", "column", "section"),
            (r"/market/paid_column/(\d+)/section/(\d+)", "paid_section", "column", "section"),
            (r"/xen/market/remix/paid_column/(\d+)/section/(\d+)", "paid_section", "column", "section"),
            # remix新版专栏单篇URL（无section路径时，ID本身作为内容ID处理）
            (r"/xen/market/remix/paid_column/(\d+)", "paid_section", "remix_id", None),
            (r"/remix/essay/(\d+)", "essay", "id", None),
            (r"/answer/(\d+)", "answer", "id", None),
            (r"/question/\d+/answer/(\d+)", "answer", "id", None),
            (r"/p/(\d+)", "post", "id", None),
            (r"/articles/(\d+)", "article", "id", None),
            (r"/article/(\d+)", "article", "id", None),
        ]
        import re
        for pat, type_, g1_name, g2_name in patterns:
            m = re.search(pat, url)
            if m:
                result["type"] = type_
                if g1_name == "column":
                    result["column_id"] = m.group(1)
                    result["section_id"] = m.group(2)
                    result["id"] = m.group(2)
                elif g1_name == "remix_id":
                    # /xen/market/remix/paid_column/{id} 无section路径时
                    # ID同时作为column_id和内容id（remix单篇/专栏入口）
                    result["column_id"] = m.group(1)
                    result["id"] = m.group(1)
                else:
                    result["id"] = m.group(1)
                return result
        return result
