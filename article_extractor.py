#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用网页正文提取器 ArticleExtractor
支持平台：微信公众号、知乎专栏、CSDN、简书、豆瓣日记
未知平台使用基于文本密度/链接密度的通用算法
仅依赖 Python 标准库，可选对接 cookie_manager 和 proxy_pool
"""

import os
import re
import sys
import json
import time
import html
import gzip
import zlib
import socket
import logging
import hashlib
import mimetypes
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.request import Request, urlopen, build_opener, ProxyHandler
from urllib.error import URLError, HTTPError
from html.parser import HTMLParser
from collections import defaultdict
from typing import Optional, Dict, List, Tuple, Any, Callable

# ---------------------------------------------------------------------------
# 可选依赖：cookie_manager / proxy_pool（存在则用，不存在则静默降级）
# ---------------------------------------------------------------------------
try:
    import cookie_manager  # type: ignore
    _HAS_COOKIE_MGR = True
except ImportError:
    _HAS_COOKIE_MGR = False
    cookie_manager = None

try:
    import proxy_pool  # type: ignore
    _HAS_PROXY_POOL = True
except ImportError:
    _HAS_PROXY_POOL = False
    proxy_pool = None

# ---------------------------------------------------------------------------
# 日志
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("ArticleExtractor")

# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------
DEFAULT_TIMEOUT = 20
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
WECHAT_UA = (
    "Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ2A.230505.002; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/116.0.0.0 Mobile Safari/537.36 "
    "MicroMessenger/8.0.40.2420(0x28002857) WeChat/arm64 Weixin NetType/WIFI "
    "Language/zh_CN ABI/arm64"
)
ZHIHU_APP_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Zhihu/9.28.0"
)
ZHIHU_REFERER = "https://www.zhihu.com/"

# 要剥离的标签（导航/侧边/广告/评论/页脚等）
BLOCK_TAGS_STRIP = {
    "script", "style", "noscript", "iframe", "svg", "canvas",
    "nav", "header", "footer", "aside", "form", "button", "input",
    "noscript", "template",
}

# 保留结构的块级标签
BLOCK_TAGS_KEEP = {
    "p", "div", "section", "article", "pre", "blockquote",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "ul", "ol", "li", "table", "thead", "tbody", "tr", "td", "th",
    "figure", "figcaption",
}

INLINE_TAGS_KEEP = {"span", "strong", "b", "em", "i", "code", "a", "img", "br", "hr"}

# 注释/推荐/广告相关的 class/id 关键词
NOISE_PATTERNS = [
    r"comment", r"reply", r"sidebar", r"footer", r"header", r"nav",
    r"menu", r"breadcrumb", r"advert", r"ad-", r"ads-", r"adsense",
    r"banner", r"popup", r"modal", r"share", r"social", r"like",
    r"recommend", r"related", r"hot", r"popular", r"tag", r"category",
    r"author-?info", r"meta-?info", r"post-?meta", r"copyright",
    r"pagination", r"page-?nav", r"next", r"prev", r"back-?to-?top",
    r"tool-?bar", r"action-?bar", r"vote", r"favor", r"collect",
    r"sign", r"login", r"register", r"qr-?code", r"qrcode",
    r"wx-?qr", r"wechat-?qr", r"pay", r"reward", r"donate",
    r"copyright", r"disclaimer", r"statement",
]
NOISE_RE = re.compile("|".join(NOISE_PATTERNS), re.I)


# ===================================================================
# URL 工具
# ===================================================================
def get_domain(url: str) -> str:
    """获取 URL 的注册域名（简化版：返回 netloc 去掉 www.）"""
    try:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if host.startswith("www."):
            host = host[4:]
        return host
    except Exception:
        return ""


def clean_url(url: str) -> str:
    """清理 URL：去 fragment，去尾部空白"""
    url, _ = urldefrag(url.strip())
    return url


def safe_filename(name: str, max_len: int = 80) -> str:
    """将标题转为安全文件名"""
    name = re.sub(r'[\\/:*?"<>|\r\n\t]+', "_", name)
    name = re.sub(r"_+", "_", name).strip("._ ")
    if len(name) > max_len:
        name = name[:max_len].rstrip("_")
    return name or "untitled"


def absolute_url(base: str, rel: str) -> str:
    """相对路径转绝对路径"""
    if not rel:
        return ""
    rel = rel.strip()
    if rel.startswith(("data:", "javascript:", "mailto:", "tel:")):
        return rel
    try:
        return urljoin(base, rel)
    except Exception:
        return rel


# ===================================================================
# HTTP 请求层
# ===================================================================
class HttpClient:
    """简单 HTTP 客户端，支持 UA / Cookie / 代理 / gzip"""

    def __init__(
        self,
        ua: str = DEFAULT_UA,
        referer: str = "",
        cookies: Optional[Dict[str, str]] = None,
        cookie_file: Optional[str] = None,
        proxy: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
    ):
        self.ua = ua
        self.referer = referer
        self.timeout = timeout
        self.cookies: Dict[str, str] = {}
        self.proxy = proxy

        # 外部传入 cookies
        if cookies:
            self.cookies.update(cookies)

        # cookie_manager 对接
        if _HAS_COOKIE_MGR and cookie_file:
            try:
                mgr_cookies = cookie_manager.load(cookie_file)
                if isinstance(mgr_cookies, dict):
                    self.cookies.update(mgr_cookies)
                logger.debug("Loaded cookies from cookie_manager")
            except Exception as e:
                logger.warning(f"cookie_manager load failed: {e}")

        # proxy_pool 对接
        if proxy is None and _HAS_PROXY_POOL:
            try:
                self.proxy = proxy_pool.get()
                logger.debug(f"Got proxy from proxy_pool: {self.proxy}")
            except Exception as e:
                logger.debug(f"proxy_pool.get() failed: {e}")

    def _build_opener(self):
        handlers = []
        if self.proxy:
            handlers.append(ProxyHandler({
                "http": self.proxy,
                "https": self.proxy,
            }))
        return build_opener(*handlers) if handlers else None

    def get(self, url: str) -> Tuple[str, str, int]:
        """
        返回 (html, final_url, status_code)
        """
        url = clean_url(url)
        headers = {
            "User-Agent": self.ua,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
        }
        if self.referer:
            headers["Referer"] = self.referer
        if self.cookies:
            headers["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())

        req = Request(url, headers=headers)
        opener = self._build_opener()

        last_err = None
        for attempt in range(2):
            try:
                if opener:
                    resp = opener.open(req, timeout=self.timeout)
                else:
                    resp = urlopen(req, timeout=self.timeout)
                break
            except (URLError, HTTPError, socket.timeout, ConnectionError) as e:
                last_err = e
                logger.warning(f"Request failed (attempt {attempt+1}): {e}")
                time.sleep(1 + attempt)
        else:
            raise last_err if last_err else RuntimeError(f"Failed to fetch {url}")

        status = resp.getcode()
        final_url = resp.geturl()
        raw = resp.read()
        encoding = resp.headers.get("Content-Encoding", "").lower()
        if encoding == "gzip":
            raw = gzip.decompress(raw)
        elif encoding == "deflate":
            try:
                raw = zlib.decompress(raw)
            except zlib.error:
                raw = zlib.decompress(raw, -zlib.MAX_WBITS)

        # 字符编码
        charset = resp.headers.get_content_charset()
        if not charset:
            # 从 meta 猜
            m = re.search(rb'charset=["\']?([\w-]+)', raw[:2048], re.I)
            charset = m.group(1).decode("ascii", "ignore") if m else "utf-8"
        try:
            text = raw.decode(charset, errors="replace")
        except (LookupError, UnicodeDecodeError):
            text = raw.decode("utf-8", errors="replace")
        return text, final_url, status


# ===================================================================
# HTML 节点树（用于密度算法）
# ===================================================================
class _Node:
    __slots__ = ("tag", "attrs", "children", "text", "tail", "parent",
                 "text_len", "link_text_len", "tag_count", "link_count",
                 "score", "depth")

    def __init__(self, tag: str, attrs: Dict[str, str], parent: Optional["_Node"] = None):
        self.tag = tag
        self.attrs = attrs
        self.children: List["_Node"] = []
        self.text = ""
        self.tail = ""
        self.parent = parent
        self.text_len = 0
        self.link_text_len = 0
        self.tag_count = 0
        self.link_count = 0
        self.score = 0.0
        self.depth = 0 if parent is None else parent.depth + 1

    def attr(self, key: str) -> str:
        return self.attrs.get(key, "")

    def cls_id(self) -> str:
        return f"{self.attrs.get('class','')} {self.attrs.get('id','')}".strip()

    def is_noise(self) -> bool:
        if self.tag in BLOCK_TAGS_STRIP:
            return True
        ci = self.cls_id()
        return bool(ci and NOISE_RE.search(ci))


class _TreeBuilder(HTMLParser):
    """把 HTML 解析成 _Node 树（正确处理 text/tail 以保持节点间文本顺序）"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self.stack = [self.root]
        self._in_pre = 0
        self._last: Optional[_Node] = None  # 最近完成的节点，用于接收 tail 文本

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attrs_d = {k.lower(): (v or "") for k, v in attrs}
        node = _Node(tag, attrs_d, self.stack[-1])
        self.stack[-1].children.append(node)
        self._last = None  # 新子节点开始，tail 归属清零
        if tag not in ("img", "br", "hr", "input", "meta", "link"):
            self.stack.append(node)
        else:
            # 自闭合标签，作为最近完成节点以便接收后续 tail
            self._last = node
        if tag == "pre":
            self._in_pre += 1

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == "pre" and self._in_pre > 0:
            self._in_pre -= 1
        # 从栈顶向上找匹配标签弹出
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                # 弹出 i 及以上所有节点，最后一个弹出的即为 _last
                last_popped = None
                while len(self.stack) > i:
                    last_popped = self.stack.pop()
                self._last = last_popped
                return

    def handle_data(self, data):
        if not self.stack:
            return
        if self._last is not None:
            # 文本追加到最近完成节点的 tail（即该节点之后、下一个兄弟之前的文本）
            self._last.tail += data
        else:
            # 否则追加到当前节点的 text（首个子元素之前的文本）
            self.stack[-1].text += data

    def error(self, message):
        pass


