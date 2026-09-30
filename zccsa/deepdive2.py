#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深挖story.zhihu.com和kepue.com"""
import subprocess
import re
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
import time
import json

AID = "1979959692122943787"
CID = "1979976139138147736"
CHAR1 = "靳川"
CHAR2 = "孟娇蕊"
TITLE = "娇娇和她的忠犬小狗"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
UA_M = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1"

out = Path("/workspace/zccsa/data/deep_dive2")
out.mkdir(parents=True, exist_ok=True)

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

def curl(url, ua=None, referer=None, timeout=12, headers=None, follow=True):
    cmd = ["curl", "-s", "--max-time", str(timeout), "-A", ua or UA,
           "--compressed", "-w", "\n__CURL__%{http_code}",
           "-c", "/tmp/c3.txt", "-b", "/tmp/c3.txt"]
    if follow:
        cmd.append("-L")
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

# === 1. 测试story.zhihu.com ===
print("="*70)
print("[1] 测试 story.zhihu.com 子域名（百度跳转过）")
print("="*70)
story_urls = [
    f"https://story.zhihu.com/market/paid_column/{CID}/section/{AID}",
    f"https://story.zhihu.com/section/{AID}",
    f"https://story.zhihu.com/p/{AID}",
    f"https://story.zhihu.com/",
    f"http://story.zhihu.com/market/paid_column/{CID}/section/{AID}",
]
for url in story_urls:
    for ua_name, ua in [("desktop", UA), ("mobile", UA_M)]:
        s, b = curl(url, ua=ua, timeout=10)
        ct = extract_text(b)
        cc = cn_count(ct)
        has1 = CHAR1 in b
        has2 = CHAR2 in b
        print(f"  [{s}] {url[8:60]} UA={ua_name} cn={cc} 靳川={'Y' if has1 else 'N'} 孟娇蕊={'Y' if has2 else 'N'}")
        if s == 200 and (has1 or has2 or cc > 200):
            (out / f"story_{ua_name}_{cc}.html").write_text(b, encoding='utf-8')
            print(f"    预览: {ct[:200]}")
            if cc > best_cn and has1:
                best_cn = cc
                best_text = ct
                best_src = f"story.zhihu.com:{ua_name}"
                print(f"    ★新纪录!")
        time.sleep(0.3)

# 从bdj_746.txt看，百度跳转用了story.zhihu.com主机名
# 让我直接用curl模拟百度跳转
print("\n  [模拟] 从百度搜索结果跳转...")
q = urllib.parse.quote(f"{TITLE} {CHAR1} {CHAR2}")
# 先访问百度拿cookie
curl("https://www.baidu.com/")
time.sleep(0.5)
s, b = curl(f"https://www.baidu.com/s?wd={q}&rn=20")
print(f"  百度搜索: status={s}, len={len(b)}")
(out / "baidu_search.html").write_text(b, encoding='utf-8')
# 提取百度跳转链接
soup = BeautifulSoup(b, 'html.parser')
jump_links = []
for a in soup.find_all('a', href=True):
    href = a['href']
    if 'baidu.com/link?' in href:
        t = a.get_text(strip=True)
        if any(k in t for k in ['娇娇','靳川','忠犬','婚后','孟娇蕊']):
            jump_links.append((t, href))
print(f"  找到{len(jump_links)}个百度跳转链接")
for i, (t, jl) in enumerate(jump_links[:10]):
    full_jl = "https://www.baidu.com" + jl if jl.startswith('/') else jl
    print(f"\n  [{i+1}] {t[:60]}")
    # 不跟随跳转，看Location头
    s2, b2 = curl(full_jl, referer=f"https://www.baidu.com/s?wd={q}", follow=False, timeout=8)
    # 提取Location
    loc_match = re.search(r'[Ll]ocation:\s*(\S+)', b2)
    if loc_match:
        loc = loc_match.group(1).strip()
        print(f"    重定向到: {loc[:100]}")
        # 跟随跳转
        s3, b3 = curl(loc, referer=full_jl, timeout=10)
        ct3 = extract_text(b3)
        cc3 = cn_count(ct3)
        has1 = CHAR1 in b3
        has2 = CHAR2 in b3
        print(f"    最终: status={s3}, cn={cc3}, 靳川={'Y' if has1 else 'N'}, 娇蕊={'Y' if has2 else 'N'}")
        (out / f"bdjump_{i}_{cc3}.html").write_text(b3, encoding='utf-8')
        if has1 and cc3 > best_cn:
            best_cn = cc3
            best_text = ct3
            best_src = f"baidu_jump_{i}"
            print(f"    ★新纪录 {cc3}字!")
            print(f"    {ct3[:300]}")
            # 如果有"点击查看完整内容"，找那个链接
            soup3 = BeautifulSoup(b3, 'html.parser')
            for ca in soup3.find_all('a', href=True):
                cat = ca.get_text(strip=True)
                cah = ca['href']
                if '完整' in cat or '继续' in cat or '阅读' in cat or '全文' in cat or '点击' in cat:
                    print(f"    内容链接: {cat} -> {cah[:100]}")
                    if cah.startswith('/'):
                        from urllib.parse import urlparse
                        parsed = urlparse(loc)
                        cah = f"{parsed.scheme}://{parsed.netloc}{cah}"
                    s4, b4 = curl(cah, referer=loc, timeout=10)
                    ct4 = extract_text(b4)
                    cc4 = cn_count(ct4)
                    has1_4 = CHAR1 in b4
                    print(f"    内容页: status={s4}, cn={cc4}, 靳川={'Y' if has1_4 else 'N'}")
                    if has1_4 and cc4 > best_cn:
                        best_cn = cc4
                        best_text = ct4
                        best_src = f"content_link:{cat[:10]}"
                        (out / f"content_{cc4}.html").write_text(b4, encoding='utf-8')
                        print(f"    ★★★ {cc4}字!")
                        print(f"    {ct4[:300]}")
    time.sleep(0.5)

