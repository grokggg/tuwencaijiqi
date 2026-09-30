# -*- coding: utf-8 -*-
"""
ZPE vNext - API Fuzzing与爬虫伪装引擎
探测各种API端点、伪装爬虫/合作伙伴请求
"""
import asyncio
import json
import random
import re
from typing import Dict, List, Any

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from core.http_client import cn_count, random_ua


class ApiFuzzEngine(BaseEngine):
    """API Fuzzing与爬虫伪装引擎"""
    
    name = "api_fuzz"
    description = "API端点探测与爬虫/合作伙伴伪装"
    priority = 80
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.article_id = config.TARGET["article_id"]
        
        # 爬虫/合作伙伴Profile
        self.profiles = {
            "baidu_spider": {
                "name": "百度爬虫",
                "ua": config.USER_AGENTS["baidu_spider"],
                "headers": {
                    "X-Forwarded-For": f"220.181.108.{random.randint(1,254)}",
                    "Accept": "text/html,application/xhtml+xml",
                }
            },
            "baidu_render": {
                "name": "百度渲染爬虫",
                "ua": "Mozilla/5.0 (compatible; Baiduspider-render/2.0; +http://www.baidu.com/search/spider.html)",
                "headers": {
                    "X-Forwarded-For": f"123.125.71.{random.randint(1,254)}",
                }
            },
            "googlebot": {
                "name": "Googlebot",
                "ua": config.USER_AGENTS["googlebot"],
                "headers": {
                    "X-Forwarded-For": f"66.249.{random.randint(1,254)}.{random.randint(1,254)}",
                }
            },
            "bingbot": {
                "name": "Bingbot",
                "ua": config.USER_AGENTS["bingbot"],
                "headers": {
                    "X-Forwarded-For": f"207.46.{random.randint(1,254)}.{random.randint(1,254)}",
                }
            },
            "sogou_spider": {
                "name": "搜狗爬虫",
                "ua": config.USER_AGENTS["sogou_spider"],
                "headers": {
                    "X-Partner-Id": "sogou",
                    "X-Crawler": "sogou",
                }
            },
            "360_spider": {
                "name": "360爬虫",
                "ua": "Mozilla/5.0 (compatible; 360Spider/2.0; +http://www.so.com/help/help_3_2.html)",
                "headers": {
                    "X-Forwarded-For": f"180.153.{random.randint(1,254)}.{random.randint(1,254)}",
                }
            },
            "shenma": {
                "name": "神马搜索",
                "ua": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Mobile/15E148 Safari/604.1 ShenmaSearch/2.0",
                "headers": {"X-Partner-Id": "shenma"}
            },
            "weread_partner": {
                "name": "微信读书合作伙伴",
                "ua": config.USER_AGENTS["weread"],
                "headers": {
                    "X-Platform-Source": "weread",
                    "X-Partner-Id": "weread",
                    "Referer": "https://weread.qq.com/",
                }
            },
            "toutiao_partner": {
                "name": "头条合作伙伴",
                "ua": config.USER_AGENTS["mobile_chrome"] + " NewsArticle/8.10.0",
                "headers": {
                    "X-Partner-Id": "toutiao",
                    "X-Channel": "toutiao",
                    "Referer": "https://www.toutiao.com/",
                }
            },
            "zhihu_ios": {
                "name": "知乎iOS App",
                "ua": config.USER_AGENTS["zhihu_app_ios"],
                "headers": {
                    "X-App-Version": "9.10.0",
                    "X-App-Build": "2600",
                    "X-Platform": "ios",
                    "X-Api-Version": "3.0.40",
                    "Accept": "*/*",
                }
            },
            "zhihu_android": {
                "name": "知乎Android App",
                "ua": config.USER_AGENTS["zhihu_app_android"],
                "headers": {
                    "X-App-Version": "9.10.0",
                    "X-Platform": "android",
                    "X-Api-Version": "3.0.40",
                }
            },
            "m_zhihu": {
                "name": "移动端m.zhihu.com",
                "ua": config.USER_AGENTS["mobile_chrome"],
                "headers": {}
            },
        }
    
    async def run(self, context: Dict[str, Any]) -> EngineResult:
        result = self.create_result()
        
        best_content = ""
        best_source = ""
        best_confidence = 0.0
        best_word_count = 0
        bypass_method = ""
        successful_bypasses = []
        
        # 构建要测试的URL列表
        test_urls = self._build_test_urls()
        
        self.logger.info(f"准备测试 {len(self.profiles)} 个身份Profile × {len(test_urls)} 个端点...")
        
        sem = asyncio.Semaphore(4)
        
        async def test_profile(profile_name: str, profile: Dict):
            async with sem:
                return await self._test_profile(profile_name, profile, test_urls)
        
        tasks = [test_profile(pn, p) for pn, p in self.profiles.items()]
        profile_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        for pr in profile_results:
            if isinstance(pr, Exception) or not pr:
                continue
            p_name, content, source, validation, method = pr
            if content and validation["is_match"]:
                successful_bypasses.append({
                    "profile": p_name,
                    "source": source,
                    "word_count": validation["word_count"],
                    "confidence": validation["confidence"],
                    "method": method,
                })
                if validation["confidence"] > best_confidence and validation["word_count"] > best_word_count:
                    best_confidence = validation["confidence"]
                    best_content = content
                    best_source = source
                    best_word_count = validation["word_count"]
                    bypass_method = method
        
        if best_content and best_word_count > 200:
            result.success = True
            result.content = best_content
            result.source_url = best_source
            result.word_count = best_word_count
            result.confidence = best_confidence
            result.bypass_method = bypass_method or f"API/爬虫伪装: {best_source} ({best_word_count}字)"
            if best_word_count > 2000 and not self._looks_truncated(best_content):
                result.bypass_found = True
        
        result.details = {
            "profiles_tested": list(self.profiles.keys()),
            "endpoints_tested": len(test_urls),
            "successful_bypasses": successful_bypasses[:10],
        }
        
        return result
    
    def _build_test_urls(self) -> List[str]:
        """构建要测试的URL列表"""
        urls = []
        aid = self.article_id
        
        # 各种页面URL
        page_urls = [
            f"https://www.zhihu.com/market/paid_column/None/section/{aid}",
            f"https://zhuanlan.zhihu.com/p/{aid}",
            f"https://www.zhihu.com/answer/{aid}",
            f"https://m.zhihu.com/question/None/answer/{aid}",
            f"https://m.zhihu.com/p/{aid}",
        ]
        
        # API端点
        api_endpoints = [
            f"https://www.zhihu.com/api/v4/articles/{aid}?include=content,excerpt,author",
            f"https://www.zhihu.com/api/v4/market/sections/{aid}?include=content",
            f"https://www.zhihu.com/api/v4/market/sections/{aid}/content",
            f"https://api.zhihu.com/articles/{aid}?include=content",
            f"https://api.zhihu.com/market/sections/{aid}?include=content",
            f"https://api.zhihu.com/v4/market/sections/{aid}?include=content",
            f"https://m.zhihu.com/api/v4/articles/{aid}?include=content",
            # 合作伙伴API
            f"https://www.zhihu.com/api/v4/market/partner/weread/sections/{aid}",
            f"https://www.zhihu.com/api/v4/market/partner/baidu/sections/{aid}",
            f"https://www.zhihu.com/api/v4/market/partner/sogou/sections/{aid}",
            f"https://www.zhihu.com/api/v4/market/partner/toutiao/sections/{aid}",
        ]
        
        urls.extend(page_urls)
        urls.extend(api_endpoints)
        return urls
    
    async def _test_profile(self, profile_name: str, profile: Dict, urls: List[str]):
        """测试单个身份Profile"""
        p_name = profile["name"]
        ua = profile["ua"]
        extra_headers = profile.get("headers", {})
        
        best_content = ""
        best_source = ""
        best_validation = None
        best_method = ""
        
        headers = {
            "User-Agent": ua,
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        headers.update(extra_headers)
        
        for url in urls:
            try:
                # 针对API添加适当的Accept头
                req_headers = dict(headers)
                if "/api/" in url:
                    req_headers["Accept"] = "application/json, text/plain, */*"
                    req_headers["Referer"] = "https://www.zhihu.com/"
                
                status, body, resp_headers = await self.http.get(url, headers=req_headers)
                
                if status != 200 or not body:
                    continue
                
                content = ""
                method = f"{p_name} -> {url}"
                
                # 尝试解析JSON响应
                if body.strip().startswith('{') or body.strip().startswith('['):
                    try:
                        data = json.loads(body)
                        content = self._extract_from_json(data)
                    except:
                        content = ""
                else:
                    # HTML响应
                    _, content = self.parser.extract_main_content(body, url)
                
                if not content or cn_count(content) < 50:
                    continue
                
                # 检查是否是错误页/登录页
                if any(skip in content for skip in ['安全验证', '登录', '请登录', 'Unauthorized', 'Forbidden']):
                    if cn_count(content) < 200:
                        continue
                
                validation = self.parser.validate_content(content)
                if validation["is_match"] and validation["word_count"] > cn_count(best_content):
                    best_content = content
                    best_source = url
                    best_validation = validation
                    best_method = method
                    
                    # 如果找到了足够长的内容，可以提前退出
                    if validation["word_count"] > 3000 and not validation["is_truncated"]:
                        break
                
            except Exception as e:
                self.logger.debug(f"  {p_name} 测试失败 {url}: {e}")
                continue
        
        if best_content:
            return (p_name, best_content, best_source, best_validation, best_method)
        return None
    
    def _extract_from_json(self, data: Any) -> str:
        """从JSON响应中提取内容字段"""
        content = ""
        
        def search_dict(d):
            nonlocal content
            if isinstance(d, dict):
                for key in ['content', 'html', 'body', 'text', 'excerpt', 'answer_content', 'section_content']:
                    if key in d and isinstance(d[key], str):
                        val = d[key]
                        # 移除HTML标签
                        if '<' in val and '>' in val:
                            from bs4 import BeautifulSoup
                            val = BeautifulSoup(val, 'html.parser').get_text(separator='\n', strip=True)
                        if cn_count(val) > cn_count(content):
                            content = val
                for v in d.values():
                    search_dict(v)
            elif isinstance(d, list):
                for item in d:
                    search_dict(item)
        
        search_dict(data)
        return content
    
    def _looks_truncated(self, content: str) -> bool:
        """检查内容是否被截断"""
        truncate_words = ['余下全文', 'VIP', '付费', '登录后', '展开全文', '购买专栏', '盐选会员']
        tail = content[-300:] if len(content) > 300 else content
        return any(w in tail for w in truncate_words)
