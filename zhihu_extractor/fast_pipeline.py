#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
快速管线 - 分步骤执行，每步立即保存结果
"""
import sys, os, json, re, subprocess, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from core.http_engine import HTTPEngine
from core.content_parser import ContentParser
from config import TARGET, USER_AGENTS, OUTPUT_DIR

def main():
    http = HTTPEngine({'timeout': 12, 'max_retries': 3, 'retry_delay': 1.0, 'rate_limit': 0.3})
    parser = ContentParser()
    ua_m = USER_AGENTS['mobile_iphone']
    ua_pc = USER_AGENTS['desktop_chrome']

    all_chapters = []
    extra_content = []

    # ========== 步骤1: 快速提取kepue 5章 ==========
    print("=" * 50)
    print("步骤1: 提取kepue.com 5章内容")
    print("=" * 50)

    for ch in range(1, 6):
        url = f'https://m.kepue.com/nvpin/38738/{ch}/'
        status, html, _ = http.get(url, ua=ua_m, timeout=12, retries=3)
        if status == 200 and html:
            content = parser.extract_content(html, url)
            v = parser.validate_content(content, TARGET)
            if v["is_valid"]:
                all_chapters.append({
                    "chapter": ch,
                    "content": content,
                    "char_count": v["char_count"],
                    "confidence": v["confidence"],
                })
                print(f"  ✓ 第{ch}章: {v['char_count']}字 (置信度={v['confidence']:.2f})")
            else:
                print(f"  ✗ 第{ch}章: 验证失败")
        else:
            print(f"  ✗ 第{ch}章: HTTP {status}")

    # 立即保存
    if all_chapters:
        save_chapters(all_chapters)

    # ========== 步骤2: 搜索额外内容 ==========
    print("\n" + "=" * 50)
    print("步骤2: 搜索额外内容（5章之外）")
    print("=" * 50)

    # 2a. 必应搜索
    print("\n--- 必应搜索 ---")
    bing_queries = [
        '"娇娇和她的忠犬小狗" 全文 阅读',
        '"孟娇蕊" "靳川" 小说 全文',
        '"婚后一年老公从不碰我" 完结 全文',
        'site:mp.weixin.qq.com "娇娇和她的忠犬小狗"',
        '"孟娇蕊天天穿的骚里骚气"',
    ]
    discovered_urls = []
    for q in bing_queries:
        url = f'https://cn.bing.com/search?q={quote(q)}'
        status, html, _ = http.get(url, ua=ua_pc, timeout=8, retries=1)
        if not html:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for li in soup.select('li.b_algo'):
            a = li.find('a', href=True)
            if a:
                href = a['href']
                text = a.get_text(strip=True)
                snippet_div = li.find('div', class_='b_caption')
                snippet = snippet_div.get_text(strip=True)[:100] if snippet_div else ''
                if any(kw in text+snippet for kw in ['靳川', '孟娇蕊', '娇娇', '忠犬', '婚后一年', '傅柏文']):
                    if href.startswith('http') and 'bing.com' not in href and 'baike.baidu' not in href:
                        discovered_urls.append({"url": href, "title": text[:60], "snippet": snippet[:100]})
                        print(f"  发现: {text[:40]}")

    # 2b. 搜狗微信搜索 - 收集片段
    print("\n--- 搜狗微信搜索 ---")
    all_snippets = []
    for q in ['娇娇和她的忠犬小狗 靳川', '孟娇蕊 靳川 小说', '娇娇和她的忠犬小狗 大结局 番外']:
        url = f'https://weixin.sogou.com/weixin?type=2&query={quote(q)}'
        status, html, _ = http.get(url, ua=ua_m, timeout=10, retries=1)
        if not html or len(html) < 500:
            continue
        soup = BeautifulSoup(html, 'html.parser')
        for item in soup.select('div.txt-box, div.news-box, li'):
            text = item.get_text(separator=' ', strip=True)
            # 提取包含新内容的片段
            if any(kw in text for kw in ['骚里骚气', '人心不是铁做', '怕女配讨厌自己', '忠犬糙汉', '澄清这件事']):
                patterns = re.findall(r'[\u4e00-\u9fff，。！？、「」【】（）\(\)~\s]{15,}', text)
                for p in patterns:
                    p = p.strip()
                    if any(kw in p for kw in ['靳川', '孟娇蕊', '娇娇', '弹幕', '媳妇', '男主', '女配']):
                        if p not in all_snippets and len(p) > 20:
                            all_snippets.append(p)

    if all_snippets:
        print(f"  收集到 {len(all_snippets)} 个新内容片段")
        for s in all_snippets[:5]:
            print(f"  - {s[:80]}...")

    # 2c. 访问发现的URL
    print(f"\n--- 访问发现的URL ({len(discovered_urls)}个) ---")
    for item in discovered_urls[:10]:
        url = item["url"]
        if 'weixin.sogou.com/link' in url:
            continue  # 跳过需要JS的搜狗跳转
        if 'zhihu.com' in url:
            continue  # 跳过知乎（已知付费墙）
        status, html, _ = http.get(url, timeout=8, retries=1)
        if not html or len(html) < 500:
            continue
        content = parser.extract_content(html, url)
        if parser.count_chinese(content) > 50:
            v = parser.validate_content(content, TARGET)
            if v["is_valid"]:
                extra_content.append({
                    "source": url,
                    "title": item["title"],
                    "content": content,
                    "char_count": v["char_count"],
                    "confidence": v["confidence"],
                })
                print(f"  ✓ {item['title'][:40]}: {v['char_count']}字")

    # ========== 步骤3: 聚合内容 ==========
    print("\n" + "=" * 50)
    print("步骤3: 聚合内容")
    print("=" * 50)

    final_content = assemble_content(all_chapters, extra_content, all_snippets)
    save_final(final_content, all_chapters, extra_content, all_snippets, http.get_stats())

    print(f"\n完成! 共 {len(all_chapters)} 章, {sum(c['char_count'] for c in all_chapters)} 字")
    if extra_content:
        print(f"额外内容: {len(extra_content)} 条, {sum(c['char_count'] for c in extra_content)} 字")
    if all_snippets:
        print(f"搜索片段: {len(all_snippets)} 个")


def save_chapters(chapters):
    """立即保存章节内容"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, "chapters.json")
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(chapters, f, ensure_ascii=False, indent=2)
    print(f"  章节已保存: {path}")


