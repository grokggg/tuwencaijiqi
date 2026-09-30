# -*- coding: utf-8 -*-
"""
ZPE vNext - 知乎付费内容提取工具 vNext
核心配置文件
"""
import os
from pathlib import Path

# 项目根目录
ROOT_DIR = Path(__file__).parent
DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
REPORTS_DIR = ROOT_DIR / "reports"

for d in [DATA_DIR, OUTPUT_DIR, REPORTS_DIR]:
    d.mkdir(exist_ok=True, parents=True)

# 目标文章配置
TARGET = {
    "article_id": "1979959692122943787",
    "title": "娇娇和她的忠犬小狗",
    "alternate_titles": [
        "婚后一年老公从不碰我",
        "边月忠犬",
        "娇娇和她的忠犬",
    ],
    "main_characters": ["靳川", "孟娇蕊", "傅柏文", "沈念念"],
    "column_id": None,  # 将在侦察中填充
    "zhihu_urls": [
        "https://www.zhihu.com/market/paid_column/None/section/1979959692122943787",
        "https://zhuanlan.zhihu.com/p/1979959692122943787",
    ],
}

# 完整内容阈值（超过此字数认为是完整内容）
COMPLETE_CONTENT_MIN_WORDS = 15000  # 盐选专栏通常1-3万字

# 请求配置
REQUEST_CONFIG = {
    "timeout": 20,
    "max_retries": 3,
    "retry_delay": 1.5,
    "concurrent_requests": 5,
    "request_delay": (0.5, 2.0),  # 随机延迟范围
}

# User-Agent 池
USER_AGENTS = {
    "desktop_chrome": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "desktop_firefox": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) "
        "Gecko/20100101 Firefox/121.0"
    ),
    "mobile_chrome": (
        "Mozilla/5.0 (Linux; Android 13; Pixel 7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "mobile_safari": (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.0 Mobile/15E148 Safari/604.1"
    ),
    "zhihu_app_ios": (
        "ZhihuHybrid-iOS/9.10.0 (com.zhihu.ios; build:2600; iOS 17.0.0) "
        "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
        "AppleWebKit/605.1.15 Mobile/15E148"
    ),
    "zhihu_app_android": (
        "ZhihuHybrid-Android/9.10.0 (com.zhihu.android; build:2600; Android 13) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36"
    ),
    "baidu_spider": (
        "Mozilla/5.0 (compatible; Baiduspider/2.0; "
        "+http://www.baidu.com/search/spider.html)"
    ),
    "googlebot": (
        "Mozilla/5.0 (compatible; Googlebot/2.1; "
        "+http://www.google.com/bot.html)"
    ),
    "sogou_spider": (
        "Sogou web spider/4.0(+http://www.sogou.com/docs/help/webmasters.htm#07)"
    ),
    "bingbot": (
        "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)"
    ),
    "weread": (
        "WeRead/6.0.4 (iPhone; iOS 16.0; Scale/3.00)"
    ),
}

# 默认请求头
DEFAULT_HEADERS_DESKTOP = {
    "User-Agent": USER_AGENTS["desktop_chrome"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
}

DEFAULT_HEADERS_MOBILE = {
    "User-Agent": USER_AGENTS["mobile_chrome"],
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# 搜索引擎配置
SEARCH_ENGINES = {
    "baidu": {
        "url": "https://www.baidu.com/s",
        "params": {"wd": "{query}", "pn": "{page}"},
        "enabled": True,
    },
    "bing": {
        "url": "https://cn.bing.com/search",
        "params": {"q": "{query}", "first": "{page}"},
        "enabled": True,
    },
    "sogou": {
        "url": "https://www.sogou.com/web",
        "params": {"query": "{query}", "page": "{page}"},
        "enabled": True,
    },
    "360": {
        "url": "https://www.so.com/s",
        "params": {"q": "{query}", "pn": "{page}"},
        "enabled": True,
    },
}

# 已知小说转载站模板（之前发现的+扩展）
NOVEL_SITES = [
    # 之前验证过的
    {"name": "kepue.com", "url_template": "https://kepue.com/search.php?q={query}"},
    {"name": "syzgly.com", "url_template": "https://www.syzgly.com/search.php?q={query}"},
    # 扩展的常见小说站
    {"name": "biquge", "url_template": "https://www.biquge5200.com/search.php?q={query}"},
    {"name": "biqukan", "url_template": "https://www.biqukan.la/search.php?q={query}"},
    {"name": "xsbiquge", "url_template": "https://www.xsbiquge.com/search.php?q={query}"},
    {"name": "shuquge", "url_template": "https://www.shuquge.com/search.php?q={query}"},
    {"name": "txt99", "url_template": "https://www.txt99.org/search.php?q={query}"},
    {"name": "ibiquges", "url_template": "https://www.ibiquges.info/search.php?q={query}"},
    {"name": "23usp", "url_template": "https://www.23usp.com/search.php?q={query}"},
    {"name": "630la", "url_template": "https://www.630la.com/search.php?q={query}"},
    {"name": "biqugexx", "url_template": "https://www.biqugexx.com/search.php?q={query}"},
    {"name": "beqege", "url_template": "https://www.beqege.cc/search.php?q={query}"},
    {"name": "bqgui", "url_template": "https://www.bqgui.cc/search.php?q={query}"},
]

# 知乎API端点模板
ZHIHU_API_ENDPOINTS = [
    # 标准API
    "https://www.zhihu.com/api/v4/articles/{article_id}?include=content",
    "https://www.zhihu.com/api/v4/market/sections/{article_id}?include=content",
    "https://api.zhihu.com/articles/{article_id}?include=content",
    "https://api.zhihu.com/market/sections/{article_id}?include=content",
    # 专栏相关
    "https://www.zhihu.com/api/v4/market/paid_columns/{column_id}/sections/{article_id}?include=content",
    # 合作伙伴API
    "https://www.zhihu.com/api/v4/market/partner/weread/sections/{article_id}",
    "https://www.zhihu.com/api/v4/market/partner/baidu/sections/{article_id}",
    "https://www.zhihu.com/api/v4/market/partner/sogou/sections/{article_id}",
    "https://www.zhihu.com/api/v4/market/partner/toutiao/sections/{article_id}",
    # 内部API变体
    "https://api.zhihu.com/v4/market/sections/{article_id}?include=content",
    "https://appcloud.zhihu.com/v4/market/sections/{article_id}?include=content",
    # m站
    "https://m.zhihu.com/api/v4/articles/{article_id}?include=content",
]

# 最大迭代次数
MAX_ITERATIONS = 5
