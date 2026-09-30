# -*- coding: utf-8 -*-
"""
ZCCSA 渲染模式探测引擎
- 使用Playwright无头浏览器分别以JS启用/禁用模式访问
- 对比DOM差异，检测"服务端返回完整HTML但前端JS/CSS隐藏"情况
- 注入反检测脚本
"""
import asyncio
import logging
import re
from typing import Any, Dict, Optional

from engines.base_engine import BaseEngine, EngineResult

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


class RenderBypassEngine(BaseEngine):
    """
    渲染模式探测引擎
    原理：很多付费墙在前端实现（JS渲染时隐藏内容），但服务端返回的HTML
    实际包含完整内容。禁用JS后直接从DOM提取内容，可验证此假设。
    """

    name = "render_bypass_engine"
    description = "渲染模式探测（JS启用/禁用DOM对比）"
    default_weight = 100

    async def _probe(self, url: str, article_id: Dict,
                     result: EngineResult) -> EngineResult:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            result.error = "playwright未安装，请运行: pip install playwright && playwright install chromium"
            return result

        parser = self._get_parser()
        js_disabled_content = None
        js_enabled_content = None

        async with async_playwright() as p:
            # ========== 1. 禁用JS模式访问 ==========
            self.logger.info("  [模式1] 禁用JavaScript访问...")
            try:
                browser = await p.chromium.launch(
                    headless=config.PLAYWRIGHT_HEADLESS,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
                )
                ctx = await browser.new_context(
                    java_script_enabled=False,
                    user_agent=config.DEFAULT_HEADERS_DESKTOP["User-Agent"],
                    viewport={"width": 1920, "height": 1080},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                page = await ctx.new_page()
                # 注入反检测（虽然JS禁用了，但是设置以防万一）
                await page.add_init_script(config.STEALTH_JS)

                self._increment_requests()
                resp = await page.goto(url, wait_until="domcontentloaded",
                                       timeout=config.PLAYWRIGHT_TIMEOUT)
                await asyncio.sleep(2)  # 等待DOM稳定

                html_no_js = await page.content()
                title_no_js = await page.title()

                js_disabled_content = parser.parse_html(
                    html_no_js, url=url, engine_name=self.name
                )
                js_disabled_content.metadata["mode"] = "js_disabled"
                js_disabled_content.metadata["http_status"] = resp.status if resp else None
                js_disabled_content.title = title_no_js or js_disabled_content.title

                self.logger.info(f"    禁用JS: {js_disabled_content.word_count_cn} 中文字")

                await ctx.close()
                await browser.close()
            except Exception as e:
                self.logger.warning(f"    禁用JS模式失败: {str(e)[:100]}")

            # ========== 2. 启用JS模式访问（基线对照） ==========
            self.logger.info("  [模式2] 启用JavaScript访问...")
            try:
                browser2 = await p.chromium.launch(
                    headless=config.PLAYWRIGHT_HEADLESS,
                    args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]
                )
                ctx2 = await browser2.new_context(
                    java_script_enabled=True,
                    user_agent=config.DEFAULT_HEADERS_DESKTOP["User-Agent"],
                    viewport={"width": 1920, "height": 1080},
                    locale="zh-CN",
                    timezone_id="Asia/Shanghai",
                )
                page2 = await ctx2.new_page()
                await page2.add_init_script(config.STEALTH_JS)

                self._increment_requests()
                resp2 = await page2.goto(url, wait_until="networkidle",
                                         timeout=config.PLAYWRIGHT_TIMEOUT)
                await asyncio.sleep(3)

                html_js = await page2.content()
                title_js = await page2.title()

                js_enabled_content = parser.parse_html(
                    html_js, url=url, engine_name=self.name
                )
                js_enabled_content.metadata["mode"] = "js_enabled"
                js_enabled_content.metadata["http_status"] = resp2.status if resp2 else None
                js_enabled_content.title = title_js or js_enabled_content.title

                self.logger.info(f"    启用JS: {js_enabled_content.word_count_cn} 中文字")

                await ctx2.close()
                await browser2.close()
            except Exception as e:
                self.logger.warning(f"    启用JS模式失败: {str(e)[:100]}")

        # ========== 3. 对比分析 ==========
        best = None
        comparison = {}

        if js_disabled_content:
            comparison["js_disabled"] = {
                "chars": js_disabled_content.char_count,
                "cn_words": js_disabled_content.word_count_cn,
                "truncated": js_disabled_content.is_truncated,
                "markers": js_disabled_content.truncation_indicators,
            }
        if js_enabled_content:
            comparison["js_enabled"] = {
                "chars": js_enabled_content.char_count,
                "cn_words": js_enabled_content.word_count_cn,
                "truncated": js_enabled_content.is_truncated,
                "markers": js_enabled_content.truncation_indicators,
            }

        # 判断哪个模式内容更完整
        candidates = [c for c in [js_disabled_content, js_enabled_content] if c]
        if candidates:
            best = max(candidates, key=lambda c: c.word_count_cn)

        # 检测付费墙绕过：禁用JS模式下内容显著多于启用JS模式
        if js_disabled_content and js_enabled_content:
            no_js_cn = js_disabled_content.word_count_cn
            js_cn = js_enabled_content.word_count_cn
            comparison["word_ratio_nojs_vs_js"] = round(
                no_js_cn / max(js_cn, 1), 2)

            if (no_js_cn >= config.MIN_CONTENT_LENGTH and
                    no_js_cn > js_cn * 1.5 and
                    not js_disabled_content.is_truncated):
                result.bypass_found = True
                result.bypass_method = (
                    f"禁用JS绕过：无JS模式{no_js_cn}字 vs 有JS模式{js_cn}字。"
                    f"内容被前端JS/CSS隐藏，服务端实际返回完整HTML。"
                )
                self.logger.info(f"  ✓ 发现前端付费墙绕过！")
                best = js_disabled_content

        # 即使没绕过，只要禁用JS下有足够内容也算成功
        if best and self._is_significant_content(best):
            result.success = True
            result.content = best
        elif best:
            result.success = False
            result.content = best

        result.details = {
            "comparison": comparison,
            "bypass_type": "frontend_js_css_hiding" if result.bypass_found else None,
        }
        return result
