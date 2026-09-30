#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
社交平台与社区搜索
微博、小红书、豆瓣、贴吧、知乎专栏等
"""
import subprocess
import re
import json
import time
import os
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup

def curl(url, ua=None, timeout=12, retries=2, headers=None):
    for attempt in range(retries):
        cmd = ['curl', '-s', '-L', '--max-time', str(timeout), '--compressed']
        if ua:
            cmd.extend(['-A', ua])
        if headers:
            for k, v in headers.items():
                cmd.extend(['-H', f'{k}: {v}'])
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

def search_weibo(keyword):
    """微博搜索"""
    results = []
    url = f'https://s.weibo.com/weibo?q={quote(keyword)}'
    headers = {
        'Referer': 'https://weibo.com/',
        'Accept': 'text/html,application/xhtml+xml'
    }
    html = curl(url, ua=UA_DESKTOP, timeout=12, headers=headers)
    if not html:
        return results
    
    soup = BeautifulSoup(html, 'html.parser')
    # 微博的内容在card-wrap里
    for card in soup.select('.card-wrap, .card'):
        content_elem = card.select_one('.txt, .content, .weibo-text')
        if content_elem:
            text = content_elem.get_text(strip=True)
            if len(text) > 20:
                results.append({'content': text[:300], 'source': 'weibo'})
    
    return results

def search_douban(keyword):
    """豆瓣搜索"""
    results = []
    # 豆瓣小组搜索
    url = f'https://www.douban.com/search?q={quote(keyword)}&cat=1013'
    html = curl(url, ua=UA_DESKTOP, timeout=12)
    if not html:
        return results
    
    soup = BeautifulSoup(html, 'html.parser')
    for result in soup.select('.result, .search-result'):
        title_elem = result.select_one('h3 a, .title a')
        content_elem = result.select_one('.content, .desc')
        if title_elem:
            title = title_elem.get_text(strip=True)
            href = title_elem.get('href', '')
            content = content_elem.get_text(strip=True) if content_elem else ''
            if any(kw in title + content for kw in ['靳川', '娇娇', '忠犬', '公狗腰']):
                results.append({
                    'title': title, 
                    'url': href, 
                    'content': content[:200],
                    'source': 'douban'
                })
    
    return results

def search_tieba(keyword):
    """百度贴吧搜索"""
    results = []
    url = f'https://tieba.baidu.com/f/search/res?ie=utf-8&qw={quote(keyword)}'
    html = curl(url, ua=UA_DESKTOP, timeout=12)
    if not html:
        return results
    
    soup = BeautifulSoup(html, 'html.parser')
    for post in soup.select('.s_post, .post'):
        title_elem = post.select_one('.p_title a, .title a')
        content_elem = post.select_one('.p_content, .content')
        if title_elem:
            title = title_elem.get_text(strip=True)
            href = title_elem.get('href', '')
            if href.startswith('/'):
                href = 'https://tieba.baidu.com' + href
            content = content_elem.get_text(strip=True) if content_elem else ''
            results.append({
                'title': title,
                'url': href,
                'content': content[:200],
                'source': 'tieba'
            })
    
    return results

def search_zhihu_col(keyword):
    """知乎专栏搜索"""
    results = []
    url = f'https://zhuanlan.zhihu.com/search?q={quote(keyword)}'
    html = curl(url, ua=UA_DESKTOP, timeout=12)
    if not html:
        return results
    
    if '靳川' in html or '娇娇' in html or '忠犬' in html:
        soup = BeautifulSoup(html, 'html.parser')
        for article in soup.select('.ArticleItem, .ContentItem'):
            title_elem = article.select_one('h2 a, .title a, a')
            if title_elem:
                title = title_elem.get_text(strip=True)
                href = title_elem.get('href', '')
                if href.startswith('/'):
                    href = 'https://zhuanlan.zhihu.com' + href
                results.append({
                    'title': title,
                    'url': href,
                    'source': 'zhihu_col'
                })
    
    return results

def search_xiaohongshu(keyword):
    """小红书搜索（尝试）"""
    results = []
    # 小红书网页版搜索
    url = f'https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}'
    html = curl(url, ua=UA_MOBILE, timeout=12)
    if html and ('靳川' in html or '娇娇' in html):
        results.append({'note': '小红书有相关内容', 'source': 'xiaohongshu'})
    return results

def search_jianshu(keyword):
    """简书搜索"""
    results = []
    url = f'https://www.jianshu.com/search?q={quote(keyword)}&page=1&type=note'
    html = curl(url, ua=UA_DESKTOP, timeout=12)
    if not html:
        return results
    
    soup = BeautifulSoup(html, 'html.parser')
    for item in soup.select('.note-list li, .content'):
        title_elem = item.select_one('.title a, a.title')
        if title_elem:
            title = title_elem.get_text(strip=True)
            href = title_elem.get('href', '')
            if href.startswith('/'):
                href = 'https://www.jianshu.com' + href
            if any(kw in title for kw in ['娇娇', '忠犬', '靳川']):
                results.append({
                    'title': title,
                    'url': href,
                    'source': 'jianshu'
                })
    
    return results

def search_short_novel_sites(keyword):
    """短篇言情小说站搜索"""
    results = []
    
    sites = [
        ('花语书阁', f'https://www.husiyu.com/search.php?q={quote(keyword)}'),
        ('随意阅读', f'https://www.syzgly.com/search?q={quote(keyword)}'),
        ('千读网', f'https://www.qianduw.com/search.php?q={quote(keyword)}'),
        ('夜读阁', f'https://www.yeduge.com/search.php?q={quote(keyword)}'),
        ('清欢网', f'https://www.qinghuan.com/search.php?q={quote(keyword)}'),
        ('乐文小说', f'https://www.lewenn.com/search.php?q={quote(keyword)}'),
        ('千千小说', f'https://www.qqxsw.com/search.php?q={quote(keyword)}'),
        ('言情后花园', f'https://www.yqxsge.cc/search.php?q={quote(keyword)}'),
        ('米趣小说', f'https://www.miquge.com/search.php?q={quote(keyword)}'),
        ('一品侠', f'https://www.shumilou.co/search.php?q={quote(keyword)}'),
        ('笔趣阁', f'https://www.biquge5200.com/search.php?q={quote(keyword)}'),
        ('新笔趣阁', f'https://www.xsbiquge.com/search.php?q={quote(keyword)}'),
        ('全本小说', f'https://www.qb5.tw/search.php?q={quote(keyword)}'),
    ]
    
    for site_name, search_url in sites:
        html = curl(search_url, ua=UA_DESKTOP, timeout=8)
        if not html:
            html = curl(search_url, ua=UA_MOBILE, timeout=8)
        
        if html and ('靳川' in html or '公狗腰' in html or '弹幕' in html):
            print(f'  ✓ {site_name}: 找到相关内容!')
            soup = BeautifulSoup(html, 'html.parser')
            
            # 找书籍链接
            for a in soup.find_all('a', href=True):
                text = a.get_text(strip=True)
                href = a['href']
                if len(text) > 4 and any(kw in text for kw in ['娇娇', '忠犬', '婚后一年', '靳川']):
                    if href.startswith('/'):
                        base = '/'.join(search_url.split('/')[:3])
                        href = base + href
                    elif not href.startswith('http'):
                        href = urljoin(search_url, href)
                    
                    results.append({
                        'site': site_name,
                        'title': text,
                        'url': href,
                        'source': 'short_novel'
                    })
                    break  # 只取第一个结果
        else:
            print(f'  ✗ {site_name}')
        
        time.sleep(0.3)
    
    return results


if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    os.makedirs('output', exist_ok=True)
    
    all_results = []
    
    queries = [
        '婚后一年老公从不碰我',
        '娇娇和她的忠犬小狗',
        '靳川 孟娇蕊',
    ]
    
    # 短篇言情小说站搜索
    print('=== 短篇言情小说站搜索 ===')
    for q in queries:
        print(f'\n搜索: {q}')
        results = search_short_novel_sites(q)
        print(f'  找到 {len(results)} 个相关站点')
        all_results.extend(results)
    
    # 简书搜索
    print('\n=== 简书搜索 ===')
    for q in queries[:2]:
        results = search_jianshu(q)
        print(f'{q}: {len(results)} 个结果')
        for r in results:
            print(f'  {r["title"][:40]}: {r["url"][:80]}')
        all_results.extend(results)
        time.sleep(1)
    
    # 豆瓣搜索
    print('\n=== 豆瓣搜索 ===')
    for q in queries[:2]:
        results = search_douban(q)
        print(f'{q}: {len(results)} 个结果')
        all_results.extend(results)
        time.sleep(1)
    
    # 保存结果
    with open('output/social_platform_results.json', 'w', encoding='utf-8') as f:
        json.dump(all_results, f, ensure_ascii=False, indent=2)
    
    print(f'\n总共找到 {len(all_results)} 个结果')
    
    # 打印小说站结果
    novel_results = [r for r in all_results if r.get('source') == 'short_novel']
    if novel_results:
        print(f'\n小说站相关结果 ({len(novel_results)}):')
        for r in novel_results:
            print(f'  [{r["site"]}] {r["title"][:40]}')
            print(f'    {r["url"]}')
