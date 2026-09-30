#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""分析百度大搜索页，提取并访问所有小说链接"""
import subprocess
import re
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
import time
import json

CHAR1 = "靳川"
CHAR2 = "孟娇蕊"
TITLE1 = "娇娇和她的忠犬小狗"
TITLE2 = "婚后一年"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
UA_M = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1"

out = Path("/workspace/zccsa/data/novel4")
out.mkdir(parents=True, exist_ok=True)

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

def curl(url, ua=None, referer=None, timeout=12, headers=None):
    cmd = ["curl", "-s", "-L", "--max-time", str(timeout), "-A", ua or UA,
           "--compressed", "-w", "\n__CURL__%{http_code}",
           "-c", "/tmp/c2.txt", "-b", "/tmp/c2.txt"]
    if referer:
        cmd.extend(["-e", referer])
    if headers:
        for k,v in headers.items():
            cmd.extend(["-H", f"{k}: {v}"])
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+3)
        parts = r.stdout.rsplit("__CURL__", 1)
        body = parts[0] if len(parts)==2 else r.stdout
        try: status = int(parts[1]) if len(parts)==2 else 0
        except: status = 0
        return status, body
    except:
        return 0, ""

def extract_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for s in soup(['script','style','nav','footer','header','iframe']):
        s.decompose()
    return soup.get_text(separator='\n', strip=True)

best_cn = 0
best_text = ""
best_src = ""

# 先获取百度cookie
curl("https://www.baidu.com/")
time.sleep(0.5)

# 搜索并保存大页面
print("[1] 获取百度搜索大页面...")
q = urllib.parse.quote(f"{TITLE1} {CHAR1} {CHAR2} 全文免费阅读")
s, body = curl(f"https://www.baidu.com/s?wd={q}&rn=50&pn=0")
print(f"  状态:{s}, 大小:{len(body)}")
(out / "baidu_main.html").write_text(body, encoding='utf-8')

# 提取所有URL（包括data-url属性和真实链接）
all_urls = set()
soup = BeautifulSoup(body, 'html.parser')
for a in soup.find_all('a', href=True):
    href = a['href']
    text = a.get_text(strip=True)
    if href.startswith('http') and 'baidu.com' not in href:
        all_urls.add((text, href))
    # 百度mu属性（真实URL）
    mu = a.get('mu', '')
    if mu:
        all_urls.add((text, mu))
# data-url
for tag in soup.find_all(attrs={'data-url': True}):
    u = tag['data-url']
    t = tag.get_text(strip=True)
    if u.startswith('http'):
        all_urls.add((t, u))

print(f"  提取到{len(all_urls)}个外链")

