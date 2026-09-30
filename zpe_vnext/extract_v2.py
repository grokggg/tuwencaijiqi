# -*- coding: utf-8 -*-
"""
提取脚本v2 - 多策略组合
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
    print("ZPE vNext - 提取模式v2")
    print("="*70)
    
    all_contents = []
    
    # 加载已有内容
    print("\n[0] 加载已有内容...")
    existing_path = Path('/workspace/zhihu_paywall_agent/output/娇娇和她的忠犬小狗.md')
    if existing_path.exists():
        existing = existing_path.read_text(encoding='utf-8')
        all_contents.append(("existing_5chapters", existing))
        print(f"  已有内容: {cn_count(existing)}字")
    
    # 策略1: 直接枚举常见小说站搜索
    print("\n[1] 直接扫描小说站...")
    
    # 直接构建搜索URL列表（小说站搜索页）
    novel_search_urls = []
    search_queries = ["娇娇和她的忠犬小狗", "婚后一年老公从不碰我"]
    
    novel_sites = [
        ("https://www.biquge5200.com/search.php?q=", "biquge5200"),
        ("https://www.biqukan.la/search.php?q=", "biqukan"),
        ("https://www.xsbiquge.com/search.php?q=", "xsbiquge"),
        ("https://www.beqege.cc/search.php?q=", "beqege"),
        ("https://www.bqgui.cc/search.php?q=", "bqgui"),
        ("https://www.shuquge.com/search.php?q=", "shuquge"),
        ("https://www.630la.com/search.php?q=", "630la"),
        ("https://www.23usp.com/search.php?q=", "23usp"),
        ("https://www.txt99.org/search.php?q=", "txt99"),
        ("https://www.ibiquges.info/search.php?q=", "ibiquges"),
        ("https://www.xbiquge.bz/search.php?q=", "xbiquge"),
        ("https://www.biqugex.com/search.php?q=", "biqugex"),
        ("https://www.qb5.tw/search.php?q=", "qb5"),
        ("https://www.shubaow.net/search.php?q=", "shubaow"),
        # 移动端m开头的
        ("https://m.biquge5200.com/search.php?q=", "m_biquge5200"),
        ("https://m.beqege.cc/search.php?q=", "m_beqege"),
    ]
    
    for base_url, site_name in novel_sites:
        for q in search_queries[:1]:
            url = base_url + quote(q)
            novel_search_urls.append((url, site_name))
    
    sem = asyncio.Semaphore(3)
    found_book_urls = []
    
    async def search_novel_site(url, site_name):
        async with sem:
            try:
                headers = {"User-Agent": random_ua()}
                status, html, _ = await http.get(url, headers=headers, timeout=8)
                if status != 200 or not html:
                    return None
                
                # 检查是否有匹配
                if not any(c in html for c in ['靳川', '孟娇蕊', '娇娇', '忠犬', '婚后一年']):
                    return None
                
                print(f"  ✓ {site_name}: 发现匹配内容")
                
                # 提取书籍链接
                soup = BeautifulSoup(html, 'html.parser')
                book_links = []
                for a in soup.find_all('a', href=True):
                    text = a.get_text(strip=True)
                    href = a['href']
                    if any(kw in text for kw in ['娇娇', '忠犬', '靳川', '婚后一年', '傅柏文']):
                        if href.startswith('/'):
                            parsed = urlparse(url)
                            href = f"{parsed.scheme}://{parsed.netloc}{href}"
                        elif not href.startswith('http'):
                            href = urljoin(url, href)
                        book_links.append((text, href))
                
                return (site_name, book_links, html)
            except Exception as e:
                return None
    
    tasks = [search_novel_site(u, n) for u, n in novel_search_urls]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for r in results:
        if isinstance(r, Exception) or not r:
            continue
        site_name, links, html = r
        for text, url in links:
            if url not in [u for _, u in found_book_urls]:
                found_book_urls.append((text, url))
                print(f"    -> {text[:35]}: {url[:70]}")
    
    print(f"  共发现 {len(found_book_urls)} 个书籍链接")
    
    # 访问书籍页面，提取章节和内容
    print("\n[2] 访问书籍页提取章节...")
    site_contents = []
    
    for book_text, book_url in found_book_urls[:10]:
        try:
            headers = {"User-Agent": random_ua()}
            status, html, _ = await http.get(book_url, headers=headers, timeout=10)
            if status != 200 or not html:
                continue
            
            if not any(c in html for c in ['靳川', '孟娇蕊', '娇娇']):
                continue
            
            # 提取章节列表
            chapters = parser.extract_chapter_links(html, book_url)
            print(f"  {book_text[:25]}: 发现 {len(chapters)} 章")
            
            if chapters and len(chapters) >= 2:
                # 爬取前30章
                async def crawl_ch(idx, ct, cu):
                    try:
                        s, h, _ = await http.get(cu, headers={"User-Agent": random_ua()}, timeout=8)
                        if s == 200 and h:
                            _, cc = parser.extract_main_content(h, cu)
                            if cn_count(cc) > 50:
                                return (idx, ct, cc)
                    except:
                        pass
                    return None
                
                ch_sem = asyncio.Semaphore(2)
                async def cc_sem(i, ct, cu):
                    async with ch_sem:
                        return await crawl_ch(i, ct, cu)
                
                ch_tasks = [cc_sem(i, ct, cu) for i, (ct, cu) in enumerate(chapters[:30])]
                ch_res = await asyncio.gather(*ch_tasks, return_exceptions=True)
                
                valid_ch = []
                for cr in ch_res:
                    if isinstance(cr, Exception) or not cr:
                        continue
                    valid_ch.append(cr)
                
                valid_ch.sort(key=lambda x: x[0])
                if valid_ch:
                    book_content = "\n\n".join([f"## {ct}\n\n{cc}" for _, ct, cc in valid_ch])
                    print(f"    成功爬取 {len(valid_ch)} 章, {cn_count(book_content)}字")
                    site_contents.append((book_url, book_content))
            else:
                # 直接提取当前页内容
                _, page_content = parser.extract_main_content(html, book_url)
                v = parser.validate_content(page_content)
                if v["is_match"] and v["word_count"] > 200:
                    print(f"    单页内容: {v['word_count']}字")
                    site_contents.append((book_url, page_content))
        
        except Exception as e:
            print(f"  处理失败: {e}")
        await asyncio.sleep(0.3)
    
    all_contents.extend(site_contents)
    
    # 策略2: 必应搜索（更稳定）
    print("\n[3] 必应搜索...")
    bing_contents = []
    try:
        for q in ["娇娇和她的忠犬小狗 免费阅读", "靳川 孟娇蕊 小说 全文", "婚后一年老公从不碰我 免费"]:
            status, html, _ = await http.get(
                f"https://cn.bing.com/search?q={quote(q)}",
                headers={"User-Agent": random_ua()},
                timeout=10
            )
            if status != 200 or not html:
                continue
            
            soup = BeautifulSoup(html, 'html.parser')
            bing_links = []
            for a in soup.find_all('a', href=True):
                href = a['href']
                text = a.get_text(strip=True)
                if href.startswith('http') and not any(skip in href for skip in ['bing.com', 'microsoft.com', 'zhihu.com', 'baidu.com']):
                    if len(text) > 5 and any(kw in text for kw in ['娇娇', '忠犬', '靳川', '孟娇蕊', '婚后一年', '免费阅读']):
                        bing_links.append((text, href))
            
            print(f"  查询 '{q[:15]}...': 发现 {len(bing_links)} 个结果")
            
            for bt, bu in bing_links[:5]:
                try:
                    s, h, _ = await http.get(bu, headers={"User-Agent": random_ua()}, timeout=8)
                    if s == 200 and h and any(c in h for c in ['靳川', '孟娇蕊', '娇娇']):
                        _, bc = parser.extract_main_content(h, bu)
                        bv = parser.validate_content(bc)
                        if bv["is_match"] and bv["word_count"] > 200:
                            print(f"    ✓ {bt[:25]}: {bv['word_count']}字")
                            bing_contents.append((bu, bc))
                            
                            # 检查是否有章节
                            bchapters = parser.extract_chapter_links(h, bu)
                            if bchapters and len(bchapters) >= 3:
                                print(f"      发现 {len(bchapters)} 章目录")
                except:
                    pass
                await asyncio.sleep(0.2)
    except Exception as e:
        print(f"  必应搜索失败: {e}")
    
    all_contents.extend(bing_contents)
    
    # 策略3: 搜狗搜索
    print("\n[4] 搜狗搜索...")
    try:
        for q in ["娇娇和她的忠犬小狗 全文", "婚后一年老公从不碰我 小说"]:
            status, html, _ = await http.get(
                f"https://www.sogou.com/web?query={quote(q)}",
                headers={"User-Agent": random_ua()},
                timeout=10
            )
            if status == 200 and html:
                soup = BeautifulSoup(html, 'html.parser')
                sg_links = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    text = a.get_text(strip=True)
                    if len(text) > 5 and any(kw in text for kw in ['娇娇', '忠犬', '靳川', '婚后一年']):
                        sg_links.append((text, href))
                
                print(f"  搜狗: {len(sg_links)} 个结果")
    except Exception as e:
        print(f"  搜狗失败: {e}")
    
    # 策略4: 360搜索
    print("\n[5] 360搜索...")
    try:
        for q in ["娇娇和她的忠犬小狗 免费阅读", "靳川 孟娇蕊 全文"]:
            status, html, _ = await http.get(
                f"https://www.so.com/s?q={quote(q)}",
                headers={"User-Agent": random_ua()},
                timeout=10
            )
            if status == 200 and html:
                soup = BeautifulSoup(html, 'html.parser')
                so_links = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    text = a.get_text(strip=True)
                    if href.startswith('http') and len(text) > 5:
                        if any(kw in text for kw in ['娇娇', '忠犬', '靳川', '婚后一年', '免费阅读']):
                            so_links.append((text, href))
                print(f"  360: {len(so_links)} 个结果")
                
                for st, su in so_links[:3]:
                    try:
                        s, h, _ = await http.get(su, headers={"User-Agent": random_ua()}, timeout=8)
                        if s == 200 and h and any(c in h for c in ['靳川', '孟娇蕊']):
                            _, sc = parser.extract_main_content(h, su)
                            sv = parser.validate_content(sc)
                            if sv["is_match"] and sv["word_count"] > 200:
                                print(f"    ✓: {sv['word_count']}字")
                                all_contents.append((su, sc))
                    except:
                        pass
    except Exception as e:
        print(f"  360失败: {e}")
    
    # 策略5: 尝试知乎m站和各种API端点（使用不同UA）
    print("\n[6] 知乎直连探测...")
    aid = "1979959692122943787"
    zhihu_urls = [
        (f"https://m.zhihu.com/p/{aid}", "mobile"),
        (f"https://www.zhihu.com/question/582374928/answer/{aid}", "answer"),
    ]
    
    zhihu_uas = [
        "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)",
        "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
        "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
        "Sogou web spider/4.0(+http://www.sogou.com/docs/help/webmasters.htm#07)",
    ]
    
    for url, ztype in zhihu_urls:
        for ua in zhihu_uas:
            try:
                h = {"User-Agent": ua}
                s, zhtml, _ = await http.get(url, headers=h, timeout=8)
                if s == 200 and zhtml and any(c in zhtml for c in ['靳川', '孟娇蕊']):
                    _, zc = parser.extract_main_content(zhtml, url)
                    zv = parser.validate_content(zc)
                    if zv["word_count"] > 200:
                        print(f"  ✓ zhihu {ztype} with {ua[:30]}: {zv['word_count']}字")
                        all_contents.append((f"zhihu_{ztype}", zc))
                        break
            except:
                pass
    
    # 汇总
    print("\n" + "="*70)
    print("[汇总] 合并所有内容...")
    
    if all_contents:
        merged = parser.merge_contents(all_contents)
        merged_wc = cn_count(merged)
        print(f"  总来源数: {len(all_contents)}")
        print(f"  合并后总字数: {merged_wc}")
        
        print(f"\n  来源统计:")
        for name, content in all_contents:
            print(f"    - {name[:40]}: {cn_count(content)}字")
        
        # 检查是否有"下一章"链接或分页信息
        print(f"\n  结尾预览 (最后800字):")
        print(merged[-800:])
        
        # 保存
        output_md = f"""# 娇娇和她的忠犬小狗

> 来源: 知乎盐选《边月忠犬》
> 主角: 孟娇蕊、靳川、傅柏文、沈念念
> 总字数: {merged_wc}
> 获取方式: ZPE vNext 多引擎聚合提取

---

{merged}
"""
        out_path = Path(__file__).parent / "output" / "娇娇和她的忠犬小狗_完整版.md"
        out_path.write_text(output_md, encoding='utf-8')
        print(f"\n  已保存到: {out_path}")
        
        # 额外检查：这篇文是不是真的只有这么多章？
        if merged_wc < 5000:
            print(f"\n  注意: 当前字数较少({merged_wc}字)，可能是短篇，也可能还有更多内容待获取")
    
    await http.close()
    return 0


if __name__ == "__main__":
    asyncio.run(main())
