# -*- coding: utf-8 -*-
"""
ocr_engine.py - OCR视觉兜底引擎 (P2)

使用Playwright截图文章页面，然后用OCR识别文字。
支持PaddleOCR（中文优先）和Tesseract作为降级。
"""
import asyncio
import logging
import re
import time
from typing import Optional, List
from pathlib import Path
from io import BytesIO

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from core.parser import ContentParser, ParsedContent, extract_article_id
from core.session_manager import SessionManager
from core.fingerprint import (
    generate_fingerprint, get_playwright_stealth_script,
    CHROME_DESKTOP_UAS, CHROME_MOBILE_UAS,
)
from core.browser_utils import get_browser_launch_args

logger = logging.getLogger(__name__)

# OCR懒加载
_ocr_instance = None
_playwright_browser = None


def _get_ocr():
    """懒加载OCR引擎"""
    global _ocr_instance
    if _ocr_instance is not None:
        return _ocr_instance

    # 优先PaddleOCR
    try:
        from paddleocr import PaddleOCR
        _ocr_instance = PaddleOCR(
            use_angle_cls=True,
            lang=config.OCR_LANG,
            use_gpu=config.OCR_USE_GPU,
            show_log=False,
        )
        logger.info("PaddleOCR加载成功")
        return _ocr_instance
    except ImportError:
        logger.info("PaddleOCR未安装，尝试Tesseract")

    # Tesseract降级
    try:
        import pytesseract
        from PIL import Image
        _ocr_instance = ("tesseract", pytesseract, Image)
        logger.info("Tesseract加载成功")
        return _ocr_instance
    except ImportError:
        logger.warning("未安装PaddleOCR或Tesseract，OCR引擎不可用")
        _ocr_instance = False
        return None


async def _get_browser():
    """获取或创建浏览器实例"""
    global _playwright_browser
    if _playwright_browser is not None:
        return _playwright_browser
    try:
        from playwright.async_api import async_playwright
        pw = await async_playwright().start()
        launch_args = get_browser_launch_args(headless=config.PLAYWRIGHT_HEADLESS)
        _playwright_browser = await pw.chromium.launch(**launch_args)
        return _playwright_browser
    except Exception as e:
        logger.error(f"启动浏览器失败: {e}")
        return None