# ===================================================================
# 平台规则
# ===================================================================
class PlatformRule:
    """单个平台的提取规则"""
    name: str = "generic"
    domains: List[str] = []

    # 标题 / 作者 / 正文 / 内容选择器（CSS-like，用正则实现）
    title_selectors: List[str] = []
    author_selectors: List[str] = []
    content_selectors: List[str] = []
    noise_selectors: List[str] = []  # 正文内部需要剔除的节点
    ua: str = DEFAULT_UA
    referer: str = ""

    def match(self, url: str) -> bool:
        host = get_domain(url)
        return any(d in host for d in self.domains)


class WeChatRule(PlatformRule):
    name = "wechat"
    domains = ["mp.weixin.qq.com"]
    title_selectors = [r'var msg_title = "([^"]+)"', r'<h1[^>]*class="rich_media_title"[^>]*>(.*?)</h1>', r'<h1[^>]*id="activity-name"[^>]*>(.*?)</h1>']
    author_selectors = [r'<a[^>]*id="js_name"[^>]*>(.*?)</a>', r'var nickname = "([^"]+)"', r'<strong[^>]*class="profile_nickname"[^>]*>(.*?)</strong>']
    content_selectors = [r'<div[^>]*class="rich_media_content[^"]*"[^>]*id="js_content"[^>]*>(.*?)</div>\s*<script', r'<div[^>]*id="js_content"[^>]*>(.*?)</div>']
    noise_selectors = [r'class="rich_media_tool"', r'class="qr_code_pc"', r'data-mpa-powered-by']
    ua = WECHAT_UA
    referer = ""


