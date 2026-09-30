#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速通道搜索
多路径并行搜索，快速定位完整版内容
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

def check_domains_alive(domains):
    """快速检查域名存活"""
    alive = []
    for domain in domains:
        cmd = ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}', 
               '--max-time', '5', f'https://{domain}']
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=7)
            code = result.stdout.strip()
            if code not in ['000', '0', ''] and not code.startswith('5'):
                alive.append(domain)
                print(f'  ✓ {domain} ({code})')
            else:
                print(f'  ✗ {domain}')
        except:
            print(f'  ✗ {domain} (timeout)')
    return alive

def search_baidu_mobile(query):
    """移动端百度搜索 - 返回所有结果链接"""
    results = []
    url = f'https://m.baidu.com/s?word={quote(query)}&rn=20'
    headers = {
        'Referer': 'https://m.baidu.com/',
        'Accept': 'text/html,application/xhtml+xml'
    }
    html = curl(url, ua=UA_MOBILE, timeout=12, headers=headers, retries=3)
    if not html:
        return results
    
    with open(f'data/bd_m_{query[:10]}.html', 'w', encoding='utf-8') as f:
        f.write(html)
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # 提取所有链接和文本
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        if len(text) > 8 and href.startswith('http') and 'baidu.com' not in href:
            # 检查是否相关
            if any(kw in text for kw in ['小说', '阅读', '全文', '免费', '娇娇', '靳川', '忠犬', '婚后', '老公']):
                results.append({'title': text, 'url': href})
    
    return results

def search_bing_deep(query):
    """必应深度搜索 - 返回更多结果"""
    results = []
    for page in range(3):  # 前三页
        first = page * 10 + 1
        url = f'https://cn.bing.com/search?q={quote(query)}&count=30&first={first}'
        html = curl(url, ua=UA_DESKTOP, timeout=12)
        if not html:
            continue
        
        soup = BeautifulSoup(html, 'html.parser')
        for li in soup.select('li.b_algo'):
            a = li.find('a', href=True)
            if not a:
                continue
            href = a['href']
            title = a.get_text(strip=True)
            
            if 'bing.com' in href or 'microsoft.com' in href:
                continue
            
            snippet_elem = li.select_one('.b_caption p, .b_snippet p')
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''
            
            results.append({'title': title, 'url': href, 'snippet': snippet[:200]})
        
        time.sleep(1)
    
    return results

def search_sogou_weixin(query):
    """搜狗微信公众号搜索"""
    results = []
    url = f'https://weixin.sogou.com/weixin?type=2&query={quote(query)}&ie=utf8'
    html = curl(url, ua=UA_DESKTOP, timeout=15)
    if not html:
        return results
    
    with open(f'data/sogou_wx_{query[:10]}.html', 'w', encoding='utf-8') as f:
        f.write(html)
    
    soup = BeautifulSoup(html, 'html.parser')
    for li in soup.select('.news-list li'):
        h3 = li.find('h3')
        if not h3:
            continue
        a = h3.find('a', href=True)
        if not a:
            continue
        
        href = a['href']
        title = a.get_text(strip=True)
        
        if href.startswith('/'):
            href = 'https://weixin.sogou.com' + href
        
        snippet_elem = li.select_one('.txt-info')
        snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''
        
        results.append({'title': title, 'url': href, 'snippet': snippet[:200]})
    
    return results

def extract_novel_content(url, max_chapters=100):
    """从小说目录页提取所有章节内容"""
    html = curl(url, ua=UA_MOBILE, timeout=15)
    if not html:
        html = curl(url, ua=UA_DESKTOP, timeout=15)
    
    if not html:
        return None
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # 找所有章节链接
    chapters = []
    for a in soup.find_all('a', href=True):
        text = a.get_text(strip=True)
        href = a['href']
        if re.search(r'第[0-9一二三四五六七八九十百千]+[章节回]', text):
            if href.startswith('/'):
                base = '/'.join(url.split('/')[:3])
                href = base + href
            elif not href.startswith('http'):
                href = urljoin(url, href)
            chapters.append({'title': text, 'url': href})
    
    if not chapters:
        return None
    
    print(f'  找到 {len(chapters)} 章')
    
    # 检查前几章是否包含目标内容
    verified = False
    for ch in chapters[:5]:
        ch_html = curl(ch['url'], ua=UA_MOBILE, timeout=8)
        if ch_html and ('靳川' in ch_html or '公狗腰' in ch_html or '弹幕' in ch_html):
            verified = True
            print(f'  ✓ 内容验证通过（{ch["title"]}）')
            break
    
    if not verified:
        print(f'  ✗ 内容验证失败')
        return None
    
    # 提取所有章节内容（限制数量）
    all_content = []
    for i, ch in enumerate(chapters[:max_chapters]):
        if i > 0 and i % 10 == 0:
            print(f'  已提取 {i}/{min(len(chapters), max_chapters)} 章')
        
        ch_html = curl(ch['url'], ua=UA_MOBILE, timeout=8)
        if not ch_html:
            ch_html = curl(ch['url'], ua=UA_DESKTOP, timeout=8)
        
        if ch_html:
            ch_soup = BeautifulSoup(ch_html, 'html.parser')
            # 尝试多种内容选择器
            content = ''
            for sel in ['#pContainer', '#content', '.content', '.chapter-content', '#chaptercontent', '.read-content']:
                elem = ch_soup.select_one(sel)
                if elem:
                    # 提取段落
                    paras = []
                    for p in elem.find_all('p'):
                        t = p.get_text(strip=True)
                        if t:
                            paras.append(t)
                    if paras:
                        content = '\n\n'.join(paras)
                    else:
                        content = elem.get_text('\n\n', strip=True)
                    break
            
            if not content:
                # 尝试body内找最长文本块
                body = ch_soup.body
                if body:
                    content = body.get_text('\n\n', strip=True)
            
            cn_count = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')
            if cn_count > 50:
                all_content.append({'title': ch['title'], 'content': content, 'cn_count': cn_count})
        
        time.sleep(0.2)
    
    total_cn = sum(c['cn_count'] for c in all_content)
    print(f'  成功提取 {len(all_content)}/{len(chapters)} 章，共 {total_cn} 字')
    
    return {
        'chapters': all_content,
        'total_chapters': len(chapters),
        'extracted_chapters': len(all_content),
        'total_cn_chars': total_cn,
        'source_url': url,
    }


