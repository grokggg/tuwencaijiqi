# -*- coding: utf-8 -*-
"""
fingerprint.py - 浏览器与设备指纹伪装

为每个HTTP会话生成独立、一致的浏览器指纹，
包括UA、屏幕分辨率、语言、平台等，并提供Playwright stealth注入脚本。
"""
import random
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional

# ============================================================
# 真实浏览器UA池（2025-2026主流版本）
# ============================================================
CHROME_DESKTOP_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
]

CHROME_MOBILE_UAS = [
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/125.0.6422.80 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/125.0.6422.80 Mobile/15E148 Safari/604.1",
    "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.6422.113 Mobile Safari/537.36",
    "Mozilla/5.0 (Linux; Android 14; SM-S928U) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.6478.71 Mobile Safari/537.36",
]

# 知乎App WebView UA
ZHIHU_APP_IOS_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Zhihu/9.28.0"
ZHIHU_APP_ANDROID_UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ2A.230505.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 Zhihu/9.28.0"

# 微信内置浏览器UA
WECHAT_UA = "Mozilla/5.0 (Linux; Android 13; Pixel 7 Build/TQ2A.230505.002; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/116.0.0.0 Mobile Safari/537.36 MicroMessenger/8.0.40.2420(0x28002857) WeChat/arm64"

# ============================================================
# 屏幕分辨率池
# ============================================================
DESKTOP_RESOLUTIONS = [
    (1920, 1080), (2560, 1440), (1366, 768),
    (1440, 900), (1536, 864), (2880, 1800),
]
MOBILE_RESOLUTIONS = [
    (390, 844),   # iPhone 12/13/14 Pro
    (393, 852),   # iPhone 14/15 Pro
    (414, 896),   # iPhone 11/XR
    (360, 800),   # Android common
    (412, 915),   # Pixel 7
    (384, 854),   # Android common
]

# ============================================================
# Accept-Language 池
# ============================================================
ACCEPT_LANGUAGES = [
    "zh-CN,zh;q=0.9,en;q=0.8",
    "zh-CN,zh;q=0.9",
    "zh-Hans-CN;q=1,en-CN;q=0.9",
    "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
]

# ============================================================
# 平台信息池
# ============================================================
PLATFORMS = ["Win32", "MacIntel", "Linux x86_64", "iPhone", "Linux armv8l"]
WEBGL_VENDORS = [
    ("Google Inc. (NVIDIA)", "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Google Inc. (Apple)", "ANGLE (Apple, Apple M1, OpenGL 4.1)"),
    ("Google Inc. (Intel)", "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)"),
    ("Apple Inc.", "Apple M1"),
]
AUDIO_CODECS = ["mp4a.40.2", "mp4a.40.5", "opus"]
VIDEO_CODECS = ["avc1.42E01E", "vp8", "vp9", "av01.0.00M.08"]

# ============================================================
# 请求头顺序（模拟Chrome真实顺序）
# ============================================================
CHROME_HEADER_ORDER = [
    "Host", "Connection", "Cache-Control", "sec-ch-ua",
    "sec-ch-ua-mobile", "sec-ch-ua-platform",
    "Upgrade-Insecure-Requests", "User-Agent",
    "Accept", "Sec-Fetch-Site", "Sec-Fetch-Mode",
    "Sec-Fetch-User", "Sec-Fetch-Dest",
    "Referer", "Accept-Encoding", "Accept-Language", "Cookie",
]


@dataclass
class Fingerprint:
    """完整的设备/浏览器指纹"""
    user_agent: str = ""
    accept_language: str = ""
    platform: str = ""
    vendor: str = "Google Inc."
    screen_width: int = 1920
    screen_height: int = 1080
    viewport_width: int = 1920
    viewport_height: int = 947
    pixel_ratio: float = 1.0
    color_depth: int = 24
    timezone: str = "Asia/Shanghai"
    timezone_offset: int = -480  # UTC+8 分钟
    webgl_vendor: str = ""
    webgl_renderer: str = ""
    audio_codec: str = ""
    video_codec: str = ""
    hardware_concurrency: int = 8
    device_memory: float = 8.0
    is_mobile: bool = False
    cookies_enabled: bool = True
    do_not_track: str = ""
    tls_impersonate: str = "chrome120"
    extra_headers: Dict[str, str] = field(default_factory=dict)

    def to_headers(self, host: str = "", referer: str = "") -> Dict[str, str]:
        """生成HTTP请求头字典"""
        is_mobile_ua = "Mobile" in self.user_agent or "Android" in self.user_agent or "iPhone" in self.user_agent
        
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
            "Accept-Language": self.accept_language,
            "Accept-Encoding": "gzip, deflate, br",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "sec-ch-ua": '"Chromium";v="125", "Not.A/Brand";v="24", "Google Chrome";v="125"',
            "sec-ch-ua-mobile": f"?{'1' if is_mobile_ua else '0'}",
            "sec-ch-ua-platform": f'"{"iOS" if "iPhone" in self.user_agent else "Android" if "Android" in self.user_agent else "Windows" if "Windows" in self.user_agent else "macOS"}"',
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none" if not referer else "same-origin",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "Connection": "keep-alive",
        }
        if host:
            headers["Host"] = host
        if referer:
            headers["Referer"] = referer
        headers.update(self.extra_headers)
        return headers

    def to_dict(self) -> dict:
        return asdict(self)


