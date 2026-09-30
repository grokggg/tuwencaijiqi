#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZCCSA-Auto v3.2 - App API直接探测
"""
import asyncio
import json
import re
import subprocess
import urllib.parse
from datetime import datetime
from pathlib import Path
from bs4 import BeautifulSoup
import httpx

UA_APP = "ZhihuHybrid-iOS/8.10.0 (com.zhihu.ios; build:2400; iOS 16.0.0)"
UA_APP_ANDROID = "ZhihuHybrid-Android/8.10.0 (com.zhihu.android; build:2400; Android 13)"
UA_WEREAD = "WeRead/6.0.4 (iPhone; iOS 16.0; Scale/3.00) AppleWebKit/605.1.15"

AID = "1979959692122943787"
CID = "1979976139138147736"

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

async def test_api():
    async with httpx.AsyncClient(follow_redirects=True, verify=False, timeout=15) as client:
        # 真正的知乎App API端点
        apis = [
            # App API v4
            f"https://api.zhihu.com/market/sections/{AID}",
            f"https://api.zhihu.com/market/columns/{CID}/sections/{AID}",
            f"https://api.zhihu.com/knowledge/sections/{AID}",
            f"https://api.zhihu.com/knowledge/columns/{CID}/sections/{AID}",
            f"https://api.zhihu.com/remix/sections/{AID}",
            f"https://api.zhihu.com/paid/sections/{AID}",
            f"https://api.zhihu.com/salt/sections/{AID}",
            f"https://api.zhihu.com/v4/market/sections/{AID}?include=content",
            f"https://api.zhihu.com/v5/market/sections/{AID}?include=content",
            # 微信读书合作API
            f"https://api.zhihu.com/partners/weread/sections/{AID}",
            f"https://weread.qq.com/wrpage/book/zhihu/{AID}",
            f"https://i.weread.qq.com/book/zhihu/{AID}",
            # 其他
            f"https://www.zhihu.com/api/v4/market/sections/{AID}",
            f"https://www.zhihu.com/api/v5/market/sections/{AID}",
            f"https://www.zhihu.com/appview/market/paid_column/{CID}/section/{AID}",
            f"https://www.zhihu.com/appview/p/{AID}",
        ]

        headers_list = [
            {"User-Agent": UA_APP, "X-App-Version": "8.10.0", "X-Api-Version": "3.0.40",
             "X-App-Build": "2400", "Accept": "application/json"},
            {"User-Agent": UA_APP_ANDROID, "X-App-Version": "8.10.0", "Accept": "application/json"},
            {"User-Agent": UA_WEREAD, "X-Partner-Id": "weread", "Accept": "application/json"},
            {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X)",
             "Accept": "text/html,application/json"},
        ]

        print("="*70)
        print("API端点探测（直接请求App API）")
        print("="*70)
        results = []
        for api in apis:
            for i, h in enumerate(headers_list):
                try:
                    r = await client.get(api, headers=h)
                    text = r.text
                    cn = cn_count(text)
                    # 尝试解析JSON content
                    content_cn = 0
                    try:
                        data = json.loads(text)
                        def find_c(obj, depth=0):
                            nonlocal content_cn
                            if depth > 5: return
                            if isinstance(obj, dict):
                                for k, v in obj.items():
                                    if k in ('content', 'body', 'content_html') and isinstance(v, str):
                                        content_cn = max(content_cn, cn_count(v))
                                    else:
                                        find_c(v, depth+1)
                            elif isinstance(obj, list):
                                for it in obj:
                                    find_c(it, depth+1)
                        find_c(data)
                    except:
                        pass
                    max_cn = max(cn, content_cn)
                    # 看状态码和错误信息
                    err = ""
                    try:
                        d = json.loads(text)
                        err = d.get('error', {}).get('message', '')[:50] if isinstance(d.get('error'), dict) else str(d.get('error',''))[:50]
                    except:
                        pass
                    if r.status_code != 404 or max_cn > 0:
                        print(f"[{r.status_code}] api={api[8:50]}... h{i} cn={max_cn} {err}")
                        if max_cn > 100:
                            print(f"  >>> CONTENT FOUND! length={len(text)}")
                            # 保存到文件
                            out = Path(f"/workspace/zccsa/reports/found_{max_cn}.json")
                            out.write_text(text, encoding='utf-8')
                            print(f"  Saved to: {out}")
                            results.append((api, h, text, max_cn))
                except Exception as e:
                    pass
                await asyncio.sleep(0.15)

        # 尝试用curl直接请求，带更多App头
        print("\n" + "="*70)
        print("Curl原生请求（带完整App签名头）")
        print("="*70)
        import subprocess
        curl_headers = [
            "-H", "User-Agent: ZhihuHybrid-iOS/8.10.0 (com.zhihu.ios; build:2400; iOS 16.0.0)",
            "-H", "X-Api-Version: 3.0.40",
            "-H", "X-App-Version: 8.10.0",
            "-H", "X-App-Build: 2400",
            "-H", "X-App-Device: iPhone14,2",
            "-H", "X-OS-Version: 16.0.0",
            "-H", "X-Network-Type: WiFi",
            "-H", "Accept: application/json",
            "-H", "Accept-Language: zh-Hans-CN;q=1",
        ]
        for api in [f"https://api.zhihu.com/market/sections/{AID}",
                    f"https://api.zhihu.com/appview/market/paid_column/{CID}/section/{AID}",
                    f"https://www.zhihu.com/appview/market/paid_column/{CID}/section/{AID}"]:
            cmd = ["curl", "-s", "-L", "--max-time", "15", "-w", "\n%{http_code}"] + curl_headers + [api]
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            parts = r.stdout.rsplit("\n", 1)
            body = parts[0] if len(parts)==2 else r.stdout
            try:
                status = int(parts[1]) if len(parts)==2 else 0
            except:
                status = 0
            cn = cn_count(body)
            print(f"[{status}] {api[8:60]} cn={cn}")
            try:
                d = json.loads(body)
                # 递归查找content
                max_c = 0
                ctext = ""
                def walk(o, d=0):
                    nonlocal max_c, ctext
                    if d>6: return
                    if isinstance(o, dict):
                        for k,v in o.items():
                            if k in ('content','content_html','body') and isinstance(v,str) and cn_count(v)>max_c:
                                max_c = cn_count(v)
                                ctext = v
                            walk(v, d+1)
                    elif isinstance(o, list):
                        for it in o: walk(it, d+1)
                walk(d)
                if max_c > 100:
                    print(f"  >>> CONTENT! cn={max_c}")
                    out = Path(f"/workspace/zccsa/reports/curl_found_{max_c}.json")
                    out.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding='utf-8')
                    print(f"  Saved to: {out}")
                else:
                    # 打印错误信息
                    e = d.get('error','')
                    if isinstance(e, dict):
                        e = e.get('message','')
                    print(f"  error: {str(e)[:100]}")
            except Exception as e:
                if '安全验证' in body or '验证' in body:
                    print("  -> 安全验证页面")
                else:
                    print(f"  not json, len={len(body)}")

        print("\n" + "="*70)
        print("总结")
        print("="*70)
        print(f"找到 {len(results)} 个可能有内容的响应")
        return results

asyncio.run(test_api())
