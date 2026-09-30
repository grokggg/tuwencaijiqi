#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速小说站搜索 - 直接用curl快速测试"""
import subprocess
import re
import json
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
import time

TITLE = "娇娇和她的忠犬小狗"
CHAR1 = "靳川"
CHAR2 = "孟娇蕊"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1"

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

def curl_get(url, extra_opts=None, timeout=12):
    cmd = ["curl", "-s", "-L", "--max-time", str(timeout), "-A", UA,
           "--compressed", "-w", "\n__CURL_STATUS__%{http_code}"]
    if extra_opts:
        cmd.extend(extra_opts)
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+3)
        parts = r.stdout.rsplit("__CURL_STATUS__", 1)
        body = parts[0] if len(parts)==2 else r.stdout
        try:
            status = int(parts[1].strip()) if len(parts)==2 else 0
        except:
            status = 0
        return status, body
    except:
        return 0, ""

def extract_links(html, base=""):
    soup = BeautifulSoup(html, 'html.parser')
    results = []
    for a in soup.find_all('a', href=True):
        t = a.get_text(strip=True)
        h = a['href']
        if t and len(t) > 2:
            if h.startswith('/') and base:
                h = base.rstrip('/') + h
            if not h.startswith('http'):
                continue
            results.append((t, h))
    return results

def extract_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for s in soup(['script','style','nav','footer','header','iframe']):
        s.decompose()
    return soup.get_text(separator='\n', strip=True)

out_dir = Path("/workspace/zccsa/data/novel2")
out_dir.mkdir(parents=True, exist_ok=True)

best_cn = 0
best_text = ""
best_src = ""

print("="*70)
print("  快速小说站全文搜索")
print("="*70)

# 直接搜索搜狗微信（这是唯一确认有结果的）
print("\n[1] 搜狗微信文章搜索（确认有结果）")
sg_url = f"https://weixin.sogou.com/weixin?type=2&query={urllib.parse.quote(TITLE + ' 靳川 孟娇蕊')}"
status, body = curl_get(sg_url)
print(f"  Status: {status}, len={len(body)}")
if status == 200:
    (out_dir / "sogou_wx.html").write_text(body, encoding='utf-8')
    soup = BeautifulSoup(body, 'html.parser')
    # 提取所有文章标题和链接
    for div in soup.find_all(['div', 'h3', 'li']):
        a = div.find('a', href=True) if div.name != 'a' else div
        if not a or not a.get('href'):
            continue
        t = a.get_text(strip=True)
        href = a['href']
        if TITLE[:3] in t or (CHAR1 in t and CHAR2 in t):
            print(f"  找到: {t[:50]}")
            # 搜狗链接
            if href.startswith('/link?'):
                full = "https://weixin.sogou.com" + href
                # 用curl跟随跳转
                s2, b2 = curl_get(full, ["-L"])
                ct = extract_text(b2)
                cc = cn_count(ct)
                has_c = CHAR1 in b2 and CHAR2 in b2
                print(f"    跳转后: status={s2}, cn={cc}, has_chars={has_c}")
                if has_c and cc > best_cn:
                    best_cn = cc
                    best_text = ct
                    best_src = f"sogou_wx:{t[:20]}"
                    (out_dir / f"sogou_best_{cc}.txt").write_text(ct, encoding='utf-8')
                    print(f"    ★ 新纪录! {cc}字")
                    print(f"    预览: {ct[:200]}")
            time.sleep(0.5)

# Bing搜索小说站
print("\n[2] Bing搜索小说全文")
for q in [f"{TITLE} 靳川 孟娇蕊 免费阅读", f"{TITLE} 全文 无弹窗"]:
    bing = f"https://cn.bing.com/search?q={urllib.parse.quote(q)}&count=20"
    status, body = curl_get(bing)
    print(f"  Bing '{q[:20]}...': {status}, len={len(body)}")
    if status == 200:
        links = extract_links(body)
        for t, u in links:
            if 'bing.com' in u or 'microsoft.com' in u:
                continue
            relevant = (TITLE[:3] in t or CHAR1 in t or CHAR2 in t or '小说' in t or '阅读' in t)
            if not relevant or len(t) < 4:
                continue
            print(f"    {t[:40]} -> {u[:60]}")
            # 访问
            s2, b2 = curl_get(u)
            if s2 == 200 and len(b2) > 1000:
                ct = extract_text(b2)
                cc = cn_count(ct)
                has_c = CHAR1 in b2 and CHAR2 in b2
                if has_c and cc > best_cn:
                    best_cn = cc
                    best_text = ct
                    best_src = f"bing:{t[:20]}"
                    (out_dir / f"bing_best_{cc}.txt").write_text(ct, encoding='utf-8')
                    print(f"      ★ {cc}字")
                    print(f"      {ct[:200]}")
            time.sleep(0.3)
    time.sleep(1)

