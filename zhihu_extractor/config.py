#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知乎付费文章内容获取系统 - 全局配置
"""

# ========== 目标文章 ==========
TARGET = {
    "article_id": "1979959692122943787",
    "title": "娇娇和她的忠犬小狗",
    "alias_titles": [
        "婚后一年老公从不碰我",
        "正想偷汉子时眼前飘过弹幕",
        "娇娇和她的忠犬小狗大结局",
    ],
    "column_name": "边月忠犬",
    "characters": ["靳川", "孟娇蕊", "傅柏文"],
    "known_chapters": 5,          # kepue.com 上已知的章节数
    "suspected_more": True,        # 搜索结果显示可能有更多章节
    "publish_date": "2025-12-08",
}

# ========== HTTP 设置 ==========
HTTP = {
    "timeout": 12,
    "max_retries": 3,
    "retry_delay": 1.0,
    "rate_limit": 0.3,              # 请求间隔（秒）
    "follow_redirects": True,
    "verify_ssl": False,
    "compression": True,
}

# ========== User-Agent 池 ==========
USER_AGENTS = {
    "desktop_chrome": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "desktop_firefox": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "mobile_iphone": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1",
    "mobile_android": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36",
    "bot_baidu": "Mozilla/5.0 (compatible; Baiduspider/2.0; +http://www.baidu.com/search/spider.html)",
    "bot_bing": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
    "bot_google": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
}

# ========== 搜索引擎 ==========
SEARCH_ENGINES = {
    "bing": {
        "url": "https://cn.bing.com/search?q={query}&first={offset}",
        "selector": "li.b_algo",
        "link_selector": "a[href]",
    },
    "sogou_wx": {
        "url": "https://weixin.sogou.com/weixin?type=2&query={query}",
        "needs_js": True,
    },
    "sogou_web": {
        "url": "https://www.sogou.com/web?query={query}",
    },
    "baidu": {
        "url": "https://www.baidu.com/s?wd={query}",
        "needs_cookie": True,
    },
    "360": {
        "url": "https://www.so.com/s?q={query}",
    },
}

# ========== 已知小说站 ==========
NOVEL_SITES = [
    # (搜索URL模板, 名称, 需要移动端UA)
    ("https://m.kepue.com/nvpin/38738/{chapter}/", "kepue", True),
    ("https://www.syzgl.com/search/?q={query}", "syzgl", False),
    ("https://www.biqubo.com/search.html?searchtype=novelname&searchkey={query}", "biqubo", False),
    ("https://www.biquge.lu/search.php?q={query}", "biquge_lu", False),
    ("https://www.lwxs99.cc/search.php?q={query}", "lwxs99", False),
    ("https://www.biquwx.la/search.php?q={query}", "biquwx", False),
    ("https://www.biqubao.com/search.php?q={query}", "biqubao", False),
    ("https://www.81zw.com/search.php?q={query}", "81zw", False),
    ("https://www.88dus.com/search.php?q={query}", "88dus", False),
    ("https://www.bqg5200.com/search.php?q={query}", "bqg5200", False),
    ("https://www.ddxsku.com/search.php?q={query}", "ddxsku", False),
    ("https://www.xbiquge.la/modules/article/waps.php?searchkey={query}", "xbiquge_la", False),
]

# ========== 知乎 API 端点 ==========
ZHIHU_API = {
    "answer": "https://www.zhihu.com/api/v4/answers/{id}?include=content",
    "article": "https://zhuanlan.zhihu.com/api/articles/{id}",
    "column_items": "https://www.zhihu.com/api/v4/columns/{column}/items",
    "answer_page": "https://www.zhihu.com/question/{qid}/answer/{aid}",
    "article_page": "https://zhuanlan.zhihu.com/p/{id}",
}

# ========== Web Archive ==========
ARCHIVE_SOURCES = [
    "https://web.archive.org/web/2025*/https://zhuanlan.zhihu.com/p/{id}",
    "https://web.archive.org/web/2025*/https://www.zhihu.com/question/*/answer/{id}",
]

# ========== 输出 ==========
OUTPUT_DIR = "/workspace/zhihu_extractor/output"
DATA_DIR = "/workspace/zhihu_extractor/data"

# ========== 编排器设置 ==========
ORCHESTRATOR = {
    "max_iterations": 5,
    "engines_order": [
        "novel_scanner",
        "search_engine",
        "wechat_miner",
        "zhihu_api",
        "cache_archive",
    ],
    "confidence_threshold": 0.7,
}
