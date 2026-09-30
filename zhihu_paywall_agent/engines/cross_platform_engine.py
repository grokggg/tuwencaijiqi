# -*- coding: utf-8 -*-
"""
cross_platform_engine.py - 多平台搜索引擎 (P1)

对每个搜索结果发起二次HTTP请求访问完整页面，
用BeautifulSoup解析正文容器，自动识别目录页并跳转第一章，
支持多章累积获取，提取全文内容。
"""
import asyncio
import concurrent.futures
import logging
import re
import time
from typing import Optional, Dict, List, Tuple
from urllib.parse import quote, urljoin, urlparse

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup
from curl_cffi import requests as curl_requests

import config
from core.parser import ContentParser, ParsedContent, extract_article_id

logger = logging.getLogger(__name__)

# 正文选择器（按优先级）
CONTENT_SELECTORS = [
    # 小说站专用
    "#chaptercontent", "#BookText", ".read-content", ".chapter-content",
    ".novel-content", ".book-content", ".contentbox", "#contentbox",
    ".txt", "#text", ".article-content", ".post-content", ".entry-content",
    "#content", ".content", ".article-body", ".post-body",
    ".main-content", "#main-content", ".story-content", ".nov-content",
    ".article", ".post", "article", ".show-content-free",
    ".rich_media_content", ".rich-content", ".RichContent",
    "main", ".main", "#main", ".page-content",
    ".read_bg",  # 随意阅读网专用
]

# 噪声容器（整个移除）
NOISE_CONTAINERS = [
    "script", "style", "nav", "footer", "header", "aside", "iframe",
    "form", "button", "input", "noscript",
    ".ad", ".advertisement", ".ads", ".adsbygoogle",
    ".recommend", ".related", ".comment", ".comments", ".comment-list",
    ".sidebar", ".side-bar", ".menu", ".navbar", ".nav-bar",
    ".share", ".social", ".like", ".vote",
    ".chapter-nav", ".chapternav", ".page-navbar",
    ".book-nav", ".page-nav", ".pagination", ".pager",
    ".pre-chapter", ".next-chapter", ".prev-chapter",
    ".bookmark", ".favorite", ".report", ".copyright",
    ".tags", ".tag", ".meta", ".info", ".author-info",
    ".up", ".down", ".prev", ".next",
    ".font", ".fontbox", ".read-btn",  # 字号调节
    ".mulu", ".dir", ".catalog",  # 目录按钮
]

# 噪声行关键词（从提取文本中过滤）
NOISE_LINE_PATTERNS = [
    r'^[A\-\+\s]+$',  # 纯字号调节 A- A A+
    r'^(上一章|下一章|返回目录|目录|加入书架|推荐阅读|相关推荐|热门推荐)',
    r'^(手机版|电脑版|APP|扫码|下载|登录|注册|广告)',
    r'^(本章未完|下一页|继续阅读|展开全文|点击下一页)',
    r'(版权所有|Copyright|侵权|请联系|第一时间|处理)',
    r'(更新时间|发布时间|字数|作者|状态|最新章节)',
    r'^https?://',
    r'^www\.',
    r'^(第\d+章|第 [\d一二三四五六七八九十]+ 章)\s*$',  # 单独的章节标题行（后面会有正文标题）
    r'^\d{4}[-\.]\d{1,2}[-\.]\d{1,2}',  # 日期开头
    r'^\d+\s*字$',  # 字数行
    r'^(侠名|佚名|未知|作者：)',  # 常见佚名作者标记
    r'^\d{1,2}:\d{2}(?::\d{2})?$',  # 纯时间
    r'^[A-Za-z0-9\s\-_/]+$',  # 纯英文/数字/符号行（非正文）
]

