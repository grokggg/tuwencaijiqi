#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
最终内容收集脚本 - 带重试机制
"""
import subprocess
from bs4 import BeautifulSoup
import re
import os
import time
from urllib.parse import quote

def curl(url, ua=None, timeout=15, retries=3):
    for attempt in range(retries):
        cmd = ['curl', '-s', '-L', '--max-time', str(timeout), '--compressed']
        if ua:
            cmd.extend(['-A', ua])
        cmd.append(url)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.stdout and len(result.stdout) > 1000:
                return result.stdout
        except:
            pass
        if attempt < retries - 1:
            time.sleep(1)
    return ''

ua_mobile = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'
ua_mobile2 = 'Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'

print('=== 从kepue获取干净内容 ===')
chapters_content = []
for ch_num in range(1, 6):
    url = f'https://m.kepue.com/nvpin/38738/{ch_num}/'
    html = ''
    for ua in [ua_mobile, ua_mobile2]:
        html = curl(url, ua=ua, timeout=10, retries=3)
        if html and len(html) > 1000:
            break
        time.sleep(0.5)
    
    if html:
        soup = BeautifulSoup(html, 'html.parser')
        content_div = soup.select_one('#pContainer')
        if content_div:
            paras = []
            for p in content_div.find_all('p'):
                text = p.get_text(strip=True)
                if text:
                    paras.append(text)
            content = '\n\n'.join(paras)
            chapters_content.append((f'第{ch_num}章', content))
            print(f'第{ch_num}章: {len(content)} 字符, {len(paras)} 段')
        else:
            print(f'第{ch_num}章: HTML获取成功但未找到内容div')
            with open(f'debug_ch{ch_num}.html', 'w', encoding='utf-8') as f:
                f.write(html)
    else:
        print(f'第{ch_num}章: HTML获取失败')

# 清理标点符号
def clean_punctuation(text):
    # 在中文上下文中替换英文标点
    text = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]),', r'\1，', text)
    text = re.sub(r',([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])', r'，\1', text)
    text = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])\?', r'\1？', text)
    text = re.sub(r'\?([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])', r'？\1', text)
    text = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])!', r'\1！', text)
    text = re.sub(r'!([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef])', r'！\1', text)
    text = re.sub(r'([\u4e00-\u9fff\u3000-\u303f\uff00-\uffef]):', r'\1：', text)
    return text

os.makedirs('output', exist_ok=True)

# 生成最终Markdown
md_lines = []
md_lines.append('# 《娇娇和她的忠犬小狗》')
md_lines.append('')
md_lines.append('| 字段 | 值 |')
md_lines.append('|------|-----|')
md_lines.append('| **作者** | 佚名（知乎盐选《边月忠犬》专栏） |')
md_lines.append('| **来源平台** | 知乎盐选专栏 |')
md_lines.append('| **文章ID** | 1979959692122943787 |')
md_lines.append('| **状态** | 已完结（共5章） |')
md_lines.append('| **主角** | 孟娇蕊（娇娇/女配）、靳川（忠犬男主） |')
md_lines.append('| **配角** | 傅柏文（弹幕哥/系统） |')
md_lines.append('| **标签** | 穿书、甜宠、双向奔赴、弹幕、年代文 |')
md_lines.append('| **获取方式** | kepue.com（科普小说网）免费转载 |')
md_lines.append('')
md_lines.append('---')
md_lines.append('')

total_cn = 0
for title, content in chapters_content:
    cleaned = clean_punctuation(content)
    cn_count = sum(1 for c in cleaned if '\u4e00' <= c <= '\u9fff')
    total_cn += cn_count
    md_lines.append(f'## {title}')
    md_lines.append('')
    md_lines.append(cleaned)
    md_lines.append('')

# 添加字数统计
md_lines.insert(14, f'| **总字数** | 约{total_cn}字 |')

final_md = '\n'.join(md_lines)
with open('output/娇娇和她的忠犬小狗_完整版.md', 'w', encoding='utf-8') as f:
    f.write(final_md)

print(f'\n总中文字数: {total_cn}')
print(f'已保存到: output/娇娇和她的忠犬小狗_完整版.md')

# 验证所有章节都获取到了
if len(chapters_content) == 5:
    print('\n✓ 所有5章已成功获取！')
else:
    print(f'\n✗ 只获取到 {len(chapters_content)}/5 章')
