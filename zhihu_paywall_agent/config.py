# -*- coding: utf-8 -*-
"""
config.py - 全局配置
"""
import os
from pathlib import Path

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = BASE_DIR / "output"
MONITOR_FILE = DATA_DIR / "monitor_stats.json"
COOKIE_FILE = DATA_DIR / "cookies.txt"
CACHE_DIR = DATA_DIR / "cache"

# 确保目录存在
for d in [DATA_DIR, OUTPUT_DIR, CACHE_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# 知乎域名与API端点
# ============================================================
ZHIHU_DOMAIN = "www.zhihu.com"
ZHIHU_API_BASE = f"https://{ZHIHU_DOMAIN}/api/v4"
ZHIHU_API_V2 = f"https://{ZHIHU_DOMAIN}/api/v2"
ZHIHU_API_V1 = f"https://{ZHIHU_DOMAIN}/api/v1"
ZHIHU_MARKET_API = f"{ZHIHU_API_BASE}/market/paid_column"
ZHIHU_OIA_URL = "https://oia.zhihu.com/km_paid_content/share"

# 用户信息校验端点（验证Cookie有效性）
ME_API = f"{ZHIHU_API_BASE}/me"

# 分享链接生成API
SHARE_CREATE_API = f"{ZHIHU_MARKET_API}/share"

# 分享授权API（获取临时token）
SHARE_GRANT_API_TEMPLATE = f"{ZHIHU_MARKET_API}/shares/{{share_id}}/grant"

# 文章内容API
ARTICLE_CONTENT_API_TEMPLATE = f"{ZHIHU_MARKET_API}/articles/{{article_id}}/content"
ARTICLE_DETAIL_API_TEMPLATE = f"{ZHIHU_MARKET_API}/articles/{{article_id}}"

# 旧版/降级API端点列表（供internal_api_engine尝试）
LEGACY_API_ENDPOINTS = [
    f"{ZHIHU_API_V2}/columns/{{}}/posts/{{}}",
    f"{ZHIHU_API_V1}/article/{{}}",
    f"{ZHIHU_API_BASE}/articles/{{}}",
    f"{ZHIHU_API_BASE}/posts/{{}}",
    f"{ZHIHU_MARKET_API}/{{}}/section/{{}}",
    f"https://oia.zhihu.com/api/v4/paid_contents/{{}}",
    f"https://api.zhihu.com/paid_contents/{{}}",
    f"https://soia.zhihu.com/km_paid_content/share",
]

# ============================================================
# TLS指纹与HTTP配置
# ============================================================
# curl_cffi 支持的Chrome版本指纹
TLS_IMPERSONATE = "chrome120"

# 请求超时（秒）
REQUEST_TIMEOUT = 20
# 重试次数
MAX_RETRIES = 3
# 重试退避初始延迟（秒）
RETRY_BACKOFF_BASE = 1.5
# 请求间隔（秒），避免触发风控
REQUEST_DELAY = (1.0, 3.0)  # 随机范围

# ============================================================
# Playwright配置
# ============================================================
PLAYWRIGHT_HEADLESS = True
PLAYWRIGHT_TIMEOUT = 30000  # 毫秒
PLAYWRIGHT_WAIT_UNTIL = "networkidle"  # 等待网络空闲
PLAYWRIGHT_VIEWPORT = {"width": 390, "height": 844}  # iPhone 12 Pro
PLAYWRIGHT_DEVICE_SCALE = 3

# ============================================================
# 搜索引擎配置（跨平台搜索）
# ============================================================
SEARCH_ENGINES = {
    "bing": "https://www.bing.com/search?q={query}",
    "baidu": "https://www.baidu.com/s?wd={query}",
    "sogou_weixin": "https://weixin.sogou.com/weixin?type=2&query={query}",
    "csdn": "https://so.csdn.net/so/search?q={query}&t=all",
    "jianshu": "https://www.jianshu.com/search?q={query}",
    "cnblogs": "https://zzk.cnblogs.com/s?w={query}",
}

# 搜索关键词模板
SEARCH_QUERY_TEMPLATES = [
    '{title} 全文',
    '{title} 知乎 盐选',
    '{title} 免费阅读',
    '{title} 转载',
    '"{title}"',
]

# ============================================================
# OCR配置
# ============================================================
OCR_LANG = "ch"  # PaddleOCR中文模型
OCR_USE_GPU = False
SCREENSHOT_DIR = DATA_DIR / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

# ============================================================
# Cookie池配置
# ============================================================
# Cookie验证间隔（秒），避免频繁校验
COOKIE_CHECK_INTERVAL = 300
# 最少保留的有效Cookie数量
MIN_VALID_COOKIES = 1
# Cookie在请求间随机轮换
COOKIE_ROTATE = True

# ============================================================
# 监控配置
# ============================================================
MONITOR_WINDOW_HOURS = 24
# 引擎初始权重（P0最高优先）
ENGINE_INITIAL_WEIGHTS = {
    "share_engine": 100,       # P0: 分享免费读
    "cookie_pool_engine": 80,   # P1: Cookie池
    "internal_api_engine": 70,  # P1: 内部API降级
    "cross_platform_engine": 60, # P1: 多平台搜索
    "cache_engine": 50,         # 缓存
    "ocr_engine": 20,           # P2: OCR兜底
    "basic_http_engine": 10,    # P3: 基础HTTP页面抓取（最终兜底）
}
# 成功率阈值，低于此值降权
MIN_SUCCESS_RATE = 0.1
# 权重衰减系数
WEIGHT_DECAY = 0.9

# ============================================================
# 内容验证配置
# ============================================================
# 判断为"完整内容"的最小正文字符数
MIN_CONTENT_LENGTH = 500
# 试读截断标记（如果包含这些词说明内容被截断）
TRUNCATION_MARKERS = [
    "阅读全文", "查看全文", "开通盐选", "继续阅读",
    "会员免费", "成为会员", "解锁全文", "付费阅读",
    "剩余.*?部分需付费", "App 内查看", "打开App",
]
# 噪声选择器（解析时自动剥离）
NOISE_SELECTORS = [
    "nav", "footer", "aside", ".sidebar", ".ad", ".advertisement",
    ".recommend", ".related", ".comment", ".CommentsContainer",
    ".Reward", ".CornerButtons", ".ContentItem-actions",
    ".Post-Sign", ".FollowButton", ".VoteButton",
    ".ModalWrap", ".AdblockBanner",
]

# ============================================================
# 日志配置
# ============================================================
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
