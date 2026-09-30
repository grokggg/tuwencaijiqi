#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
内部服务回源测试脚本
使用 curl_cffi 伪装 Chrome 120 TLS 指纹，测试内部请求头组合
"""

import uuid
import re
import json
from itertools import product
from curl_cffi import requests as curl_requests

TARGET_URL = "https://www.zhihu.com/market/paid_column/1979976139138147736/section/1979959692122943787"
SUCCESS_THRESHOLD = 2000
OUTPUT_FILE = "/workspace/internal_bypass_success.md"

# 基础浏览器头（Chrome 120）
BASE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
}

# 内部服务调用头组
INTERNAL_HEADERS_GROUP = {
    "X-Forwarded-For": "127.0.0.1",
    "X-Real-IP": "127.0.0.1",
    "X-Request-ID": str(uuid.uuid4()),
    "X-Zhihu-Internal": "true",
    "X-Service": "search-index",
    "X-Caller": "ssr-service",
    "X-From": "zhihu-frontend",
}

# SEO SSR服务头组
SEO_HEADERS_VARIANTS = [
    {},  # 不使用SEO头
    {
        "User-Agent": "Mozilla/5.0 (compatible; ZhihuSearchBot/1.0; +https://www.zhihu.com/robots)",
        "X-Purpose": "seo-render",
        "X-Render-Engine": "v8",
    },
    {
        "User-Agent": "ZhihuRender/1.0",
        "X-Purpose": "seo-render",
        "X-Render-Engine": "v8",
    },
]

# 缓存/回源头组
CACHE_HEADERS_VARIANTS = [
    {},  # 不使用缓存头
    {
        "X-Cache-Purge": "true",
        "X-Refresh-Cache": "true",
        "X-No-Cache": "false",
        "Cache-Control": "no-store, must-revalidate",
    },
    {
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    },
]

# 内部头开关组合
INTERNAL_VARIANTS = [
    {},  # 不加内部头
    INTERNAL_HEADERS_GROUP,  # 加全部内部头
]

def count_chinese(text):
    """统计中文字符数"""
    return len(re.findall(r'[\u4e00-\u9fff]', text))

def extract_article_content(html):
    """从HTML中提取可能的文章内容"""
    # 尝试提取初始数据中的内容
    patterns = [
        r'"content":"(.*?)","copyrightPermission',
        r'"content":"(.*?)","isVipContent',
        r'<div[^>]*class="[^"]*RichText[^"]*"[^>]*>(.*?)</div>',
        r'<article[^>]*>(.*?)</article>',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, html, re.DOTALL)
        if matches:
            return max(matches, key=len)
    return html

def test_combination(combo_name, headers):
    """测试单个请求头组合"""
    print(f"\n[*] 测试组合: {combo_name}")
    try:
        resp = curl_requests.get(
            TARGET_URL,
            headers=headers,
            impersonate="chrome120",
            timeout=30,
            allow_redirects=True,
        )
        print(f"    状态码: {resp.status_code}")
        print(f"    响应长度: {len(resp.text)} 字符")
        
        chinese_count = count_chinese(resp.text)
        print(f"    中文字符数: {chinese_count}")
        
        # 检查是否包含付费墙关键词
        paywall_keywords = ['开通会员', '付费内容', '最低 0.3', '查看完整', 'salt', 'vip_content']
        has_paywall = any(kw in resp.text for kw in paywall_keywords)
        print(f"    付费墙标记: {'是' if has_paywall else '否'}")
        
        # 提取可能的正文区域
        content = extract_article_content(resp.text)
        content_chinese = count_chinese(content)
        print(f"    正文区域汉字: {content_chinese}")
        
        success = chinese_count > SUCCESS_THRESHOLD or content_chinese > SUCCESS_THRESHOLD
        print(f"    结果: {'✓ 成功' if success else '✗ 未通过'}")
        
        return {
            "success": success,
            "status_code": resp.status_code,
            "total_chars": len(resp.text),
            "chinese_chars": chinese_count,
            "content_chinese": content_chinese,
            "has_paywall": has_paywall,
            "response_text": resp.text,
            "headers": headers,
        }
    except Exception as e:
        print(f"    请求失败: {str(e)}")
        return {
            "success": False,
            "error": str(e),
        }

def main():
    print("=" * 70)
    print("知乎内部服务回源测试脚本")
    print("目标URL:", TARGET_URL)
    print("TLS指纹: Chrome 120")
    print("成功阈值: 中文字符 >", SUCCESS_THRESHOLD)
    print("=" * 70)
    
    # 生成所有组合
    combos = []
    combo_id = 0
    
    for internal_h, seo_h, cache_h in product(INTERNAL_VARIANTS, SEO_HEADERS_VARIANTS, CACHE_HEADERS_VARIANTS):
        combo_id += 1
        headers = {}
        headers.update(BASE_HEADERS)
        
        # 设置默认UA（如果SEO头中没有指定）
        if "User-Agent" not in seo_h:
            headers["User-Agent"] = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        
        headers.update(internal_h)
        headers.update(seo_h)
        headers.update(cache_h)
        
        combo_name_parts = []
        if internal_h:
            combo_name_parts.append("内部头")
        if seo_h:
            combo_name_parts.append("SEO头")
        if cache_h:
            combo_name_parts.append("缓存头")
        if not combo_name_parts:
            combo_name_parts.append("基线（仅浏览器头）")
        
        combo_name = f"#{combo_id} " + "+".join(combo_name_parts)
        combos.append((combo_name, headers))
    
    print(f"\n共生成 {len(combos)} 种请求头组合，开始测试...\n")
    
    # 测试所有组合
    results = []
    first_success = None
    
    for combo_name, headers in combos:
        result = test_combination(combo_name, headers)
        result["combo_name"] = combo_name
        results.append(result)
        
        if result.get("success") and first_success is None:
            first_success = result
            print(f"\n[!] 发现成功组合: {combo_name}")
            # 不立即break，继续测试更多组合收集信息，但优先记录第一个成功
    
    # 总结结果
    print("\n" + "=" * 70)
    print("测试结果汇总")
    print("=" * 70)
    
    success_count = sum(1 for r in results if r.get("success"))
    print(f"总组合数: {len(results)}")
    print(f"成功组合数: {success_count}")
    
    # 找出汉字数最多的结果
    best_result = max(results, key=lambda r: r.get("chinese_chars", 0) if not r.get("error") else 0)
    print(f"最佳响应: {best_result['combo_name']}")
    print(f"  状态码: {best_result.get('status_code')}")
    print(f"  总字符: {best_result.get('total_chars')}")
    print(f"  汉字数: {best_result.get('chinese_chars')}")
    print(f"  付费墙: {'有' if best_result.get('has_paywall') else '无'}")
    
    # 保存最佳结果（优先使用成功的，否则保存汉字最多的）
    save_result = first_success if first_success else best_result
    
    output_lines = []
    output_lines.append("# 知乎内部回源测试结果\n")
    output_lines.append(f"**测试时间**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    output_lines.append(f"**目标URL**: {TARGET_URL}\n")
    output_lines.append(f"**成功组合**: {save_result['combo_name']}\n")
    output_lines.append(f"**状态码**: {save_result.get('status_code')}\n")
    output_lines.append(f"**总字符数**: {save_result.get('total_chars')}\n")
    output_lines.append(f"**汉字数**: {save_result.get('chinese_chars')}\n")
    output_lines.append(f"**付费墙**: {'有' if save_result.get('has_paywall') else '无'}\n")
    output_lines.append("\n## 使用的请求头\n")
    output_lines.append("```json\n")
    output_lines.append(json.dumps(save_result.get("headers", {}), ensure_ascii=False, indent=2))
    output_lines.append("\n```\n")
    output_lines.append("\n## 响应内容（前5000字符）\n")
    output_lines.append("```html\n")
    output_lines.append(save_result.get("response_text", "")[:5000])
    output_lines.append("\n```\n")
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(output_lines))
    
    print(f"\n结果已保存到: {OUTPUT_FILE}")
    
    # 打印所有组合的简要结果
    print("\n各组合详细结果:")
    for r in results:
        status = "✓" if r.get("success") else "✗"
        chars = r.get("chinese_chars", 0)
        paywall = "有付费墙" if r.get("has_paywall") else "无付费墙"
        print(f"  {status} {r['combo_name']}: 汉字{chars} | {paywall}")

if __name__ == "__main__":
    main()