def generate_fingerprint(mobile: bool = False, zhihu_app: bool = False,
                         wechat: bool = False) -> Fingerprint:
    """
    生成一个随机但一致的设备指纹。

    Args:
        mobile: 是否生成移动端指纹
        zhihu_app: 是否使用知乎App WebView UA
        wechat: 是否使用微信浏览器UA
    """
    if zhihu_app:
        if random.random() < 0.5:
            ua = ZHIHU_APP_IOS_UA
            fp = Fingerprint(
                user_agent=ua,
                accept_language="zh-Hans-CN;q=1",
                platform="iPhone",
                screen_width=390, screen_height=844,
                viewport_width=390, viewport_height=709,
                pixel_ratio=3.0, color_depth=32,
                is_mobile=True,
                tls_impersonate="safari17_0",  # iOS WebView
            )
        else:
            ua = ZHIHU_APP_ANDROID_UA
            w, h = random.choice(MOBILE_RESOLUTIONS)
            fp = Fingerprint(
                user_agent=ua,
                accept_language="zh-CN,zh;q=0.9",
                platform="Linux armv8l",
                screen_width=w, screen_height=h,
                viewport_width=w, viewport_height=int(h * 0.85),
                pixel_ratio=random.choice([2.75, 3.0, 3.5]),
                color_depth=24,
                is_mobile=True,
                extra_headers={"X-Requested-With": "com.zhihu.android"},
            )
    elif wechat:
        fp = Fingerprint(
            user_agent=WECHAT_UA,
            accept_language="zh-CN,zh;q=0.9",
            platform="Linux armv8l",
            screen_width=390, screen_height=844,
            viewport_width=390, viewport_height=709,
            pixel_ratio=3.0, color_depth=24,
            is_mobile=True,
            extra_headers={"X-Requested-With": "com.tencent.mm"},
        )
    elif mobile:
        ua = random.choice(CHROME_MOBILE_UAS)
        w, h = random.choice(MOBILE_RESOLUTIONS)
        vendor, renderer = random.choice(WEBGL_VENDORS)
        fp = Fingerprint(
            user_agent=ua,
            accept_language=random.choice(ACCEPT_LANGUAGES),
            platform="iPhone" if "iPhone" in ua else "Linux armv8l",
            screen_width=w, screen_height=h,
            viewport_width=w, viewport_height=int(h * 0.85),
            pixel_ratio=random.choice([2.0, 2.75, 3.0]),
            color_depth=32 if "iPhone" in ua else 24,
            webgl_vendor=vendor, webgl_renderer=renderer,
            audio_codec=random.choice(AUDIO_CODECS),
            video_codec=random.choice(VIDEO_CODECS),
            hardware_concurrency=random.choice([4, 6, 8]),
            device_memory=random.choice([4.0, 6.0, 8.0]),
            is_mobile=True,
        )
    else:
        ua = random.choice(CHROME_DESKTOP_UAS)
        w, h = random.choice(DESKTOP_RESOLUTIONS)
        vendor, renderer = random.choice(WEBGL_VENDORS)
        fp = Fingerprint(
            user_agent=ua,
            accept_language=random.choice(ACCEPT_LANGUAGES),
            platform="Win32" if "Windows" in ua else "MacIntel" if "Macintosh" in ua else "Linux x86_64",
            screen_width=w, screen_height=h,
            viewport_width=w, viewport_height=h - 93,  # 减去浏览器栏
            pixel_ratio=random.choice([1.0, 1.25, 1.5, 2.0]),
            color_depth=24,
            webgl_vendor=vendor, webgl_renderer=renderer,
            audio_codec=random.choice(AUDIO_CODECS),
            video_codec=random.choice(VIDEO_CODECS),
            hardware_concurrency=random.choice([4, 6, 8, 12, 16]),
            device_memory=random.choice([8.0, 16.0, 32.0]),
            is_mobile=False,
        )
    return fp


