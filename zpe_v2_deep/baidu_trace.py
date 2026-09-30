#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
百度跳转链接追踪
"""
import subprocess
from bs4 import BeautifulSoup
from urllib.parse import quote, urljoin
import re
import time

def curl_binary(url, ua=None, timeout=15, retries=2, headers=None):
    """返回二进制内容"""
    for attempt in range(retries):
        cmd = ['curl', '-s', '-L', '--max-time', str(timeout), '--compressed']
        if ua:
            cmd.extend(['-A', ua])
        if headers:
            for k, v in headers.items():
                cmd.extend(['-H', f'{k}: {v}'])
        cmd.append(url)
        try:
            result = subprocess.run(cmd, capture_output=True, timeout=timeout+5)
            if result.stdout and len(result.stdout) > 300:
                return result.stdout
        except:
            pass
        if attempt < retries - 1:
            time.sleep(1)
    return b''

def decode_html(data):
    """尝试多种编码解码HTML"""
    for encoding in ['utf-8', 'gbk', 'gb2312', 'gb18030', 'big5']:
        try:
            return data.decode(encoding)
        except:
            continue
    return data.decode('utf-8', errors='replace')

UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
UA_MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'

# 百度搜索关键词
print('=== 百度搜索并提取真实链接 ===')

queries = [
    '娇娇和她的忠犬小狗 全文免费阅读 沈念念',
    '婚后一年老公从不碰我 靳川 孟娇蕊 后续',
    '娇娇和她的忠犬小狗 孟娇蕊 靳川 忆相思',
]

all_real_urls = []

for q in queries:
    print(f'\n搜索: {q}')
    bd_url = f'https://www.baidu.com/s?wd={quote(q)}&rn=20'
    headers = {
        'Referer': 'https://www.baidu.com/',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    }
    
    data = curl_binary(bd_url, ua=UA, timeout=15, headers=headers)
    html = decode_html(data)
    
    print(f'  页面长度: {len(html)}')
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # 找所有结果链接
    for div in soup.select('.result, .c-container'):
        h3 = div.find('h3')
        if not h3:
            continue
        a = h3.find('a', href=True)
        if not a:
            continue
        
        title = a.get_text(strip=True)
        href = a['href']
        
        # 检查是否相关
        if any(kw in title for kw in ['靳川', '娇娇', '忠犬', '婚后一年', '孟娇蕊', '沈念念', '忆相思']):
            print(f'\n  标题: {title[:60]}')
            print(f'  百度跳转: {href[:80]}')
            
            # 获取真实URL
            cmd = ['curl', '-s', '-o', '/dev/null', '-w', '%{url_effective}',
                   '-L', '--max-time', '10', '-A', UA, '--compressed', href]
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=15)
                real_url = result.stdout.decode('utf-8', errors='replace').strip()
                print(f'  真实URL: {real_url[:100]}')
                
                if real_url and 'baidu.com' not in real_url:
                    all_real_urls.append((title, real_url))
            except:
                pass
    
    time.sleep(1)

print(f'\n\n共找到 {len(all_real_urls)} 个真实URL')

# 访问这些URL
print('\n=== 访问真实URL ===')
found_full = False

for i, (title, url) in enumerate(all_real_urls):
    print(f'\n[{i+1}] {title[:50]}')
    print(f'    {url[:80]}')
    
    data = curl_binary(url, ua=UA, timeout=15)
    if not data:
        data = curl_binary(url, ua=UA_MOBILE, timeout=15)
    
    if data:
        html = decode_html(data)
        has_jc = '靳川' in html
        has_snn = '沈念念' in html
        has_dm = '弹幕' in html
        
        soup = BeautifulSoup(html, 'html.parser')
        page_title = soup.title.string if soup.title else 'N/A'
        
        print(f'  长度: {len(html)}, 标题: {page_title[:50]}')
        print(f'  靳川: {has_jc}, 沈念念: {has_snn}, 弹幕: {has_dm}')
        
        # 找章节列表
        chapters = []
        for a in soup.find_all('a', href=True):
            text = a.get_text(strip=True)
            if re.search(r'第[0-9一二三四五六七八九十百千]+[章节回]', text):
                chapters.append(text)
        
        print(f'  章节数: {len(chapters)}')
        if chapters:
            print(f'  章节: {chapters[:15]}')
        
        # 如果章节数>10，可能是完整版
        if len(chapters) > 10 and has_jc:
            print(f'  ✓ 可能是完整版!')
            found_full = True
            
            # 保存
            safe_title = re.sub(r'[^\w]', '_', title[:20])
            with open(f'data/full_candidate_{i}.html', 'w', encoding='utf-8') as f:
                f.write(html)
    
    time.sleep(0.5)

if not found_full:
    print('\n未找到明显的完整版，继续深入搜索...')
