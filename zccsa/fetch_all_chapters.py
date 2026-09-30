#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""遍历kepue.com所有章节，拼接完整小说"""
import subprocess
import re
import time
from pathlib import Path
from bs4 import BeautifulSoup

BASE_URL = "https://kepue.com/nvpin/38738/"
CHAPTER_URL = "https://kepue.com/nvpin/38738/{}/"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 Version/16.0 Mobile/15E148 Safari/604.1"
CHAR1 = "靳川"

out = Path("/workspace/zccsa")

def cn_count(t):
    return len(re.findall(r'[\u4e00-\u9fff]', t or ""))

def curl(url, referer=None, timeout=12):
    cmd = ["curl", "-s", "-L", "--max-time", str(timeout), "-A", UA,
           "--compressed", "-c", "/tmp/c5.txt", "-b", "/tmp/c5.txt",
           "-w", "\n__STATUS__%{http_code}"]
    if referer:
        cmd.extend(["-e", referer])
    cmd.append(url)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+3)
        parts = r.stdout.rsplit("__STATUS__", 1)
        body = parts[0] if len(parts)==2 else r.stdout
        try: status = int(parts[1]) if len(parts)==2 else 0
        except: status = 0
        return status, body
    except:
        return 0, ""

def extract_chapter_content(html):
    """从章节页提取正文，需要找到正文div"""
    soup = BeautifulSoup(html, 'html.parser')
    for s in soup(['script','style','nav','footer','header','a']):
        s.decompose()
    # 尝试常见正文选择器
    for sel in ['#content', '.content', '#chaptercontent', '.chapter-content',
                '.read-content', '.article-content', '#BookText', '.txt',
                '#htmlContent', '.novel-content', '.showtxt', '.article-con']:
        el = soup.select_one(sel)
        if el:
            t = el.get_text(separator='\n', strip=True)
            if cn_count(t) > 100:
                return t
    # 如果找不到特定div，取所有p标签
    ps = soup.find_all('p')
    if ps:
        t = '\n'.join(p.get_text(strip=True) for p in ps if p.get_text(strip=True))
        if cn_count(t) > 100:
            return t
    # 取最大的文本块
    text = soup.get_text(separator='\n', strip=True)
    return text

# 第一步：获取目录页，找最大章节号
print("="*70)
print("获取章节目录页...")
print("="*70)
s, catalog_html = curl(BASE_URL)
print(f"目录页: status={s}, len={len(catalog_html)}")
(out / "data/catalog.html").write_text(catalog_html, encoding='utf-8')

# 提取所有章节链接
soup = BeautifulSoup(catalog_html, 'html.parser')
chapter_urls = []
for a in soup.find_all('a', href=True):
    href = a['href']
    t = a.get_text(strip=True)
    if re.match(r'^/?nvpin/38738/\d+/?$', href) or re.search(r'nvpin/38738/\d+', href):
        m = re.search(r'nvpin/38738/(\d+)', href)
        if m:
            ch_num = int(m.group(1))
            ch_title = t if t else f"第{ch_num}章"
            chapter_urls.append((ch_num, ch_title, f"https://kepue.com/nvpin/38738/{ch_num}/"))

# 去重并排序
chapter_urls = sorted(list(set(chapter_urls)), key=lambda x: x[0])
print(f"从目录页找到 {len(chapter_urls)} 个章节链接")

# 如果目录页没找到足够章节，自动探测
if len(chapter_urls) < 5:
    print("目录页链接不足，开始自动探测章节号...")
    max_ch = 1
    for ch in range(1, 200):
        url = CHAPTER_URL.format(ch)
        s, b = curl(url, referer=BASE_URL, timeout=8)
        has_char = CHAR1 in b
        title_match = re.search(r'<title>(.*?)</title>', b)
        title = title_match.group(1) if title_match else ""
        is_chapter = "第" in title and "章" in title and ch > 1
        if s == 200 and (has_char or is_chapter or ch <= 10):
            ct = extract_chapter_content(b)
            cc = cn_count(ct)
            if cc > 50 or has_char:
                chapter_urls.append((ch, f"第{ch}章", url))
                max_ch = ch
                print(f"  发现章节{ch}: cn={cc}")
                time.sleep(0.2)
                continue
        # 连续3个章节失败则停止
        if ch > max_ch + 5 and s != 200:
            break
        time.sleep(0.15)