# ============================================================
# Playwright Stealth 脚本（隐藏自动化痕迹）
# ============================================================
PLAYWRIGHT_STEALTH_JS = """
() => {
    // 1. 覆盖 navigator.webdriver
    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

    // 2. 模拟 chrome 对象
    window.chrome = {
        runtime: {
            connect: () => {},
            sendMessage: () => {},
            onMessage: { addListener: () => {}, removeListener: () => {} },
            getPlatformInfo: (cb) => cb({ os: 'mac', arch: 'arm', nacl_arch: 'arm' }),
        },
        loadTimes: () => ({
            commitLoadTime: Date.now()/1000 - Math.random()*5,
            connectionInfo: 'h2',
            finishDocumentLoadTime: Date.now()/1000,
            finishLoadTime: Date.now()/1000,
            firstPaintAfterLoadTime: 0,
            firstPaintTime: Date.now()/1000 - Math.random()*3,
            navigationType: 'Other',
            npnNegotiatedProtocol: 'h2',
            requestTime: Date.now()/1000 - Math.random()*5,
            startLoadTime: Date.now()/1000 - Math.random()*5,
            wasAlternateProtocolAvailable: false,
            wasFetchedViaSpdy: true,
            wasNpnNegotiated: true,
        }),
        csi: () => ({
            onloadT: Date.now(),
            pageT: Math.random()*1000,
            startE: Date.now() - Math.random()*1000,
            tran: 15,
        }),
        app: { isInstalled: false, InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' }, RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' } },
    };

    // 3. 覆盖 permissions.query
    const originalQuery = window.navigator.permissions.query;
    window.navigator.permissions.query = (parameters) => (
        parameters.name === 'notifications' ?
            Promise.resolve({ state: Notification.permission }) :
            originalQuery(parameters)
    );

    // 4. 覆盖 plugins（模拟真实插件数量）
    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const plugins = [
                { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai', description: '' },
                { name: 'Native Client', filename: 'internal-nacl-plugin', description: '' },
            ];
            plugins.refresh = () => {};
            return plugins;
        },
    });

    // 5. 覆盖 languages
    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });

    // 6. 隐藏自动化框架痕迹
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_;
    delete window.cdc_asdjflasutopfhvcZLmcfl_;

    // 7. 覆盖 toString 检查
    const originalToString = Function.prototype.toString;
    Function.prototype.toString = function() {
        if (this === Function.prototype.toString) return originalToString.call(this);
        const s = originalToString.call(this);
        if (s.includes('native code') && !s.includes('[native code]')) {
            return 'function ' + (this.name || '') + '() { [native code] }';
        }
        return s;
    };

    // 8. 模拟 webgl 信息
    const getParameter = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(param) {
        if (param === 37445) return 'Google Inc. (Intel)';  // UNMASKED_VENDOR_WEBGL
        if (param === 37446) return 'ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0, D3D11)';
        return getParameter.call(this, param);
    };

    // 9. 模拟 mediaDevices
    if (navigator.mediaDevices) {
        const origEnumerate = navigator.mediaDevices.enumerateDevices;
        navigator.mediaDevices.enumerateDevices = async function() {
            const devices = await origEnumerate.call(this);
            if (devices.length === 0) {
                return [
                    { deviceId: 'default', kind: 'audioinput', label: 'Default - 麦克风', groupId: 'default' },
                    { deviceId: 'default', kind: 'audiooutput', label: 'Default - 扬声器', groupId: 'default' },
                ];
            }
            return devices;
        };
    }

    // 10. 模拟 Battery API
    if (navigator.getBattery) {
        navigator.getBattery = async () => ({
            charging: true,
            chargingTime: 0,
            dischargingTime: Infinity,
            level: 0.86 + Math.random()*0.14,
            addEventListener: () => {},
            removeEventListener: () => {},
            onchargingchange: null,
            onchargingtimechange: null,
            ondischargingtimechange: null,
            onlevelchange: null,
        });
    }

    // 11. 覆盖 connection (Network Information API)
    if (navigator.connection) {
        Object.defineProperty(navigator.connection, 'rtt', { get: () => 50 + Math.floor(Math.random()*50) });
        Object.defineProperty(navigator.connection, 'downlink', { get: () => 5 + Math.random()*5 });
        Object.defineProperty(navigator.connection, 'effectiveType', { get: () => '4g' });
    }
}
"""


def get_playwright_stealth_script() -> str:
    """返回Playwright stealth JS代码"""
    return PLAYWRIGHT_STEALTH_JS
