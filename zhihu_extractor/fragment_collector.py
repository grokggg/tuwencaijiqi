#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZCCSA 碎片搜集引擎 v1.0
从互联网边角料中挖掘和拼凑小说完整内容
"""
import subprocess, re, json, os, time
from urllib.parse import quote, urljoin, unquote
from bs4 import BeautifulSoup
from typing import List, Dict, Tuple
from difflib import SequenceMatcher

# ========== 配置 ==========
TARGET = {
    "title": "娇娇和她的忠犬小狗",
    "aliases": ["婚后一年老公从不碰我", "正想偷汉子时眼前飘过弹幕"],
    "characters": ["靳川", "孟娇蕊", "傅柏文", "娇娇"],
    "column": "边月忠犬",
    "article_id": "1979959692122943787",
}

UA_POOL = [
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
    'Mozilla/5.0 (iPad; CPU OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
]

OUTPUT_DIR = '/workspace/zhihu_extractor/output'
DATA_DIR = '/workspace/zhihu_extractor/data'
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(DATA_DIR, exist_ok=True)

# ========== HTTP工具 ==========
def curl(url: str, ua_idx: int = 0, timeout: int = 10, headers: dict = None, follow: bool = True) -> str:
    cmd = ['curl', '-s', '--max-time', str(timeout), '--compressed']
    if follow:
        cmd.append('-L')
    cmd.extend(['-A', UA_POOL[ua_idx % len(UA_POOL)]])
    if headers:
        for k, v in headers.items():
            cmd.extend(['-H', f'{k}: {v}'])
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 5)
        return r.stdout
    except:
        return ''

# ========== 文本工具 ==========
def cn_count(text: str) -> int:
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')

def is_valid_fragment(text: str) -> bool:
    """判断是否是有效的小说片段"""
    if not text or cn_count(text) < 15:
        return False
    # 必须包含至少一个主角名或特征
    has_char = any(c in text for c in TARGET["characters"])
    has_feature = any(f in text for f in ['弹幕', '【', '】', '媳妇', '男主', '女配', '下一章', '章节', '全文', '免费阅读'])
    # 排除明显的非内容
    exclude = ['搜索', '登录', '注册', '下载', 'APP', '广告', '关注', '点赞', '评论', 'copyright', 'Copyright']
    has_exclude = sum(1 for e in exclude if e in text) > 3
    return (has_char or has_feature) and not has_exclude

def clean_text(text: str) -> str:
    """清洗文本"""
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;|&lt;|&gt;|&amp;', ' ', text)
    text = re.sub(r'\s+', ' ', text)
    text = text.strip()
    return text

def similarity(a: str, b: str) -> float:
    """计算文本相似度"""
    return SequenceMatcher(None, a, b).ratio()

# ========== 搜集渠道 ==========
class FragmentCollector:
    def __init__(self):
        self.fragments = []  # {source, text, url, context, confidence}
        self.seen_texts = set()
        self.stats = {}

    def add_fragment(self, text: str, source: str, url: str = '', context: str = '', confidence: float = 0.5):
        """添加碎片（去重）"""
        text = clean_text(text)
        if not is_valid_fragment(text):
            return
        
        # 去重：检查是否与已有片段高度相似
        for existing in self.seen_texts:
            if similarity(text, existing) > 0.8:
                return
        
        self.seen_texts.add(text)
        self.fragments.append({
            "text": text,
            "source": source,
            "url": url,
            "context": context,
            "confidence": confidence,
            "cn_count": cn_count(text),
        })

    # ------ 搜索引擎渠道 ------
    def collect_from_bing(self):
        """必应搜索"""
        print('[必应] 开始搜集...')
        queries = [
            # 标题搜索
            f'"{TARGET["title"]}"',
            f'"{TARGET["title"]}" 全文',
            f'"{TARGET["title"]}" 阅读',
            f'"{TARGET["title"]}" 完结',
            f'"{TARGET["title"]}" 大结局',
            # 别名搜索
            f'"{TARGET["aliases"][0]}"',
            f'"{TARGET["aliases"][0]}" 全文',
            # 角色名+特征
            '"靳川" "孟娇蕊"',
            '"靳川" "孟娇蕊" 弹幕',
            '"靳川" "傅柏文"',
            # 独特短语（从搜索结果中发现的）
            '"孟娇蕊天天穿的骚里骚气"',
            '"人心不是铁做的" "靳川"',
            '"忠犬糙汉" "弹幕"',
            '"孟同志，你找我是有什么事吗"',
            '"你可知男主胯下是何等凶险之地"',
            # 论坛/讨论
            f'{TARGET["title"]} 读后感',
            f'{TARGET["title"]} 剧情',
            f'{TARGET["title"]} 结局',
            '靳川 孟娇蕊 后续',
        ]
        
        found = 0
        for q in queries:
            url = f'https://cn.bing.com/search?q={quote(q)}&count=20'
            html = curl(url, ua_idx=found, timeout=8)
            if not html or len(html) < 500:
                continue
            
            soup = BeautifulSoup(html, 'html.parser')
            for li in soup.select('li.b_algo'):
                a = li.find('a', href=True)
                if not a:
                    continue
                href = a['href']
                title = a.get_text(strip=True)
                snippet_div = li.find('div', class_='b_caption')
                snippet = snippet_div.get_text(separator=' ', strip=True) if snippet_div else ''
                
                # 从摘要中提取片段
                combined = title + ' ' + snippet
                if any(c in combined for c in TARGET["characters"]):
                    # 提取可能的内容片段
                    text_blocks = re.findall(r'[\u4e00-\u9fff，。！？、「」【】（）""~\.\,\?\!\s\w]{20,}', combined)
                    for block in text_blocks:
                        self.add_fragment(block, f"必应搜索摘要:{q[:20]}", href, title, 0.4)
                    found += 1
            
            time.sleep(0.3)
        
        self.stats['bing'] = found
        print(f'[必应] 搜集完成: {found}条相关结果')

    def collect_from_sogou(self):
        """搜狗搜索（网页+微信）"""
        print('[搜狗] 开始搜集...')
        queries = [
            TARGET["title"],
            f'{TARGET["title"]} 全文阅读',
            f'{TARGET["title"]} 大结局',
            '靳川 孟娇蕊 弹幕',
            TARGET["aliases"][0],
            '"孟娇蕊" "靳川"',
        ]
        
        found = 0
        for q in queries:
            # 搜狗微信
            url = f'https://weixin.sogou.com/weixin?type=2&query={quote(q)}'
            html = curl(url, ua_idx=1, timeout=10)
            if html and len(html) > 500:
                soup = BeautifulSoup(html, 'html.parser')
                for item in soup.select('div.txt-box, div.news-box, li'):
                    text = item.get_text(separator=' ', strip=True)
                    if any(c in text for c in TARGET["characters"]):
                        # 提取片段
                        blocks = re.findall(r'[\u4e00-\u9fff，。！？、「」【】（）""~\.\,\?\!\s]{15,}', text)
                        for block in blocks:
                            self.add_fragment(block, "搜狗微信", '', q[:30], 0.3)
                        found += 1
            
            # 搜狗网页
            url2 = f'https://www.sogou.com/web?query={quote(q)}'
            html2 = curl(url2, ua_idx=0, timeout=8)
            if html2 and len(html2) > 500:
                soup2 = BeautifulSoup(html2, 'html.parser')
                for item in soup2.select('div.vrwrap, div.rb, div.results'):
                    text = item.get_text(separator=' ', strip=True)
                    if any(c in text for c in TARGET["characters"]):
                        blocks = re.findall(r'[\u4e00-\u9fff，。！？、「」【】（）""~\.\,\?\!\s]{15,}', text)
                        for block in blocks:
                            self.add_fragment(block, "搜狗网页", '', q[:30], 0.3)
            
            time.sleep(0.5)
        
        self.stats['sogou'] = found
        print(f'[搜狗] 搜集完成: {found}条结果')

    # ------ 小说平台渠道 ------
    def collect_from_novel_sites(self):
        """系统性搜索小说站"""
        print('[小说站] 开始搜集...')
        
        # 大量小说站搜索URL
        sites = [
            # (搜索URL模板, 名称, 编码方式)
            ('https://www.biqubo.com/search.html?searchtype=novelname&searchkey={q}', 'biqubo', 'get'),
            ('https://www.biquge.lu/search.php?q={q}', 'biquge_lu', 'get'),
            ('https://www.biquwx.la/search.php?q={q}', 'biquwx', 'get'),
            ('https://www.xbiquge.la/modules/article/waps.php?searchkey={q}', 'xbiquge_la', 'get'),
            ('https://www.biqubao.com/search.php?q={q}', 'biqubao', 'get'),
            ('https://www.81zw.com/search.php?q={q}', '81zw', 'get'),
            ('https://www.88dus.com/search.php?q={q}', '88dus', 'get'),
            ('https://www.bqg5200.com/search.php?q={q}', 'bqg5200', 'get'),
            ('https://www.syzgl.com/search/?q={q}', 'syzgl', 'get'),
            ('https://www.ddxsku.com/search.php?q={q}', 'ddxsku', 'get'),
            ('https://www.lwxs99.cc/search.php?q={q}', 'lwxs99', 'get'),
            ('https://www.shubaow.net/search.php?q={q}', 'shubaow', 'get'),
            ('https://www.qb5.tw/search.php?q={q}', 'qb5', 'get'),
            ('https://www.23usp.com/search.php?q={q}', '23usp', 'get'),
            ('https://www.txt99.org/search.php?q={q}', 'txt99', 'get'),
            ('https://www.ibiquges.info/search.php?q={q}', 'ibiquges', 'get'),
            ('https://www.xbiquge.bz/search.php?q={q}', 'xbiquge_bz', 'get'),
            ('https://www.biqugex.com/search.php?q={q}', 'biqugex', 'get'),
            ('https://www.biquge.co/search.php?q={q}', 'biquge_co', 'get'),
            ('https://www.biqukan.la/search.php?q={q}', 'biqukan', 'get'),
            ('https://www.xsbiquge.com/search.php?q={q}', 'xsbiquge', 'get'),
            ('https://www.beqege.cc/search.php?q={q}', 'beqege', 'get'),
            ('https://www.bqgui.cc/search.php?q={q}', 'bqgui', 'get'),
            ('https://www.shuquge.com/search.php?q={q}', 'shuquge', 'get'),
            ('https://www.630la.com/search.php?q={q}', '630la', 'get'),
            # 移动端
            ('https://m.biqubo.com/search.html?searchtype=novelname&searchkey={q}', 'm_biqubo', 'get'),
            ('https://m.beqege.cc/search.php?q={q}', 'm_beqege', 'get'),
        ]
        
        found = 0
        queries = [TARGET["title"], TARGET["aliases"][0]]
        
        for base_url, site_name, method in sites:
            for q in queries[:1]:  # 只用主标题搜索
                url = base_url.format(q=quote(q))
                html = curl(url, ua_idx=0 if not site_name.startswith('m_') else 1, timeout=6)
                if not html or len(html) < 500:
                    continue
                
                if any(c in html for c in TARGET["characters"]) or '娇娇' in html:
                    # 找到目标！尝试提取内容
                    soup = BeautifulSoup(html, 'html.parser')
                    for a in soup.find_all('a', href=True):
                        text = a.get_text(strip=True)
                        href = a['href']
                        if any(kw in text for kw in ['娇娇', '忠犬', '靳川', '孟娇蕊', '婚后一年']):
                            full_url = urljoin(url, href)
                            # 访问该页面
                            ch_html = curl(full_url, ua_idx=0, timeout=8)
                            if ch_html:
                                # 提取章节列表
                                ch_soup = BeautifulSoup(ch_html, 'html.parser')
                                # 找章节链接
                                chapter_links = []
                                for ch_a in ch_soup.find_all('a', href=True):
                                    ch_text = ch_a.get_text(strip=True)
                                    ch_href = ch_a['href']
                                    if re.search(r'第[0-9一二三四五六七八九十百千]+[章节回]', ch_text):
                                        ch_full = urljoin(full_url, ch_href)
                                        chapter_links.append((ch_text, ch_full))
                                
                                if chapter_links:
                                    print(f'  [{site_name}] 找到{len(chapter_links)}章!')
                                    # 访问前几章提取内容
                                    for ch_title, ch_url in chapter_links[:10]:
                                        content_html = curl(ch_url, ua_idx=0, timeout=8)
                                        if content_html:
                                            content_soup = BeautifulSoup(content_html, 'html.parser')
                                            # 找正文
                                            for selector in ['#content', '.content', '#chaptercontent', '.chapter-content', '#booktext', '#nr1']:
                                                content_div = content_soup.select_one(selector)
                                                if content_div:
                                                    content_text = content_div.get_text(separator='\n', strip=True)
                                                    if cn_count(content_text) > 50:
                                                        self.add_fragment(content_text, f'小说站:{site_name}', ch_url, ch_title, 0.9)
                                                        found += 1
                                                        break
                                else:
                                    # 直接提取页面内容
                                    content_text = ''
                                    for selector in ['#content', '.content', '#chaptercontent', '.chapter-content']:
                                        div = ch_soup.select_one(selector)
                                        if div:
                                            content_text = div.get_text(separator='\n', strip=True)
                                            break
                                    if cn_count(content_text) > 50:
                                        self.add_fragment(content_text, f'小说站:{site_name}', full_url, text, 0.8)
                                        found += 1
                time.sleep(0.2)
        
        self.stats['novel_sites'] = found
        print(f'[小说站] 搜集完成: {found}条内容')

    # ------ 论坛/社交平台 ------
    def collect_from_forums(self):
        """论坛和社交平台"""
        print('[论坛/社交] 开始搜集...')
        found = 0
        
        # 百度贴吧搜索
        print('  [贴吧] ...')
        for q in [TARGET["title"], f'{TARGET["title"]} 知乎', '靳川 孟娇蕊']:
            url = f'https://tieba.baidu.com/f/search/res?ie=utf-8&qw={quote(q)}'
            html = curl(url, ua_idx=0, timeout=8)
            if html and len(html) > 500:
                soup = BeautifulSoup(html, 'html.parser')
                for item in soup.select('div.s_post, div.search-result-item'):
                    text = item.get_text(separator=' ', strip=True)
                    if any(c in text for c in TARGET["characters"]):
                        blocks = re.findall(r'[\u4e00-\u9fff，。！？、「」【】（）""~\.\,\?\!\s]{20,}', text)
                        for block in blocks:
                            self.add_fragment(block, "百度贴吧", url, q[:30], 0.3)
                            found += 1
        
        # 豆瓣搜索
        print('  [豆瓣] ...')
        for q in [TARGET["title"], '靳川 孟娇蕊 小说']:
            url = f'https://www.douban.com/search?q={quote(q)}'
            html = curl(url, ua_idx=0, timeout=8, headers={'Referer': 'https://www.douban.com/'})
            if html and len(html) > 500:
                soup = BeautifulSoup(html, 'html.parser')
                for item in soup.select('div.result, div.content'):
                    text = item.get_text(separator=' ', strip=True)
                    if any(c in text for c in TARGET["characters"]):
                        blocks = re.findall(r'[\u4e00-\u9fff，。！？、「」【】（）""~\.\,\?\!\s]{20,}', text)
                        for block in blocks:
                            self.add_fragment(block, "豆瓣", url, q[:30], 0.3)
                            found += 1
        
        # 微博搜索（通过sina搜索）
        print('  [微博] ...')
        for q in [TARGET["title"], '靳川 孟娇蕊']:
            url = f'https://s.weibo.com/weibo?q={quote(q)}'
            html = curl(url, ua_idx=0, timeout=8)
            if html and len(html) > 500:
                soup = BeautifulSoup(html, 'html.parser')
                for item in soup.select('div.card-wrap, div[action-type="feed_list_item"]'):
                    text = item.get_text(separator=' ', strip=True)
                    if any(c in text for c in TARGET["characters"]):
                        blocks = re.findall(r'[\u4e00-\u9fff，。！？、「」【】（）""~\.\,\?\!\s]{20,}', text)
                        for block in blocks:
                            self.add_fragment(block, "微博", url, q[:30], 0.2)
                            found += 1
        
        self.stats['forums'] = found
        print(f'[论坛/社交] 搜集完成: {found}条结果')

    # ------ 扩展搜索 ------
    def collect_from_360(self):
        """360搜索"""
        print('[360搜索] 开始搜集...')
        queries = [
            f'"{TARGET["title"]}"',
            '"靳川" "孟娇蕊"',
            f'{TARGET["aliases"][0]} 全文',
        ]
        found = 0
        for q in queries:
            url = f'https://www.so.com/s?q={quote(q)}'
            html = curl(url, ua_idx=0, timeout=8)
            if html:
                soup = BeautifulSoup(html, 'html.parser')
                for li in soup.select('li.res-list, div.res-item'):
                    text = li.get_text(separator=' ', strip=True)
                    if any(c in text for c in TARGET["characters"]):
                        blocks = re.findall(r'[\u4e00-\u9fff，。！？、「」【】（）""~\.\,\?\!\s]{20,}', text)
                        for block in blocks:
                            self.add_fragment(block, "360搜索", url, q[:30], 0.3)
                            found += 1
        self.stats['360'] = found
        print(f'[360搜索] 搜集完成: {found}条')

    def collect_from_baidu(self):
        """百度搜索"""
        print('[百度] 开始搜集...')
        queries = [
            f'"{TARGET["title"]}"',
            f'"{TARGET["title"]}" 全文 阅读',
            '"靳川" "孟娇蕊"',
            f'{TARGET["aliases"][0]} 完结',
        ]
        found = 0
        for q in queries:
            url = f'https://www.baidu.com/s?wd={quote(q)}'
            html = curl(url, ua_idx=0, timeout=10, headers={'Accept-Language': 'zh-CN,zh;q=0.9'})
            if html and len(html) > 500:
                soup = BeautifulSoup(html, 'html.parser')
                for div in soup.select('div.result, div.c-container'):
                    text = div.get_text(separator=' ', strip=True)
                    if any(c in text for c in TARGET["characters"]):
                        blocks = re.findall(r'[\u4e00-\u9fff，。！？、「」【】（）""~\.\,\?\!\s]{20,}', text)
                        for block in blocks:
                            self.add_fragment(block, "百度搜索", url, q[:30], 0.3)
                            found += 1
        self.stats['baidu'] = found
        print(f'[百度] 搜集完成: {found}条')

    def run_all(self):
        """运行所有搜集渠道"""
        print('=' * 60)
        print('ZCCSA 碎片搜集引擎 v1.0 - 搬仓行动开始')
        print('=' * 60)
        
        self.collect_from_bing()
        self.collect_from_sogou()
        self.collect_from_360()
        self.collect_from_baidu()
        self.collect_from_novel_sites()
        self.collect_from_forums()
        
        print('\n' + '=' * 60)
        print(f'搜集完成! 共获得 {len(self.fragments)} 个碎片')
        print(f'各渠道统计: {self.stats}')
        total_cn = sum(f['cn_count'] for f in self.fragments)
        print(f'碎片总字数: {total_cn}')
        print('=' * 60)
        
        # 保存碎片
        self.save()
        return self.fragments

    def save(self):
        """保存碎片到文件"""
        path = os.path.join(DATA_DIR, 'fragments.json')
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self.fragments, f, ensure_ascii=False, indent=2)
        print(f'碎片已保存: {path}')


# ========== 内容拼凑引擎 ==========
class ContentAssembler:
    def __init__(self, known_content_path: str, fragments: List[Dict]):
        self.known_content = open(known_content_path, 'r', encoding='utf-8').read() if os.path.exists(known_content_path) else ''
        self.fragments = fragments
        self.new_content = []  # 不在已知内容中的新片段
    
    def analyze(self):
        """分析碎片，区分已知内容和新内容"""
        print('\n[拼凑引擎] 开始分析碎片...')
        
        for frag in self.fragments:
            text = frag['text']
            # 检查是否在已知内容中
            if text in self.known_content:
                continue
            
            # 检查是否包含已知内容的子串
            is_known = False
            for known_sent in re.findall(r'[\u4e00-\u9fff，。！？、]{10,}', self.known_content):
                if known_sent in text and len(known_sent) > 10:
                    is_known = True
                    break
            
            if not is_known:
                # 这是新内容！
                self.new_content.append(frag)
        
        print(f'[拼凑引擎] 发现 {len(self.new_content)} 个新碎片（不在已知5章中）')
        total_new_cn = sum(f['cn_count'] for f in self.new_content)
        print(f'[拼凑引擎] 新内容总字数: {total_new_cn}')
        
        return self.new_content
    
    def assemble(self) -> str:
        """拼凑最终版本"""
        # 按置信度排序
        self.new_content.sort(key=lambda x: x['confidence'], reverse=True)
        
        lines = []
        lines.append('# 《娇娇和她的忠犬小狗》')
        lines.append('')
        lines.append('## 说明')
        lines.append('')
        lines.append(f'- 基础版本: kepue.com获取的5章完整内容')
        lines.append(f'- 额外碎片: {len(self.new_content)}个碎片，来自搜索引擎摘要、社交平台讨论等公开渠道')
        lines.append('- 注意: 碎片内容可能包含推广文案、读者评论等非原文内容，已尽量筛选')
        lines.append('')
        lines.append('---')
        lines.append('')
        
        # 已知的5章内容
        # 提取已有章节
        known_chapters = self._extract_known_chapters()
        for ch_title, ch_content in known_chapters:
            lines.append(f'## {ch_title}')
            lines.append('')
            lines.append(ch_content)
            lines.append('')
        
        # 新发现的碎片
        if self.new_content:
            lines.append('## 搜集到的额外内容碎片')
            lines.append('')
            lines.append('以下内容来自搜索引擎摘要、社交平台讨论、公众号推广等公开渠道，')
            lines.append('可能包含正文之外的推广文案、剧情讨论等，仅供参考。')
            lines.append('')
            
            # 去重并展示
            seen = set()
            for i, frag in enumerate(self.new_content, 1):
                text = frag['text']
                # 再次去重
                if text in seen:
                    continue
                seen.add(text)
                
                # 过滤掉太短或太像广告的
                if frag['cn_count'] < 20:
                    continue
                
                source = frag['source']
                context = frag['context']
                confidence = frag['confidence']
                
                # 跳过明显的广告/搜索摘要
                if any(kw in text for kw in ['搜索结果', '百度为您找到', '为您推荐', '下载APP', '扫码']):
                    continue
                
                lines.append(f'### 碎片 {i} (来源: {source}, 置信度: {confidence:.1f})')
                if context:
                    lines.append(f'上下文: {context}')
                lines.append('')
                lines.append(f'> {text}')
                lines.append('')
        
        return '\n'.join(lines)
    
    def _extract_known_chapters(self) -> List[Tuple[str, str]]:
        """从已知内容中提取章节"""
        chapters = []
        
        # 读取已知的5章完整内容
        known_path = '/workspace/娇娇和她的忠犬小狗_v2.md'
        if os.path.exists(known_path):
            content = open(known_path, 'r', encoding='utf-8').read()
            # 按章节分割
            parts = re.split(r'## 第(\d+)章', content)
            if len(parts) > 1:
                for i in range(1, len(parts), 2):
                    ch_num = parts[i]
                    ch_content = parts[i+1] if i+1 < len(parts) else ''
                    # 清理章节内容
                    ch_content = re.sub(r'## 补充内容.*$', '', ch_content, flags=re.DOTALL)
                    ch_content = re.sub(r'## 搜索发现.*$', '', ch_content, flags=re.DOTALL)
                    ch_content = ch_content.strip()
                    chapters.append((f'第{ch_num}章', ch_content))
        
        if not chapters:
            # 回退：直接从kepue获取
            chapters = self._fetch_kepue_chapters()
        
        return chapters
    
    def _fetch_kepue_chapters(self) -> List[Tuple[str, str]]:
        """从kepue获取5章"""
        chapters = []
        for ch in range(1, 6):
            url = f'https://m.kepue.com/nvpin/38738/{ch}/'
            html = curl(url, ua_idx=1, timeout=10)
            if html:
                soup = BeautifulSoup(html, 'html.parser')
                div = soup.select_one('#pContainer')
                if div:
                    paras = [p.get_text(strip=True) for p in div.find_all('p') if p.get_text(strip=True)]
                    content = '\n\n'.join(paras)
                    chapters.append((f'第{ch}章', content))
        return chapters
    
    def save_assembled(self, content: str):
        """保存拼凑结果"""
        path = os.path.join(OUTPUT_DIR, '娇娇和她的忠犬小狗_拼凑完整版.md')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f'[拼凑引擎] 最终版本已保存: {path}')
        return path


# ========== 主入口 ==========
if __name__ == '__main__':
    # 1. 搜集碎片
    collector = FragmentCollector()
    fragments = collector.run_all()
    
    # 2. 拼凑内容
    assembler = ContentAssembler(
        '/workspace/娇娇和她的忠犬小狗_v2.md',
        fragments
    )
    new_frags = assembler.analyze()
    final_content = assembler.assemble()
    output_path = assembler.save_assembled(final_content)
    
    # 3. 打印摘要
    print('\n' + '=' * 60)
    print('搬仓行动总结')
    print('=' * 60)
    print(f'已知章节: 5章 (kepue.com)')
    print(f'搜集碎片: {len(fragments)} 个')
    print(f'新发现碎片: {len(new_frags)} 个')
    print(f'新内容字数: 约{sum(f["cn_count"] for f in new_frags)}字')
    print(f'输出文件: {output_path}')
