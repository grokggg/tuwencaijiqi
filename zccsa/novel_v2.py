#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用别名搜索并处理Bing大页面 + 正确处理搜狗跳转"""
import subprocess
import re
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
import json
import time

TITLES = ["娇娇和她的忠犬小狗", "婚后一年老公从不碰我", "婚后一年，老公从不碰我"]
CHAR1 = "靳川"
CHAR2 = "孟娇蕊"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
UA_M = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1"

out = Path("/workspace/zccsa/data/novel3")
out.mkdir(parents=True, exist_ok=True)

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

def curl(url, headers=None, ua=None, timeout=15, referer=None):
    cmd = ["curl", "-s", "-L", "--max-time", str(timeout), "-A", ua or UA,
           "--compressed", "-w", "\n__CURL__%{http_code}", "-c", "/tmp/cookies.txt", "-b", "/tmp/cookies.txt"]
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
    for s in soup(['script','style','nav','footer','header','iframe','noscript']):
        s.decompose()
    return soup.get_text(separator='\n', strip=True)

def get_links(html, base_domain=""):
    soup = BeautifulSoup(html, 'html.parser')
    result = []
    for a in soup.find_all('a', href=True):
        t = a.get_text(strip=True)
        h = a['href']
        if t and len(t) > 2 and h.startswith('http'):
            result.append((t, h))
    return result

best_cn = 0
best_text = ""
best_src = ""
best_url = ""

# 先访问搜狗主页获取cookie
print("[0] 获取搜狗Cookie...")
s, b = curl("https://weixin.sogou.com/", ua=UA)
print(f"  sogou首页: {s}")
time.sleep(1)

print("\n[1] 搜狗微信搜索（带Cookie）...")
for title in TITLES[:1]:
    q = urllib.parse.quote(f"{title} {CHAR1} {CHAR2}")
    sg = f"https://weixin.sogou.com/weixin?type=2&query={q}&ie=utf8"
    s, body = curl(sg, referer="https://weixin.sogou.com/")
    print(f"  搜索 '{title}': status={s}, len={len(body)}")
    (out / "sogou.html").write_text(body, encoding='utf-8')
    if s == 200:
        soup = BeautifulSoup(body, 'html.parser')
        # 找所有结果项
        results = soup.select('div.txt-box') or soup.select('li') or soup.find_all(['h3','h4'])
        links_found = []
        for a in soup.find_all('a', href=True):
            t = a.get_text(strip=True)
            h = a['href']
            if len(t) > 5 and (CHAR1 in t or CHAR2 in t or title[:3] in t):
                if h.startswith('/link?url='):
                    full = "https://weixin.sogou.com" + h
                    links_found.append((t, full))
        print(f"  找到{len(links_found)}个相关结果")
        for t, u in links_found[:8]:
            print(f"    标题: {t[:60]}")
            # 访问搜狗跳转链接（带cookie）
            s2, b2 = curl(u, referer=sg)
            ct = extract_text(b2)
            cc = cn_count(ct)
            has_chars = CHAR1 in b2 and CHAR2 in b2
            print(f"    跳转: status={s2}, cn={cc}, has_chars={has_chars}, final_url_len={len(b2)}")
            # 检查是否是验证码页面
            if '请输入验证码' in b2 or 'antispider' in b2:
                print(f"    -> 被反爬验证码拦截")
            if has_chars and cc > best_cn:
                best_cn = cc
                best_text = ct
                best_src = f"sogou:{t[:20]}"
                best_url = u
                (out / f"sogou_{cc}.txt").write_text(ct, encoding='utf-8')
                print(f"    ★ 新纪录 {cc}字")
                print(f"    {ct[:300]}")
            time.sleep(1)

