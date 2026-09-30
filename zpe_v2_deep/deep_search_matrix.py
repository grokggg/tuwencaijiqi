#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
深度搜索矩阵引擎
使用独特锚点短语在多个搜索引擎和平台上深度搜索
"""
import subprocess
import re
import json
import time
import os
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup

def curl(url, ua=None, timeout=15, retries=2, headers=None):
    """可靠的HTTP请求"""
    for attempt in range(retries):
        cmd = ['curl', '-s', '-L', '--max-time', str(timeout), '--compressed']
        if ua:
            cmd.extend(['-A', ua])
        if headers:
            for k, v in headers.items():
                cmd.extend(['-H', f'{k}: {v}'])
        cmd.append(url)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout+5)
            if result.stdout and len(result.stdout) > 500:
                return result.stdout
        except:
            pass
        if attempt < retries - 1:
            time.sleep(1)
    return ''

UA_DESKTOP = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
UA_MOBILE = 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1'

class DeepSearchMatrix:
    """深度搜索矩阵"""
    
    def __init__(self, output_dir='output'):
        self.output_dir = output_dir
        self.results = []  # (source, query, title, url, snippet, confidence)
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs('data', exist_ok=True)
    
    def search_bing(self, query, max_results=10):
        """必应搜索"""
        results = []
        url = f'https://cn.bing.com/search?q={quote(query)}&count=30'
        html = curl(url, ua=UA_DESKTOP, timeout=12)
        if not html:
            return results
        
        soup = BeautifulSoup(html, 'html.parser')
        for li in soup.select('li.b_algo'):
            a = li.find('a', href=True)
            if not a:
                continue
            href = a['href']
            title = a.get_text(strip=True)
            
            # 跳过bing自家链接
            if 'bing.com' in href or 'microsoft.com' in href:
                continue
            
            # 获取摘要
            snippet_elem = li.select_one('.b_caption p, .b_snippet p, p')
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''
            
            results.append({
                'title': title,
                'url': href,
                'snippet': snippet[:200]
            })
            if len(results) >= max_results:
                break
        
        return results
    
    def search_sogou(self, query, max_results=10):
        """搜狗搜索"""
        results = []
        url = f'https://www.sogou.com/web?query={quote(query)}'
        html = curl(url, ua=UA_DESKTOP, timeout=12)
        if not html:
            return results
        
        soup = BeautifulSoup(html, 'html.parser')
        for div in soup.select('.vrwrap, .rb'):
            h3 = div.find('h3')
            if not h3:
                continue
            a = h3.find('a', href=True)
            if not a:
                continue
            
            href = a['href']
            title = a.get_text(strip=True)
            
            # 搜狗的链接是跳转链接，需要解析
            if href.startswith('/link?'):
                href = 'https://www.sogou.com' + href
            
            snippet_elem = div.select_one('.str_info, .fz-mid, .txt-info')
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''
            
            results.append({
                'title': title,
                'url': href,
                'snippet': snippet[:200]
            })
            if len(results) >= max_results:
                break
        
        return results
    
    def search_360(self, query, max_results=10):
        """360搜索"""
        results = []
        url = f'https://www.so.com/s?q={quote(query)}'
        html = curl(url, ua=UA_DESKTOP, timeout=12)
        if not html:
            return results
        
        soup = BeautifulSoup(html, 'html.parser')
        for li in soup.select('.res-list, .result'):
            h3 = li.find('h3')
            if not h3:
                continue
            a = h3.find('a', href=True)
            if not a:
                continue
            
            href = a['href']
            title = a.get_text(strip=True)
            
            if href.startswith('/'):
                href = 'https://www.so.com' + href
            
            snippet_elem = li.select_one('.res-desc, .desc, p')
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''
            
            results.append({
                'title': title,
                'url': href,
                'snippet': snippet[:200]
            })
            if len(results) >= max_results:
                break
        
        return results
    
    def search_toutiao(self, query, max_results=10):
        """头条搜索"""
        results = []
        url = f'https://so.toutiao.com/search?keyword={quote(query)}&pd=information'
        html = curl(url, ua=UA_MOBILE, timeout=12)
        if not html:
            return results
        
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            title = a.get_text(strip=True)
            if len(title) > 10 and ('toutiao' in href or 'pstatp' in href):
                results.append({
                    'title': title,
                    'url': href if href.startswith('http') else 'https:' + href,
                    'snippet': ''
                })
                if len(results) >= max_results:
                    break
        
        return results
    
    def search_weixin_sogou(self, query, max_results=10):
        """搜狗微信搜索"""
        results = []
        url = f'https://weixin.sogou.com/weixin?type=2&query={quote(query)}'
        html = curl(url, ua=UA_DESKTOP, timeout=12)
        if not html:
            return results
        
        soup = BeautifulSoup(html, 'html.parser')
        for li in soup.select('.news-list li, .wx-rb'):
            h3 = li.find('h3')
            if not h3:
                continue
            a = h3.find('a', href=True)
            if not a:
                continue
            
            href = a['href']
            title = a.get_text(strip=True)
            
            if href.startswith('/'):
                href = 'https://weixin.sogou.com' + href
            
            snippet_elem = li.select_one('.txt-info, p')
            snippet = snippet_elem.get_text(strip=True) if snippet_elem else ''
            
            results.append({
                'title': title,
                'url': href,
                'snippet': snippet[:200]
            })
            if len(results) >= max_results:
                break
        
        return results
    
    def search_baidu_mobile(self, query, max_results=10):
        """移动端百度搜索"""
        results = []
        url = f'https://m.baidu.com/s?word={quote(query)}'
        headers = {
            'Referer': 'https://m.baidu.com/',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
        }
        html = curl(url, ua=UA_MOBILE, timeout=12, headers=headers)
        if not html:
            return results
        
        soup = BeautifulSoup(html, 'html.parser')
        for a in soup.find_all('a', href=True):
            href = a['href']
            title = a.get_text(strip=True)
            if len(title) > 12 and 'baidu.com' not in href and href.startswith('http'):
                # 过滤掉导航链接
                if any(kw in title for kw in ['小说', '阅读', '全文', '免费', '娇娇', '靳川', '忠犬']):
                    results.append({
                        'title': title,
                        'url': href,
                        'snippet': ''
                    })
                    if len(results) >= max_results:
                        break
        
        return results
    
    def calculate_confidence(self, result, query):
        """计算结果置信度"""
        score = 0
        
        title = result.get('title', '')
        snippet = result.get('snippet', '')
        url = result.get('url', '')
        
        combined = title + ' ' + snippet
        
        # 包含主角名
        if '靳川' in combined:
            score += 30
        if '孟娇蕊' in combined or '娇娇' in combined:
            score += 20
        if '傅柏文' in combined:
            score += 15
        
        # 包含独特元素
        if '弹幕' in combined:
            score += 20
        if '公狗腰' in combined:
            score += 25
        if '年代文' in combined or '年代' in combined:
            score += 10
        
        # 标题包含书名
        for t in ['娇娇和她的忠犬小狗', '婚后一年老公从不碰我', '边月忠犬']:
            if t in title:
                score += 25
                break
        
        # 来源类型加分
        novel_sites = ['kepue', 'biqu', 'shuquge', '630la', '23usp', 'txt99', 
                       'xbiquge', 'bqgui', 'beqege', 'shu8', 'xsbiquge',
                       'yikan', 'syzgly', 'husiyu', '7729', '99csw', 'kanunu']
        if any(site in url for site in novel_sites):
            score += 15
        
        # 摘要长度加分
        if len(snippet) > 50:
            score += 5
        
        return min(score, 100)
    
    def run_search(self, queries, engines=None):
        """运行多引擎搜索"""
        if engines is None:
            engines = ['bing', 'sogou', '360']
        
        engine_map = {
            'bing': self.search_bing,
            'sogou': self.search_sogou,
            '360': self.search_360,
            'toutiao': self.search_toutiao,
            'weixin': self.search_weixin_sogou,
            'baidu_mobile': self.search_baidu_mobile,
        }
        
        all_results = []
        seen_urls = set()
        
        for i, query in enumerate(queries):
            print(f'\n[{i+1}/{len(queries)}] 搜索: {query[:50]}...')
            
            for engine_name in engines:
                if engine_name not in engine_map:
                    continue
                
                engine_func = engine_map[engine_name]
                try:
                    results = engine_func(query, max_results=8)
                    print(f'  {engine_name}: {len(results)} 个结果')
                    
                    for r in results:
                        url = r['url']
                        if url in seen_urls:
                            continue
                        seen_urls.add(url)
                        
                        confidence = self.calculate_confidence(r, query)
                        r['source'] = engine_name
                        r['query'] = query
                        r['confidence'] = confidence
                        
                        all_results.append(r)
                    
                    time.sleep(0.5)  # 限速
                except Exception as e:
                    print(f'  {engine_name}: 出错 - {e}')
            
            # 每5个查询保存一次
            if (i + 1) % 5 == 0:
                self._save_results(all_results)
        
        # 按置信度排序
        all_results.sort(key=lambda x: x['confidence'], reverse=True)
        self._save_results(all_results)
        
        return all_results
    
    def _save_results(self, results):
        """保存结果"""
        with open(f'{self.output_dir}/search_results.json', 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        
        # 同时保存高置信度结果的摘要
        high_conf = [r for r in results if r['confidence'] >= 40]
        with open(f'{self.output_dir}/high_confidence_results.txt', 'w', encoding='utf-8') as f:
            f.write(f'高置信度结果: {len(high_conf)} 个\n\n')
            for i, r in enumerate(high_conf[:50]):
                f.write(f'[{i+1}] 置信度: {r["confidence"]} | 来源: {r["source"]}\n')
                f.write(f'    标题: {r["title"]}\n')
                f.write(f'    URL: {r["url"]}\n')
                f.write(f'    摘要: {r["snippet"][:100]}\n\n')


if __name__ == '__main__':
    # 导入锚点提取器
    import sys
    sys.path.insert(0, '.')
    from anchor_extractor import extract_anchors, generate_search_queries
    
    # 读取已知内容
    with open('/workspace/娇娇和她的忠犬小狗_完整版.md', 'r', encoding='utf-8') as f:
        content = f.read()
    
    anchors = extract_anchors(content)
    print(f'提取到 {len(anchors)} 个锚点短语')
    
    titles = [
        '娇娇和她的忠犬小狗',
        '婚后一年老公从不碰我',
        '边月忠犬',
    ]
    
    queries = generate_search_queries(anchors, titles)
    print(f'生成 {len(queries)} 个搜索查询')
    
    # 运行搜索
    searcher = DeepSearchMatrix(output_dir='output')
    
    # 第一轮：用最独特的短语搜索
    print('\n=== 第一轮深度搜索 ===')
    # 优先使用弹幕短语（最独特）
    priority_queries = [q for q in queries if '弹幕' in q or '公狗腰' in q or '奋战到天亮' in q]
    # 加上角色名组合
    priority_queries.extend([
        '靳川 孟娇蕊 弹幕 小说 全文',
        '娇娇和她的忠犬小狗 全文免费阅读',
        '婚后一年老公从不碰我 小说 完整版',
        '靳川 公狗腰 年代文 小说',
    ])
    
    results = searcher.run_search(priority_queries[:20], 
                                  engines=['bing', 'sogou', '360'])
    
    print(f'\n共找到 {len(results)} 个唯一结果')
    print(f'高置信度(>=40): {len([r for r in results if r["confidence"] >= 40])}')
    print(f'极高置信度(>=60): {len([r for r in results if r["confidence"] >= 60])}')
    
    # 打印Top 10
    print('\n=== Top 10 结果 ===')
    for i, r in enumerate(results[:10]):
        print(f'{i+1}. [{r["confidence"]}分] {r["title"][:40]}')
        print(f'   {r["url"][:80]}')