class ZhihuRule(PlatformRule):
    name = "zhihu"
    domains = ["zhihu.com", "zhuanlan.zhihu.com"]
    title_selectors = [r'<h1[^>]*class="Post-Title"[^>]*>(.*?)</h1>', r'<title>(.*?)</title>']
    author_selectors = [r'<meta[^>]*itemprop="name"[^>]*content="([^"]+)"', r'<a[^>]*class="UserLink-link[^"]*"[^>]*>(.*?)</a>', r'"author":\s*\{\s*"name":\s*"([^"]+)"']
    content_selectors = [r'<div[^>]*class="Post-RichTextContainer[^"]*"[^>]*>(.*?)</div>\s*</div>\s*<div[^>]*class="Post-Sub', r'<div[^>]*class="RichContent-inner[^"]*"[^>]*>(.*?)</div>']
    noise_selectors = [r'class="ztext-empty-paragraph"', r'data-za-detail-view-path-module']
    ua = DEFAULT_UA
    referer = ZHIHU_REFERER


class ZhihuPaidRule(PlatformRule):
    """知乎付费内容（盐选/盐言故事）提取规则
    分享链接域名为 oia.zhihu.com，需要使用知乎App UA 才能获取正文HTML
    """
    name = "zhihu_paid"
    domains = ["oia.zhihu.com"]
    title_selectors = [
        r'<h1[^>]*class="Post-Title"[^>]*>(.*?)</h1>',
        r'<h1[^>]*class="manuscript-title"[^>]*>(.*?)</h1>',
        r'<title>(.*?)</title>',
        r'"title":\s*"([^"]+)"',
        r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"',
    ]
    author_selectors = [
        r'<meta[^>]*itemprop="name"[^>]*content="([^"]+)"',
        r'<a[^>]*class="UserLink-link[^"]*"[^>]*>(.*?)</a>',
        r'"author":\s*\{\s*"name":\s*"([^"]+)"',
        r'<span[^>]*class="author-name[^"]*"[^>]*>(.*?)</span>',
        r'<div[^>]*class="AuthorInfo-name[^"]*"[^>]*>.*?<meta[^>]*itemprop="name"[^>]*content="([^"]+)"',
        r'"authorName":\s*"([^"]+)"',
    ]
    content_selectors = [
        # 盐言故事 manuscript 容器
        r'<div[^>]*class="manuscript[^"]*"[^>]*>(.*?)</div>\s*<(?:div|script|footer)[^>]*class="(?:Recommend|recommend|comment|footer|Bottom)',
        # 盐选专栏 RichContent
        r'<div[^>]*class="RichContent-inner[^"]*"[^>]*>(.*?)</div>',
        # 普通专栏文章
        r'<div[^>]*class="Post-RichTextContainer[^"]*"[^>]*>(.*?)</div>',
        # 兜底：article 标签
        r'<article[^>]*>(.*?)</article>',
    ]
    noise_selectors = [
        r'class="ztext-empty-paragraph"',
        r'data-za-detail-view-path-module',
        r'class="RecommendFactor"',
        r'class="RichContent-actions"',
        r'class="ContentItem-actions"',
        r'class="manuscript-bottom"',
        r'class="manuscript-recommend"',
        r'class="pay-barrier"',
        r'class="salt-pay-wall"',
    ]
    ua = ZHIHU_APP_UA
    referer = ZHIHU_REFERER


class CsdnRule(PlatformRule):
    name = "csdn"
    domains = ["csdn.net", "blog.csdn.net"]
    title_selectors = [r'<h1[^>]*class="title-article"[^>]*>(.*?)</h1>', r'<h1[^>]*id="articleContentId"[^>]*>(.*?)</h1>', r'<title>(.*?)</title>']
    author_selectors = [r'<a[^>]*class="follow-nickName[^"]*"[^>]*>(.*?)</a>', r'<meta[^>]*name="author"[^>]*content="([^"]+)"']
    content_selectors = [r'<div[^>]*id="article_content"[^>]*>(.*?)</div>\s*<div[^>]*class="article-copyright', r'<div[^>]*id="content_views"[^>]*>(.*?)</div>']
    noise_selectors = [r'class="article-copyright"', r'class="recommend-box"', r'class="blog-tags-box"', r'id="blogExtensionBox"', r'class="person-messagebox"']
    ua = DEFAULT_UA
    referer = "https://www.csdn.net/"


class JianShuRule(PlatformRule):
    name = "jianshu"
    domains = ["jianshu.com", "www.jianshu.com"]
    title_selectors = [r'<h1[^>]*class="title"[^>]*>(.*?)</h1>', r'<title>(.*?)</title>']
    author_selectors = [r'<a[^>]*class="name"[^>]*>(.*?)</a>', r'<meta[^>]*name="author"[^>]*content="([^"]+)"']
    content_selectors = [r'<article[^>]*>(.*?)</article>', r'<div[^>]*class="show-content[^"]*"[^>]*>(.*?)</div>']
    noise_selectors = [r'class="show-content-free"', r'class="image-container-fill"']
    ua = DEFAULT_UA
    referer = "https://www.jianshu.com/"


class DoubanDiaryRule(PlatformRule):
    name = "douban_diary"
    domains = ["douban.com", "www.douban.com"]
    title_selectors = [r'<h1[^>]*class="note-title"[^>]*>(.*?)</h1>', r'<title>(.*?)</title>']
    author_selectors = [r'<a[^>]*class="note-author"[^>]*>(.*?)</a>', r'<span[^>]*property="v:author"[^>]*>(.*?)</span>']
    content_selectors = [r'<div[^>]*class="note"[^>]*id="link-report"[^>]*>(.*?)</div>', r'<div[^>]*class="grid-16-8 clearfix"[^>]*>.*?<div[^>]*class="article"[^>]*>(.*?)</div>']
    noise_selectors = [r'class="note-footer"', r'class="mod-recomm"', r'class="comment"', r'id="comments"']
    ua = DEFAULT_UA
    referer = "https://www.douban.com/"