# 直接尝试常见小说站搜索
print("\n[3] 直接尝试小说站搜索")
novel_search_urls = [
    ("xbiquge", f"https://www.xbiquge.la/search.php?keyword={urllib.parse.quote(TITLE)}"),
    ("bqg5200", f"https://www.biquge5200.cc/search.php?q={urllib.parse.quote(TITLE)}"),
    ("shuquge", f"https://www.shuquge.com/search.php?q={urllib.parse.quote(TITLE)}"),
    ("bequge", f"https://www.bequge.com/search.php?q={urllib.parse.quote(TITLE)}"),
    ("69shu", f"https://www.69shu.com/modules/article/search.php?searchkey={urllib.parse.quote(TITLE)}"),
    ("xs.la", f"https://www.xs.la/search.php?keyword={urllib.parse.quote(TITLE)}"),
    ("biqiuge", f"https://www.biqiuge.com/search?keyword={urllib.parse.quote(TITLE)}"),
]

for name, url in novel_search_urls:
    status, body = curl_get(url, timeout=8)
    print(f"  {name}: {status}, len={len(body)}")
    if status == 200 and len(body) > 500:
        ct = extract_text(body)
        cc = cn_count(ct)
        # 找结果链接
        links = extract_links(body, url.split('/')[0] + '//' + url.split('/')[2])
        novel_links = [(t,u) for t,u in links if (TITLE[:3] in t or CHAR1 in t or CHAR2 in t) and 'search' not in u]
        for t, u in novel_links[:3]:
            print(f"    结果: {t[:30]} -> {u[:60]}")
            s2, b2 = curl_get(u, timeout=8)
            if s2 == 200:
                ct2 = extract_text(b2)
                cc2 = cn_count(ct2)
                has_c = CHAR1 in b2 and CHAR2 in b2
                if has_c and cc2 > best_cn:
                    best_cn = cc2
                    best_text = ct2
                    best_src = f"{name}:{t[:15]}"
                    (out_dir / f"{name}_{cc2}.txt").write_text(ct2, encoding='utf-8')
                    print(f"      ★ {cc2}字")
                    print(f"      {ct2[:200]}")
                # 如果有章节列表，尝试第一章
                ch_links = [(ct,cu) for ct,cu in extract_links(b2, url.split('/')[0] + '//' + url.split('/')[2])
                           if re.search(r'第[一二三四五六七八九十百千\d]+章', ct) or '章节' in ct or '正文' in ct]
                for cht, chu in ch_links[:2]:
                    s3, b3 = curl_get(chu, timeout=8)
                    if s3 == 200:
                        ct3 = extract_text(b3)
                        cc3 = cn_count(ct3)
                        has_c3 = CHAR1 in b3
                        if has_c3 and cc3 > best_cn:
                            best_cn = cc3
                            best_text = ct3
                            best_src = f"{name}:{cht[:15]}"
                            (out_dir / f"{name}_ch_{cc3}.txt").write_text(ct3, encoding='utf-8')
                            print(f"      ★章节 {cht[:20]}: {cc3}字")
    time.sleep(0.5)

print(f"\n{'='*70}")
print(f"  搜索完成")
print(f"{'='*70}")
print(f"  最佳: {best_cn}字 via {best_src}")
if best_cn > 500:
    print(f"  预览: {best_text[:500]}")
    (out_dir / "FINAL_BEST.txt").write_text(best_text, encoding='utf-8')
    print(f"  已保存到 {out_dir / 'FINAL_BEST.txt'}")
else:
    print("  未找到足够长的内容")
