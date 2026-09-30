# -*- coding: utf-8 -*-
"""
parser.py - HTML/JSON内容提取与清洗

从各引擎返回的原始数据中提取标题、作者、正文，
转换为干净的Markdown格式。
"""
import re
import json
import logging
import html as html_module
from typing import Optional, Dict, List, Tuple, Any
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlparse

import config

logger = logging.getLogger(__name__)

# 尝试导入可选依赖
try:
    from selectolax.parser import HTMLParser as SelectolaxParser
    HAS_SELECTOLAX = True
except ImportError:
    HAS_SELECTOLAX = False
    from html.parser import HTMLParser as StdHTMLParser

try:
    import html2text
    HAS_HTML2TEXT = True
except ImportError:
    HAS_HTML2TEXT = False


@dataclass
class ParsedContent:
    """解析后的文章内容"""
    title: str = ""
    author: str = ""
    content_html: str = ""
    content_markdown: str = ""
    images: List[str] = field(default_factory=list)
    original_url: str = ""
    platform: str = ""
    is_truncated: bool = True  # 默认标记为截断，需验证
    content_length: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "author": self.author,
            "content_markdown": self.content_markdown,
            "images": self.images,
            "original_url": self.original_url,
            "platform": self.platform,
            "is_truncated": self.is_truncated,
            "content_length": self.content_length,
        }


