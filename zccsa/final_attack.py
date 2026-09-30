#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""直接获取kepue全文 + 处理百度跳转"""
import subprocess
import re
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
import time

CHAR1 = "靳川"
CHAR2 = "孟娇蕊"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"
UA_M = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1"

out = Path("/workspace/zccsa/data/final_attack")
out.mkdir(parents=True, exist_ok=True)

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

def curl(url, ua=None, referer=None, timeout=12, follow=True, headers=None):
    cmd = ["curl", "-s", "--max-time", str(timeout), "-A", ua or UA,
           "--compressed", "-w", "\n__HTTP_STATUS__%{http_code}\n__REDIRECT_URL__%{redirect_url}",
           "-c", "/tmp/c4.txt", "-b", "/tmp/c4.txt"]
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
        stdout = r.stdout
        status = 0
        redirect_url = ""
        body = stdout
        m_status = re.search(r'__HTTP_STATUS__(\d+)', stdout)
        if m_status:
            status = int(m_status.group(1))
            body = stdout[:m_status.start()]
        m_redir = re.search(r'__REDIRECT_URL__(\S+)', stdout)
        if m_redir:
            redirect_url = m_redir.group(1)
        return status, body, redirect_url
    except Exception as e:
        return 0, str(e), ""

def extract_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for s in soup(['script','style','nav','footer','header','iframe']):
        s.decompose()
    return soup.get_text(separator='\n', strip=True)

def get_links(html, base_url=""):
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    for a in soup.find_all('a', href=True):
        t = a.get_text(strip=True)
        h = a['href']
        if t and h:
            if h.startswith('/') and base_url:
                from urllib.parse import urlparse
                p = urlparse(base_url)
                h = f"{p.scheme}://{p.netloc}{h}"
            elif not h.startswith('http'):
                if base_url:
                    h = base_url.rstrip('/') + '/' + h.lstrip('/')
            links.append((t, h))
    return links

full_content = ""
best_cn = 0

# === 1. 访问kepue小说页 ===
print("="*70)
print("[1] 访问 kepue.com/nvpin/38738/ (立即阅读页面)")
print("="*70)
s, b, redir = curl("https://kepue.com/nvpin/38738/", timeout=15)
print(f"  status={s}, len={len(b)}, redirect={redir}")
(out / "kepue_nvpin.html").write_text(b, encoding='utf-8')

ct = extract_text(b)
cc = cn_count(ct)
has1 = CHAR1 in b
has2 = CHAR2 in b
print(f"  cn={cc}, 靳川={'Y' if has1 else 'N'}, 孟娇蕊={'Y' if has2 else 'N'}")
print(f"  预览: {ct[:500]}")

# 提取所有章节链接
soup = BeautifulSoup(b, 'html.parser')
chapter_links = []
for a in soup.find_all('a', href=True):
    t = a.get_text(strip=True)
    h = a['href']
    if not t:
        continue
    if '/chapter/' in h or '/read/' in h or '/nvpin/' in h:
        if h.startswith('/'):
            h = "https://kepue.com" + h
        chapter_links.append((t, h))
    # 也检查是否是章节标题
    if re.search(r'第[0-9一二三四五六七八九十百千]+[章节回]', t):
        if h.startswith('/'):
            h = "https://kepue.com" + h
        chapter_links.append((t, h))

# 去重
seen = set()
unique_chapters = []
for t, h in chapter_links:
    if h not in seen:
        seen.add(h)
        unique_chapters.append((t, h))
print(f"\n  找到{len(unique_chapters)}个章节/内容链接")

# 访问所有章节链接
for i, (t, h) in enumerate(unique_chapters[:20]):
    print(f"\n  [{i+1}] {t[:40]} -> {h[-40:]}")
    s2, b2, _ = curl(h, referer="https://kepue.com/nvpin/38738/", timeout=10)
    ct2 = extract_text(b2)
    cc2 = cn_count(ct2)
    has1_2 = CHAR1 in b2
    print(f"    status={s2}, cn={cc2}, 靳川={'Y' if has1_2 else 'N'}")
    if has1_2 and cc2 > best_cn:
        best_cn = cc2
        full_content = ct2
        (out / f"kepue_ch_{i}_{cc2}.html").write_text(b2, encoding='utf-8')
        print(f"    ★ {cc2}字")
        print(f"    预览: {ct2[:300]}")
    time.sleep(0.2)