chapter_urls = sorted(list(set(chapter_urls)), key=lambda x: x[0])
print(f"\n最终章节数: {len(chapter_urls)}")
for n, t, u in chapter_urls:
    print(f"  第{n}章: {t[:30]}")

# 第二步：抓取所有章节
print(f"\n{'='*70}")
print("开始抓取所有章节...")
print("="*70)

all_chapters = []
total_cn = 0
novel_title = "娇娇和她的忠犬小狗"

for i, (ch_num, ch_title, url) in enumerate(chapter_urls):
    s, html = curl(url, referer=BASE_URL if i==0 else chapter_urls[i-1][2], timeout=10)
    if s != 200:
        print(f"  [{i+1}/{len(chapter_urls)}] 第{ch_num}章 HTTP {s}, 跳过")
        time.sleep(0.3)
        continue
    content = extract_chapter_content(html)
    cc = cn_count(content)
    # 清理导航文字
    content = re.sub(r'^.*?第\d+章\s*', '', content, count=1, flags=re.S)
    content = re.sub(r'科普小说网.*?娇娇和她的忠犬小狗\s*', '', content, count=1, flags=re.S)
    content = re.sub(r'精彩小说尽在科普小说网.*?$', '', content, flags=re.M)
    content = content.strip()
    if content:
        all_chapters.append((ch_title, content))
        total_cn += cn_count(content)
        print(f"  [{i+1}/{len(chapter_urls)}] {ch_title[:25]:25s} -> {cc}字 (累计{total_cn}字)")
    else:
        print(f"  [{i+1}/{len(chapter_urls)}] {ch_title[:25]:25s} -> 内容提取失败")
    time.sleep(0.2)

# 第三步：组装Markdown
print(f"\n{'='*70}")
print("组装完整Markdown文档...")
print("="*70)

md_parts = [
    f"# {novel_title}",
    "",
    f"> **作者**: 侠名（忆相思）",
    f"> **来源**: kepue.com 科普小说网",
    f"> **主角**: 孟娇蕊、靳川",
    f"> **类型**: 短篇虐文 / 年代文 / 弹幕女配",
    f"> **状态**: 已完结",
    f"> **抓取时间**: {time.strftime('%Y-%m-%d %H:%M:%S')}",
    f"> **总字数**: {total_cn} 中文字",
    "",
    "---",
    "",
    "## 简介",
    "",
    "婚后一年，老公从不碰我。正想偷汉子时，眼前飘过弹幕。",
    "",
    "【女配糊涂啊！你可知男主胯下是何等凶险之地？不碰你是担心你受不住！】",
    "",
    "【怕女配讨厌自己忍到要爆炸了也不敢上手，结果老婆跟野男人跑了哈哈哈。】",
    "",
    "【嘻嘻她不犯错，女主怎么救赎男主呀，妹宝后面吃得可好了，日夜砰砰砰。】",
    "",
    "---",
    "",
]

for ch_title, content in all_chapters:
    md_parts.append(f"## {ch_title}")
    md_parts.append("")
    md_parts.append(content)
    md_parts.append("")
    md_parts.append("---")
    md_parts.append("")

md_content = "\n".join(md_parts)

final_path = out / "final_success.md"
final_path.write_text(md_content, encoding='utf-8')

print(f"\n{'='*70}")
print(f"  全文抓取完成！")
print(f"{'='*70}")
print(f"  章节数: {len(all_chapters)}")
print(f"  总字数: {total_cn} 中文字")
print(f"  保存到: {final_path}")
print(f"\n  内容预览（前1000字）:")
print(f"  {'-'*50}")
preview = '\n'.join(md_content.split('\n')[:60])
print(preview[:1500])