# 小说转载站（site搜索专用）
NOVEL_REPOST_SITES = [
    # 知乎盐选搬运站
    "onehu.xyz", "yankeng.cc", "zhihustory.com", "zhihuxs.com",
    "8dks.com", "zhihubg.com", "yanmo8.com", "ireadshort.com",
    "xiaoguanwang.com", "husiyu.com", "ituohai.com",
    "duanwenxue.com", "anystories.net", "zhaishuyuan.com",
    # 小说转载/笔趣阁系
    "biqugexx.net", "bqgui.cc", "ibiquges.info", "biquge5200.cc",
    "23us.la", "dingdiann.com", "qidian.com", "zongheng.com",
    "xsbiquge.com", "shuquge.com", "bxwxorg.la", "wxsc.com",
    "69shu.com", "23txt.com", "77xsw.com", "37zw.net",
    "beqege.com", "biqooge.com", "pgebook.com", "uuks.com",
    # 短篇/言情/免费阅读
    "hongxiu.com", "jjwxc.net", "xxsy.net", "fanqienovel.com",
    "shuhaige.com", "tadu.com", "yawen8.com", "gudanwenxue.com",
    "sanjiange.com", "xiaomawenxue.com", "syzgly.com",
    "mochoublog.com", "zhangxin.tv", "vipreading.com",
]

# 跳过的非内容域名
SKIP_DOMAINS = [
    "douyin.com", "tiktok.com", "bilibili.com", "youtube.com",
    "sohu.com", "sina.com.cn", "163.com", "qq.com", "weibo.com",
    "taobao.com", "jd.com", "tmall.com", "pinduoduo.com",
    "baidu.com", "bing.com", "google.com", "sogou.com",
    "zhihu.com", "xiaohongshu.com", "douban.com",
    "weixin.qq.com", "mp.weixin.qq.com",
    "apple.com", "github.com", "iiilab.com", "dgtle.com", "smzdm.com",
]


