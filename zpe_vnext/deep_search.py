# -*- coding: utf-8 -*-
"""
深度搜索脚本 - 多策略并发搜索
"""
import asyncio
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, quote, urlparse
from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).parent))
from core.http_client import HttpClient, cn_count, random_ua
from core.parser import ContentParser


async def main():
    http = HttpClient()
    parser = ContentParser()
    
    print("="*70)
    print("ZPE vNext - 深度搜索模式")
    print("="*70)
    
    # 搜索查询组合 - 更精准
    search_queries = [
        # 标题变体
        "娇娇和她的忠犬小狗 完整版",
        "娇娇和她的忠犬小狗 免费阅读 第6章",
        "娇娇和她的忠犬小狗 全文在线阅读",
        "婚后一年老公从不碰我 完整版",
        "婚后一年老公从不碰我 小说 全文",
        # 主角+情节
        "靳川 孟娇蕊 弹幕 小说",
        "靳川 孟娇蕊 免费阅读 完整版",
        "孟娇蕊 靳川 忠犬 小说",
        # 加入更有辨识度的情节
        "女配眼神不好使啊 放着宽肩窄腰 小说",
        "孟同志 你找我是有什么事吗 靳川",
        "我不仅要做 我还要天天做 小说",
    ]
    
    all_found_urls = set()
    all_contents = []
    
    headers = {"User-Agent": random_ua()}
    
    # 1. 多搜索引擎搜索
    print("\n[1] 多搜索引擎并发搜索...")
    search_engines = [
        ("https://www.baidu.com/s", "wd", 0),
        ("https://cn.bing.com/search", "q", 1),
        ("https://www.sogou.com/web", "query", 1),
        ("https://www.so.com/s", "q", 0),
    ]
    
    sem = asyncio.Semaphore(3)
    
    async def search_one(engine_url: str, param_name: str, page_offset: int, query: str):
        async with sem:
            results = []
            try:
                for page in range(0, 3):
                    params = {param_name: query}
                    if param_name == "wd":  # baidu
                        params["pn"] = page * 10
                    elif param_name == "q" and "so.com" in engine_url:  # 360
                        params["pn"] = page * 10
                    elif param_name == "query":  # sogou
                        params["page"] = page + 1
                    else:  # bing
                        params["first"] = page * 10 + 1
                    
                    h = {"User-Agent": random_ua()}
                    status, html, _ = await http.get(engine_url, headers=h, params=params)
                    if status == 200 and html:
                        # 提取URL
                        soup = BeautifulSoup(html, 'html.parser')
                        for a in soup.find_all('a', href=True):
                            href = a['href']
                            text = a.get_text(strip=True)
                            if any(kw in text for kw in ['娇娇', '忠犬', '靳川', '孟娇蕊', '婚后一年']) and len(text) > 4:
                                # 处理跳转链接
                                if 'baidu.com/link' in href or 'sogou.com/link' in href:
                                    results.append(("redirect", href, text))
                                elif href.startswith('http') and not any(skip in href for skip in ['baidu.com', 'bing.com', 'sogou.com', 'so.com', 'zhihu.com']):
                                    results.append(("direct", href, text))
                    await asyncio.sleep(0.3)
            except Exception as e:
                pass
            return results
    
    tasks = []
    for query in search_queries:
        for engine_url, param, offset in search_engines:
            tasks.append(search_one(engine_url, param, offset, query))
    
    search_results = await asyncio.gather(*tasks, return_exceptions=True)
    
    redirect_urls = []
    direct_urls = []
    
    for sr in search_results:
        if isinstance(sr, Exception) or not sr:
            continue
        for typ, url, text in sr:
            if typ == "redirect":
                redirect_urls.append(url)
            else:
                direct_urls.append((url, text))
    
    print(f"  发现 {len(redirect_urls)} 个跳转链接, {len(direct_urls)} 个直接链接")
    
    # 2. 跟随百度/搜狗跳转链接
    print("\n[2] 跟随跳转链接获取真实URL...")
    async def follow_redirect(r_url: str):
        try:
            h = {"User-Agent": random_ua()}
            status, html, headers_resp = await http.get(r_url, headers=h, follow_redirects=True)
            # httpx会自动跟随重定向，获取最终URL
            return str(headers_resp.get('content-location', r_url))
        except:
            return None
    
    # 注意：我们需要手动处理重定向，让我用另一种方式
    real_urls = []
    for r_url in redirect_urls[:30]:
        try:
            h = {"User-Agent": random_ua()}
            # 不自动跟随，获取Location头
            status, _, resp_headers = await http.get(r_url, headers=h, follow_redirects=False)
            location = resp_headers.get('location', '')
            if location and location.startswith('http'):
                real_urls.append(location)
                print(f"  跳转: {location[:80]}")
        except Exception as e:
            pass
        await asyncio.sleep(0.2)
    
    # 合并所有发现的URL
    all_urls = list(set(real_urls + [u for u, _ in direct_urls]))
    print(f"\n  共获得 {len(all_urls)} 个唯一URL")
    
    # 3. 访问所有发现的URL，提取内容
    print("\n[3] 访问URL提取内容...")
    
    async def fetch_url(url: str):
        try:
            h = {"User-Agent": random_ua()}
            status, html, _ = await http.get(url, headers=h, timeout=15)
            if status != 200 or not html or len(html) < 500:
                return None
            
            # 检查是否有目标内容
            if not any(c in html for c in ['靳川', '孟娇蕊', '傅柏文']):
                # 再检查标题
                if not any(t in html for t in ['娇娇和她的忠犬小狗', '婚后一年老公从不碰我']):
                    return None
            
            title, content = parser.extract_main_content(html, url)
            validation = parser.validate_content(content)
            
            # 提取章节链接
            chapters = parser.extract_chapter_links(html, url)
            
            return {
                "url": url,
                "title": title,
                "content": content,
                "word_count": validation["word_count"],
                "is_match": validation["is_match"],
                "confidence": validation["confidence"],
                "chapters": chapters,
                "html": html,
            }
        except Exception as e:
            return None
    
    fetch_tasks = [fetch_url(u) for u in all_urls[:50]]
    fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)
    
    best_result = None
    best_word_count = 0
    all_chapters = []
    valid_results = []
    
    for fr in fetch_results:
        if isinstance(fr, Exception) or not fr:
            continue
        valid_results.append(fr)
        if fr["chapters"] and len(fr["chapters"]) >= 3:
            print(f"  发现章节目录: {fr['url']} ({len(fr['chapters'])}章)")
            all_chapters.extend(fr["chapters"])
        if fr["is_match"] and fr["word_count"] > best_word_count:
            best_word_count = fr["word_count"]
            best_result = fr
            print(f"  ✓ 匹配内容: {fr['title'][:40]} - {fr['word_count']}字 (置信度:{fr['confidence']:.2f})")
    
    print(f"\n  有效结果: {len(valid_results)}, 最佳: {best_word_count}字")
    
    # 4. 如果发现章节列表，爬取章节
    if all_chapters:
        print(f"\n[4] 爬取发现的 {len(all_chapters)} 个章节...")
        
        # 去重
        seen = set()
        unique_chapters = []
        for t, u in all_chapters:
            if u not in seen:
                seen.add(u)
                unique_chapters.append((t, u))
        
        async def crawl_chapter(idx: int, title: str, url: str):
            try:
                h = {"User-Agent": random_ua()}
                status, html, _ = await http.get(url, headers=h, timeout=15)
                if status == 200 and html:
                    _, content = parser.extract_main_content(html, url)
                    if cn_count(content) > 50:
                        return (idx, title, content)
            except:
                pass
            return None
        
        ch_sem = asyncio.Semaphore(2)
        async def crawl_with_sem(idx, title, url):
            async with ch_sem:
                return await crawl_chapter(idx, title, url)
        
        ch_tasks = [crawl_with_sem(i, t, u) for i, (t, u) in enumerate(unique_chapters[:80])]
        ch_results = await asyncio.gather(*ch_tasks, return_exceptions=True)
        
        valid_chapters = []
        for cr in ch_results:
            if isinstance(cr, Exception) or not cr:
                continue
            valid_chapters.append(cr)
        
        valid_chapters.sort(key=lambda x: x[0])
        print(f"  成功爬取 {len(valid_chapters)}/{len(unique_chapters)} 章")
        
        if valid_chapters:
            chapter_content = "\n\n".join([f"## {t}\n\n{c}" for _, t, c in valid_chapters])
            if cn_count(chapter_content) > best_word_count:
                best_word_count = cn_count(chapter_content)
                best_result = {
                    "url": "chapter_crawl",
                    "title": "娇娇和她的忠犬小狗",
                    "content": chapter_content,
                    "word_count": best_word_count,
                }
    
    # 5. 暴力枚举kepue章节（可能目录只显示前5章，但后面的章节URL仍然可访问）
    print("\n[5] 暴力枚举kepue.com章节 (6-100)...")
    brute_contents = []
    
    async def try_kepue_ch(num: int):
        for url in [
            f"https://kepue.com/nvpin/38738/{num}.html",
            f"https://kepue.com/nvpin/38738/{num}/",
            f"https://m.kepue.com/nvpin/38738/{num}/",
        ]:
            try:
                h = {"User-Agent": random_ua()}
                status, html, _ = await http.get(url, headers=h, timeout=10)
                if status == 200 and html and any(c in html for c in ['靳川', '孟娇蕊', '傅柏文']):
                    _, content = parser.extract_main_content(html, url)
                    if cn_count(content) > 50:
                        # 检查是否是错误页
                        if '404' not in content and '不存在' not in content:
                            title = f"第{num}章"
                            # 尝试从HTML提取标题
                            soup = BeautifulSoup(html, 'html.parser')
                            h1 = soup.find('h1')
                            if h1:
                                title = h1.get_text(strip=True)
                            return (num, title, content)
            except:
                pass
        return None
    
    brute_sem = asyncio.Semaphore(3)
    async def brute_with_sem(num):
        async with brute_sem:
            return await try_kepue_ch(num)
    
    brute_tasks = [brute_with_sem(n) for n in range(6, 101)]
    brute_results = await asyncio.gather(*brute_tasks, return_exceptions=True)
    
    valid_brute = []
    for br in brute_results:
        if isinstance(br, Exception) or not br:
            continue
        valid_brute.append(br)
    
    valid_brute.sort(key=lambda x: x[0])
    print(f"  枚举发现 {len(valid_brute)} 个额外章节")
    
    if valid_brute:
        brute_content = "\n\n".join([f"## {t}\n\n{c}" for _, t, c in valid_brute])
        brute_contents.append(("kepue_brute", brute_content))
        print(f"  枚举内容字数: {cn_count(brute_content)}")
    
    # 6. 尝试更多小说站搜索
    print("\n[6] 扫描更多小说站...")
    novel_search_urls = [
        f"https://www.biquge5200.com/search.php?q={quote('娇娇和她的忠犬小狗')}",
        f"https://www.biqukan.la/search.php?q={quote('娇娇和她的忠犬小狗')}",
        f"https://www.xsbiquge.com/search.php?q={quote('娇娇和她的忠犬小狗')}",
        f"https://www.beqege.cc/search.php?q={quote('娇娇和她的忠犬小狗')}",
        f"https://www.bqgui.cc/search.php?q={quote('娇娇和她的忠犬小狗')}",
    ]
    
    for surl in novel_search_urls:
        try:
            h = {"User-Agent": random_ua()}
            status, html, _ = await http.get(surl, headers=h, timeout=10)
            if status == 200 and html and any(c in html for c in ['靳川', '娇娇']):
                print(f"  发现匹配: {surl}")
                # 提取书籍链接
                soup = BeautifulSoup(html, 'html.parser')
                for a in soup.find_all('a', href=True):
                    text = a.get_text(strip=True)
                    href = a['href']
                    if any(kw in text for kw in ['娇娇', '忠犬', '靳川', '婚后一年']):
                        if href.startswith('/'):
                            parsed = urlparse(surl)
                            href = f"{parsed.scheme}://{parsed.netloc}{href}"
                        print(f"    -> {text[:40]}: {href}")
        except:
            pass
    
    # 7. 汇总所有内容
    print("\n" + "="*70)
    all_final_contents = []
    
    # 加入已有内容
    existing_content = open('/workspace/zhihu_paywall_agent/output/娇娇和她的忠犬小狗.md', 'r', encoding='utf-8').read()
    all_final_contents.append(("existing", existing_content))
    
    if best_result and best_result["content"]:
        all_final_contents.append(("best_search", best_result["content"]))
    
    all_final_contents.extend(brute_contents)
    
    if all_final_contents:
        merged = parser.merge_contents(all_final_contents)
        merged_word_count = cn_count(merged)
        print(f"汇总后总字数: {merged_word_count}")
        
        # 保存结果
        output_md = f"""# 娇娇和她的忠犬小狗

> 主角: 孟娇蕊、靳川、傅柏文、沈念念
> 总字数: {merged_word_count}
> 获取方式: 多引擎聚合搜索 + 章节爬取

---

{merged}
"""
        out_path = Path(__file__).parent / "output" / "娇娇和她的忠犬小狗_深度搜索版.md"
        out_path.write_text(output_md, encoding='utf-8')
        print(f"已保存到: {out_path}")
        
        # 显示结尾
        print(f"\n内容结尾 (最后500字):")
        print(merged[-500:])
    
    await http.close()


if __name__ == "__main__":
    asyncio.run(main())