# === 2. 百度跳转 ===
print("\n" + "="*70)
print("[2] 百度跳转链接（不跟随跳转，直接获取Location）")
print("="*70)
curl("https://www.baidu.com/", ua=UA)
time.sleep(0.5)
q = urllib.parse.quote(f"娇娇和她的忠犬小狗 靳川 孟娇蕊 全文")
s, b, _ = curl(f"https://www.baidu.com/s?wd={q}&rn=30", follow=True)
print(f"  百度搜索: status={s}, len={len(b)}")
(out / "baidu_q.html").write_text(b, encoding='utf-8')
soup = BeautifulSoup(b, 'html.parser')
jump_links = []
for a in soup.find_all('a', href=True):
    href = a['href']
    t = a.get_text(strip=True)
    if 'baidu.com/link?' in href and any(k in t for k in ['娇娇','靳川','忠犬','婚后','孟娇蕊','阅读','全文','小狗']):
        if href.startswith('/'):
            href = "https://www.baidu.com" + href
        jump_links.append((t, href))
print(f"  找到{len(jump_links)}个跳转链接")

for i, (t, jl) in enumerate(jump_links[:15]):
    print(f"\n  [{i+1}] {t[:60]}")
    # 不跟随跳转，获取Location
    s2, b2, loc = curl(jl, referer=f"https://www.baidu.com/s?wd={q}", follow=False, timeout=8)
    print(f"    HTTP状态: {s2}, Location: {loc[:100] if loc else 'None'}")
    if loc and 'zhihu.com' in loc:
        print(f"    *** 跳转到知乎! 直接访问 ***")
        s3, b3, _ = curl(loc, referer=jl, timeout=10)
        ct3 = extract_text(b3)
        cc3 = cn_count(ct3)
        has1_3 = CHAR1 in b3
        has2_3 = CHAR2 in b3
        print(f"    status={s3}, cn={cc3}, 靳川={'Y' if has1_3 else 'N'}, 娇蕊={'Y' if has2_3 else 'N'}")
        (out / f"zhihu_bd_{i}.html").write_text(b3, encoding='utf-8')
        if has1_3 and cc3 > best_cn:
            best_cn = cc3
            full_content = ct3
            print(f"    ★ 知乎内容 {cc3}字!")
            print(f"    {ct3[:300]}")
    elif loc and 'kepue' in loc or (loc and any(d in loc for d in ['xiaoshuo','book','read','novel','wenxue'])):
        s3, b3, _ = curl(loc, referer=jl, timeout=10)
        ct3 = extract_text(b3)
        cc3 = cn_count(ct3)
        has1_3 = CHAR1 in b3
        print(f"    访问小说站: status={s3}, cn={cc3}, 靳川={'Y' if has1_3 else 'N'}")
        if has1_3 and cc3 > best_cn:
            best_cn = cc3
            full_content = ct3
            (out / f"novel_bd_{i}.html").write_text(b3, encoding='utf-8')
            print(f"    ★ {cc3}字!")
    elif loc:
        # 尝试访问任何跳转结果
        s3, b3, _ = curl(loc, referer=jl, timeout=10)
        ct3 = extract_text(b3)
        cc3 = cn_count(ct3)
        has1_3 = CHAR1 in b3
        if has1_3 and cc3 > best_cn:
            best_cn = cc3
            full_content = ct3
            (out / f"bdjump_{i}.html").write_text(b3, encoding='utf-8')
            print(f"    ★ {cc3}字!")
    time.sleep(0.3)

# === 3. 检查INITIAL_STATE/SSR数据 ===
print("\n" + "="*70)
print("[3] 检查已保存页面中的内嵌数据")
print("="*70)
for html_file in out.glob("*.html"):
    try:
        html = html_file.read_text(encoding='utf-8')
        # 检查INITIAL_STATE
        for pattern in [
            r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
            r'<script id="js-initialData"[^>]*>(.*?)</script>',
            r'"content"\s*:\s*"((?:[^"\\]|\\.){100,})"',
        ]:
            for m in re.finditer(pattern, html, re.S):
                raw = m.group(1)
                c = cn_count(raw)
                if c > best_cn and CHAR1 in raw:
                    print(f"  {html_file.name}: 找到内嵌数据 cn={c}")
                    best_cn = c
                    # 解码unicode
                    try:
                        decoded = raw.encode().decode('unicode_escape')
                        if cn_count(decoded) > c:
                            full_content = decoded
                    except:
                        full_content = raw
    except Exception:
        pass

# === 4. 保存最终结果 ===
print("\n" + "="*70)
print("[最终结果]")
print("="*70)
print(f"  最佳字数: {best_cn}")
if best_cn > 500:
    print(f"  预览:\n{full_content[:800]}")
    (out / "FINAL_CONTENT.txt").write_text(full_content, encoding='utf-8')
    print(f"\n  保存到: {out / 'FINAL_CONTENT.txt'}")
else:
    print("  未找到足够长的内容")
