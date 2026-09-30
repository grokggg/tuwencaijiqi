#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
小说站深度扫描引擎
系统性扫描大量小说站，寻找完整版内容
"""
import subprocess
import re
import json
import time
import os
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup

def curl(url, ua=None, timeout=12, retries=2):
    for attempt in range(retries):
        cmd = ['curl', '-s', '-L', '--max-time', str(timeout), '--compressed']
        if ua:
            cmd.extend(['-A', ua])
        cmd.append(url)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
            if result.stdout and len(result.stdout) > 300:
                return result.stdout
        except:
            pass
        if attempt < retries - 1:
            time.sleep(1)
    return ''

UA_DESKTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
UA_MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'

# 小说站列表 - 包含搜索URL模式和内容提取规则
NOVEL_SITES = [
    # 站点名, 搜索URL模式, 结果选择器, 章节页内容选择器
    ('笔趣阁5200', 'https://www.biquge5200.com/search.php?q=', 
     '.result-item .result-game-item-title a, .search-list li a', 
     '#content, .content'),
    ('笔趣阁', 'https://www.biqukan.la/search.php?q=',
     'ul li a', '#content'),
    ('新笔趣阁', 'https://www.xsbiquge.com/search.php?q=',
     '.result-list .result-item a', '#content'),
    ('笔趣阁', 'https://www.beqege.cc/search.php?q=',
     '.search-list a, ul li a', '#content'),
    ('书趣阁', 'https://www.shuquge.com/search.php?q=',
     '.search-list a, ul li a', '#content'),
    ('630小说', 'https://www.630la.com/search.php?q=',
     'ul li a, .search-result a', '#content'),
    ('23小说', 'https://www.23usp.com/search.php?q=',
     'ul li a, .search-result a', '#content'),
    ('txt99', 'https://www.txt99.org/search.php?q=',
     'ul li a, .search-result a', '#content'),
    ('xbiquge', 'https://www.xbiquge.bz/search.php?q=',
     'ul li a, .result a', '#content'),
    ('笔趣阁x', 'https://www.biqugex.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('全本小说', 'https://www.qb5.tw/search.php?q=',
     'ul li a, .result a', '#content'),
    ('书宝网', 'https://www.shubaow.net/search.php?q=',
     'ul li a, .result a', '#content'),
    # 移动端
    ('m.biquge5200', 'https://m.biquge5200.com/search.php?q=',
     'ul li a, .list a', '#content, .content'),
    ('m.beqege', 'https://m.beqege.cc/search.php?q=',
     'ul li a, .list a', '#content, .content'),
    # 其他类型站点
    ('科普小说', 'https://m.kepue.com/search.php?q=',
     'ul li a, .list a', '#pContainer, .content'),
    ('随意阅读', 'https://www.syzgly.com/search?q=',
     'ul li a, .list a', '#content, .content'),
    ('花语书阁', 'https://www.husiyu.com/search.php?q=',
     'ul li a, .list a', '#content, .content'),
    # 更多站
    ('biquge.lu', 'https://www.biquge.lu/search.php?q=',
     'ul li a, .result a', '#content'),
    ('lwxs99', 'https://www.lwxs99.cc/search.php?q=',
     'ul li a, .result a', '#content'),
    ('biquwx', 'https://www.biquwx.la/search.php?q=',
     'ul li a, .result a', '#content'),
    ('81中文', 'https://www.81zw.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('69书', 'https://www.69shu.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('biquges', 'https://www.biquges.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('88读书', 'https://www.88dus.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('xbiquwx', 'https://www.xbiquwx.la/search.php?q=',
     'ul li a, .result a', '#content'),
    ('新笔趣阁xx', 'https://www.xxbiquge.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('一品侠', 'https://www.shumilou.co/search.php?q=',
     'ul li a, .result a', '#content'),
    ('棉花糖', 'https://www.mianhuatang.la/search.php?q=',
     'ul li a, .result a', '#content'),
    ('顶点小说', 'https://www.dingdiann.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('万本', 'https://www.wanbentxt.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('乐文', 'https://www.lewenn.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('千千', 'https://www.qqxsw.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('八一中文', 'https://www.81zw.net/search.php?q=',
     'ul li a, .result a', '#content'),
    ('看书啦', 'https://www.kanunu8.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('奇书网', 'https://www.qisuu.la/search.php?q=',
     'ul li a, .result a', '#content'),
    ('飘天', 'https://www.piaotia.com/search.php?q=',
     'ul li a, .result a', '#content'),
    ('思路客', 'https://www.siluke.tw/search.php?q=',
     'ul li a, .result a', '#content'),
    ('言情后花园', 'https://www.yqxsge.cc/search.php?q=',
     'ul li a, .result a', '#content'),
    ('小说阅读网', 'https://www.readnovel.com/search?keyword=',
     'ul li a, .result a', '#content, .content'),
    ('17k', 'https://search.17k.com/search.xhtml?c.q=',
     'ul li a, .result a', '#content, .content'),
    ('纵横中文', 'https://search.zongheng.com/s?keyword=',
     'ul li a, .result a', '#content, .content'),
]


class NovelSiteScanner:
    """小说站深度扫描器"""
    
    def __init__(self, output_dir='output'):
        self.output_dir = output_dir
        self.found_sites = []
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs('data/novel_sites', exist_ok=True)
    
    def check_site_alive(self, search_url):
        """检查站点是否存活"""
        domain = search_url.split('/')[2]
        cmd = ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', 
               '--max-time', '5', f'https://{domain}']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
            code = result.stdout.strip()
            return code not in ['000', '0', '']
        except:
            return False
    
    def search_site(self, site_info, query):
        """在单个站点搜索"""
        site_name, search_url_pattern, result_selector, content_selector = site_info
        search_url = search_url_pattern + quote(query)
        
        html = curl(search_url, ua=UA_DESKTOP, timeout=10)
        if not html:
            # 尝试移动端UA
            html = curl(search_url, ua=UA_MOBILE, timeout=10)
        
        if not html:
            return None
        
        # 保存原始HTML用于调试
        safe_name = re.sub(r'[^\w]', '_', site_name)
        with open(f'data/novel_sites/{safe_name}_search.html', 'w', encoding='utf-8') as f:
            f.write(html)
        
        soup = BeautifulSoup(html, 'html.parser')
        
        # 检查页面是否包含目标内容关键词
        page_text = soup.get_text()
        if not any(kw in page_text for kw in ['靳川', '娇娇', '忠犬', '婚后一年', '公狗腰', '弹幕']):
            # 可能是搜索结果页但没有匹配，或者格式不对
            pass
        
        # 尝试多种方式找结果链接
        results = []
        
        # 方法1: 使用指定选择器
        for selector in result_selector.split(', '):
            try:
                items = soup.select(selector)
                for a in items:
                    href = a.get('href', '')
                    text = a.get_text(strip=True)
                    if href and text and len(text) > 3:
                        if href.startswith('/'):
                            base = '/'.join(search_url.split('/')[:3])
                            href = base + href
                        elif not href.startswith('http'):
                            href = urljoin(search_url, href)
                        results.append({'title': text, 'url': href})
            except:
                pass
        
        # 方法2: 找所有包含关键词的链接
        if not results:
            for a in soup.find_all('a', href=True):
                text = a.get_text(strip=True)
                href = a['href']
                if len(text) > 4 and any(kw in text for kw in ['娇娇', '忠犬', '靳川', '婚后一年', '老公']):
                    if href.startswith('/'):
                        base = '/'.join(search_url.split('/')[:3])
                        href = base + href
                    elif not href.startswith('http'):
                        href = urljoin(search_url, href)
                    results.append({'title': text, 'url': href})
        
        if not results:
            return None
        
        # 检查每个结果的相关性
        relevant = []
        for r in results[:5]:  # 只检查前5个
            try:
                chapter_html = curl(r['url'], ua=UA_DESKTOP, timeout=8)
                if not chapter_html:
                    chapter_html = curl(r['url'], ua=UA_MOBILE, timeout=8)
                
                if chapter_html and ('靳川' in chapter_html or '公狗腰' in chapter_html or '弹幕' in chapter_html):
                    # 提取内容
                    ch_soup = BeautifulSoup(chapter_html, 'html.parser')
                    
                    # 找章节列表
                    chapters = []
                    for a in ch_soup.find_all('a', href=True):
                        text = a.get_text(strip=True)
                        href = a['href']
                        if re.search(r'第[0-9一二三四五六七八九十百千]+[章节回]', text):
                            if href.startswith('/'):
                                base = '/'.join(r['url'].split('/')[:3])
                                href = base + href
                            elif not href.startswith('http'):
                                href = urljoin(r['url'], href)
                            chapters.append({'title': text, 'url': href})
                    
                    # 提取正文
                    content = ''
                    for sel in content_selector.split(', '):
                        elem = ch_soup.select_one(sel)
                        if elem:
                            content = elem.get_text(strip=True)
                            break
                    
                    cn_count = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
                    
                    relevant.append({
                        'site': site_name,
                        'book_title': r['title'],
                        'book_url': r['url'],
                        'chapters_found': len(chapters),
                        'chapter_list': chapters[:20],  # 只保存前20章
                        'content_preview': content[:200],
                        'content_cn_chars': cn_count,
                        'has_jinchuan': '靳川' in chapter_html,
                        'has_danmu': '弹幕' in chapter_html,
                        'has_gonggouyao': '公狗腰' in chapter_html,
                    })
            except:
                pass
            
            time.sleep(0.3)
        
        return relevant if relevant else None
    
    def scan_all_sites(self, queries):
        """扫描所有站点"""
        results = []
        
        for query in queries:
            print(f'\n搜索关键词: {query}')
            
            for i, site in enumerate(NOVEL_SITES):
                site_name = site[0]
                print(f'  [{i+1}/{len(NOVEL_SITES)}] {site_name}...', end=' ')
                
                try:
                    result = self.search_site(site, query)
                    if result:
                        print(f'找到 {len(result)} 个匹配!')
                        for r in result:
                            print(f'    - {r["book_title"][:30]} ({r["chapters_found"]}章)')
                        results.extend(result)
                    else:
                        print('无匹配')
                except Exception as e:
                    print(f'出错: {e}')
                
                time.sleep(0.2)
        
        # 保存结果
        with open(f'{self.output_dir}/novel_site_results.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        return results


if __name__ == '__main__':
    scanner = NovelSiteScanner(output_dir='output')
    
    # 搜索关键词（按优先级排序）
    queries = [
        '婚后一年老公从不碰我',
        '娇娇和她的忠犬小狗',
        '靳川 孟娇蕊',
        '边月忠犬',
    ]
    
    print(f'开始扫描 {len(NOVEL_SITES)} 个小说站...')
    results = scanner.scan_all_sites(queries)
    
    print(f'\n{"="*50}')
    print(f'扫描完成! 找到 {len(results)} 个相关结果')
    
    # 按章节数排序
    results.sort(key=lambda x: x['chapters_found'], reverse=True)
    
    for i, r in enumerate(results[:20]):
        print(f'\n{i+1}. [{r["site"]}] {r["book_title"]}')
        print(f'   章节数: {r["chapters_found"]}, 字数: {r["content_cn_chars"]}')
        print(f'   URL: {r["book_url"]}')
        print(f'   靳川: {r["has_jinchuan"]}, 弹幕: {r["has_danmu"]}, 公狗腰: {r["has_gonggouyao"]}')