def assemble_content(chapters, extra, snippets):
    """聚合所有内容"""
    lines = []
    lines.append("# 《娇娇和她的忠犬小狗》")
    lines.append("")
    lines.append("| 字段 | 值 |")
    lines.append("|------|-----|")
    lines.append("| **文章ID** | 1979959692122943787 |")
    lines.append("| **来源** | 知乎盐选《边月忠犬》专栏 |")
    lines.append(f"| **已获取章节** | {len(chapters)}章 |")
    lines.append(f"| **总字数** | 约{sum(c['char_count'] for c in chapters)}字 |")
    lines.append("| **主角** | 孟娇蕊（娇娇/女配）、靳川（忠犬男主） |")
    lines.append("| **获取方式** | kepue.com（科普小说网）免费转载 |")
    lines.append("")
    lines.append("---")
    lines.append("")

    for ch in sorted(chapters, key=lambda x: x['chapter']):
        lines.append(f"## 第{ch['chapter']}章")
        lines.append("")
        lines.append(ch['content'])
        lines.append("")

    if extra:
        lines.append("## 补充内容（来自其他来源）")
        lines.append("")
        for e in extra:
            lines.append(f"### {e['title']}")
            lines.append(f"来源: {e['source']}")
            lines.append("")
            lines.append(e['content'])
            lines.append("")

    if snippets:
        lines.append("## 搜索发现的内容片段（5章之外）")
        lines.append("")
        lines.append("以下片段来自搜狗微信搜索结果，属于原文5章之外的额外内容：")
        lines.append("")
        seen = set()
        for s in snippets:
            if s not in seen:
                seen.add(s)
                lines.append(f"- {s}")
                lines.append("")

    return '\n'.join(lines)


def save_final(content, chapters, extra, snippets, stats):
    """保存最终结果"""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # 保存Markdown
    md_path = os.path.join(OUTPUT_DIR, "娇娇和她的忠犬小狗_完整版.md")
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"  完整版已保存: {md_path}")

    # 保存JSON结果
    json_path = os.path.join(OUTPUT_DIR, "results.json")
    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump({
            "chapters": [{"chapter": c['chapter'], "char_count": c['char_count'], "confidence": c['confidence']} for c in chapters],
            "extra_content": [{"source": e['source'], "char_count": e['char_count']} for e in extra],
            "snippets_count": len(snippets),
            "http_stats": stats,
        }, f, ensure_ascii=False, indent=2)
    print(f"  结果摘要已保存: {json_path}")


if __name__ == "__main__":
    main()
