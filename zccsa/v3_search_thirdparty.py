#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终搜索：第三方转载、全文泄露、TXT下载
"""
import asyncio
import re
import urllib.parse
from pathlib import Path
import httpx
from bs4 import BeautifulSoup
from datetime import datetime

TITLE = "娇娇和她的忠犬小狗"

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

async def search():
    UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    async with httpx.AsyncClient(follow_redirects=True, verify=False, timeout=15) as client:
        results = []

        queries = [
            f"{TITLE} 全文阅读",
            f"{TITLE} TXT下载",
            f"{TITLE} 百度网盘",
            f"{TITLE} 知乎 免费",
            f"site:zhihu.com {TITLE}",
            f"娇娇和她的忠犬小狗 小说",
            f"{TITLE} 笔趣阁",
            f"{TITLE} 番外",
        ]

        print("搜索第三方转载/全文泄露...")
        print("="*60)
        best_url = None
        best_cn = 0
        best_text = ""

        for q in queries:
            print(f"\n搜索: {q}")
            # Bing搜索
            try:
                r = await client.get(f"https://www.bing.com/search?q={urllib.parse.quote(q)}",
                                    headers={"User-Agent": UA})
                if r.status_code == 200:
                    urls = re.findall(r'https?://[^\s"\'<>]+', r.text)
                    urls = [u.split('&')[0].rstrip('/') for u in urls
                            if any(d in u for d in ('.com', '.cn', '.net', '.org'))
                            and 'bing.com' not in u and 'microsoft.com' not in u]
                    urls = list(set(urls))[:8]
                    for url in urls:
                        try:
                            r2 = await client.get(url, headers={"User-Agent": UA}, timeout=10)
                            text = r2.text
                            has_title = TITLE[:5] in text
                            cn = cn_count(text)
                            soup = BeautifulSoup(text, 'html.parser')
                            for s in soup(['script','style','nav','footer']): s.decompose()
                            body = soup.get_text(separator='\n', strip=True)
                            cn_body = cn_count(body)
                            if has_title and cn_body > best_cn:
                                best_cn = cn_body
                                best_url = url
                                best_text = body
                                print(f"  ★ {url[:60]}... cn={cn_body}")
                                if cn_body > 1000:
                                    print(f"    Preview: {body[:300]}")
                            elif has_title:
                                print(f"    - {url[:60]}... cn={cn_body}")
                        except Exception as e:
                            pass
                        await asyncio.sleep(0.3)
            except Exception as e:
                print(f"  Search error: {e}")
            await asyncio.sleep(1)

        print("\n" + "="*60)
        print(f"最佳结果: {best_url}")
        print(f"中文字数: {best_cn}")
        if best_cn > 500:
            print(f"\n内容预览:\n{best_text[:1000]}")
            out = Path(f"/workspace/zccsa/reports/third_party_found_{best_cn}.txt")
            out.write_text(best_text, encoding='utf-8')
            print(f"\n保存到: {out}")

        return best_url, best_cn, best_text

asyncio.run(search())
