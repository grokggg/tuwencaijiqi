#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""深挖侦察发现的高潜力路径"""
import asyncio
import re
import json
import subprocess
from pathlib import Path
from bs4 import BeautifulSoup
import httpx
import urllib.parse

TITLE = "娇娇和她的忠犬小狗"
AID = "1979959692122943787"
CID = "1979976139138147736"

UA_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1"
UA_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

def extract_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for s in soup(['script','style','nav','footer','header','aside']):
        s.decompose()
    return soup.get_text(separator='\n', strip=True)

def extract_links(html, base_domain=""):
    soup = BeautifulSoup(html, 'html.parser')
    links = []
    for a in soup.find_all('a', href=True):
        href = a['href']
        text = a.get_text(strip=True)
        if base_domain and base_domain not in href and not href.startswith('http'):
            if href.startswith('/'):
                href = 'https://' + base_domain + href
        if text and len(text) > 3:
            links.append((text, href))
    return links

async def deep_dive():
    client = httpx.AsyncClient(verify=False, timeout=15, follow_redirects=True,
                               headers={"Accept-Language": "zh-CN,zh;q=0.9"})
    out_dir = Path("/workspace/zccsa/data/deepdive")
    out_dir.mkdir(parents=True, exist_ok=True)

    # === 1. CURL mobile zhihu - 129KB 响应分析 ===
    print("="*70)
    print("[1] 深入分析 m.zhihu.com curl响应（129KB/3667cn）")
    print("="*70)
    url = f"https://m.zhihu.com/market/paid_column/{CID}/section/{AID}"
    cmd = ["curl", "-s", "-L", "--max-time", "15", "-A", UA_MOBILE, url]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
    html = r.stdout
    print(f"  响应大小: {len(html)} bytes")
    (out_dir / "m_zhihu_raw.html").write_text(html, encoding='utf-8')

    # 检查INITIAL_STATE
    m = re.search(r'<script id="js-initialData"[^>]*>(.*?)</script>', html, re.S)
    if m:
        try:
            init = json.loads(m.group(1))
            init_str = json.dumps(init, ensure_ascii=False)
            print(f"  INITIAL_STATE大小: {len(init_str)} chars")
            # 搜索标题
            for kw in ["娇娇", "忠犬", "小狗"]:
                idx = init_str.find(kw)
                if idx >= 0:
                    print(f"  找到关键词 '{kw}' 在位置 {idx}")
                    snippet = init_str[max(0,idx-100):idx+800]
                    print(f"  上下文: {snippet[:400]}")
                    print()
            # 递归找content字段
            def walk(o, d=0, path=""):
                results = []
                if d > 7: return results
                if isinstance(o, dict):
                    for k, v in o.items():
                        np = f"{path}.{k}" if path else k
                        if k in ('content','content_html','body','paid_content','excerpt','summary') and isinstance(v, str):
                            c = cn_count(v)
                            if c > 50:
                                results.append((np, c, v[:200]))
                        results.extend(walk(v, d+1, np))
                elif isinstance(o, list):
                    for i, it in enumerate(o):
                        results.extend(walk(it, d+1, f"{path}[{i}]"))
                return results
            contents = walk(init)
            contents.sort(key=lambda x: x[1], reverse=True)
            print(f"  INITIAL_STATE中找到{len(contents)}个content字段:")
            for p, c, prev in contents[:5]:
                print(f"    {p}: {c}字")
                print(f"      {prev[:100]}")
        except Exception as e:
            print(f"  INITIAL_STATE解析失败: {e}")
    else:
        print("  未找到js-initialData")
        # 检查其他数据注入点
        for pattern in [r'window\.__INITIAL_STATE__\s*=\s*({.*?});',
                        r'window\.__DATA__\s*=\s*({.*?});',
                        r'"content"\s*:\s*"[^"]{50,}"']:
            m2 = re.search(pattern, html, re.S)
            if m2:
                print(f"  找到模式: {pattern[:30]}...")
                print(f"  值: {m2.group(0)[:300]}")

    # 检查页面文本
    text = extract_text(html)
    print(f"\n  页面纯文本cn: {cn_count(text)}")
    print(f"  页面标题: ", end="")
    soup = BeautifulSoup(html, 'html.parser')
    if soup.title:
        print(soup.title.string)
    print(f"  文本预览: {text[:500]}")

    # 提取所有链接
    links = extract_links(html, "www.zhihu.com")
    zhihu_links = [(t,u) for t,u in links if 'zhihu.com' in u or u.startswith('/')]
    print(f"\n  知乎相关链接({len(zhihu_links)}):")
    for t, u in zhihu_links[:15]:
        print(f"    {t[:30]:30s} -> {u[:80]}")

    await asyncio.sleep(1)

    # === 2. B站搜索结果深入 ===
    print("\n" + "="*70)
    print("[2] 深入分析B站（7410cn，标题完全匹配）")
    print("="*70)
    bili_search = f"https://search.bilibili.com/all?keyword={urllib.parse.quote(TITLE)}"
    r = await client.get(bili_search, headers={"User-Agent": UA_CHROME})
    print(f"  B站搜索页: {r.status_code}, {len(r.text)} bytes")
    (out_dir / "bilibili_search.html").write_text(r.text, encoding='utf-8')
    # 提取B站视频/文章链接
    bili_links = re.findall(r'href="//(www\.bilibili\.com/[^\s"\'?<>]+)', r.text)
    bili_links = list(set(bili_links))
    bili_links = ["https://" + l for l in bili_links if any(k in l for k in ('video', 'read', 'opus', 'article'))]
    print(f"  B站相关链接: {len(bili_links)}")
    for bl in bili_links[:5]:
        print(f"    {bl}")
    # 访问B站专栏文章
    read_links = [l for l in bili_links if '/read/' in l or '/opus/' in l or '/article/' in l]
    for rl in read_links[:3]:
        try:
            rr = await client.get(rl, headers={"User-Agent": UA_CHROME}, timeout=10)
            if rr.status_code == 200:
                rt = extract_text(rr.text)
                c = cn_count(rt)
                has_t = TITLE[:4] in rr.text
                print(f"\n  B站文章 {rl.split('/')[-1]}: cn={c}, has_title={has_t}")
                if c > 500:
                    print(f"  预览: {rt[:500]}")
                    (out_dir / f"bilibili_{rl.split('/')[-1][:20]}.txt").write_text(rt, encoding='utf-8')
        except Exception as e:
            print(f"  B站请求失败: {e}")
        await asyncio.sleep(0.5)

    # 也检查B站初始数据
    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*({.*?});', r.text, re.S)
    if m:
        try:
            data = json.loads(m.group(1))
            ds = json.dumps(data, ensure_ascii=False)
            idx = ds.find("娇娇")
            if idx >= 0:
                print(f"\n  B站INITIAL_STATE中找到标题，上下文:")
                print(f"  {ds[max(0,idx-200):idx+500]}")
        except:
            pass

    await asyncio.sleep(1)

    # === 3. 百度文库深入 ===
    print("\n" + "="*70)
    print("[3] 深入分析百度文库（7959cn）")
    print("="*70)
    wk_search = f"https://wenku.baidu.com/search?word={urllib.parse.quote(TITLE)}"
    r = await client.get(wk_search, headers={"User-Agent": UA_CHROME})
    print(f"  文库搜索页: {r.status_code}, {len(r.text)} bytes")
    (out_dir / "wenku_search.html").write_text(r.text, encoding='utf-8')
    wk_links = re.findall(r'href="(https?://wenku\.baidu\.com/[^\s"<>]+)', r.text)
    wk_links = list(set(wk_links))[:5]
    print(f"  文库链接: {len(wk_links)}")
    for wl in wk_links:
        print(f"    {wl[:100]}")
        try:
            wr = await client.get(wl, headers={"User-Agent": UA_CHROME}, timeout=10)
            wt = extract_text(wr.text)
            c = cn_count(wt)
            print(f"    cn={c}")
            if c > 500:
                print(f"    预览: {wt[:300]}")
        except Exception as e:
            print(f"    失败: {e}")
        await asyncio.sleep(0.5)

    await asyncio.sleep(1)

    # === 4. 搜狗微信深入 ===
    print("\n" + "="*70)
    print("[4] 深入分析搜狗微信（1095cn，has_title=Y）")
    print("="*70)
    sg_url = f"https://weixin.sogou.com/weixin?type=2&query={urllib.parse.quote(TITLE)}"
    r = await client.get(sg_url, headers={"User-Agent": UA_CHROME})
    print(f"  搜狗微信: {r.status_code}, {len(r.text)} bytes")
    (out_dir / "sogou_weixin.html").write_text(r.text, encoding='utf-8')
    # 提取文章链接
    soup = BeautifulSoup(r.text, 'html.parser')
    for a in soup.find_all('a', href=True):
        text = a.get_text(strip=True)
        href = a['href']
        if TITLE[:3] in text or (len(text) > 10 and '狗' in text and '娇' in text):
            print(f"  可能相关: '{text[:40]}' -> {href[:80]}")
    # 搜狗的链接通常是跳转链接
    sg_links = re.findall(r'href="(/link\?url=[^"]+)"', r.text)
    print(f"  搜狗跳转链接: {len(sg_links)}")
    for sl in sg_links[:5]:
        full_url = "https://weixin.sogou.com" + sl
        try:
            sr = await client.get(full_url, headers={"User-Agent": UA_CHROME}, timeout=10, follow_redirects=True)
            st = extract_text(sr.text)
            c = cn_count(st)
            has_t = TITLE[:4] in sr.text
            print(f"  跳转后URL: {sr.url} cn={c} has_title={has_t}")
            if c > 500 or has_t:
                print(f"  预览: {st[:400]}")
                (out_dir / f"sogou_wx_{c}.html").write_text(sr.text, encoding='utf-8')
        except Exception as e:
            print(f"  失败: {e}")
        await asyncio.sleep(0.5)

    await asyncio.sleep(1)

    # === 5. 头条搜索深入 ===
    print("\n" + "="*70)
    print("[5] 深入分析头条搜索（5178cn）")
    print("="*70)
    tt_url = f"https://so.toutiao.com/search?keyword={urllib.parse.quote(TITLE)}"
    r = await client.get(tt_url, headers={"User-Agent": UA_CHROME})
    print(f"  头条搜索: {r.status_code}, {len(r.text)} bytes")
    (out_dir / "toutiao_search.html").write_text(r.text, encoding='utf-8')
    # 提取头条文章链接
    tt_links = re.findall(r'"(https?://(?:www\.)?toutiao\.com/(?:article|item|a)/[0-9]+[^"]*)"', r.text)
    tt_links += re.findall(r'href="(https?://(?:www\.)?toutiao\.com/[^"]+)"', r.text)
    tt_links = list(set(tt_links))[:5]
    print(f"  头条文章链接: {len(tt_links)}")
    for tl in tt_links:
        print(f"    {tl[:80]}")
        try:
            tr = await client.get(tl, headers={"User-Agent": UA_CHROME}, timeout=10)
            tt = extract_text(tr.text)
            c = cn_count(tt)
            has_t = TITLE[:4] in tr.text
            print(f"    cn={c} has_title={has_t}")
            if c > 500 or has_t:
                print(f"    预览: {tt[:300]}")
        except Exception as e:
            print(f"    失败: {e}")
        await asyncio.sleep(0.5)

    await asyncio.sleep(1)

    # === 6. 360搜索深入 ===
    print("\n" + "="*70)
    print("[6] 深入分析360搜索（2445cn）")
    print("="*70)
    so_url = f"https://www.so.com/s?q={urllib.parse.quote(TITLE)}"
    r = await client.get(so_url, headers={"User-Agent": UA_CHROME})
    print(f"  360搜索: {r.status_code}, {len(r.text)} bytes")
    (out_dir / "360_search.html").write_text(r.text, encoding='utf-8')
    soup = BeautifulSoup(r.text, 'html.parser')
    for a in soup.find_all('a', href=True):
        t = a.get_text(strip=True)
        if TITLE[:3] in t and len(t) > 5:
            href = a['href']
            print(f"  相关结果: '{t[:50]}' -> {href[:80]}")

    await asyncio.sleep(1)

    # === 7. 百度知道深入 ===
    print("\n" + "="*70)
    print("[7] 深入分析百度知道（1759cn）")
    print("="*70)
    zd_url = f"https://zhidao.baidu.com/search?word={urllib.parse.quote(TITLE)}"
    r = await client.get(zd_url, headers={"User-Agent": UA_CHROME})
    print(f"  百度知道: {r.status_code}, {len(r.text)} bytes")
    (out_dir / "zhidao_search.html").write_text(r.text, encoding='utf-8')
    soup = BeautifulSoup(r.text, 'html.parser')
    for a in soup.find_all('a', href=True):
        t = a.get_text(strip=True)
        if TITLE[:3] in t or ('娇' in t and '狗' in t):
            print(f"  相关: '{t[:50]}' -> {a['href'][:80]}")

    await asyncio.sleep(1)

    # === 8. Bing搜索深入 - 提取所有链接 ===
    print("\n" + "="*70)
    print("[8] 深入分析Bing搜索结果（提取所有链接）")
    print("="*70)
    bing_url = f"https://www.bing.com/search?q={urllib.parse.quote(TITLE + ' 知乎')}&count=30"
    r = await client.get(bing_url, headers={"User-Agent": UA_CHROME})
    print(f"  Bing: {r.status_code}, {len(r.text)} bytes")
    (out_dir / "bing_search.html").write_text(r.text, encoding='utf-8')
    soup = BeautifulSoup(r.text, 'html.parser')
    bing_results = []
    for li in soup.find_all('li', class_='b_algo'):
        a = li.find('a', href=True)
        if a:
            title = a.get_text(strip=True)
            href = a['href']
            desc = li.find('p')
            desc_text = desc.get_text(strip=True) if desc else ""
            bing_results.append((title, href, desc_text))
    print(f"  Bing找到{len(bing_results)}个结果:")
    for title, href, desc in bing_results[:15]:
        print(f"    [{title[:40]}]")
        print(f"      {href[:80]}")
        print(f"      {desc[:80]}")
        print()
        # 访问可能有全文的链接
        if any(d in href for d in ('zhihu.com', 'bilibili.com', 'jian shu', 'toutiao', 'weibo', 'douban', 'wenku')):
            try:
                rr = await client.get(href, headers={"User-Agent": UA_CHROME}, timeout=10, follow_redirects=True)
                rt = extract_text(rr.text)
                c = cn_count(rt)
                has_t = TITLE[:4] in rr.text
                print(f"      -> 访问: status={rr.status_code}, cn={c}, has_title={has_t}")
                if c > 500 and has_t:
                    print(f"      预览: {rt[:300]}")
                    (out_dir / f"bing_result_{c}.txt").write_text(rt, encoding='utf-8')
            except Exception as e:
                print(f"      -> 访问失败: {type(e).__name__}")
            await asyncio.sleep(0.3)

    await client.aclose()
    print("\n" + "="*70)
    print("  深挖完成，结果保存在 data/deepdive/")
    print("="*70)

asyncio.run(deep_dive())