if __name__ == '__main__':
    os.makedirs('data', exist_ok=True)
    os.makedirs('output', exist_ok=True)
    
    all_findings = []
    
    # 策略1: 百度移动端搜索（结果更多）
    print('=== 策略1: 百度移动端搜索 ===')
    baidu_queries = [
        '婚后一年老公从不碰我 全文免费阅读',
        '娇娇和她的忠犬小狗 完整版',
        '靳川 孟娇蕊 小说 结局',
        '边月忠犬 知乎 全文',
        '婚后一年老公从不碰我 靳川',
    ]
    
    baidu_results = []
    for q in baidu_queries:
        print(f'\n搜索: {q}')
        results = search_baidu_mobile(q)
        print(f'  找到 {len(results)} 个结果')
        for r in results:
            print(f'    {r["title"][:40]}')
        baidu_results.extend(results)
        time.sleep(1)
    
    # 策略2: 必应深度搜索（3页）
    print('\n=== 策略2: 必应深度搜索 ===')
    bing_queries = [
        '婚后一年老公从不碰我 小说 免费阅读',
        '"公狗腰" "靳川" 小说',
        '"弹幕" "年代文" 娇娇 忠犬',
    ]
    
    bing_results = []
    for q in bing_queries:
        print(f'\n搜索: {q}')
        results = search_bing_deep(q)
        print(f'  找到 {len(results)} 个结果')
        bing_results.extend(results)
        time.sleep(1)
    
    # 策略3: 搜狗微信搜索
    print('\n=== 策略3: 搜狗微信公众号搜索 ===')
    weixin_queries = [
        '婚后一年老公从不碰我',
        '娇娇和她的忠犬小狗',
        '边月忠犬 知乎',
    ]
    
    weixin_results = []
    for q in weixin_queries:
        print(f'\n搜索: {q}')
        results = search_sogou_weixin(q)
        print(f'  找到 {len(results)} 个结果')
        for r in results[:5]:
            print(f'    {r["title"][:40]}')
        weixin_results.extend(results)
        time.sleep(2)  # 微信搜索限速
    
    # 保存所有搜索结果
    all_search_results = {
        'baidu': baidu_results,
        'bing': bing_results,
        'weixin': weixin_results,
    }
    
    with open('output/all_search_results.json', 'w', encoding='utf-8') as f:
        json.dump(all_search_results, f, ensure_ascii=False, indent=2)
    
    # 筛选高价值目标进行深度提取
    print('\n=== 筛选高价值目标 ===')
    
    # 合并并去重
    all_urls = {}
    for source, results in all_search_results.items():
        for r in results:
            url = r['url']
            if url not in all_urls:
                all_urls[url] = {
                    'title': r.get('title', ''),
                    'snippet': r.get('snippet', ''),
                    'sources': [source],
                }
            else:
                all_urls[url]['sources'].append(source)
    
    # 按价值排序
    candidates = []
    for url, info in all_urls.items():
        score = 0
        title = info['title']
        snippet = info['snippet']
        combined = title + ' ' + snippet
        
        if '靳川' in combined: score += 30
        if '娇娇' in combined or '孟娇蕊' in combined: score += 20
        if '弹幕' in combined: score += 20
        if '公狗腰' in combined: score += 25
        if '傅柏文' in combined: score += 15
        if '婚后一年' in title: score += 25
        if '忠犬' in title: score += 20
        
        # 多源出现加分
        score += len(info['sources']) * 5
        
        # 小说站加分
        if any(s in url for s in ['kepue', 'biqu', 'shuquge', '630la', '23usp', 'husiyu', 'syzgly']):
            score += 15
        
        if score >= 30:
            candidates.append({'url': url, 'score': score, **info})
    
    candidates.sort(key=lambda x: x['score'], reverse=True)
    print(f'找到 {len(candidates)} 个高价值候选')
    
    for i, c in enumerate(candidates[:20]):
        print(f'{i+1}. [{c["score"]}分] {c["title"][:40]}')
        print(f'   {c["url"][:80]}')
        print(f'   来源: {", ".join(c["sources"])}')
    
    # 保存候选列表
    with open('output/high_value_candidates.json', 'w', encoding='utf-8') as f:
        json.dump(candidates, f, ensure_ascii=False, indent=2)