class GenericRule(PlatformRule):
    """兜底通用规则"""
    name = "generic"
    domains = []
    ua = DEFAULT_UA
    referer = ""


# ===================================================================
# HTML -> Markdown 转换器
# ===================================================================
class HtmlToMarkdown(HTMLParser):
    """将 HTML 片段转换为 Markdown"""

    def __init__(self, base_url: str = ""):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.out: List[str] = []
        self._stack: List[str] = []
        self._list_stack: List[str] = []  # ul/ol
        self._list_idx: List[int] = []
        self._in_pre = False
        self._pre_lang = ""
        self._pre_buf: List[str] = []
        self._in_blockquote = 0
        self._table_buf: List[List[str]] = []
        self._table_row: List[str] = []
        self._table_cell: List[str] = []
        self._in_th = False
        self._link_href = ""
        self._link_stack: List[Tuple[str, int]] = []  # (href, out_index_start)
        self._img_src = ""
        self._img_alt = ""
        self._skip = 0  # >0 时跳过内容
        self._skip_tags = set()

    # ------------------ 工具 ------------------
    def _flush(self, s: str = ""):
        if s:
            self.out.append(s)

    def _newline(self, n: int = 1):
        self.out.append("\n" * n)

    def _strip_text(self, s: str) -> str:
        if self._in_pre:
            return s
        return re.sub(r"\s+", " ", s).strip()

    def _current_tag(self) -> str:
        return self._stack[-1] if self._stack else ""

    # ------------------ 事件 ------------------
    def handle_starttag(self, tag, attrs):
        if self._skip > 0:
            self._skip += 1
            return
        tag = tag.lower()
        attrs_d = {k.lower(): (v or "") for k, v in attrs}

        # 直接跳过的标签
        if tag in BLOCK_TAGS_STRIP:
            self._skip = 1
            self._skip_tags.add(tag)
            return

        # 噪声节点
        ci = f"{attrs_d.get('class','')} {attrs_d.get('id','')}".strip()
        if ci and NOISE_RE.search(ci) and tag in BLOCK_TAGS_KEEP:
            # 高置信噪声直接跳过
            if any(k in ci.lower() for k in ("comment", "footer", "sidebar", "advert", "recommend", "related")):
                self._skip = 1
                self._skip_tags.add(tag)
                return

        self._stack.append(tag)

        # 标题
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._newline(1)
            level = int(tag[1])
            self.out.append("#" * level + " ")

        # 段落
        elif tag == "p":
            self._newline(1)

        # 粗体
        elif tag in ("strong", "b"):
            self.out.append("**")
        # 斜体
        elif tag in ("em", "i"):
            self.out.append("*")
        # 行内代码
        elif tag == "code" and not self._in_pre:
            self.out.append("`")

        # 预格式/代码块
        elif tag == "pre":
            self._in_pre = True
            self._pre_buf = []
            self._pre_lang = attrs_d.get("class", "").replace("language-", "").strip() or ""
            self._newline(1)
            self.out.append("```" + self._pre_lang + "\n")
        elif tag == "code" and self._in_pre:
            pass  # pre 内部的 code 标签忽略

        # 引用块
        elif tag == "blockquote":
            self._in_blockquote += 1
            self._newline(1)

        # 列表
        elif tag in ("ul", "ol"):
            self._list_stack.append(tag)
            self._list_idx.append(0)
            self._newline(1)
        elif tag == "li":
            if self._list_stack:
                indent = "  " * (len(self._list_stack) - 1)
                if self._list_stack[-1] == "ol":
                    self._list_idx[-1] += 1
                    self.out.append(f"{indent}{self._list_idx[-1]}. ")
                else:
                    self.out.append(f"{indent}- ")

        # 链接
        elif tag == "a":
            href = attrs_d.get("href", "")
            href = absolute_url(self.base_url, href)
            if href and not href.startswith(("javascript:", "mailto:", "tel:", "#")):
                self._link_stack.append((href, len(self.out)))
            else:
                self._link_stack.append(("", len(self.out)))

        # 图片
        elif tag == "img":
            src = attrs_d.get("src", "") or attrs_d.get("data-src", "") or attrs_d.get("data-original", "")
            alt = attrs_d.get("alt", "") or attrs_d.get("title", "")
            src = absolute_url(self.base_url, src)
            if src:
                self.out.append(f"![{alt}]({src})")

        # 水平线
        elif tag == "hr":
            self._newline(1)
            self.out.append("---\n")
        elif tag == "br":
            self.out.append("  \n")

        # 表格
        elif tag == "table":
            self._table_buf = []
        elif tag == "tr":
            self._table_row = []
        elif tag in ("td", "th"):
            self._table_cell = []
            self._in_th = (tag == "th")

    def handle_endtag(self, tag):
        if self._skip > 0:
            self._skip -= 1
            if self._skip == 0:
                self._skip_tags.clear()
            return
        tag = tag.lower()

        # 闭合栈顶
        if self._stack and self._stack[-1] == tag:
            self._stack.pop()
        elif tag in self._stack:
            while self._stack and self._stack[-1] != tag:
                self._stack.pop()
            if self._stack:
                self._stack.pop()

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._newline(1)
        elif tag == "p":
            self._newline(2)
        elif tag in ("strong", "b"):
            self.out.append("**")
        elif tag in ("em", "i"):
            self.out.append("*")
        elif tag == "code":
            if self._in_pre:
                # pre 结束时会处理
                pass
            else:
                self.out.append("`")
        elif tag == "pre":
            self._in_pre = False
            pre_text = "".join(self._pre_buf)
            pre_text = pre_text.strip("\n")
            self.out.append(pre_text)
            self.out.append("\n```\n")
        elif tag == "blockquote":
            self._in_blockquote = max(0, self._in_blockquote - 1)
            self._newline(1)
        elif tag in ("ul", "ol"):
            if self._list_stack:
                self._list_stack.pop()
                self._list_idx.pop()
            self._newline(1)
        elif tag == "li":
            self._newline(1)
        elif tag == "a":
            if self._link_stack:
                href, start_idx = self._link_stack.pop()
                if href and start_idx < len(self.out):
                    inner = "".join(self.out[start_idx:])
                    inner = inner.strip()
                    # 截断到 start_idx，替换为 Markdown 链接
                    del self.out[start_idx:]
                    if inner:
                        self.out.append(f"[{inner}]({href})")
            self._link_href = ""
        elif tag in ("td", "th"):
            cell_text = "".join(self._table_cell).strip().replace("\n", " ")
            self._table_row.append(cell_text)
            self._table_cell = []
        elif tag == "tr":
            if self._table_row:
                self._table_buf.append(self._table_row)
            self._table_row = []
        elif tag == "table":
            self._emit_table()
            self._table_buf = []

    def handle_data(self, data):
        if self._skip > 0:
            return
        if self._in_pre:
            self._pre_buf.append(data)
            return
        if self._table_cell is not None and self._current_tag() in ("td", "th"):
            self._table_cell.append(self._strip_text(data))
            return
        text = self._strip_text(data)
        if not text:
            return

        # 引用块前缀
        if self._in_blockquote and self.out and self.out[-1].endswith("\n"):
            self.out.append("> ")

        self.out.append(text)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        # 自闭合标签不压栈，直接视为已结束
        if tag in ("img", "br", "hr", "input", "meta", "link"):
            pass
        else:
            self.handle_endtag(tag)

    # ------------------ 表格输出 ------------------
    def _emit_table(self):
        if not self._table_buf:
            return
        rows = self._table_buf
        max_cols = max(len(r) for r in rows)
        # 对齐列数
        rows = [r + [""] * (max_cols - len(r)) for r in rows]
        self._newline(1)
        # 表头
        header = rows[0]
        self.out.append("| " + " | ".join(c.replace("|", "\\|") for c in header) + " |\n")
        self.out.append("| " + " | ".join(["---"] * max_cols) + " |\n")
        for row in rows[1:]:
            self.out.append("| " + " | ".join(c.replace("|", "\\|") for c in row) + " |\n")
        self._newline(1)

    # ------------------ 后处理 ------------------
    def get_markdown(self) -> str:
        md = "".join(self.out)
        # 清理多余空行
        md = re.sub(r"\n{3,}", "\n\n", md)
        # 清理引用块空行
        md = re.sub(r"(> \s*\n){2,}", "> \n", md)
        # 包裹链接：简单扫描 a 标签文本和 href 的遗留（本实现采用文本直出，保留可读）
        return md.strip()


