#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Phase 0: 全面网络侦察"""
import asyncio
import subprocess
import json
import re
import httpx

TARGET_TITLE = "娇娇和她的忠犬小狗"
ARTICLE_ID = "1979959692122943787"

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

async def test_url(client, name, url, headers=None, method="GET", timeout=10):
    try:
        r = await client.request(method, url, headers=headers or {}, timeout=timeout, follow_redirects=True)
        body = r.text[:2000]
        has_title = TARGET_TITLE[:4] in r.text
        cn = cn_count(r.text)
        print(f"  [{r.status_code}] {name:30s} cn={cn:5d} has_title={'Y' if has_title else 'N'} len={len(r.text)}")
        if r.status_code == 200 and cn > 100:
            print(f"       Preview: {body[:200].strip()[:150]}")
        return {"name": name, "url": url, "status": r.status_code, "cn": cn, "has_title": has_title}
    except Exception as e:
        etype = type(e).__name__
        print(f"  [ERR ] {name:30s} {etype}: {str(e)[:60]}")
        return {"name": name, "url": url, "status": 0, "cn": 0, "has_title": False, "error": etype}

async def main():
    print("="*70)
    print("  Phase 0: 全面网络侦察")
    print("="*70)

    UA_CHROME = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    UA_MOBILE = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1"
    client = httpx.AsyncClient(verify=False, timeout=10, follow_redirects=True,
                               headers={"User-Agent": UA_CHROME, "Accept-Language": "zh-CN,zh;q=0.9"})

    results = []

    # === 1. 搜索引擎可达性 ===
    print("\n[1] 搜索引擎可达性测试")
    print("-"*70)
    search_tests = [
        ("baidu", "https://www.baidu.com"),
        ("baidu_search", f"https://www.baidu.com/s?wd={TARGET_TITLE}"),
        ("bing", "https://www.bing.com"),
        ("bing_search", f"https://www.bing.com/search?q={TARGET_TITLE}+知乎"),
        ("bing_cn", "https://cn.bing.com"),
        ("sogou", "https://www.sogou.com"),
        ("sogou_search", f"https://www.sogou.com/web?query={TARGET_TITLE}"),
        ("sogou_weixin", f"https://weixin.sogou.com/weixin?type=2&query={TARGET_TITLE}"),
        ("360_search", f"https://www.so.com/s?q={TARGET_TITLE}"),
        ("toutiao_search", f"https://so.toutiao.com/search?keyword={TARGET_TITLE}"),
        ("google", "https://www.google.com"),
        ("google_search", f"https://www.google.com/search?q={TARGET_TITLE}"),
        ("duckduckgo", "https://duckduckgo.com/html/?q=" + TARGET_TITLE),
        ("yandex", "https://yandex.com/search/?text=" + TARGET_TITLE),
    ]
    for name, url in search_tests:
        r = await test_url(client, name, url)
        results.append(r)
        await asyncio.sleep(0.5)

    # === 2. 知乎各子域名/路径 ===
    print("\n[2] 知乎域名/路径测试")
    print("-"*70)
    zhihu_tests = [
        # 主站
        ("zhihu_main", "https://www.zhihu.com"),
        ("zhihu_mobile", "https://m.zhihu.com"),
        ("zhihu_zhuanlan", "https://zhuanlan.zhihu.com"),
        ("zhihu_api", "https://api.zhihu.com"),
        ("zhihu_drd", "https://drd.zhihu.com"),
        ("zhihu_lab", "https://lab.zhihu.com"),
        # 直接访问目标
        ("target_html", f"https://www.zhihu.com/market/paid_column/1979976139138147736/section/{ARTICLE_ID}"),
        ("target_appview", f"https://www.zhihu.com/appview/market/paid_column/1979976139138147736/section/{ARTICLE_ID}"),
        ("target_mobile", f"https://m.zhihu.com/market/paid_column/1979976139138147736/section/{ARTICLE_ID}"),
        ("target_zhuanlan", f"https://zhuanlan.zhihu.com/p/{ARTICLE_ID}"),
        # oEmbed
        ("oembed", f"https://www.zhihu.com/oembed?url=https://www.zhihu.com/market/paid_column/1979976139138147736/section/{ARTICLE_ID}"),
        # RSS
        ("rss", f"https://www.zhihu.com/rss"),
        # 专栏页
        ("column_page", f"https://www.zhihu.com/market/paid_column/1979976139138147736"),
        ("column_xen", f"https://www.zhihu.com/xen/market/remix/paid_column/1979976139138147736"),
    ]
    for name, url in zhihu_tests:
        r = await test_url(client, name, url)
        results.append(r)
        await asyncio.sleep(0.3)

    # === 3. 第三方内容平台搜索 ===
    print("\n[3] 第三方内容平台")
    print("-"*70)
    third_party = [
        ("weibo_search", f"https://s.weibo.com/weibo?q={TARGET_TITLE}"),
        ("douban_search", f"https://www.douban.com/search?q={TARGET_TITLE}"),
        ("jianbjian", f"https://www.jianshu.com/search?q={TARGET_TITLE}"),
        ("csdn_search", f"https://so.csdn.net/so/search?q={TARGET_TITLE}"),
        ("zhihu_zhuanlan_search", f"https://www.zhihu.com/search?type=content&q={TARGET_TITLE}"),
        ("toutiao", f"https://so.toutiao.com/search?keyword={TARGET_TITLE}+盐选"),
        ("baidu_zhidao", f"https://zhidao.baidu.com/search?word={TARGET_TITLE}"),
        ("baidu_tieba", f"https://tieba.baidu.com/f?kw={TARGET_TITLE}"),
        ("baidu_wenku", f"https://wenku.baidu.com/search?word={TARGET_TITLE}"),
        ("xiaohongshu", f"https://www.xiaohongshu.com/search_result?keyword={TARGET_TITLE}"),
        ("bilibili", f"https://search.bilibili.com/all?keyword={TARGET_TITLE}"),
        ("weread_search", f"https://weread.qq.com/web/search/global?keyword={TARGET_TITLE}"),
        ("qq_read", f"https://book.qq.com/search?kw={TARGET_TITLE}"),
    ]
    for name, url in third_party:
        r = await test_url(client, name, url)
        results.append(r)
        await asyncio.sleep(0.5)

    # === 4. curl测试（绕过httpx） ===
    print("\n[4] CURL原始请求测试")
    print("-"*70)
    curl_tests = [
        ("curl_zhihu_m", f"https://m.zhihu.com/market/paid_column/1979976139138147736/section/{ARTICLE_ID}",
         ["-A", UA_MOBILE]),
        ("curl_zhihu_http", f"http://www.zhihu.com/market/paid_column/1979976139138147736/section/{ARTICLE_ID}",
         ["-A", UA_CHROME]),
        ("curl_ipv4", f"https://www.zhihu.com/market/paid_column/1979976139138147736/section/{ARTICLE_ID}",
         ["-A", UA_CHROME, "-4"]),
        ("curl_bing_sogou", f"https://www.sogou.com/web?query={TARGET_TITLE}+全文",
         ["-A", UA_CHROME]),
    ]
    for name, url, opts in curl_tests:
        cmd = ["curl", "-s", "-L", "--max-time", "10", "-w", "\n%{http_code}"] + opts + [url]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            parts = r.stdout.rsplit("\n", 1)
            body = parts[0] if len(parts)==2 else r.stdout
            try: status = int(parts[1]) if len(parts)==2 else 0
            except: status = 0
            cn = cn_count(body)
            has_t = TARGET_TITLE[:4] in body
            print(f"  [{status}] {name:30s} cn={cn:5d} has_title={'Y' if has_t else 'N'} len={len(body)}")
            if status == 200 and cn > 200:
                print(f"       Preview: {body[:300].strip()[:200]}")
        except Exception as e:
            print(f"  [ERR ] {name:30s} {type(e).__name__}")

    # === 5. DNS/IP测试 ===
    print("\n[5] DNS解析测试")
    print("-"*70)
    for domain in ["www.zhihu.com", "api.zhihu.com", "zhuanlan.zhihu.com", "m.zhihu.com"]:
        try:
            r = subprocess.run(["dig", "+short", domain], capture_output=True, text=True, timeout=5)
            ips = r.stdout.strip().split("\n")
            print(f"  {domain:25s} -> {ips[:3]}")
        except:
            try:
                r = subprocess.run(["nslookup", domain], capture_output=True, text=True, timeout=5)
                for line in r.stdout.split("\n"):
                    if "Address" in line and not line.startswith("Server"):
                        print(f"  {domain:25s} -> {line.strip()}")
                        break
            except Exception as e:
                print(f"  {domain:25s} -> lookup failed: {e}")

    await client.aclose()

    # 总结
    print("\n" + "="*70)
    print("  侦察总结")
    print("="*70)
    reachable = [r for r in results if r.get("status", 0) == 200]
    has_content = [r for r in results if r.get("cn", 0) > 500]
    has_title = [r for r in results if r.get("has_title", False)]
    print(f"  可达(200): {len(reachable)}/{len(results)}")
    print(f"  有内容(>500cn): {len(has_content)}")
    print(f"  包含标题: {len(has_title)}")
    for r in has_title:
        print(f"    - {r['name']}: status={r['status']}, cn={r['cn']}")

    # 保存结果
    with open("/workspace/zccsa/data/recon_results.json", "w") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n  侦察结果已保存到 data/recon_results.json")

asyncio.run(main())
