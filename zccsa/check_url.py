#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""快速检查URL内容"""
import httpx
import re
import urllib.parse
from bs4 import BeautifulSoup

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def count_cn(text):
    return len(re.findall(r'[\u4e00-\u9fff]', text))

async def check_url(url, headers=None):
    async with httpx.AsyncClient(follow_redirects=True, verify=False, timeout=15) as client:
        h = {"User-Agent": UA}
        if headers:
            h.update(headers)
        r = await client.get(url, headers=h)
        print(f"\nURL: {url}")
        print(f"Status: {r.status_code}")
        print(f"Content-Type: {r.headers.get('content-type', '')}")
        print(f"Total CN chars: {count_cn(r.text)}")

        # 尝试解析HTML
        if 'html' in r.headers.get('content-type', ''):
            soup = BeautifulSoup(r.text, 'html.parser')
            # 找文章内容
            for selector in ['.Post-RichText', '.RichText', 'article', '.post-content', '.ContentItem']:
                el = soup.select_one(selector)
                if el:
                    text = el.get_text(separator='\n', strip=True)
                    print(f"Found '{selector}': {count_cn(text)} CN chars")
                    if count_cn(text) > 100:
                        print(f"Preview: {text[:500]}")
                        return text
            # 找title
            title = soup.find('h1')
            if title:
                print(f"Title: {title.get_text(strip=True)}")
            # 检查是否有付费墙
            if '付费' in r.text or '会员' in r.text or '盐选' in r.text:
                print("Detected paywall/member keywords!")
                # 找截断标记
                if '开通会员' in r.text or '继续阅读' in r.text:
                    print("Found truncation marker: 开通会员/继续阅读")
        return r.text

import asyncio

async def main():
    # 检查找到的专栏文章
    await check_url("https://zhuanlan.zhihu.com/p/467392329")

    # 搜索盐选专栏文章
    print("\n" + "="*60)
    print("搜索盐选付费文章...")
    async with httpx.AsyncClient(follow_redirects=True, verify=False, timeout=15) as client:
        # 百度搜索盐选文章
        q = urllib.parse.quote("娇娇和她的忠犬小狗 盐选专栏 付费")
        r = await client.get(f"https://www.baidu.com/s?wd={q}", headers={"User-Agent": UA})
        urls = re.findall(r'https?://(?:www\.)?zhihu\.com/market/[^\s"\'<>]+', r.text)
        urls += re.findall(r'https?://(?:www\.)?zhihu\.com/[^\s"\'<>]*?paid[^\s"\'<>]*', r.text)
        print(f"Baidu found zhihu market URLs: {urls[:5]}")

        # 搜索盐选专栏
        q2 = urllib.parse.quote("site:zhihu.com/market 娇娇和她的忠犬小狗")
        r2 = await client.get(f"https://www.bing.com/search?q={q2}", headers={"User-Agent": UA})
        urls2 = re.findall(r'https?://(?:www\.)?zhihu\.com/[^\s"\'<>]+', r2.text)
        market_urls = [u for u in urls2 if 'market' in u or 'paid' in u]
        print(f"Bing found market URLs: {market_urls[:5]}")

asyncio.run(main())