print(f"\n[2] Bing深度分析（177KB页面）...")
for title in TITLES:
    bing_url = f"https://cn.bing.com/search?q={urllib.parse.quote(title + ' ' + CHAR1 + ' ' + CHAR2 + ' 全文阅读')}&count=30"
    s, body = curl(bing_url)
    print(f"  Bing '{title[:10]}...': {s}, {len(body)} bytes")
    if s == 200:
        (out / f"bing_{title[:5]}.html").write_text(body, encoding='utf-8')
        links = get_links(body)
        # 过滤相关链接
        relevant = [(t,u) for t,u in links
                    if not any(x in u for x in ['bing.com','microsoft.com','msn.com','live.com'])
                    and (CHAR1 in t or CHAR2 in t or title[:3] in t or '小说' in t or '阅读' in t or '全文' in t)]
        print(f"  相关链接: {len(relevant)}")
        for t, u in relevant[:15]:
            print(f"    {t[:50]:50s} -> {u[:70]}")
            s2, b2 = curl(u, referer=bing_url, timeout=10)
            if s2 == 200 and len(b2) > 1000:
                ct = extract_text(b2)
                cc = cn_count(ct)
                has_c = CHAR1 in b2 and CHAR2 in b2
                if has_c and cc > best_cn:
                    best_cn = cc
                    best_text = ct
                    best_src = f"bing:{t[:20]}"
                    best_url = u
                    (out / f"bing_best_{cc}.txt").write_text(ct, encoding='utf-8')
                    print(f"      ★ {cc}字!")
                    print(f"      {ct[:300]}")
                    # 检查章节链接
                    soup2 = BeautifulSoup(b2, 'html.parser')
                    ch_links = []
                    for ca in soup2.find_all('a', href=True):
                        ct2 = ca.get_text(strip=True)
                        ch = ca['href']
                        if re.search(r'第[0-9一二三四五六七八九十百千]+章', ct2) or '下一页' in ct2 or '下一章' in ct2:
                            if ch.startswith('/'):
                                ch = '/'.join(u.split('/')[:3]) + ch
                            ch_links.append((ct2, ch))
                    if ch_links and cc < 5000:
                        print(f"      发现{len(ch_links)}个章节链接，尝试第一章...")
                        for cht, chu in ch_links[:2]:
                            s3, b3 = curl(chu, referer=u, timeout=10)
                            if s3 == 200:
                                ct3 = extract_text(b3)
                                cc3 = cn_count(ct3)
                                if cc3 > best_cn:
                                    best_cn = cc3
                                    best_text = ct3
                                    best_src = f"chapter:{cht[:15]}"
                                    best_url = chu
                                    (out / f"chapter_{cc3}.txt").write_text(ct3, encoding='utf-8')
                                    print(f"      ★章节 {cht}: {cc3}字")
                elif has_c:
                    print(f"      cn={cc} (有主角名但较短)")
            time.sleep(0.3)
    time.sleep(1)

# 额外：用别名搜索百度
print(f"\n[3] 百度搜索别名...")
for title in TITLES:
    bd = f"https://www.baidu.com/s?wd={urllib.parse.quote(title + ' ' + CHAR1 + ' ' + CHAR2 + ' 全文')}&rn=20"
    s, body = curl(bd)
    print(f"  百度 '{title[:10]}': {s}, {len(body)}")
    if s == 200:
        # 百度跳转链接
        bd_links = re.findall(r'href="(https?://www\.baidu\.com/link\?[^"]+)"', body)
        direct = re.findall(r'(https?://[a-zA-Z0-9.-]+\.(?:com|cn|net|la|lu|cc|io|me)/(?:book|read|novel|article|chapter|txt|xiaoshuo|xs|shu)[^\s"\'<>]*)', body)
        print(f"  跳转链接: {len(bd_links)}, 直链: {len(direct)}")
        for du in list(set(direct))[:5]:
            print(f"    直链: {du[:80]}")
            s2, b2 = curl(du, timeout=10)
            if s2 == 200:
                ct = extract_text(b2)
                cc = cn_count(ct)
                has_c = CHAR1 in b2 and CHAR2 in b2
                if has_c and cc > best_cn:
                    best_cn = cc
                    best_text = ct
                    best_src = f"baidu:{du[:30]}"
                    best_url = du
                    (out / f"bd_{cc}.txt").write_text(ct, encoding='utf-8')
                    print(f"    ★ {cc}字")
        # 访问跳转链接
        for jl in bd_links[:5]:
            s2, b2 = curl(jl, referer=bd, timeout=10)
            if s2 == 200:
                ct = extract_text(b2)
                cc = cn_count(ct)
                has_c = CHAR1 in b2 and CHAR2 in b2
                if has_c and cc > best_cn:
                    best_cn = cc
                    best_text = ct
                    best_src = f"bd_link"
                    best_url = jl
                    (out / f"bdj_{cc}.txt").write_text(ct, encoding='utf-8')
                    print(f"    ★跳转链接 {cc}字")
    time.sleep(1)

print(f"\n{'='*70}")
print(f"  最终结果")
print(f"{'='*70}")
print(f"  最佳: {best_cn}字")
print(f"  来源: {best_src}")
print(f"  URL: {best_url}")
if best_cn > 200:
    print(f"\n  内容预览:\n{best_text[:500]}")
    (out / "FINAL_RESULT.txt").write_text(best_text, encoding='utf-8')
    print(f"\n  保存到: {out / 'FINAL_RESULT.txt'}")
else:
    print("  未找到有效内容")
