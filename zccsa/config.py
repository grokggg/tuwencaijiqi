# -*- coding: utf-8 -*-
"""
ZCCSA - Zero-Cookie Content Security Auditor
全局配置文件
"""
import os
from pathlib import Path

# ============================================================
# 基础路径配置
# ============================================================
BASE_DIR = Path(__file__).parent.resolve()
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"

DATA_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# ============================================================
# 目标平台配置
# ============================================================
TARGET_DOMAIN = "zhihu.com"
BASE_URL = f"https://www.{TARGET_DOMAIN}"

# 付费内容URL模式
PAID_URL_PATTERNS = [
    r"zhihu\.com/market/paid_column/\d+/section/\d+",
    r"zhihu\.com/remix/essay/\d+",
    r"zhihu\.com/xen/\d+",
    r"zhuanlan\.zhihu\.com/p/\d+",
]

# ============================================================
# TLS指纹/会话配置
# ============================================================
# curl_cffi 伪装目标浏览器版本
IMPERSONATE_BROWSER = "chrome120"

# 请求超时（秒）
REQUEST_TIMEOUT = 15
# 指数退避重试配置
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.5  # 重试间隔基数（秒）
RETRY_BACKOFF_MAX = 10    # 最大重试间隔

# ============================================================
# 请求头默认值（Chrome 120 特征）
# ============================================================
DEFAULT_HEADERS_DESKTOP = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,"
              "image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"macOS"',
}

DEFAULT_HEADERS_MOBILE = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                  "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 "
                  "Mobile/15E148 Safari/604.1",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh-Hans;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Mobile-UA": "iPhone",
}

# ============================================================
# CDN缓存探测配置
# ============================================================
# 基线截断内容长度阈值（字节），超过则视为完整内容
BYPASS_LENGTH_THRESHOLD = 2000
# 内容Hash比较时是否忽略HTML标签
HASH_STRIP_HTML = True

# CDN Fuzzing 头模板（内网IP伪装、服务间调用、缓存控制等）
CDN_FUZZ_HEADERS = {
    "internal_ip": [
        {"X-Forwarded-For": "10.0.0.1"},
        {"X-Forwarded-For": "172.16.0.1"},
        {"X-Forwarded-For": "192.168.1.1"},
        {"X-Real-IP": "127.0.0.1"},
        {"X-Originating-IP": "[::1]"},
    ],
    "service_call": [
        {"X-Zhihu-Service": "article-api"},
        {"X-Internal-Request": "true"},
        {"X-Request-From": "internal"},
        {"X-Forwarded-Host": "article-api.zhihu.com"},
    ],
    "cache_control": [
        {"Cache-Control": "no-cache", "Pragma": "no-cache"},
        {"Cache-Control": "max-age=0"},
        {"Cache-Control": "no-store"},
        {"X-Cache-Bypass": "1"},
    ],
    "vendor_specific": [
        {"X-Vendor": "aliyun"},
        {"CF-Cache-Status": "HIT"},
        {"X-Cache": "HIT"},
        {"X-Cache-Lookup": "HIT"},
        {"Via": "cache25.l2cn1822[0,0,200-0,H], cache22.l2cn1822[0,0]"},
    ],
}

# ============================================================
# API端点扫描配置
# ============================================================
API_ENDPOINTS = [
    # 经典API
    "/api/v4/articles/{id}",
    "/api/v4/articles/{id}/concerned",
    "/api/v3/articles/{id}",
    "/api/v2/articles/{id}",
    "/api/articles/{id}",
    # 付费专栏/盐选
    "/api/v4/paid_columns/{column_id}/sections/{section_id}",
    "/api/v4/market/paid/columns/{column_id}/sections/{section_id}",
    "/api/v5/columns/{column_id}/sections/{section_id}",
    "/remix/api/essay/{id}",
    "/api/v4/remix/essays/{id}",
    # 老版本/移动端
    "/node/Answer/{id}",
    "/question/{id}/answer/{id}",
    "/appview/answer/{id}",
    "/api/v4/answers/{id}",
    "/api/v3/answers/{id}",
    # 专栏文章
    "/api/v4/posts/{id}",
    "/api/posts/{id}",
    # M端
    "/api/v4/market/paid/columns/{id}?include=newest_section",
]