class ContentParser:
    """
    统一内容解析器。支持：
    1. 知乎API JSON响应解析
    2. HTML正文提取（基于文本密度/标签评分）
    3. HTML转Markdown
    4. 截断检测
    """

    def __init__(self):
        self._h2t = None
        if HAS_HTML2TEXT:
            self._h2t = html2text.HTML2Text()
            self._h2t.body_width = 0
            self._h2t.ignore_links = False
            self._h2t.ignore_images = False
            self._h2t.ignore_emphasis = False
            self._h2t.protect_links = True
            self._h2t.unicode_snob = True

    # ============================================================
    # JSON API响应解析
    # ============================================================
    def parse_api_json(self, data: dict, base_url: str = "") -> Optional[ParsedContent]:
        """
        解析知乎API返回的JSON数据。
        支持多种API响应格式（market/paid_column, articles, posts等）。
        """
        if not isinstance(data, dict):
            return None

        content = ParsedContent(original_url=base_url)

        # 递归搜索关键字段
        title, author, body_html, images = self._extract_from_json(data)

        if not body_html and not title:
            return None

        content.title = self._clean_text(title)
        content.author = self._clean_text(author)
        content.content_html = body_html or ""

        # 补全图片URL
        content.images = self._resolve_image_urls(images, base_url)

        # HTML转Markdown
        content.content_markdown = self.html_to_markdown(content.content_html, base_url)
        content.content_length = len(self._strip_html(content.content_html))

        # 截断检测
        content.is_truncated = self._check_truncation(content.content_markdown, content.content_html)

        return content if content.title or content.content_markdown else None

    def _extract_from_json(self, data: Any, depth: int = 0) -> Tuple[str, str, str, List[str]]:
        """
        递归从JSON结构中提取title/author/content/images。
        返回 (title, author, content_html, images)
        """
        if depth > 8 or data is None:
            return "", "", "", []

        title = ""
        author = ""
        content_html = ""
        images = []

        if isinstance(data, str):
            # 检查是否是HTML内容
            if data.strip().startswith("<") and len(data) > 100:
                return "", "", data, []
            return "", "", "", []

        if isinstance(data, list):
            for item in data[:5]:
                t, a, c, imgs = self._extract_from_json(item, depth + 1)
                if t and not title: title = t
                if a and not author: author = a
                if c and len(c) > len(content_html): content_html = c
                images.extend(imgs)
            return title, author, content_html, images

        if isinstance(data, dict):
            # 常见字段映射
            # 标题
            for key in ["title", "name", "question_title", "column_title"]:
                if key in data and isinstance(data[key], str) and len(data[key]) > 2:
                    if not title or len(data[key]) > len(title):
                        title = data[key]

            # 作者
            if "author" in data and isinstance(data["author"], dict):
                author = data["author"].get("name", "") or data["author"].get("url_token", "")
            elif "author" in data and isinstance(data["author"], str):
                author = data["author"]
            elif "user" in data and isinstance(data["user"], dict):
                author = data["user"].get("name", "")
            for key in ["author_name", "creator_name", "writer_name"]:
                if key in data and isinstance(data[key], str):
                    author = data[key]

            # 正文HTML
            for key in ["content", "body", "html_content", "rich_content", "manuscript", "text"]:
                if key in data and isinstance(data[key], str) and len(data[key]) > 100:
                    if "<" in data[key] or len(data[key]) > len(content_html):
                        if len(data[key]) > len(content_html):
                            content_html = data[key]

            # 图片
            if "images" in data and isinstance(data["images"], list):
                for img in data["images"]:
                    if isinstance(img, str):
                        images.append(img)
                    elif isinstance(img, dict):
                        for img_key in ["url", "src", "original_src", "image", "thumbnail"]:
                            if img_key in img:
                                images.append(img[img_key])
                                break

            # 图片（从内容HTML中提取）
            if "image_urls" in data and isinstance(data["image_urls"], list):
                images.extend([u for u in data["image_urls"] if isinstance(u, str)])

            # 检查是否有data包裹
            if "data" in data and isinstance(data["data"], dict):
                t, a, c, imgs = self._extract_from_json(data["data"], depth + 1)
                if t and not title: title = t
                if a and not author: author = a
                if c and len(c) > len(content_html): content_html = c
                images.extend(imgs)

            # 递归其他字段
            if not content_html or not title:
                for key, value in data.items():
                    if key in ["title", "name", "author", "content", "body", "data",
                               "images", "image_urls", "question_title"]:
                        continue
                    if isinstance(value, (dict, list)):
                        t, a, c, imgs = self._extract_from_json(value, depth + 1)
                        if t and not title: title = t
                        if a and not author: author = a
                        if c and len(c) > len(content_html): content_html = c
                        images.extend(imgs)

        return title, author, content_html, list(set(images))

    # ============================================================
    # HTML页面解析
    # ============================================================
    def parse_html(self, html_text: str, url: str = "",
                   content_selectors: Optional[List[str]] = None) -> Optional[ParsedContent]:
        """
        从HTML页面提取正文。优先使用指定选择器，否则用密度算法。
        """
        if not html_text or len(html_text) < 100:
            return None

        content = ParsedContent(original_url=url)

        if HAS_SELECTOLAX:
            return self._parse_with_selectolax(html_text, url, content_selectors, content)
        else:
            return self._parse_with_regex(html_text, url, content)

    def _parse_with_selectolax(self, html_text: str, url: str,
                                selectors: Optional[List[str]],
                                content: ParsedContent) -> Optional[ParsedContent]:
        """使用selectolax快速解析HTML"""
        tree = SelectolaxParser(html_text)

        # 提取标题
        title = ""
        for sel in ["h1.Post-Title", "h1.QuestionHeader-title", "h1.article-title",
                    "h1.title", "h1", "title"]:
            node = tree.css_first(sel)
            if node:
                title = node.text(strip=True)
                if title and len(title) > 2:
                    break
        # og:title
        if not title:
            meta = tree.css_first('meta[property="og:title"]')
            if meta:
                title = meta.attributes.get("content", "")
        content.title = self._clean_text(title)

        # 提取作者
        author = ""
        for sel in [".AuthorInfo-name", ".AuthorInfo .UserLink-link",
                    ".author-name", ".Post-Author .UserLink-link",
                    'meta[name="author"]']:
            node = tree.css_first(sel)
            if node:
                if sel.startswith("meta"):
                    author = node.attributes.get("content", "")
                else:
                    author = node.text(strip=True)
                if author:
                    break
        content.author = self._clean_text(author)

        # 移除噪声节点
        for noise_sel in config.NOISE_SELECTORS:
            for node in tree.css(noise_sel):
                node.decompose()

        # 移除script/style/noscript
        for tag in ["script", "style", "noscript", "iframe", "svg", "form"]:
            for node in tree.css(tag):
                node.decompose()

        # 尝试指定选择器
        body_html = ""
        if selectors:
            for sel in selectors:
                node = tree.css_first(sel)
                if node:
                    html = node.html
                    text_len = len(re.sub(r'<[^>]+>', '', html))
                    if text_len > config.MIN_CONTENT_LENGTH:
                        body_html = html
                        break

        # 通用密度算法
        if not body_html:
            body_html = self._find_best_node_selectolax(tree)

        if not body_html:
            # 最后尝试article/main标签
            for sel in ["article", "main", ".post-content", ".article-content",
                        ".entry-content", "#content", ".content"]:
                node = tree.css_first(sel)
                if node:
                    html = node.html
                    if len(re.sub(r'<[^>]+>', '', html)) > 200:
                        body_html = html
                        break

        content.content_html = body_html
        content.content_markdown = self.html_to_markdown(body_html, url)
        content.content_length = len(self._strip_html(body_html))
        content.images = self._extract_images_from_html(body_html, url)
        content.is_truncated = self._check_truncation(content.content_markdown, body_html)

        return content if content.title or content.content_length > 100 else None

    def _find_best_node_selectolax(self, tree) -> str:
        """
        基于文本密度和链接密度的正文节点查找算法。
        """
        best_node = None
        best_score = 0.0

        # 正向加分标签
        positive_tags = {"article", "main", "section", "div", "p", "pre", "blockquote"}
        # 负向减分标签
        negative_class_pattern = re.compile(
            r'comment|sidebar|footer|header|nav|menu|ad|banner|recommend|related|'
            r'share|social|tag|meta|info|author|date|time|breadcrumb|pagination|'
            r'popup|modal|dialog|toast|login|register|subscribe|newsletter|'
            r'widget|card|list|feed|stream|search|toolbar|button|btn',
            re.I
        )
        positive_class_pattern = re.compile(
            r'content|article|post|story|body|text|main|rich|manuscript|reader|'
            r'chapter|passage|essay|markdown',
            re.I
        )

        for node in tree.css("div, article, main, section"):
            # 计算文本长度
            text = node.text(separator=" ", strip=True)
            text_len = len(text)

            if text_len < config.MIN_CONTENT_LENGTH:
                continue

            # 计算链接密度
            link_text = ""
            link_count = 0
            for a in node.css("a"):
                link_text += a.text(strip=True)
                link_count += 1
            link_density = len(link_text) / max(text_len, 1)

            # 计算标点符号密度（中文文章标点多）
            punct_count = len(re.findall(r'[，。！？；：、""''…—\.\,\!\?\;\:]', text))
            punct_density = punct_count / max(text_len, 1)

            # 段落数
            p_count = len(node.css("p"))
            # 图片数
            img_count = len(node.css("img"))

            # 评分
            score = 0.0
            score += text_len * 0.1           # 文本长度
            score += p_count * 20             # 段落数加分
            score += punct_density * 500      # 标点密度加分（中文特征）
            score += img_count * 10           # 适当图片
            score -= link_density * 300       # 链接密度减分
            score -= link_count * 5           # 链接数量减分

            # 标签加分
            tag = node.tag
            if tag in ("article", "main"):
                score += 100
            elif tag == "section":
                score += 20

            # class/id加分/减分
            classes = node.attributes.get("class", "")
            nid = node.attributes.get("id", "")
            class_id = f"{classes} {nid}"
            if negative_class_pattern.search(class_id):
                score -= 150
            if positive_class_pattern.search(class_id):
                score += 80

            if score > best_score:
                best_score = score
                best_node = node

        if best_node:
            return best_node.html
        return ""

    def _parse_with_regex(self, html_text: str, url: str,
                           content: ParsedContent) -> Optional[ParsedContent]:
        """无selectolax时的降级解析（正则方式）"""
        # 标题
        title_m = re.search(r'<title>(.*?)</title>', html_text, re.S)
        if title_m:
            content.title = self._clean_text(html_module.unescape(title_m.group(1)))

        og_title = re.search(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', html_text)
        if og_title:
            content.title = self._clean_text(html_module.unescape(og_title.group(1)))

        # 作者
        author_m = re.search(r'<meta[^>]*name="author"[^>]*content="([^"]+)"', html_text)
        if author_m:
            content.author = self._clean_text(html_module.unescape(author_m.group(1)))

        # 尝试找正文区域
        body_html = ""
        for tag in ["article", "main"]:
            pattern = rf'<{tag}[^>]*>(.*?)</{tag}>'
            m = re.search(pattern, html_text, re.S | re.I)
            if m:
                candidate = m.group(1)
                text_len = len(re.sub(r'<[^>]+>', '', candidate))
                if text_len > config.MIN_CONTENT_LENGTH:
                    body_html = candidate
                    break

        # 简单的div密度评分
        if not body_html:
            divs = re.findall(r'<div[^>]*>(.*?)</div>', html_text, re.S)
            best_len = 0
            for div in divs:
                text = re.sub(r'<[^>]+>', '', div)
                text_len = len(text.strip())
                if text_len > best_len:
                    # 检查链接密度
                    links = re.findall(r'<a[^>]*>(.*?)</a>', div, re.S)
                    link_text = ''.join(re.sub(r'<[^>]+>', '', l) for l in links)
                    if len(link_text) / max(text_len, 1) < 0.5:
                        best_len = text_len
                        body_html = div

        content.content_html = body_html
        content.content_markdown = self.html_to_markdown(body_html, url)
        content.content_length = len(self._strip_html(body_html))
        content.images = self._extract_images_from_html(body_html, url)
        content.is_truncated = self._check_truncation(content.content_markdown, body_html)

        return content if content.title or content.content_length > 100 else None

    # ============================================================
    # HTML转Markdown
    # ============================================================
    def html_to_markdown(self, html_text: str, base_url: str = "") -> str:
        """将HTML转换为Markdown"""
        if not html_text:
            return ""

        if self._h2t:
            md = self._h2t.handle(html_text)
        else:
            md = self._simple_html_to_md(html_text)

        # 补全相对链接
        if base_url:
            md = self._resolve_links_in_md(md, base_url)

        # 清理多余空行
        md = re.sub(r'\n{3,}', '\n\n', md)
        return md.strip()

    def _simple_html_to_md(self, html_text: str) -> str:
        """简易HTML到Markdown转换（无html2text时使用）"""
        text = html_text

        # 代码块
        text = re.sub(r'<pre[^>]*><code[^>]*>(.*?)</code></pre>',
                      lambda m: f"\n```\n{html_module.unescape(m.group(1))}\n```\n",
                      text, flags=re.S)
        text = re.sub(r'<pre[^>]*>(.*?)</pre>',
                      lambda m: f"\n```\n{self._strip_tags(m.group(1))}\n```\n",
                      text, flags=re.S)

        # 标题
        for i in range(6, 0, -1):
            text = re.sub(rf'<h{i}[^>]*>(.*?)</h{i}>',
                          lambda m, n=i: f"\n{'#' * n} {self._strip_tags(m.group(1))}\n",
                          text, flags=re.S)

        # 加粗/斜体
        text = re.sub(r'<(strong|b)[^>]*>(.*?)</\1>', r'**\2**', text, flags=re.S)
        text = re.sub(r'<(em|i)[^>]*>(.*?)</\1>', r'*\2*', text, flags=re.S)

        # 引用
        text = re.sub(r'<blockquote[^>]*>(.*?)</blockquote>',
                      lambda m: '\n' + '\n'.join(f"> {line}" for line in self._strip_tags(m.group(1)).split('\n') if line.strip()) + '\n',
                      text, flags=re.S)

        # 图片
        text = re.sub(r'<img[^>]*src="([^"]+)"[^>]*alt="([^"]*)"[^>]*/?>',
                      r'![\2](\1)', text)
        text = re.sub(r'<img[^>]*src="([^"]+)"[^>]*/?>', r'![](\1)', text)

        # 链接
        text = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.S)

        # 列表
        text = re.sub(r'<li[^>]*>(.*?)</li>', r'- \1\n', text, flags=re.S)
        text = re.sub(r'</?(ul|ol|li)[^>]*>', '\n', text)

        # 段落和换行
        text = re.sub(r'<br\s*/?>', '\n', text)
        text = re.sub(r'</p>', '\n\n', text)
        text = re.sub(r'<p[^>]*>', '', text)

        # 移除剩余标签
        text = self._strip_tags(text)
        text = html_module.unescape(text)
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text.strip()

    # ============================================================
    # 工具方法
    # ============================================================
    def _strip_html(self, html_text: str) -> str:
        """移除所有HTML标签，返回纯文本"""
        if not html_text:
            return ""
        text = re.sub(r'<[^>]+>', ' ', html_text)
        text = html_module.unescape(text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _strip_tags(self, text: str) -> str:
        """移除HTML标签"""
        return re.sub(r'<[^>]+>', '', text)

    def _clean_text(self, text: str) -> str:
        """清理文本"""
        if not text:
            return ""
        text = html_module.unescape(text)
        text = re.sub(r'\s+', ' ', text)
        return text.strip()

    def _extract_images_from_html(self, html_text: str, base_url: str) -> List[str]:
        """从HTML中提取图片URL"""
        urls = []
        # 优先懒加载属性
        for attr in ["data-src", "data-original", "data-url", "src"]:
            found = re.findall(rf'<img[^>]*{attr}="([^"]+)"', html_text, re.I)
            for u in found:
                u = html_module.unescape(u)
                if u.startswith("data:"):
                    continue
                full_url = urljoin(base_url, u) if base_url else u
                if full_url not in urls:
                    urls.append(full_url)
        return urls

    def _resolve_image_urls(self, urls: List[str], base_url: str) -> List[str]:
        """补全图片URL"""
        resolved = []
        for u in urls:
            if u.startswith("data:"):
                continue
            full = urljoin(base_url, u) if base_url else u
            if full not in resolved:
                resolved.append(full)
        return resolved

    def _resolve_links_in_md(self, md: str, base_url: str) -> str:
        """补全Markdown中的相对链接"""
        def replace_link(m):
            alt = m.group(1)
            url = m.group(2)
            if url.startswith(("http://", "https://", "mailto:", "#", "javascript:")):
                return m.group(0)
            full = urljoin(base_url, url)
            return f"[{alt}]({full})"
        md = re.sub(r'\[([^\]]*)\]\(([^)]+)\)', replace_link, md)
        return md

    def _check_truncation(self, markdown: str, html: str) -> bool:
        """
        检查内容是否被截断。
        返回True表示内容不完整（被截断）。
        """
        combined = markdown + " " + html
        for marker in config.TRUNCATION_MARKERS:
            if re.search(marker, combined):
                return True

        # 如果正文太短，可能也是截断
        text_len = len(self._strip_html(html))
        if text_len < config.MIN_CONTENT_LENGTH:
            return True

        return False

    def is_content_complete(self, content: ParsedContent) -> bool:
        """判断内容是否完整可用"""
        return (not content.is_truncated and
                content.content_length >= config.MIN_CONTENT_LENGTH and
                bool(content.title or content.content_markdown))

    # ============================================================
    # Markdown文件生成
    # ============================================================
    def to_markdown_file(self, content: ParsedContent, include_meta: bool = True) -> str:
        """生成完整的Markdown文件内容"""
        lines = []

        if include_meta:
            if content.title:
                lines.append(f"# {content.title}")
                lines.append("")
            meta_parts = []
            if content.author:
                meta_parts.append(f"· 作者：{content.author}")
            if content.platform:
                meta_parts.append(f"· 平台：{content.platform}")
            if content.original_url:
                meta_parts.append(f"· 原文：{content.original_url}")
            if meta_parts:
                lines.extend(meta_parts)
                lines.append("")
                lines.append("---")
                lines.append("")

        if content.content_markdown:
            lines.append(content.content_markdown)
            lines.append("")

        if include_meta:
            lines.append("---")
            lines.append("")
            lines.append("由知乎盐选内容获取智能体自动提取 | 仅供个人学习使用")

        return "\n".join(lines)


def extract_article_id(url: str) -> Dict[str, str]:
    """
    从知乎URL中提取文章/专栏/章节ID。
    返回 dict，可能包含 column_id, article_id, section_id, share_id, answer_id, post_id, story_id。
    """
    ids = {}
    if not url:
        return ids

    # oia.zhihu.com 付费分享链接
    m = re.search(r'km_pst=([^&]+)', url)
    if m:
        ids["km_pst"] = m.group(1)
    m = re.search(r'share_code=([^&]+)', url)
    if m:
        ids["share_code"] = m.group(1)

    # /market/paid_column/{column_id}/section/{section_id}
    m = re.search(r'/market/paid_column/(\d+)(?:/section/(\d+))?', url)
    if m:
        ids["column_id"] = m.group(1)
        if m.group(2):
            ids["section_id"] = m.group(2)

    # /market/paid_column/{column_id}
    m = re.search(r'/market/paid_column/(\d+)', url)
    if m and "column_id" not in ids:
        ids["column_id"] = m.group(1)

    # /p/{answer_id} (知乎问答)
    m = re.search(r'/p/(\d+)', url)
    if m:
        ids["answer_id"] = m.group(1)

    # /question/{qid}/answer/{aid}
    m = re.search(r'/question/(\d+)/answer/(\d+)', url)
    if m:
        ids["question_id"] = m.group(1)
        ids["answer_id"] = m.group(2)

    # /articles/{article_id}
    m = re.search(r'/articles?/(\d+)', url)
    if m:
        ids["article_id"] = m.group(1)

    # /posts/{post_id}
    m = re.search(r'/posts/(\d+)', url)
    if m:
        ids["post_id"] = m.group(1)

    # share参数
    m = re.search(r'[?&]share=([^&]+)', url)
    if m:
        ids["share_id"] = m.group(1)

    # 对于付费专栏，section_id 等价于 article_id（用于内容API）
    if "section_id" in ids and "article_id" not in ids:
        ids["article_id"] = ids["section_id"]

    return ids