# ===================================================================
# 通用正文抽取（基于文本密度 + 链接密度）
# ===================================================================
class GenericExtractor:
    """
    基于 DOM 树的文本密度/链接密度算法抽取正文节点
    思路参考：CEPR / Readability 简化版
    """

    # 正文容器候选标签（权重更高）
    CONTENT_TAGS = {"article", "main", "section", "div", "td"}

    def __init__(self, html_text: str, base_url: str = ""):
        self.html = html_text
        self.base_url = base_url
        self._tree = self._build_tree()

    def _build_tree(self) -> _Node:
        # 先移除 script/style 大块减少解析负担
        cleaned = re.sub(r"<script[\s\S]*?</script>", "", self.html, flags=re.I)
        cleaned = re.sub(r"<style[\s\S]*?</style>", "", cleaned, flags=re.I)
        cleaned = re.sub(r"<!--[\s\S]*?-->", "", cleaned)
        builder = _TreeBuilder()
        try:
            builder.feed(cleaned)
            builder.close()
        except Exception as e:
            logger.warning(f"HTML parse error: {e}")
        return builder.root

    def _calc_stats(self, node: _Node) -> int:
        """递归计算每个节点的文本长度、链接文本长度"""
        # 先算自身文本
        own_text = node.text or ""
        is_link = (node.tag == "a")
        if is_link:
            node.link_text_len += len(own_text.strip())
        node.text_len += len(re.sub(r"\s+", "", own_text))
        node.tag_count = 1
        node.link_count = 1 if is_link else 0

        for child in node.children:
            if child.is_noise():
                continue
            self._calc_stats(child)
            node.text_len += child.text_len
            node.link_text_len += child.link_text_len
            node.tag_count += child.tag_count
            node.link_count += child.link_count
            # child.tail 是 node 内位于 child 之后的文本
            tail = child.tail or ""
            tail_clean = re.sub(r"\s+", "", tail)
            node.text_len += len(tail_clean)
            if is_link:
                node.link_text_len += len(tail.strip())

        return node.text_len

    def _score(self, node: _Node):
        """计算节点得分"""
        if node.text_len < 25:
            node.score = 0
            return
        text_len = node.text_len
        link_density = node.link_text_len / max(text_len, 1)
        tag_bonus = 0.0
        if node.tag in ("article", "main"):
            tag_bonus += 30
        elif node.tag == "section":
            tag_bonus += 15
        elif node.tag == "div":
            tag_bonus += 5
        elif node.tag == "td":
            tag_bonus -= 5
        # class/id 加分
        ci = node.cls_id().lower()
        if ci:
            if re.search(r"article|content|post|entry|main|body|text|story|rich_media", ci):
                tag_bonus += 25
            if NOISE_RE.search(ci):
                tag_bonus -= 30
        # 逗号/句号数量（中文句号）
        punct = (node.text or "").count("，") + (node.text or "").count("。") + \
                (node.text or "").count(".") + (node.text or "").count(",")
        for c in node.children:
            punct += (c.text or "").count("，") + (c.text or "").count("。")

        # 基础分：文本长度 * (1 - 链接密度)
        base = text_len * (1 - link_density * 1.5)
        node.score = base + tag_bonus + punct * 2
        # 段落密度：子节点中 p/pre/blockquote 多的节点加分
        p_count = sum(1 for c in node.children if c.tag in ("p", "pre", "blockquote", "h1", "h2", "h3"))
        node.score += p_count * 10

    def _find_best_node(self, node: _Node) -> Optional[_Node]:
        self._score(node)
        best = node if node.score > 0 else None
        for child in node.children:
            if child.is_noise():
                continue
            cand = self._find_best_node(child)
            if cand is None:
                continue
            if best is None or cand.score > best.score:
                best = cand
        return best

    def _node_to_html(self, node: _Node) -> str:
        """把选中的节点序列化为 HTML 片段"""
        parts: List[str] = []
        self._serialize(node, parts)
        return "".join(parts)

    def _serialize(self, node: _Node, out: List[str]):
        for child in node.children:
            if child.is_noise():
                continue
            attrs_str = ""
            if child.attrs:
                attrs_str = " " + " ".join(
                    f'{k}="{html.escape(v, quote=True)}"' for k, v in child.attrs.items()
                    if k in ("href", "src", "alt", "title", "class", "id", "colspan", "rowspan", "data-src", "data-original")
                )
            if child.tag in ("img", "br", "hr", "input"):
                out.append(f"<{child.tag}{attrs_str} />")
                if child.tail:
                    out.append(html.escape(child.tail))
                continue
            out.append(f"<{child.tag}{attrs_str}>")
            if child.text:
                out.append(html.escape(child.text))
            self._serialize(child, out)
            out.append(f"</{child.tag}>")
            if child.tail:
                out.append(html.escape(child.tail))

    # ------ 标题 / 作者 ------
    def _find_title(self) -> str:
        # 1. <title>
        m = re.search(r"<title[^>]*>(.*?)</title>", self.html, re.S | re.I)
        if m:
            t = html.unescape(re.sub(r"\s+", " ", m.group(1))).strip()
            # 去除常见站点后缀
            t = re.sub(r"[-_|]\s*(CSDN|知乎|简书|豆瓣|博客园|博客|Blog)[:\s]*$", "", t).strip()
            if t:
                return t
        # 2. <h1>
        m = re.search(r"<h1[^>]*>(.*?)</h1>", self.html, re.S | re.I)
        if m:
            t = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip()
            if t:
                return t
        return "未命名文章"

    def _find_author(self) -> str:
        # meta author
        m = re.search(r'<meta[^>]*name=["\']author["\'][^>]*content=["\']([^"\']+)["\']', self.html, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
        m = re.search(r'<meta[^>]*property=["\']article:author["\'][^>]*content=["\']([^"\']+)["\']', self.html, re.I)
        if m:
            return html.unescape(m.group(1)).strip()
        return "未知作者"

    # ------ 入口 ------
    def extract(self) -> Tuple[str, str, str, List[str]]:
        """返回 (title, author, content_html, images)"""
        title = self._find_title()
        author = self._find_author()
        self._calc_stats(self._tree)
        best = self._find_best_node(self._tree)
        if best is None:
            # 退化：取 body
            m = re.search(r"<body[^>]*>([\s\S]*?)</body>", self.html, re.I)
            content_html = m.group(1) if m else self.html
        else:
            content_html = self._node_to_html(best)

        # 收集图片
        images = []
        for m in re.finditer(r'<img[^>]+(?:src|data-src|data-original)=["\']([^"\']+)["\']', content_html, re.I):
            src = absolute_url(self.base_url, m.group(1))
            if src and not src.startswith("data:"):
                images.append(src)
        # 去重保序
        seen = set()
        images = [x for x in images if not (x in seen or seen.add(x))]
        return title, author, content_html, images


# ===================================================================
# 主类
# ===================================================================
class ArticleExtractor:
    """通用网页正文提取器"""

    def __init__(
        self,
        output_dir: str = "output",
        download_images: bool = False,
        image_dir_name: str = "images",
        cookies: Optional[Dict[str, str]] = None,
        cookie_file: Optional[str] = None,
        proxy: Optional[str] = None,
        timeout: int = DEFAULT_TIMEOUT,
        save_markdown: bool = True,
    ):
        self.output_dir = output_dir
        self.download_images = download_images
        self.image_dir_name = image_dir_name
        self.cookies = cookies
        self.cookie_file = cookie_file
        self.proxy = proxy
        self.timeout = timeout
        self.save_markdown = save_markdown

        self.rules: List[PlatformRule] = [
            WeChatRule(),
            ZhihuPaidRule(),  # 必须在 ZhihuRule 之前，优先匹配 oia.zhihu.com
            ZhihuRule(),
            CsdnRule(),
            JianShuRule(),
            DoubanDiaryRule(),
        ]
        self.generic_rule = GenericRule()

    # ------------------------------------------------------------------
    # 规则匹配
    # ------------------------------------------------------------------
    def _match_rule(self, url: str) -> PlatformRule:
        for rule in self.rules:
            if rule.match(url):
                return rule
        return self.generic_rule

    # ------------------------------------------------------------------
    # HTTP
    # ------------------------------------------------------------------
    def _fetch(self, url: str, rule: PlatformRule) -> Tuple[str, str]:
        client = HttpClient(
            ua=rule.ua,
            referer=rule.referer,
            cookies=self.cookies,
            cookie_file=self.cookie_file,
            proxy=self.proxy,
            timeout=self.timeout,
        )
        html_text, final_url, status = client.get(url)
        logger.info(f"Fetched {url} -> {status} (rule={rule.name})")
        return html_text, final_url

    # ------------------------------------------------------------------
    # 平台定向提取
    # ------------------------------------------------------------------
    def _regex_first(self, patterns: List[str], text: str, flags=re.S | re.I) -> str:
        for p in patterns:
            m = re.search(p, text, flags)
            if not m:
                continue
            val = m.group(1)
            val = re.sub(r"<[^>]+>", "", val)
            val = html.unescape(val)
            val = re.sub(r"\s+", " ", val).strip()
            if val:
                return val
        return ""

    def _extract_by_rule(
        self, rule: PlatformRule, html_text: str, base_url: str
    ) -> Tuple[str, str, str, List[str]]:
        """使用平台规则抽取，失败则回退到通用算法"""
        title = self._regex_first(rule.title_selectors, html_text)
        author = self._regex_first(rule.author_selectors, html_text)

        content_html = ""
        for p in rule.content_selectors:
            m = re.search(p, html_text, re.S | re.I)
            if m:
                content_html = m.group(1)
                break

        # 清理噪声
        if content_html:
            for np in rule.noise_selectors:
                # 删除匹配的整个标签块（简化：贪婪删除到下一个同级别 close 比较复杂，这里删除 class 所在开标签到最近 </div> 之间）
                content_html = re.sub(
                    rf'<(\w+)[^>]*{np}[^>]*>[\s\S]*?</\1>',
                    "", content_html, flags=re.I
                )

        if not content_html or len(re.sub(r"<[^>]+>", "", content_html).strip()) < 50:
            logger.info(f"Rule {rule.name} failed, fallback to generic")
            ge = GenericExtractor(html_text, base_url)
            g_title, g_author, g_html, g_imgs = ge.extract()
            title = title or g_title
            author = author or g_author
            content_html = g_html
        else:
            # 收集图片
            images = []
            for m in re.finditer(r'<img[^>]+(?:src|data-src|data-original)=["\']([^"\']+)["\']', content_html, re.I):
                src = absolute_url(base_url, m.group(1))
                if src and not src.startswith("data:"):
                    images.append(src)
            seen = set()
            images = [x for x in images if not (x in seen or seen.add(x))]

        if not title:
            title = "未命名文章"
        if not author:
            author = "未知作者"

        return title, author, content_html, images if 'images' in dir() else []

    # ------------------------------------------------------------------
    # 图片下载
    # ------------------------------------------------------------------
    def _download_image(self, url: str, save_dir: str) -> str:
        """下载图片到本地，返回本地路径（相对 Markdown 文件）"""
        try:
            os.makedirs(save_dir, exist_ok=True)
            ext = os.path.splitext(urlparse(url).path)[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg"):
                ext = ".jpg"
            h = hashlib.md5(url.encode("utf-8")).hexdigest()[:12]
            fname = f"{h}{ext}"
            fpath = os.path.join(save_dir, fname)
            if os.path.exists(fpath) and os.path.getsize(fpath) > 0:
                return os.path.join(self.image_dir_name, fname)

            req = Request(url, headers={"User-Agent": DEFAULT_UA, "Referer": url})
            resp = urlopen(req, timeout=self.timeout)
            data = resp.read()
            with open(fpath, "wb") as f:
                f.write(data)
            logger.debug(f"Downloaded image {url} -> {fpath}")
            return os.path.join(self.image_dir_name, fname)
        except Exception as e:
            logger.warning(f"Download image failed: {url} -> {e}")
            return url

    # ------------------------------------------------------------------
    # HTML -> Markdown
    # ------------------------------------------------------------------
    def _html_to_md(self, content_html: str, base_url: str) -> str:
        conv = HtmlToMarkdown(base_url=base_url)
        try:
            conv.feed(content_html)
            conv.close()
        except Exception as e:
            logger.warning(f"HTML->MD convert error: {e}")
        return conv.get_markdown()

    def _replace_image_links(
        self, md: str, images: List[str], article_dir: str
    ) -> Tuple[str, List[str]]:
        """根据是否下载图片替换 Markdown 中的图片链接"""
        if not self.download_images:
            return md, images
        img_dir = os.path.join(article_dir, self.image_dir_name)
        local_images = []
        for img_url in images:
            local = self._download_image(img_url, img_dir)
            local_images.append(local)

        def _replace(m):
            alt = m.group(1)
            url = m.group(2)
            if url in images:
                idx = images.index(url)
                local = local_images[idx]
                return f"![{alt}]({local})"
            return m.group(0)

        new_md = re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _replace, md)
        return new_md, local_images

    # ------------------------------------------------------------------
    # 单篇提取
    # ------------------------------------------------------------------
    def extract(self, url: str) -> Dict[str, Any]:
        """
        提取单个 URL，返回字典：
        {
            "url": ...,
            "platform": ...,
            "title": ...,
            "author": ...,
            "content_markdown": ...,
            "content_html": ...,
            "images": [...],
            "saved_path": ...  # 若 save_markdown=True
        }
        """
        url = clean_url(url)
        rule = self._match_rule(url)
        html_text, final_url = self._fetch(url, rule)
        title, author, content_html, images = self._extract_by_rule(rule, html_text, final_url)
        md = self._html_to_md(content_html, final_url)

        saved_path = ""
        local_images = images
        if self.save_markdown:
            # 目录结构：output_dir/platform/author/
            platform_dir = os.path.join(self.output_dir, safe_filename(rule.name))
            author_dir = os.path.join(platform_dir, safe_filename(author))
            os.makedirs(author_dir, exist_ok=True)
            md, local_images = self._replace_image_links(md, images, author_dir)
            fname = safe_filename(title) + ".md"
            fpath = os.path.join(author_dir, fname)
            # 文件头
            header = (
                f"# {title}\n\n"
                f"- 作者：{author}\n"
                f"- 平台：{rule.name}\n"
                f"- 原文：{final_url}\n\n"
                f"---\n\n"
            )
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(header + md)
            saved_path = fpath
            logger.info(f"Saved: {fpath}")

        return {
            "url": final_url,
            "platform": rule.name,
            "title": title,
            "author": author,
            "content_markdown": md,
            "content_html": content_html,
            "images": local_images,
            "saved_path": saved_path,
        }

    # ------------------------------------------------------------------
    # 批量提取
    # ------------------------------------------------------------------
    def extract_batch(self, url_list: List[str], delay: float = 1.0) -> List[Dict[str, Any]]:
        results = []
        for i, url in enumerate(url_list, 1):
            logger.info(f"[{i}/{len(url_list)}] Extracting: {url}")
            try:
                res = self.extract(url)
                results.append(res)
            except Exception as e:
                logger.error(f"Failed to extract {url}: {e}")
                results.append({
                    "url": url,
                    "error": str(e),
                    "title": "",
                    "author": "",
                    "content_markdown": "",
                    "content_html": "",
                    "images": [],
                    "saved_path": "",
                })
            if delay > 0 and i < len(url_list):
                time.sleep(delay)
        return results


# ===================================================================
# 自测
# ===================================================================
def _self_test():
    """自测代码：构造至少 3 个不同平台的 URL 进行提取测试
    注意：实际网络环境可能影响抓取结果，失败时打印原因。
    """
    test_urls = [
        # 微信公众号示例文章（示例 URL，实际可能失效）
        "https://mp.weixin.qq.com/s/test_article",
        # 知乎付费内容（盐选/盐言故事）分享链接
        "https://oia.zhihu.com/km_paid_content/share?km_pst=3AYY8ESOBxAnZmkzyr8r5Xkyk-QmglmuP1pNme3a7WkfGwPf_vuVLXJepqOCUXwRXHIs-8r6rSVeXtiTWBS39f78mVXJA00nsoJ45UHK5Xx-2n4%3D&share_code=RMmzFvaqNgvU&utm_psn=2067376697343844450",
        # 知乎专栏示例
        "https://zhuanlan.zhihu.com/p/123456789",
        # CSDN 博客示例
        "https://blog.csdn.net/test/article/details/123456789",
        # 简书示例
        "https://www.jianshu.com/p/abcdef123456",
        # 豆瓣日记示例
        "https://www.douban.com/note/123456789/",
    ]

    extractor = ArticleExtractor(
        output_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), "article_output"),
        download_images=False,
        save_markdown=True,
        timeout=15,
    )

    print("=" * 60)
    print("ArticleExtractor 自测开始")
    print(f"共 {len(test_urls)} 个测试 URL")
    print("=" * 60)

    # 为了演示，在无网络或 URL 失效时，我们用构造的 HTML 片段验证核心逻辑
    print("\n[1/2] 规则匹配测试：")
    for u in test_urls:
        rule = extractor._match_rule(u)
        print(f"  {u[:60]:<60s} -> {rule.name}")

    print("\n[2/2] HTML 解析与 Markdown 转换测试（离线构造数据）：")

    # 构造模拟 HTML 测试通用提取器
    test_html = """
    <!DOCTYPE html>
    <html>
    <head><title>测试文章标题 - 示例站点</title>
    <meta name="author" content="测试作者"></head>
    <body>
    <nav><a href="/">首页</a><a href="/about">关于</a></nav>
    <div class="sidebar">侧边栏广告 广告广告广告</div>
    <article class="article-content">
        <h1 class="title">测试文章标题</h1>
        <p>这是第一篇<strong>加粗</strong>段落，包含<em>斜体</em>和<code>行内代码</code>。</p>
        <p>第二段，这里有一个<a href="https://example.com">链接示例</a>。</p>
        <h2>二级标题</h2>
        <blockquote>这是一段引用文字，用于测试引用块。</blockquote>
        <pre><code class="language-python">
def hello():
    print("Hello, World!")
        </code></pre>
        <p>下面是图片：</p>
        <p><img src="/images/test.jpg" alt="测试图片"></p>
        <table>
            <tr><th>列1</th><th>列2</th></tr>
            <tr><td>A</td><td>B</td></tr>
            <tr><td>C</td><td>D</td></tr>
        </table>
        <ul>
            <li>列表项 1</li>
            <li>列表项 2</li>
            <li>列表项 3</li>
        </ul>
    </article>
    <div class="footer">页脚 版权所有 2024</div>
    <div class="comments">
        <div class="comment">评论1：这篇文章不错</div>
        <div class="comment">评论2：学到了</div>
    </div>
    </body></html>
    """

    ge = GenericExtractor(test_html, base_url="https://example.com/post/1")
    title, author, content_html, images = ge.extract()
    print(f"  标题: {title}")
    print(f"  作者: {author}")
    print(f"  正文HTML长度: {len(content_html)}")
    print(f"  图片: {images}")

    md = extractor._html_to_md(content_html, "https://example.com/post/1")
    print(f"\n  Markdown 输出预览：")
    print("  " + "-" * 50)
    for line in md.splitlines()[:30]:
        print("  " + line)
    print("  " + "-" * 50)

    # 测试文件名清理
    print(f"\n  安全文件名测试: '{safe_filename('Hello/World:测试*标题?')}' -> '{safe_filename('Hello/World:测试*标题?')}'")

    # 测试 URL 绝对路径补全
    print(f"  相对路径补全: '/images/a.jpg' + base 'https://x.com/y/z' -> '{absolute_url('https://x.com/y/z', '/images/a.jpg')}'")
    print(f"  相对路径补全: 'b.jpg' + base 'https://x.com/y/z' -> '{absolute_url('https://x.com/y/z', 'b.jpg')}'")

    print("\n" + "=" * 60)
    print("自测完成。类名 ArticleExtractor 可直接使用。")
    print("在线批量抓取示例:")
    print("  extractor = ArticleExtractor(output_dir='output')")
    print("  result = extractor.extract('https://example.com/article')")
    print("  results = extractor.extract_batch(['url1','url2','url3'])")
    print("=" * 60)


if __name__ == "__main__":
    _self_test()