# 搜索结果中的真实域名
print("\n[2] 访问所有小说相关链接...")
count = 0
for text, url in sorted(all_urls, key=lambda x: -1 if any(k in x[0] for k in ['娇娇','靳川','孟娇蕊','忠犬','婚后','小说','阅读','全文','免费']) else 1):
    if count >= 30:
        break
    # 跳过无关域名
    skip_domains = ['baidu.com', 'bilibili.com', 'zhihu.com', 'bing.com', 'google.com',
                    'sogou.com', 'sohu.com', 'qq.com', 'weibo.com', 'douyin.com',
                    'xiaohongshu.com', 'douban.com', 'csdn.net', 'jianshu.com']
    if any(d in url for d in skip_domains):
        continue
    relevant = any(k in text for k in ['娇娇','靳川','孟娇蕊','忠犬','婚后','小说','阅读','全文','章节','免费'])
    if not relevant:
        continue
    count += 1
    print(f"\n  [{count}] {text[:50]}")
    print(f"      URL: {url[:80]}")
    try:
        s2, b2 = curl(url, referer="https://www.baidu.com/", timeout=10)
        ct = extract_text(b2)
        cc = cn_count(ct)
        has_c = CHAR1 in b2 and CHAR2 in b2
        has_t = TITLE1[:3] in b2 or "婚后一年" in b2
        print(f"      status={s2}, cn={cc}, has_chars={has_c}, has_title={has_t}, len={len(b2)}")
        if s2 == 200 and len(b2) > 1000:
            (out / f"page_{count}_{cc}.html").write_text(b2, encoding='utf-8')
            if has_c and cc > best_cn:
                best_cn = cc
                best_text = ct
                best_src = f"baidu:{text[:20]}"
                print(f"      ★★★ 新纪录! {cc}字")
                print(f"      {ct[:300]}")
            elif has_c:
                print(f"      有主角名 cn={cc}")
                # 提取内容区域
                soup2 = BeautifulSoup(b2, 'html.parser')
                # 找正文div
                for sel in ['.content', '#content', '.article-content', '.read-content',
                            '.chapter-content', '.text', '.novel-content', '.showtxt',
                            '#contentbox', '.body', '#htmlContent', '.txt']:
                    el = soup2.select_one(sel)
                    if el:
                        et = el.get_text(separator='\n', strip=True)
                        ec = cn_count(et)
                        if ec > best_cn and CHAR1 in et:
                            best_cn = ec
                            best_text = et
                            best_src = f"baidu:{sel}"
                            print(f"      ★★★ 通过{sel}提取: {ec}字")
                            print(f"      {et[:300]}")
                            break
                # 提取下一章/章节列表链接
                ch_links = []
                for ca in soup2.find_all('a', href=True):
                    cat = ca.get_text(strip=True)
                    cah = ca['href']
                    if re.search(r'第[0-9一二三四五六七八九十百千]+章', cat) or '下一章' in cat or '下一页' in cat or '继续阅读' in cat:
                        if cah.startswith('/'):
                            from urllib.parse import urlparse
                            parsed = urlparse(url)
                            cah = f"{parsed.scheme}://{parsed.netloc}{cah}"
                        ch_links.append((cat, cah))
                if ch_links and best_cn < 3000:
                    print(f"      发现{len(ch_links)}个章节链接")
                    for cht, chu in ch_links[:2]:
                        s3, b3 = curl(chu, referer=url, timeout=10)
                        if s3 == 200:
                            ct3 = extract_text(b3)
                            cc3 = cn_count(ct3)
                            if CHAR1 in b3 and cc3 > best_cn:
                                best_cn = cc3
                                best_text = ct3
                                best_src = f"chapter:{cht[:15]}"
                                print(f"      ★章节 '{cht}': {cc3}字")
    except Exception as e:
        print(f"      错误: {e}")
    time.sleep(0.3)

# 额外：直接搜索kepue.com（之前拿到746字）
print(f"\n\n[3] 直接检查kepue.com章节链接...")
s, b = curl("https://kepue.com/chapter/131488.html", timeout=10)
if s == 200:
    ct = extract_text(b)
    cc = cn_count(ct)
    has_c = CHAR1 in b and CHAR2 in b
    print(f"  kepue: status={s}, cn={cc}, has_chars={has_c}")
    if has_c and cc > best_cn:
        best_cn = cc
        best_text = ct
        best_src = "kepue"
        print(f"  预览: {ct[:500]}")
    # 找其他章节
    soup = BeautifulSoup(b, 'html.parser')
    for a in soup.find_all('a', href=True):
        t = a.get_text(strip=True)
        h = a['href']
        if re.search(r'第[0-9一二三四五六七八九十百千]+章', t) or '下一页' in t:
            print(f"  章节: {t} -> {h}")

# 再试：百度第二页
print(f"\n[4] 百度搜索第二页...")
s, body2 = curl(f"https://www.baidu.com/s?wd={q}&rn=50&pn=50")
if s == 200:
    soup2 = BeautifulSoup(body2, 'html.parser')
    urls2 = set()
    for a in soup2.find_all('a', href=True):
        if a['href'].startswith('http') and 'baidu.com' not in a['href']:
            urls2.add((a.get_text(strip=True), a['href']))
    print(f"  第二页URL: {len(urls2)}")
    for t, u in list(urls2)[:15]:
        if any(k in t for k in ['娇娇','靳川','孟娇蕊','忠犬','婚后','小说','阅读']):
            print(f"    {t[:50]} -> {u[:70]}")

print(f"\n{'='*70}")
print(f"  本轮最佳: {best_cn}字 via {best_src}")
if best_cn > 200:
    print(f"  预览: {best_text[:500]}")
    (out / "BEST.txt").write_text(best_text, encoding='utf-8')
    print(f"  保存: {out / 'BEST.txt'}")
else:
    print("  仍未找到足够内容")
