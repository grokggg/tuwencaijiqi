#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
锚点短语提取器
从已知内容中提取独特的、可用于搜索的短语
"""
import re

def extract_anchors(content):
    """从文本中提取独特锚点短语"""
    anchors = []
    
    # 1. 提取弹幕内容（带【】的）- 非常独特
    danmu_pattern = r'【([^】]+)】'
    danmus = re.findall(danmu_pattern, content)
    for d in danmus:
        if len(d) > 10 and len(d) < 50:
            # 过滤掉太短或太长的
            anchors.append(('弹幕', d))
    
    # 2. 提取对话内容（带「」的）
    dialog_pattern = r'「([^」]+)」'
    dialogs = re.findall(dialog_pattern, content)
    for d in dialogs:
        if len(d) > 8 and len(d) < 40:
            anchors.append(('对话', d))
    
    # 3. 提取独特描述性句子
    lines = content.split('\n')
    for line in lines:
        line = line.strip()
        # 长度适中，且包含独特元素
        if 15 < len(line) < 60:
            # 包含角色名或独特词汇
            if any(name in line for name in ['靳川', '孟娇蕊', '傅柏文', '公狗腰', '弹幕']):
                if '，' in line or '。' in line:
                    anchors.append(('描述', line))
    
    # 去重
    seen = set()
    unique_anchors = []
    for atype, text in anchors:
        if text not in seen:
            seen.add(text)
            unique_anchors.append((atype, text))
    
    return unique_anchors

def generate_search_queries(anchors, titles):
    """生成搜索查询组合"""
    queries = []
    
    # 标题 + 独特短语
    for title in titles:
        for atype, text in anchors[:15]:
            if atype in ['弹幕', '对话']:
                # 用独特短语搜索
                queries.append(f'"{text}" {title}')
                queries.append(f'"{text}" 小说')
                queries.append(f'"{text}" 全文')
    
    # 纯独特短语（带引号精确匹配）
    for atype, text in anchors[:20]:
        if atype == '弹幕' and len(text) > 12:
            queries.append(f'"{text}"')
        elif atype == '对话' and len(text) > 10:
            queries.append(f'"{text}" 小说')
    
    # 角色名 + 关键词组合
    role_combos = [
        '靳川 孟娇蕊 弹幕 小说',
        '靳川 公狗腰 小说',
        '孟娇蕊 靳川 年代文',
        '傅柏文 弹幕 知乎',
        '靳川 孟娇蕊 婚后一年',
        '娇娇 靳川 忠犬',
    ]
    queries.extend(role_combos)
    
    # 去重并限制数量
    seen = set()
    unique_q = []
    for q in queries:
        if q not in seen:
            seen.add(q)
            unique_q.append(q)
    
    return unique_q[:50]  # 最多50个查询

if __name__ == '__main__':
    # 读取已知内容
    with open('/workspace/娇娇和她的忠犬小狗_完整版.md', 'r', encoding='utf-8') as f:
        content = f.read()
    
    anchors = extract_anchors(content)
    print(f'提取到 {len(anchors)} 个锚点短语:\n')
    for atype, text in anchors[:20]:
        print(f'  [{atype}] {text[:50]}')
    
    titles = [
        '娇娇和她的忠犬小狗',
        '婚后一年老公从不碰我',
        '边月忠犬',
    ]
    
    queries = generate_search_queries(anchors, titles)
    print(f'\n生成 {len(queries)} 个搜索查询:')
    for i, q in enumerate(queries[:20]):
        print(f'  {i+1}. {q[:60]}')