# ============================================================
# 内容提取配置
# ============================================================
# 内容完整性阈值
MIN_CONTENT_LENGTH = 500  # 中文字符数
COMPLETE_CONTENT_LENGTH = 2000  # 视为完整内容的阈值

# 正文CSS选择器（按优先级）
CONTENT_SELECTORS = [
    # 知乎原生
    ".Post-RichTextContainer",
    ".RichText.ztext.Post-RichText",
    ".RichContent-inner",
    ".Post-Main",
    "article",
    ".ContentItem-article",
    # 通用
    ".article-content",
    ".post-content",
    ".content",
    "#content",
    ".entry-content",
    # 小说类
    ".novel-content",
    ".chapter-content",
    ".book-content",
    # 转载站常见
    ".read-content",
    "#chaptercontent",
    ".txt",
]

# 需要移除的噪声标签
NOISE_SELECTORS = [
    "script", "style", "noscript", "iframe",
    ".ContentItem-actions",
    ".Post-Subtitle",
    ".Post-Topics",
    ".AuthorInfo",
    ".Post-StickyBanner",
    ".Recommendations-Main",
    ".CommentList",
    ".Adslot",
    "nav", "footer", "header",
    ".modal", ".dialog", ".toast",
]

# ============================================================
# 引擎默认权重（越高越先执行）
# ============================================================
ENGINE_WEIGHTS = {
    "render_bypass_engine": 100,
    "api_endpoint_scanner": 90,
    "cdn_cache_engine": 80,
    "render_diff_engine": 70,
    "snapshot_engine": 60,
    "partner_token_engine": 50,
}

# ============================================================
# 监控配置
# ============================================================
MONITOR_STATS_FILE = DATA_DIR / "engine_stats.json"
MONITOR_WINDOW_HOURS = 24
# 权重衰减因子（每次失败后权重乘以该值）
WEIGHT_DECAY_FACTOR = 0.9
# 成功后权重恢复因子
WEIGHT_RECOVERY_FACTOR = 1.1
WEIGHT_MAX = 150
WEIGHT_MIN = 10

# ============================================================
# 并发与速率控制
# ============================================================
# CDN Fuzzing最大并发
CDN_FUZZ_CONCURRENCY = 8
# API扫描最大并发
API_SCAN_CONCURRENCY = 5
# 请求间隔（秒），用于速率控制
REQUEST_DELAY_MIN = 0.3
REQUEST_DELAY_MAX = 1.0

# ============================================================
# Playwright配置（渲染模式探测）
# ============================================================
PLAYWRIGHT_HEADLESS = True
PLAYWRIGHT_TIMEOUT = 20000  # 毫秒
# 反检测脚本
STEALTH_JS = """
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
window.chrome = { runtime: {} };
Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
Object.defineProperty(navigator, 'languages', {get: () => ['zh-CN', 'zh', 'en']});
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications' ?
        Promise.resolve({ state: Notification.permission }) :
        originalQuery(parameters)
);
"""

# ============================================================
# 第三方平台信任链配置
# ============================================================
PARTNER_HEADERS = {
    "wechat_read": [
        {"Referer": "https://weread.qq.com/"},
        {"Origin": "https://weread.qq.com"},
        {"X-Weread-Request": "1"},
    ],
    "zhihu_daily": [
        {"Referer": "https://daily.zhihu.com/"},
    ],
    "zhihu_mobile": [
        {"X-App-Version": "8.10.0"},
        {"X-App-Build": "2400"},
        {"X-App-Code": "100"},
    ],
}

# ============================================================
# 搜索引擎/快照源配置
# ============================================================
SEARCH_ENGINES = {
    "bing": "https://www.bing.com/search?q=site:zhihu.com+{title}",
    "baidu": "https://www.baidu.com/s?wd=site:zhihu.com+{title}",
    "google_cache": "https://webcache.googleusercontent.com/search?q=cache:{url}",
    "archive": "https://web.archive.org/web/2024*/{url}",
}
