#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""搜索小说站点获取全文 - 主角靳川、孟娇蕊"""
import asyncio
import re
import urllib.parse
from pathlib import Path
from bs4 import BeautifulSoup
import httpx

TITLE = "娇娇和她的忠犬小狗"
CHAR1 = "靳川"
CHAR2 = "孟娇蕊"

UA_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
UA_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1"

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

def extract_text(html):
    soup = BeautifulSoup(html, 'html.parser')
    for s in soup(['script','style','nav','footer','header']):
        s.decompose()
    return soup.get_text(separator='\n', strip=True)

async def search_and_fetch():
    client = httpx.AsyncClient(verify=False, timeout=15, follow_redirects=True,
                               headers={"User-Agent": UA_CHROME, "Accept-Language": "zh-CN,zh;q=0.9"})
    out_dir = Path("/workspace/zccsa/data/novel_search")
    out_dir.mkdir(parents=True, exist_ok=True)

    best_content = ""
    best_cn = 0
    best_source = ""
    best_url = ""

    # 搜索关键词组合
    queries = [
        f"{TITLE} 靳川 孟娇蕊 全文",
        f"{TITLE} 小说 免费阅读",
        f"{TITLE} 完整版",
        f"靳川 孟娇蕊 小说",
        f"{TITLE} txt下载",
        f"{TITLE} 知乎 盐选 后续",
        f"娇娇和她的忠犬小狗 番外",
    ]

    # 小说站点域名列表
    novel_domains = [
        "www.biquge.co", "www.biquge.com", "www.biquwx.la", "www.bqkan8.com",
        "www.xbiquge.la", "www.biquge5200.com", "www.ibiquge.info",
        "www.shuquge.com", "www.booktxt.net", "www.wenxuemi6.com",
        "www.jdxs520.com", "www.23us.la", "www.23wx.la", "www.toshuw.com",
        "www.sanjiange.com", "wap.sanjiange.com", "www.xiaomawenxue.com",
        "www.ptwxz.com", "www.zuowenchina.com", "www.shupeng.com",
        "www.qidian.com", "www.zongheng.com", "www.jjwxc.net",
        "www.17k.com", "www.hongxiu.com", "www.xs.la",
        "m.630book.com", "www.630book.la", "www.63shu.com",
        "www.bequge.com", "www.dingdiann.com", "www.xxbiquge.com",
        "www.biqubao.com", "www.biqumo.com", "www.biquge5200.cc",
        "www.mianhuatang.la", "www.biqugex.com", "www.biqug.net",
        "www.lwxs.com", "www.lwxs520.com", "www.81xsw.com",
        "www.xbiquwx.com", "www.bswtan.com", "www.biquge.lu",
    ]

    print("="*70)
    print("  小说全文搜索 - 多引擎+多关键词")
    print("="*70)

    for qi, query in enumerate(queries):
        print(f"\n[搜索{qi+1}/{len(queries)}] {query}")

        # Bing搜索
        try:
            bing_url = f"https://www.bing.com/search?q={urllib.parse.quote(query)}&count=20"
            r = await client.get(bing_url)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, 'html.parser')
                links = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    text = a.get_text(strip=True)
                    if href.startswith('http') and 'bing.com' not in href and 'microsoft.com' not in href:
                        # 检查是否是小说相关链接
                        novel_kw = ['小说', '阅读', '全文', '免费', '章节', 'txt', '书库', '番外', '完结']
                        is_novel = any(k in text for k in novel_kw) or any(d in href for d in novel_domains)
                        has_title = TITLE[:3] in text or CHAR1 in text or CHAR2 in text
                        if (is_novel or has_title) and len(text) > 5:
                            links.append((text, href))

                print(f"  Bing找到{len(links)}个相关链接")
                for text, href in links[:8]:
                    print(f"    {text[:50]} -> {href[:70]}")
                    try:
                        rr = await client.get(href, timeout=10)
                        if rr.status_code == 200:
                            body_text = extract_text(rr.text)
                            has_all = (CHAR1 in rr.text and CHAR2 in rr.text) or TITLE[:4] in rr.text
                            c = cn_count(body_text)
                            # 如果页面包含主角名且字数较多，可能是正文
                            if has_all and c > 500:
                                print(f"      ★★★ 发现正文! cn={c}, 含主角名")
                                print(f"      预览: {body_text[:300]}")
                                if c > best_cn:
                                    best_cn = c
                                    best_content = body_text
                                    best_source = f"bing:{text[:30]}"
                                    best_url = href
                                    (out_dir / f"best_{c}.txt").write_text(body_text, encoding='utf-8')
                                    if c > 2000:
                                        print(f"      >>> 达到成功阈值!")
                                        # 检查是否有章节列表/下一章链接
                                        soup2 = BeautifulSoup(rr.text, 'html.parser')
                                        next_links = []
                                        for na in soup2.find_all('a', href=True):
                                            nt = na.get_text(strip=True)
                                            nh = na['href']
                                            if any(k in nt for k in ['下一章', '下一页', '下一章', '继续阅读', '章节列表', '正文']):
                                                next_links.append((nt, nh))
                                        if next_links:
                                            print(f"      发现{len(next_links)}个章节导航链接")
                            elif has_all:
                                print(f"      cn={c} (含主角名但内容较少)")
                    except Exception as e:
                        pass
                    await asyncio.sleep(0.3)
        except Exception as e:
            print(f"  Bing搜索失败: {e}")

        await asyncio.sleep(1)

        # 百度搜索（重点搜索小说站）
        try:
            bd_url = f"https://www.baidu.com/s?wd={urllib.parse.quote(query)}&rn=20"
            r = await client.get(bd_url)
            if r.status_code == 200:
                # 百度的链接需要从跳转链接提取
                bd_links = re.findall(r'href="(https?://www\.baidu\.com/link\?[^"]+)"', r.text)
                # 直接找目标URL
                direct_urls = re.findall(r'(https?://(?:www\.)?(?:[a-zA-Z0-9]+\.)+(?:com|cn|net|la|lu|cc|me|io|info|org)/[^\s"\'<>"]+)', r.text)
                novel_urls = [u for u in direct_urls if any(d in u for d in novel_domains) or '小说' in r.text[max(0,r.text.find(u)-200):r.text.find(u)+200]]
                novel_urls = list(set(novel_urls))[:5]
                print(f"  百度找到{len(novel_urls)}个小说站链接")
                for nu in novel_urls:
                    print(f"    {nu[:80]}")
                    try:
                        rr = await client.get(nu, timeout=10)
                        if rr.status_code == 200:
                            bt = extract_text(rr.text)
                            c = cn_count(bt)
                            has_all = CHAR1 in rr.text and CHAR2 in rr.text
                            if has_all and c > 500:
                                print(f"      ★ cn={c}, 含主角名!")
                                if c > best_cn:
                                    best_cn = c
                                    best_content = bt
                                    best_source = f"baidu:{nu[:30]}"
                                    best_url = nu
                                    (out_dir / f"best_bd_{c}.txt").write_text(bt, encoding='utf-8')
                    except:
                        pass
                    await asyncio.sleep(0.3)
        except Exception as e:
            print(f"  百度搜索失败: {e}")

        await asyncio.sleep(1)

    # 直接尝试一些常见小说搜索路径
    print(f"\n\n{'='*70}")
    print("  直接尝试小说站搜索接口")
    print("="*70)
    novel_search_apis = [
        # 笔趣阁类
        ("biquge", f"https://www.biquge.co/search.php?q={urllib.parse.quote(TITLE)}"),
        ("bqg5200", f"https://www.biquge5200.com/search.php?q={urllib.parse.quote(TITLE)}"),
        # 69书吧
        ("69shu", f"https://www.69shu.com/modules/article/search.php?searchkey={urllib.parse.quote(TITLE)}"),
        # 言情小说
        ("txt99", f"https://www.txt99.org/search/{urllib.parse.quote(TITLE)}"),
    ]
    for name, url in novel_search_apis:
        try:
            r = await client.get(url, timeout=10, headers={"User-Agent": UA_MOBILE})
            print(f"  {name}: status={r.status_code}, len={len(r.text)}")
            if r.status_code == 200 and len(r.text) > 1000:
                bt = extract_text(r.text)
                c = cn_count(bt)
                has_chars = CHAR1 in r.text or CHAR2 in r.text
                print(f"    cn={c}, has_chars={has_chars}")
                # 提取小说页面链接
                soup = BeautifulSoup(r.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    at = a.get_text(strip=True)
                    ah = a['href']
                    if TITLE[:3] in at or (CHAR1 in at and CHAR2 in at):
                        if not ah.startswith('http'):
                            ah = url.split('/')[0] + '//' + url.split('/')[2] + ah
                        print(f"    小说链接: {at[:30]} -> {ah[:70]}")
                        try:
                            rr = await client.get(ah, timeout=10)
                            if rr.status_code == 200:
                                rt = extract_text(rr.text)
                                rc = cn_count(rt)
                                if rc > best_cn and CHAR1 in rr.text:
                                    best_cn = rc
                                    best_content = rt
                                    best_source = name
                                    best_url = ah
                                    (out_dir / f"direct_{name}_{rc}.txt").write_text(rt, encoding='utf-8')
                                    print(f"    ★ 新纪录 cn={rc}")
                        except:
                            pass
        except Exception as e:
            print(f"  {name}: {type(e).__name__}")
        await asyncio.sleep(0.5)

    await client.aclose()

    print(f"\n\n{'='*70}")
    print("  搜索完成")
    print(f"{'='*70}")
    print(f"  最佳结果: {best_cn}字")
    print(f"  来源: {best_source}")
    print(f"  URL: {best_url}")

    if best_cn > 500:
        print(f"\n  内容预览:")
        print(f"  {best_content[:500]}")

    return best_content, best_cn, best_source, best_url

asyncio.run(search_and_fetch())