# === 2. 深挖kepue.com ===
print("\n" + "="*70)
print("[2] 深挖 kepue.com（已有2021字，含靳川）")
print("="*70)
s, b = curl("https://kepue.com/chapter/131488.html", timeout=10)
print(f"  章节页: status={s}, len={len(b)}")
(out / "kepue_chapter.html").write_text(b, encoding='utf-8')
soup = BeautifulSoup(b, 'html.parser')
# 找"立即阅读"链接和章节列表
for a in soup.find_all('a', href=True):
    t = a.get_text(strip=True)
    h = a['href']
    if t and len(t) > 1:
        if '阅读' in t or '章' in t or '列表' in t or '目录' in t or '下一页' in t or '首页' in t:
            print(f"  链接: {t[:30]} -> {h[:80]}")
            if h.startswith('/'):
                h = "https://kepue.com" + h
            elif not h.startswith('http'):
                h = "https://kepue.com/" + h
            # 访问
            s2, b2 = curl(h, referer="https://kepue.com/chapter/131488.html", timeout=10)
            if s2 == 200:
                ct2 = extract_text(b2)
                cc2 = cn_count(ct2)
                has1 = CHAR1 in b2
                print(f"    status={s2}, cn={cc2}, 靳川={'Y' if has1 else 'N'}")
                (out / f"kepue_{t[:10]}_{cc2}.html").write_text(b2, encoding='utf-8')
                if has1 and cc2 > best_cn:
                    best_cn = cc2
                    best_text = ct2
                    best_src = f"kepue:{t[:10]}"
                    print(f"    ★ {cc2}字!")
                    print(f"    {ct2[:300]}")
                    # 如果是目录页，找第一章
                    soup2 = BeautifulSoup(b2, 'html.parser')
                    ch_count = 0
                    for ca in soup2.find_all('a', href=True):
                        cat = ca.get_text(strip=True)
                        cah = ca['href']
                        if re.search(r'第[0-9一二三四五六七八九十百千]+章', cat) or '第1章' in cat or '第一章' in cat:
                            ch_count += 1
                            if ch_count <= 3:
                                if cah.startswith('/'):
                                    cah = "https://kepue.com" + cah
                                elif not cah.startswith('http'):
                                    cah = "https://kepue.com/" + cah
                                s3, b3 = curl(cah, referer=h, timeout=10)
                                ct3 = extract_text(b3)
                                cc3 = cn_count(ct3)
                                has1_3 = CHAR1 in b3
                                print(f"      章节 '{cat}': status={s3}, cn={cc3}, 靳川={'Y' if has1_3 else 'N'}")
                                if has1_3 and cc3 > best_cn:
                                    best_cn = cc3
                                    best_text = ct3
                                    best_src = f"kepue_ch:{cat[:10]}"
                                    (out / f"kepue_chapter_{cc3}.html").write_text(b3, encoding='utf-8')
                                    print(f"      ★ {cc3}字!")
                                    print(f"      {ct3[:300]}")

# === 3. 检查其他可能的知乎子域名 ===
print("\n" + "="*70)
print("[3] 测试其他知乎子域名")
print("="*70)
subdomains = ["story.zhihu.com", "drd.zhihu.com", "api.zhihu.com", "zhuanlan.zhihu.com",
              "m.zhihu.com", "www.zhihu.com", "pay.zhihu.com", "read.zhihu.com",
              "book.zhihu.com", "novel.zhihu.com", "yanxuan.zhihu.com", "salt.zhihu.com"]
test_paths = [f"/market/paid_column/{CID}/section/{AID}", f"/section/{AID}", f"/p/{AID}"]
for sd in subdomains:
    for path in test_paths[:1]:
        url = f"https://{sd}{path}"
        s, b = curl(url, ua=UA_M, timeout=8)
        has1 = CHAR1 in b
        cc = cn_count(b)
        if s == 200 and (has1 or cc > 200):
            print(f"  [{s}] {url} cn={cc} 靳川={'Y' if has1 else 'N'} ***")
            (out / f"sub_{sd.replace('.','_')}_{cc}.html").write_text(b, encoding='utf-8')
            ct = extract_text(b)
            if has1 and cc > best_cn:
                best_cn = cc
                best_text = ct
                best_src = sd
        elif s != 403 and s != 0:
            print(f"  [{s}] {url} cn={cc}")
        time.sleep(0.2)

print(f"\n{'='*70}")
print(f"  本轮最佳: {best_cn}字 via {best_src}")
if best_cn > 200:
    print(f"  预览: {best_text[:500]}")
    (out / "BEST_SO_FAR.txt").write_text(best_text, encoding='utf-8')
else:
    print("  未找到足够内容")