def _make_fresh_session(mobile: bool = False):
    """创建全新的curl_cffi session（不经过session池，避免线程安全问题）"""
    sess = curl_requests.Session(impersonate="chrome120")
    ua_desktop = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    ua_mobile = ("Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                 "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                 "Mobile/15E148 Safari/604.1")
    sess.headers.update({
        "User-Agent": ua_mobile if mobile else ua_desktop,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate, br",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    })
    return sess


def _http_get(url: str, referer: str = "https://www.bing.com/",
              mobile: bool = False, timeout: int = 10, verify: bool = False) -> Tuple[int, str, str]:
    """独立HTTP GET请求，返回 (status, html, final_url)。不重试，快速失败。"""
    sess = _make_fresh_session(mobile=mobile)
    try:
        resp = sess.get(
            url,
            headers={"Referer": referer},
            timeout=timeout,
            allow_redirects=True,
            verify=verify,
        )
        # 编码处理
        html = resp.text
        if hasattr(resp, 'encoding') and resp.encoding:
            try:
                html = resp.content.decode(resp.encoding, errors='ignore')
            except:
                pass
        meta_charset = re.search(r'<meta[^>]*charset=["\']?([^"\'>\s;]+)', html[:2000], re.I)
        if meta_charset:
            try:
                html = resp.content.decode(meta_charset.group(1), errors='ignore')
            except:
                pass
        return resp.status_code, html, resp.url
    except Exception as e:
        raise
    finally:
        try:
            sess.close()
        except:
            pass


class CrossPlatformEngine:
    """多平台搜索引擎 - 二次请求+BS4正文提取+目录页自动跳转+多章累积"""

    name = "cross_platform_engine"

    def __init__(self, session_manager=None):
        self.parser = ContentParser()
        self.sm = session_manager  # 保留参数兼容，实际HTTP用独立session

    async def fetch(self, url: str, title_hint: str = "") -> Optional[ParsedContent]:
        start_time = time.time()
        ids = extract_article_id(url) if url else {}

        title = title_hint
        if not title and url:
            title = await self._fetch_title(url, ids)
        if not title:
            logger.warning("无法获取文章标题，跨平台搜索跳过")
            return None

        logger.info(f"跨平台搜索标题: {title}")

        # 构建搜索查询
        search_queries = [
            f'"{title}" 全文阅读',
            f'"{title}" 免费阅读',
            f'"{title}" 小说',
            f'{title} 知乎 盐选',
            title,
        ]
        for site in NOVEL_REPOST_SITES[:15]:
            search_queries.append(f'site:{site} "{title}"')

        # 执行搜索
        all_links = []
        searched = set()
        for query in search_queries[:12]:
            if query in searched:
                continue
            searched.add(query)
            try:
                links = await asyncio.to_thread(self._search_bing, query)
                all_links.extend(links)
            except Exception as e:
                logger.debug(f"搜索失败: {e}")
            await asyncio.sleep(0.2)

        # 去重并过滤
        seen = set()
        unique_links = []
        for link, link_title in all_links:
            try:
                parsed = urlparse(link)
                domain = parsed.netloc.lower()
                if any(skip in domain for skip in SKIP_DOMAINS):
                    continue
                clean_url = f"{parsed.scheme}://{domain}{parsed.path}"
            except:
                clean_url = link
            if clean_url not in seen and "zhihu.com" not in link:
                seen.add(clean_url)
                unique_links.append((link, link_title))

        logger.info(f"找到 {len(unique_links)} 个候选链接")

        # 逐一访问
        for i, (link, link_title) in enumerate(unique_links[:15]):
            logger.info(f"  [{i+1}/{min(len(unique_links),15)}] 访问: {link[:80]}")
            try:
                content = await asyncio.wait_for(
                    self._extract_with_chapters(link, title),
                    timeout=35
                )
                if content and content.content_length >= 500:
                    content.platform = self._detect_platform(link)
                    if not content.title:
                        content.title = title
                    logger.info(f"跨平台引擎成功 ({content.platform}): "
                                f"{content.title} ({content.content_length}字)")
                    return content
            except asyncio.TimeoutError:
                logger.debug("  超时跳过")
                continue
            except Exception as e:
                logger.debug(f"  失败: {str(e)[:60]}")
                continue

        logger.info("跨平台引擎未找到完整内容")
        return None

    async def _fetch_title(self, url: str, ids: Dict) -> str:
        """从知乎页面获取标题"""
        try:
            status, html, final_url = await asyncio.to_thread(
                _http_get, url, "https://www.zhihu.com/", False, 8
            )
            if status == 200:
                m = re.search(r'<title>(.*?)</title>', html, re.S)
                if m:
                    t = re.sub(r'[-_|]\s*知乎\s*$', '', m.group(1)).strip()
                    if len(t) > 2:
                        return t
        except:
            pass
        return ""

    def _search_bing(self, query: str) -> List[Tuple[str, str]]:
        """Bing搜索，返回 [(url, title), ...]"""
        results = []
        search_url = f"https://www.bing.com/search?q={quote(query)}&count=20"
        try:
            status, html, final_url = _http_get(search_url, "https://www.bing.com/", False, 12)
            if status != 200:
                return results
            soup = BeautifulSoup(html, "lxml")
            for li in soup.select("li.b_algo"):
                h2 = li.find("h2")
                if h2:
                    a = h2.find("a", href=True)
                    if a:
                        link = a["href"]
                        lt = a.get_text(strip=True)
                        if link.startswith("http"):
                            domain = urlparse(link).netloc.lower()
                            if not any(skip in domain for skip in SKIP_DOMAINS):
                                results.append((link, lt))
        except Exception as e:
            logger.debug(f"Bing搜索异常: {e}")
        return results[:15]

    async def _extract_with_chapters(self, url: str, expected_title: str) -> Optional[ParsedContent]:
        """访问页面，如为目录页则跳转第一章（支持多级目录跳转），累积多章内容"""
        # 提取标题关键词用于相关性验证
        title_keywords = self._extract_title_keywords(expected_title)

        for mobile in [False, True]:
            try:
                status, html, final_url = await asyncio.to_thread(
                    _http_get, url, "https://www.bing.com/", mobile, 10
                )
                if status != 200 or len(html) < 200:
                    continue

                # 验证页面相关性（标题/正文必须包含足够多的关键词）
                if not self._check_page_relevance(html, expected_title, title_keywords):
                    logger.debug(f"  页面不相关，跳过")
                    continue

                # 解析当前页面
                content = self._parse_html(html, final_url, expected_title)

                # 验证内容相关性
                if content and not self._check_content_relevance(content, expected_title, title_keywords):
                    logger.debug(f"  内容不相关，跳过")
                    continue

                # 如果正文足够长（>=2000字），直接返回
                if content and content.content_length >= 2000:
                    return content

                # 多级目录跳转（最多2层）
                chapter_url = self._resolve_chapter_url(html, final_url, mobile=mobile, max_depth=2)
                if chapter_url and chapter_url != final_url:
                    logger.debug(f"  目录页→第一章: {chapter_url[:70]}")
                    # 章节链尝试当前UA，失败则尝试切换UA
                    ch_content = await self._fetch_chapter_chain(
                        chapter_url, expected_title, mobile, max_chapters=5
                    )
                    if not ch_content or not self._check_content_relevance(ch_content, expected_title, title_keywords):
                        ch_content = await self._fetch_chapter_chain(
                            chapter_url, expected_title, not mobile, max_chapters=5
                        )
                    if ch_content and ch_content.content_length >= 500:
                        if self._check_content_relevance(ch_content, expected_title, title_keywords):
                            return ch_content

                # 单页内容>=500也算有效
                if content and content.content_length >= 500:
                    return content

            except asyncio.TimeoutError:
                raise
            except Exception as e:
                logger.debug(f"  提取异常: {str(e)[:50]}")
                continue

        return None

    def _extract_title_keywords(self, title: str) -> List[str]:
        """从标题提取关键词（2字以上有意义词组），返回按长度降序排列"""
        import re as _re
        # 移除标点和常见无意义词
        clean = _re.sub(r'[《》""''【】\[\]「」()（）、，。！？\s]+', '', title)
        # 移除常见停用字
        stop_chars = set('的了是在和与我你他她它们这那一个上下不也就都而及或')
        # 提取所有2-4字的连续中文片段作为候选
        keywords = set()
        for length in [4, 3, 2]:
            for i in range(len(clean) - length + 1):
                chunk = clean[i:i+length]
                if _re.match(r'^[\u4e00-\u9fff]+$', chunk):
                    # 不包含停用字
                    if not any(c in stop_chars for c in chunk):
                        keywords.add(chunk)
        # 按长度降序，长词优先
        result = sorted(keywords, key=lambda x: -len(x))
        return result[:10]  # 最多10个关键词

    def _check_page_relevance(self, html: str, expected_title: str, keywords: List[str]) -> bool:
        """检查页面是否与目标标题相关"""
        soup = BeautifulSoup(html, "lxml")
        # 获取页面标题区域文本
        page_title = ""
        t = soup.find("title")
        if t:
            page_title = t.get_text(strip=True)
        h1 = soup.find("h1")
        if h1:
            page_title += " " + h1.get_text(strip=True)
        h2 = soup.find("h2")
        if h2:
            page_title += " " + h2.get_text(strip=True)

        if not page_title:
            return True  # 无法判断，放过

        # 计算匹配的关键词（优先长词匹配）
        matched_long = sum(1 for kw in keywords if len(kw) >= 3 and kw in page_title)
        matched_all = sum(1 for kw in keywords if kw in page_title)

        # 标题中直接包含原标题的核心部分
        # 提取expected_title中连续4字以上的片段
        import re as _re
        clean_expected = _re.sub(r'[《》""''【】\[\]「」()（）、，。！？\s]+', '', expected_title)
        core_phrases = []
        for length in [4, 3]:
            for i in range(len(clean_expected) - length + 1):
                phrase = clean_expected[i:i+length]
                if _re.match(r'^[\u4e00-\u9fff]+$', phrase):
                    core_phrases.append(phrase)

        # 如果页面标题包含4字以上原标题片段，高度相关
        if any(phrase in page_title for phrase in core_phrases):
            return True

        # 至少有一个3字以上关键词匹配，或者两个2字关键词匹配
        if matched_long >= 1 or matched_all >= 2:
            return True

        # 检查正文前2000字
        body_text = soup.get_text()[:2000]
        if any(phrase in body_text for phrase in core_phrases):
            return True

        return False

    def _check_content_relevance(self, content: Optional[ParsedContent], expected_title: str, keywords: List[str]) -> bool:
        """检查提取的内容是否与目标相关"""
        if not content:
            return False
        text_to_check = (content.title or "") + " " + (content.content_markdown or "")[:800]

        # 原标题的4字片段匹配
        import re as _re
        clean_expected = _re.sub(r'[《》""''【】\[\]「」()（）、，。！？\s]+', '', expected_title)
        for length in [4, 3]:
            for i in range(len(clean_expected) - length + 1):
                phrase = clean_expected[i:i+length]
                if _re.match(r'^[\u4e00-\u9fff]+$', phrase) and phrase in text_to_check:
                    return True

        # 关键词匹配
        matched_long = sum(1 for kw in keywords if len(kw) >= 3 and kw in text_to_check)
        matched_all = sum(1 for kw in keywords if kw in text_to_check)
        return matched_long >= 1 or matched_all >= 2

    def _resolve_chapter_url(self, html: str, base_url: str, mobile: bool = False, max_depth: int = 2) -> Optional[str]:
        """递归解析目录页，直到找到真正的第一章URL（支持多级跳转）"""
        visited = {base_url}
        current_url = base_url
        current_html = html

        for depth in range(max_depth + 1):
            ch_url = self._find_chapter_url(current_html, current_url)
            if not ch_url or ch_url in visited:
                break
            # 检查ch_url是否看起来像章节页
            if self._looks_like_chapter_url(ch_url, current_url):
                return ch_url
            # 否则是另一个目录页，获取它继续查找
            visited.add(ch_url)
            try:
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    fut = pool.submit(_http_get, ch_url, current_url, mobile, 8)
                    status, new_html, final = fut.result(timeout=10)
                if status == 200 and len(new_html) > 200:
                    current_url = final
                    current_html = new_html
                    ch_url2 = self._find_chapter_url(current_html, current_url)
                    if ch_url2 and ch_url2 not in visited and self._looks_like_chapter_url(ch_url2, current_url):
                        return ch_url2
            except:
                break
        return None

    def _looks_like_chapter_url(self, url: str, base_url: str) -> bool:
        """判断URL是否看起来像章节页（而非目录页/排行页）"""
        from urllib.parse import urlparse
        path = urlparse(url).path.lower()
        # 排除明显的非章节页
        if any(kw in path for kw in ["/paihang", "/rank", "/top", "/sort", "/category",
                                      "/list", "/mulu", "/catalog", "/dir/", "/allvisit",
                                      "/author", "/tags", "/search", "/zhuajue", "/zuozhe"]):
            return False
        # 章节页URL特征
        if re.search(r'[/_-][1-5](?:\.html?)?/?$', path):
            return True
        if re.search(r'/\d+/[1-5](?:\.html?)?/?$', path):
            return True
        if re.search(r'chapter[/_-][1-5]', path, re.I):
            return True
        if re.search(r'/(?:read|view)/\d+', path, re.I):
            return True
        if re.search(r'/\d+/\d+\.html?$', path):
            return True
        return False

    async def _fetch_chapter_chain(self, first_ch_url: str, expected_title: str,
                                    mobile: bool, max_chapters: int = 5) -> Optional[ParsedContent]:
        """从第一章开始，跟随'下一章'链接累积多章内容"""
        all_parts = []
        all_titles = []
        author = ""
        platform = ""
        current_url = first_ch_url
        visited = set()

        for ch_idx in range(max_chapters):
            if not current_url or current_url in visited:
                break
            visited.add(current_url)

            try:
                status, html, final_url = await asyncio.wait_for(
                    asyncio.to_thread(
                        _http_get, current_url,
                        first_ch_url, mobile, 10
                    ),
                    timeout=12
                )
                if status != 200 or len(html) < 200:
                    break

                parsed = self._parse_html(html, final_url, expected_title)
                if not parsed or parsed.content_length < 100:
                    break

                if parsed.title and parsed.title not in all_titles:
                    all_titles.append(parsed.title)
                if parsed.author and not author:
                    author = parsed.author
                if not platform:
                    platform = parsed.platform or ""

                # 获取正文并清理
                text = parsed.content_markdown or ""
                if not text and parsed.content_html:
                    text = BeautifulSoup(parsed.content_html, "lxml").get_text(separator="\n", strip=True)
                if text:
                    # 去除重复的章节标题行
                    text_clean = self._clean_chapter_text(text, expected_title)
                    if text_clean:
                        all_parts.append(f"## 第{ch_idx+1}章\n\n{text_clean}")

                # 找下一章链接
                next_url = self._find_next_chapter(html, final_url)
                if not next_url or next_url in visited:
                    break
                current_url = next_url
                await asyncio.sleep(0.3)

            except Exception as e:
                logger.debug(f"  章节获取失败: {str(e)[:50]}")
                break

        if not all_parts:
            return None

        combined_text = '\n\n'.join(all_parts)
        content = ParsedContent()
        content.original_url = first_ch_url
        content.title = all_titles[0] if all_titles else expected_title
        content.author = author
        content.platform = platform
        content.content_markdown = combined_text
        content.content_html = f"<div>{combined_text}</div>"
        content.content_length = len(combined_text)
        content.is_truncated = content.content_length < config.MIN_CONTENT_LENGTH
        return content

    def _parse_html(self, html: str, url: str, expected_title: str) -> Optional[ParsedContent]:
        """BeautifulSoup解析正文，返回ParsedContent"""
        soup = BeautifulSoup(html, "lxml")

        # 1. 标题
        page_title = ""
        t = soup.find("title")
        if t:
            page_title = t.get_text(strip=True)
            page_title = re.sub(r'[-_|]\s*(知乎|笔趣阁|顶点小说|小说网|免费阅读|全文阅读|无弹窗|精选章节|完整版|大结局|最新章节列表|最新章节).*$', '', page_title).strip()
            page_title = re.sub(r'^第\d+章\s*', '', page_title).strip()
        if not page_title:
            og = soup.find("meta", property="og:title")
            if og and og.get("content"):
                page_title = og["content"].strip()
        if not page_title:
            h1 = soup.find("h1")
            if h1:
                page_title = h1.get_text(strip=True)

        # 2. 作者
        author = ""
        for sel in [".author", ".writer", ".book-author", ".novel-author",
                    "meta[name=author]", ".article-author"]:
            el = soup.select_one(sel)
            if el:
                author = el.get("content", "") if el.name == "meta" else el.get_text(strip=True)
                if author:
                    break

        # 3. 移除噪声容器
        for sel in NOISE_CONTAINERS:
            for el in soup.select(sel):
                el.decompose()

        # 4. 遍历选择器找最长正文
        best_text = ""
        for selector in CONTENT_SELECTORS:
            for el in soup.select(selector):
                text = el.get_text(separator="\n", strip=True)
                text = self._clean_chapter_text(text)
                if len(text) > len(best_text):
                    best_text = text

        # 5. 兜底：找所有<p>集合
        if len(best_text) < 200:
            ps = soup.find_all("p")
            if ps:
                lines = []
                for p in ps:
                    t = p.get_text(strip=True)
                    if len(t) > 5:
                        lines.append(t)
                combined = '\n\n'.join(lines)
                combined = self._clean_chapter_text(combined)
                if len(combined) > len(best_text):
                    best_text = combined

        # 6. 兜底：含<br>的长div
        if len(best_text) < 200:
            for div in soup.find_all("div"):
                brs = div.find_all("br")
                if len(brs) >= 2:
                    text = div.get_text(separator="\n", strip=True)
                    text = self._clean_chapter_text(text)
                    if len(text) > len(best_text):
                        best_text = text

        if len(best_text) < 50:
            return None

        content = ParsedContent()
        content.original_url = url
        content.title = page_title or expected_title
        content.author = author
        content.content_markdown = best_text
        content.content_html = f"<div>{best_text}</div>"
        content.content_length = len(best_text)
        content.platform = self._detect_platform(url)
        # 超过最小内容长度即视为有效（多章累积会更多）
        content.is_truncated = len(best_text) < config.MIN_CONTENT_LENGTH
        return content

    def _clean_chapter_text(self, text: str, expected_title: str = "") -> str:
        """清理正文中的噪声行"""
        lines = text.split('\n')
        cleaned = []
        found_content_start = False
        # 提取标题关键词用于过滤重复标题行
        title_words = set()
        if expected_title:
            for w in re.findall(r'[\u4e00-\u9fff]{2,}', expected_title):
                if len(w) >= 2:
                    title_words.add(w)

        for line in lines:
            line = line.strip()
            if not line:
                if cleaned and cleaned[-1] != '':
                    cleaned.append('')
                continue
            # 检查噪声模式
            is_noise = False
            for pat in NOISE_LINE_PATTERNS:
                if re.search(pat, line):
                    is_noise = True
                    break
            # 额外过滤：内容开始前的短行（标题、作者、字数等元数据）
            if not is_noise and not found_content_start:
                # 短行且不含句末标点，很可能是标题/元数据
                if len(line) < 20 and not re.search(r'[。！？…]', line):
                    # 如果是书名的一部分，也过滤
                    if line == expected_title or any(w in line and len(line) <= len(w) + 2 for w in title_words):
                        is_noise = True
                if len(line) >= 20 or re.search(r'[。！？]', line):
                    found_content_start = True
            if not is_noise:
                cleaned.append(line)
                if len(line) >= 20 or re.search(r'[。！？]', line):
                    found_content_start = True
        # 合并多余空行
        result = []
        prev_empty = False
        for line in cleaned:
            if line == '':
                if not prev_empty:
                    result.append('')
                prev_empty = True
            else:
                result.append(line)
                prev_empty = False
        return '\n\n'.join(result).strip()

    def _find_chapter_url(self, html: str, base_url: str) -> Optional[str]:
        """从目录页找到第一章正文链接"""
        soup = BeautifulSoup(html, "lxml")
        read_kws = ["立即阅读", "开始阅读", "点击阅读", "在线阅读", "全文阅读",
                    "免费阅读", "正文阅读", "开始看书", "第一章", "第1章"]

        # 1. 优先：找文本含"第一章/第1章"且URL看起来像章节的链接
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]
            if not href or href.startswith("#") or "javascript:" in href.lower():
                continue
            full = urljoin(base_url, href)
            if not full.startswith("http") or full == base_url:
                continue
            if text.startswith("第一章") or text.startswith("第1章") or text == "1":
                if urlparse(base_url).netloc in full:
                    return full

        # 2. 次优先：找URL模式看起来像章节的链接（-数字.html, /数字/, 等）
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if not href or href.startswith("#") or "javascript:" in href.lower():
                continue
            full = urljoin(base_url, href)
            if not full.startswith("http") or full == base_url:
                continue
            if self._looks_like_chapter_url(full, base_url) and urlparse(base_url).netloc in full:
                # 确保是第一章（URL中有1或链接文本是"1"）
                if re.search(r'[/_-]1(?:\.html?)?/?$', href) or text in ("1", "01", "第一章"):
                    return full

        # 3. 最后：找"立即阅读"类按钮
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            href = a["href"]
            if not href or href.startswith("#") or "javascript:" in href.lower():
                continue
            full = urljoin(base_url, href)
            if not full.startswith("http") or full == base_url:
                continue
            for kw in read_kws[:7]:
                if kw in text:
                    # 如果链接看起来是章节URL直接返回，否则也要返回（后续_resolve_chapter_url会处理）
                    return full

        # 4. 兜底：第一个数字.html链接
        for a in soup.find_all("a", href=True):
            href = a["href"]
            text = a.get_text(strip=True)
            if re.search(r'\d+\.html?$', href) and len(text) <= 40:
                full = urljoin(base_url, href)
                if urlparse(base_url).netloc in full and full != base_url:
                    return full
        return None

    def _find_next_chapter(self, html: str, base_url: str) -> Optional[str]:
        """找下一章链接"""
        soup = BeautifulSoup(html, "lxml")
        next_kws = ["下一章", "下一页", "下一页>", "下章", "next", ">", ">>"]
        for a in soup.find_all("a", href=True):
            text = a.get_text(strip=True)
            for kw in next_kws:
                if kw in text.lower() or text == kw:
                    href = a["href"]
                    if href and not href.startswith("#") and "javascript:" not in href.lower():
                        full = urljoin(base_url, href)
                        if full.startswith("http") and full != base_url:
                            # 防止链接到目录页
                            if "catalog" not in href.lower() and "mulu" not in href.lower() and "dir" not in href.lower():
                                return full
        return None

    def _detect_platform(self, url: str) -> str:
        domain = urlparse(url).netloc.lower()
        for site in NOVEL_REPOST_SITES:
            if site in domain:
                return site.split('.')[0]
        if "csdn.net" in domain: return "csdn"
        if "jianshu.com" in domain: return "jianshu"
        if "cnblogs.com" in domain: return "cnblogs"
        if "weixin" in domain: return "wechat"
        parts = domain.split('.')
        return parts[-2] if len(parts) >= 2 else "unknown"
