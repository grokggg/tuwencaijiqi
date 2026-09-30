# -*- coding: utf-8 -*-
"""
快速提取脚本 - 专注高价值路径
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
    print("ZPE vNext - 快速提取模式")
    print("="*70)
    
    all_contents = []
    
    # 加入已有内容
    print("\n[0] 加载已有内容...")
    existing_path = Path('/workspace/zhihu_paywall_agent/output/娇娇和她的忠犬小狗.md')
    if existing_path.exists():
        existing = existing_path.read_text(encoding='utf-8')
        all_contents.append(("existing", existing))
        print(f"  已有内容: {cn_count(existing)}字")
    
    # 1. 暴力枚举kepue章节（1-100），但使用更智能的检测
    print("\n[1] 枚举kepue.com章节...")
    headers_mobile = {"User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Version/17.0 Mobile/15E148 Safari/604.1"}
    
    found_chapters = []
    
    async def try_ch(num):
        url = f"https://m.kepue.com/nvpin/38738/{num}/"
        try:
            status, html, _ = await http.get(url, headers=headers_mobile, timeout=8)
            if status == 200 and html and len(html) > 1000:
                # 检查是否是有效章节
                if any(c in html for c in ['靳川', '孟娇蕊', '傅柏文', '弹幕']):
                    # 检查是否是404或错误页
                    if '404' not in html[:500] and '不存在' not in html[:500]:
                        title = f"第{num}章"
                        soup = BeautifulSoup(html, 'html.parser')
                        h1 = soup.find('h1')
                        if h1:
                            title = h1.get_text(strip=True)
                        _, content = parser.extract_main_content(html, url)
                        if cn_count(content) > 30:
                            return (num, title, content)
        except:
            pass
        return None
    
    sem = asyncio.Semaphore(5)
    async def try_sem(num):
        async with sem:
            return await try_ch(num)
    
    tasks = [try_sem(n) for n in range(1, 81)]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    for r in results:
        if isinstance(r, Exception) or not r:
            continue
        found_chapters.append(r)
    
    found_chapters.sort(key=lambda x: x[0])
    print(f"  找到 {len(found_chapters)} 个章节")
    
    if found_chapters:
        ch_content = "\n\n".join([f"## {t}\n\n{c}" for _, t, c in found_chapters])
        print(f"  章节内容总字数: {cn_count(ch_content)}")
        all_contents.append(("kepue_mobile", ch_content))
    
    # 2. 百度搜索，只搜索几个关键查询
    print("\n[2] 百度搜索关键查询...")
    queries = [
        "娇娇和她的忠犬小狗 全文免费阅读",
        "婚后一年老公从不碰我 完整版",
    ]
    
    found_urls = []
    headers_bd = {"User-Agent": random_ua()}
    
    for q in queries:
        try:
            status, html, _ = await http.get(f"https://www.baidu.com/s?wd={quote(q)}", headers=headers_bd, timeout=10)
            if status == 200 and html:
                soup = BeautifulSoup(html, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    text = a.get_text(strip=True)
                    if 'baidu.com/link' in href and len(text) > 5:
                        if any(kw in text for kw in ['娇娇', '忠犬', '靳川', '婚后一年', '免费阅读']):
                            found_urls.append((href, text))
        except Exception as e:
            print(f"  搜索失败: {e}")
        await asyncio.sleep(0.5)
    
    print(f"  发现 {len(found_urls)} 个搜索结果")
    
    # 3. 跟随搜索结果，提取内容和章节
    print("\n[3] 访问搜索结果...")
    novel_contents = []
    
    for r_url, r_text in found_urls[:10]:
        try:
            # 获取真实URL
            status, _, resp_h = await http.get(r_url, headers=headers_bd, follow_redirects=False, timeout=8)
            real_url = resp_h.get('location', '')
            if not real_url or not real_url.startswith('http'):
                continue
            
            print(f"  访问: {r_text[:30]} -> {real_url[:60]}")
            
            status2, html2, _ = await http.get(real_url, headers={"User-Agent": random_ua()}, timeout=10)
            if status2 != 200 or not html2:
                continue
            
            if not any(c in html2 for c in ['靳川', '孟娇蕊', '娇娇']):
                continue
            
            title, content = parser.extract_main_content(html2, real_url)
            validation = parser.validate_content(content)
            
            if validation["is_match"] and validation["word_count"] > 200:
                print(f"    ✓ 匹配: {validation['word_count']}字")
                novel_contents.append((real_url, content))
            
            # 提取章节链接
            chapters = parser.extract_chapter_links(html2, real_url)
            if chapters and len(chapters) >= 3:
                print(f"    发现 {len(chapters)} 个章节，爬取前20章...")
                chaps_to_crawl = chapters[:30]
                ch_results = []
                
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
                
                ch_tasks = [cc_sem(i, ct, cu) for i, (ct, cu) in enumerate(chaps_to_crawl)]
                ch_res = await asyncio.gather(*ch_tasks, return_exceptions=True)
                
                valid_ch = []
                for cr in ch_res:
                    if isinstance(cr, Exception) or not cr:
                        continue
                    valid_ch.append(cr)
                
                valid_ch.sort(key=lambda x: x[0])
                if valid_ch:
                    site_ch_content = "\n\n".join([f"## {ct}\n\n{cc}" for _, ct, cc in valid_ch])
                    print(f"    爬取到 {len(valid_ch)} 章, {cn_count(site_ch_content)}字")
                    novel_contents.append((real_url + "_chapters", site_ch_content))
        
        except Exception as e:
            print(f"  处理失败: {e}")
        await asyncio.sleep(0.3)
    
    all_contents.extend(novel_contents)
    
    # 4. 必应搜索补充
    print("\n[4] 必应搜索补充...")
    try:
        for q in ["娇娇和她的忠犬小狗 小说", "靳川 孟娇蕊 弹幕 全文"]:
            status, html, _ = await http.get(f"https://cn.bing.com/search?q={quote(q)}", headers={"User-Agent": random_ua()}, timeout=10)
            if status == 200 and html:
                soup = BeautifulSoup(html, 'html.parser')
                bing_urls = []
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    text = a.get_text(strip=True)
                    if href.startswith('http') and not any(skip in href for skip in ['bing.com', 'microsoft.com', 'zhihu.com']):
                        if any(kw in text for kw in ['娇娇', '忠犬', '靳川', '孟娇蕊']):
                            bing_urls.append((href, text))
                
                print(f"  必应发现 {len(bing_urls)} 个结果")
                
                for bu, bt in bing_urls[:5]:
                    try:
                        s, h, _ = await http.get(bu, headers={"User-Agent": random_ua()}, timeout=8)
                        if s == 200 and h and any(c in h for c in ['靳川', '孟娇蕊']):
                            _, bc = parser.extract_main_content(h, bu)
                            bv = parser.validate_content(bc)
                            if bv["is_match"] and bv["word_count"] > 200:
                                print(f"    ✓ 必应来源: {bv['word_count']}字")
                                all_contents.append((bu, bc))
                    except:
                        pass
                    await asyncio.sleep(0.2)
    except Exception as e:
        print(f"  必应搜索失败: {e}")
    
    # 5. 合并所有内容
    print("\n" + "="*70)
    print("[5] 合并所有内容...")
    
    if all_contents:
        merged = parser.merge_contents(all_contents)
        merged_wc = cn_count(merged)
        print(f"  合并后总字数: {merged_wc}")
        
        # 输出内容统计
        print(f"\n  各来源统计:")
        for name, content in all_contents:
            print(f"    - {name}: {cn_count(content)}字")
        
        # 保存最终结果
        output_md = f"""# 娇娇和她的忠犬小狗

> 来源: 知乎盐选《边月忠犬》
> 主角: 孟娇蕊、靳川、傅柏文、沈念念
> 总字数: {merged_wc}
> 获取方式: ZPE vNext 多引擎聚合

---

{merged}
"""
        
        out_path = Path(__file__).parent / "output" / "娇娇和她的忠犬小狗_完整版.md"
        out_path.write_text(output_md, encoding='utf-8')
        print(f"\n  已保存到: {out_path}")
        
        # 显示开头和结尾预览
        print(f"\n  开头预览:")
        print(merged[:300])
        print(f"\n  ...")
        print(f"\n  结尾预览:")
        print(merged[-500:])
    else:
        print("  未能获取到有效内容")
    
    await http.close()
    return 0


if __name__ == "__main__":
    asyncio.run(main())