class OcrEngine:
    """
    OCR视觉兜底引擎。
    截图页面+OCR识别文字，适用于所有文本提取方式都失败的情况。
    """

    name = "ocr_engine"

    def __init__(self, session_manager: SessionManager):
        self.sm = session_manager
        self.parser = ContentParser()

    async def fetch(self, url: str) -> Optional[ParsedContent]:
        """
        截图+OCR提取内容。
        """
        start_time = time.time()

        ocr = _get_ocr()
        if ocr is None:
            logger.warning("OCR引擎不可用，跳过")
            return None

        browser = await _get_browser()
        if not browser:
            return None

        content = ParsedContent(original_url=url, platform="zhihu_ocr")

        # 分别尝试桌面端和移动端视口
        viewports = [
            ("desktop", {"width": 1440, "height": 900}, CHROME_DESKTOP_UAS[0]),
            ("mobile", {"width": 390, "height": 844}, CHROME_MOBILE_UAS[0]),
        ]

        for vp_name, viewport, ua in viewports:
            try:
                logger.info(f"OCR尝试 {vp_name} 视口")
                context = await browser.new_context(
                    user_agent=ua,
                    viewport=viewport,
                    device_scale_factor=2,
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                    is_mobile=(vp_name == "mobile"),
                    has_touch=(vp_name == "mobile"),
                )
                await context.add_init_script(get_playwright_stealth_script())
                page = await context.new_page()

                try:
                    await page.goto(url, wait_until="domcontentloaded",
                                   timeout=config.PLAYWRIGHT_TIMEOUT)
                    await asyncio.sleep(3)

                    # 关闭登录弹窗
                    for close_sel in [".Modal-closeButton", "button[aria-label=关闭]",
                                     ".close-btn", ".signFlowModal .Button"]:
                        try:
                            btn = await page.query_selector(close_sel)
                            if btn:
                                await btn.click()
                                await asyncio.sleep(0.5)
                        except:
                            pass

                    # 滚动到底部加载全部内容
                    await page.evaluate("""
                        async () => {
                            await new Promise((resolve) => {
                                let totalHeight = 0;
                                const distance = 500;
                                const timer = setInterval(() => {
                                    const scrollHeight = document.body.scrollHeight;
                                    window.scrollBy(0, distance);
                                    totalHeight += distance;
                                    if(totalHeight >= scrollHeight){
                                        clearInterval(timer);
                                        resolve();
                                    }
                                }, 200);
                            });
                        }
                    """)
                    await asyncio.sleep(2)

                    # 获取标题
                    if not content.title:
                        title_el = await page.query_selector("h1")
                        if title_el:
                            content.title = (await title_el.inner_text()).strip()
                        else:
                            content.title = await page.title()

                    # 全屏截图
                    screenshot_path = config.SCREENSHOT_DIR / f"ocr_{vp_name}_{int(time.time())}.png"
                    await page.screenshot(path=str(screenshot_path), full_page=True)
                    logger.info(f"截图保存: {screenshot_path}")

                    # OCR识别
                    text = await self._ocr_image(str(screenshot_path), ocr)
                    if text and len(text) > config.MIN_CONTENT_LENGTH:
                        # 清理OCR文字
                        text = self._clean_ocr_text(text)
                        if len(text) > len(content.content_markdown):
                            content.content_markdown = text
                            content.content_length = len(text)
                            content.is_truncated = False

                    # 也可以分段截图（针对很长的文章，分块识别提高精度）
                    segments = await self._screenshot_segments(page)
                    if segments:
                        seg_text = []
                        for seg_path in segments:
                            t = await self._ocr_image(seg_path, ocr)
                            if t:
                                seg_text.append(t)
                        full_text = "\n\n".join(seg_text)
                        full_text = self._clean_ocr_text(full_text)
                        if len(full_text) > len(content.content_markdown):
                            content.content_markdown = full_text
                            content.content_length = len(full_text)
                            content.is_truncated = False

                finally:
                    await page.close()
                    await context.close()

                if content.content_length >= config.MIN_CONTENT_LENGTH:
                    elapsed = time.time() - start_time
                    logger.info(f"OCR引擎成功 ({vp_name}): {content.title} ({content.content_length}字)")
                    return content

            except Exception as e:
                logger.warning(f"OCR {vp_name} 失败: {e}")
                continue

        logger.info("OCR引擎未能提取有效内容")
        return content if content.content_length > 100 else None

    async def _ocr_image(self, image_path: str, ocr) -> str:
        """对图片执行OCR，返回文本"""
        if isinstance(ocr, tuple) and ocr[0] == "tesseract":
            return self._ocr_tesseract(image_path, ocr)
        else:
            return await asyncio.to_thread(self._ocr_paddle, image_path, ocr)

    def _ocr_paddle(self, image_path: str, ocr) -> str:
        """PaddleOCR识别"""
        try:
            result = ocr.ocr(image_path, cls=True)
            lines = []
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) >= 2:
                        text = line[1][0] if isinstance(line[1], (list, tuple)) else str(line[1])
                        confidence = line[1][1] if isinstance(line[1], (list, tuple)) and len(line[1]) > 1 else 1.0
                        if confidence > 0.5:
                            lines.append(text)
            return "\n".join(lines)
        except Exception as e:
            logger.warning(f"PaddleOCR识别失败: {e}")
            return ""

    def _ocr_tesseract(self, image_path: str, ocr_tuple) -> str:
        """Tesseract识别"""
        try:
            _, pytesseract, Image = ocr_tuple
            img = Image.open(image_path)
            text = pytesseract.image_to_string(img, lang='chi_sim+eng')
            return text
        except Exception as e:
            logger.warning(f"Tesseract识别失败: {e}")
            return ""

    async def _screenshot_segments(self, page, segment_height: int = 2000) -> List[str]:
        """分段截图，避免长页面截图压缩导致OCR精度下降"""
        segments = []
        try:
            scroll_height = await page.evaluate("document.body.scrollHeight")
            viewport_height = page.viewport_size["height"]
            y = 0
            idx = 0
            while y < scroll_height:
                await page.evaluate(f"window.scrollTo(0, {y})")
                await asyncio.sleep(0.3)
                seg_path = str(config.SCREENSHOT_DIR / f"seg_{int(time.time())}_{idx}.png")
                await page.screenshot(path=seg_path)
                segments.append(seg_path)
                y += segment_height
                idx += 1
                if idx > 20:  # 最多20段
                    break
        except Exception as e:
            logger.debug(f"分段截图失败: {e}")
        return segments

    def _clean_ocr_text(self, text: str) -> str:
        """清理OCR识别文本"""
        if not text:
            return ""
        # 移除常见OCR噪声
        lines = text.split("\n")
        cleaned = []
        noise_patterns = [
            r'^知乎$', r'^盐选$', r'^广告$', r'^APP$',
            r'^打开.*App', r'^下载.*知乎', r'^立即打开',
            r'^相关推荐', r'^评论$', r'^点赞$',
            r'^\d+(\.\d+)?[kKwW万]?$',  # 纯数字（点赞数等）
        ]
        for line in lines:
            line = line.strip()
            if not line:
                if cleaned and cleaned[-1] != "":
                    cleaned.append("")
                continue
            is_noise = False
            for pat in noise_patterns:
                if re.match(pat, line):
                    is_noise = True
                    break
            if not is_noise:
                cleaned.append(line)

        text = "\n".join(cleaned)
        text = re.sub(r'\n{3,}', '\n\n', text)
        return text.strip()
