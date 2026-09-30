#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
main.py - 知乎盐选内容自动化获取智能体调度中心

输入知乎付费/盐选文章URL，按动态权重依次调用各引擎，
一旦某个引擎成功返回完整内容立即返回结果。
"""
import asyncio
import logging
import sys
import time
import re
import argparse
from pathlib import Path
from typing import Optional, List, Dict, Any
from datetime import datetime

# 确保项目根目录在路径中
PROJECT_DIR = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_DIR))

import config
from core.parser import ContentParser, ParsedContent, extract_article_id
from core.session_manager import SessionManager
from core.monitor import Monitor
from core.fingerprint import generate_fingerprint

# 引擎导入
from engines.cache_engine import CacheEngine
from engines.share_engine import ShareEngine, cleanup as share_cleanup
from engines.cookie_pool_engine import CookiePoolEngine
from engines.internal_api_engine import InternalApiEngine
from engines.cross_platform_engine import CrossPlatformEngine
from engines.ocr_engine import OcrEngine
from engines.basic_http_engine import BasicHttpEngine

# 日志配置
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
    format=config.LOG_FORMAT,
    datefmt=config.LOG_DATE_FORMAT,
)
logger = logging.getLogger("ContentAgent")


class ContentAgent:
    """
    知乎盐选内容获取智能体。
    多引擎调度，按成功率动态排序，一旦成功立即返回。
    """

    def __init__(self, cookie_file: Optional[str] = None,
                 output_dir: Optional[str] = None,
                 proxy_pool: Optional[List[str]] = None,
                 download_images: bool = False):
        self.output_dir = Path(output_dir) if output_dir else config.OUTPUT_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.download_images = download_images

        # 初始化核心组件
        self.session_mgr = SessionManager(cookie_file=cookie_file, proxy_pool=proxy_pool)
        self.monitor = Monitor()
        self.parser = ContentParser()
        self.cache = CacheEngine()

        # 初始化引擎
        self.engines = {
            "cache_engine": self.cache,
            "share_engine": ShareEngine(self.session_mgr),
            "cookie_pool_engine": CookiePoolEngine(self.session_mgr),
            "internal_api_engine": InternalApiEngine(self.session_mgr),
            "cross_platform_engine": CrossPlatformEngine(self.session_mgr),
            "ocr_engine": OcrEngine(self.session_mgr),
            "basic_http_engine": BasicHttpEngine(self.session_mgr),
        }

        logger.info("ContentAgent 初始化完成")
        logger.info(f"Cookie池大小: {len(self.session_mgr.cookies)}")
        logger.info(f"输出目录: {self.output_dir}")

    async def fetch(self, url: str, title_hint: str = "") -> Optional[ParsedContent]:
        """
        执行完整的内容获取流程。

        Args:
            url: 知乎文章URL
            title_hint: 可选的标题提示（跨平台搜索时使用）
        Returns:
            ParsedContent 或 None
        """
        url = url.strip()
        if not url:
            logger.error("URL为空")
            return None

        # 标准化URL
        if not url.startswith("http"):
            url = "https://" + url

        ids = extract_article_id(url)
        logger.info(f"=" * 60)
        logger.info(f"开始获取: {url[:80]}")
        logger.info(f"提取ID: {ids}")
        logger.info(f"=" * 60)

        # 获取引擎执行顺序（按动态权重排序）
        ranked = self.monitor.get_ranked_engines()
        logger.info(f"引擎执行顺序: {[name for name, _ in ranked]}")

        result = None
        failed_reasons = []

        for engine_name, weight in ranked:
            if engine_name not in self.engines:
                continue

            engine = self.engines[engine_name]
            logger.info(f"--- 尝试引擎: {engine_name} (权重={weight:.1f}) ---")

            start = time.time()
            try:
                if engine_name == "cross_platform_engine":
                    content = await engine.fetch(url, title_hint=title_hint)
                else:
                    content = await engine.fetch(url)

                elapsed = time.time() - start

                if content and self.parser.is_content_complete(content):
                    # 补全元信息
                    if not content.original_url:
                        content.original_url = url
                    if not content.platform:
                        content.platform = self._detect_platform(url)

                    # 记录成功
                    self.monitor.record_success(engine_name, elapsed)

                    # 保存到缓存
                    self.cache.save(url, content)

                    result = content
                    logger.info(f"✅ 引擎 [{engine_name}] 成功获取内容!")
                    break
                elif content:
                    # 内容不完整，继续尝试
                    logger.info(f"引擎 [{engine_name}] 返回内容不完整 "
                                f"(截断={content.is_truncated}, 长度={content.content_length})")
                    self.monitor.record_failure(engine_name, "内容不完整/被截断", elapsed)
                    failed_reasons.append(f"{engine_name}: 内容截断")
                    # 如果是第一次有内容，保存下来作为备选
                    if result is None or content.content_length > result.content_length:
                        result = content
                else:
                    self.monitor.record_failure(engine_name, "无内容返回", elapsed)
                    failed_reasons.append(f"{engine_name}: 无内容")

            except Exception as e:
                elapsed = time.time() - start
                error_msg = str(e)[:200]
                logger.error(f"引擎 [{engine_name}] 异常: {error_msg}")
                self.monitor.record_failure(engine_name, error_msg, elapsed)
                failed_reasons.append(f"{engine_name}: {error_msg}")

        # 输出报告
        if result:
            self._print_report(url, result, failed_reasons)
        else:
            logger.error("所有引擎均失败!")
            logger.info(f"失败原因: {failed_reasons}")
            print(f"\n[EXTRACTION_REPORT]")
            print(f"URL: {url}")
            print(f"Status: failed")
            print(f"Reasons: {'; '.join(failed_reasons)}")
            print(f"[/EXTRACTION_REPORT]")

        return result

    async def fetch_batch(self, urls: List[str], delay: float = 2.0) -> List[Optional[ParsedContent]]:
        """
        批量获取文章。
        Args:
            urls: URL列表
            delay: 每条间隔（秒）
        """
        results = []
        total = len(urls)
        for i, url in enumerate(urls):
            logger.info(f"\n>>> 批量进度: {i+1}/{total}")
            content = await self.fetch(url)
            results.append(content)
            if i < total - 1:
                await asyncio.sleep(delay)
        return results

    def save_to_file(self, content: ParsedContent, filename: Optional[str] = None) -> Path:
        """
        保存内容为Markdown文件。
        文件组织: output/{平台}/{作者}/{标题}.md
        """
        platform = content.platform or "unknown"
        author = content.author or "未知作者"
        title = content.title or "untitled"

        # 清理文件名中的非法字符
        safe_title = re.sub(r'[\\/:*?"<>|\n\r\t]', '_', title).strip()
        safe_title = safe_title[:80]  # 限制长度
        safe_author = re.sub(r'[\\/:*?"<>|\s]', '_', author).strip()[:30]
        safe_platform = re.sub(r'[^\w-]', '_', platform)

        # 创建目录
        save_dir = self.output_dir / safe_platform / safe_author
        save_dir.mkdir(parents=True, exist_ok=True)

        if not filename:
            filename = f"{safe_title}.md"

        filepath = save_dir / filename
        md_content = self.parser.to_markdown_file(content, include_meta=True)
        filepath.write_text(md_content, encoding="utf-8")

        logger.info(f"文件已保存: {filepath}")
        return filepath

    def _detect_platform(self, url: str) -> str:
        if "zhihu.com" in url:
            if "oia.zhihu.com" in url:
                return "zhihu_paid"
            if "market/paid_column" in url:
                return "zhihu_salt"
            return "zhihu"
        if "mp.weixin" in url:
            return "wechat"
        if "csdn.net" in url:
            return "csdn"
        if "jianshu.com" in url:
            return "jianshu"
        if "cnblogs.com" in url:
            return "cnblogs"
        return "web"

    def _print_report(self, url: str, content: ParsedContent, failed: List[str]):
        """输出提取报告"""
        print(f"\n{'='*60}")
        print(f"[EXTRACTION_REPORT]")
        print(f"URL: {url}")
        print(f"Platform: {content.platform}")
        print(f"Title: {content.title}")
        print(f"Author: {content.author}")
        print(f"Content_Length: {content.content_length}")
        print(f"Images: {len(content.images)}")
        print(f"Is_Truncated: {content.is_truncated}")
        print(f"Status: done")
        if failed:
            print(f"Failed_Engines: {'; '.join(failed)}")
        print(f"[/EXTRACTION_REPORT]")
        print(f"{'='*60}")

    async def close(self):
        """清理资源"""
        self.session_mgr.close_all()
        await share_cleanup()

    def print_stats(self):
        """打印监控统计"""
        print(self.monitor.summary())


def _read_urls_from_input(urls_input: str) -> List[str]:
    """从输入解析URL列表（支持单行/多行/文件路径）"""
    urls = []
    # 检查是否是文件路径
    path = Path(urls_input)
    if path.exists() and path.is_file():
        text = path.read_text(encoding="utf-8")
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#") and ("http" in line or "zhihu.com" in line):
                urls.append(line)
    else:
        # 直接按换行分隔
        for line in urls_input.split("\n"):
            line = line.strip()
            if line and ("http" in line or "zhihu.com" in line):
                urls.append(line)
    return urls


async def main():
    parser = argparse.ArgumentParser(
        description="知乎盐选内容自动化获取智能体 v1.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python main.py "https://www.zhihu.com/market/paid_column/xxx/section/yyy"
  python main.py --title "娇娇和她的忠犬小狗"
  python main.py -f urls.txt
  python main.py -c cookies.txt -o output "https://..."
  echo "https://..." | python main.py --stdin
        """
    )
    parser.add_argument("url", nargs="?", help="知乎文章URL")
    parser.add_argument("--title", "-t", help="通过文章标题搜索并提取（跨平台搜索）")
    parser.add_argument("-f", "--file", help="包含URL列表的文件（每行一个URL）")
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取URL")
    parser.add_argument("-c", "--cookies", help="Cookie文件路径")
    parser.add_argument("-o", "--output", help="输出目录", default=str(config.OUTPUT_DIR))
    parser.add_argument("--proxy", help="代理地址 (e.g. http://127.0.0.1:7890)")
    parser.add_argument("--no-save", action="store_true", help="不保存文件，仅输出")
    parser.add_argument("--stats", action="store_true", help="显示引擎统计")
    parser.add_argument("--reset-stats", action="store_true", help="重置统计数据")
    parser.add_argument("--verbose", "-v", action="store_true", help="详细日志")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 收集URL
    urls = []
    if args.url:
        urls.append(args.url)
    if args.file:
        file_urls = _read_urls_from_input(args.file)
        urls.extend(file_urls)
    if args.stdin:
        import select
        if select.select([sys.stdin], [], [], 0.1)[0]:
            stdin_text = sys.stdin.read()
            urls.extend(_read_urls_from_input(stdin_text))

    # 如果没有URL参数且没有--title，进入交互模式
    if not urls and not args.stats and not args.reset_stats and not args.title:
        print("📄 知乎盐选内容获取智能体 v1.0 已就绪")
        print()
        print("请输入知乎文章URL（支持批量，每行一个URL，空行开始执行）:")
        print("（输入 /stats 查看统计，/reset 重置统计，/quit 退出）")
        print()

        agent = ContentAgent(
            cookie_file=args.cookies,
            output_dir=args.output,
            proxy_pool=[args.proxy] if args.proxy else None,
        )

        if args.stats:
            agent.print_stats()

        if args.reset_stats:
            agent.monitor.reset_stats()
            print("统计已重置")

        while True:
            try:
                line = input("> ").strip()
            except (EOFError, KeyboardInterrupt):
                break

            if not line:
                continue
            if line in ("/quit", "/exit", "quit", "exit", "q"):
                break
            if line == "/stats":
                agent.print_stats()
                continue
            if line == "/reset":
                agent.monitor.reset_stats()
                print("统计已重置")
                continue

            # 支持多行输入
            batch_urls = [line]
            while True:
                try:
                    next_line = input("  ").strip()
                except (EOFError, KeyboardInterrupt):
                    break
                if not next_line:
                    break
                if next_line.startswith("http"):
                    batch_urls.append(next_line)
                else:
                    break

            for url in batch_urls:
                content = await agent.fetch(url)
                if content and not args.no_save:
                    filepath = agent.save_to_file(content)
                    # 打印正文预览
                    print(f"\n--- 正文预览 (前1000字) ---")
                    print(content.content_markdown[:1000])
                    if len(content.content_markdown) > 1000:
                        print(f"\n... (共{content.content_length}字，完整内容见文件)")
                    print(f"\n完整文件: {filepath}\n")
                elif content:
                    print(f"\n--- 正文 ---")
                    print(content.content_markdown[:3000])
                    if len(content.content_markdown) > 3000:
                        print(f"\n... (共{content.content_length}字)")

        await agent.close()
        return

    # 非交互模式
    agent = ContentAgent(
        cookie_file=args.cookies,
        output_dir=args.output,
        proxy_pool=[args.proxy] if args.proxy else None,
    )

    if args.stats:
        agent.print_stats()
        return

    if args.reset_stats:
        agent.monitor.reset_stats()
        print("统计已重置")
        return

    # 如果指定了--title，使用跨平台引擎搜索
    if args.title and not urls:
        print(f"🔍 通过标题搜索: {args.title}")
        title_hint = args.title
        # 使用跨平台搜索引擎
        cross_engine = agent.engines.get("cross_platform_engine")
        if cross_engine:
            content = await cross_engine.fetch("", title_hint=title_hint)
            if content:
                if not args.no_save:
                    filepath = agent.save_to_file(content)
                    print(f"\n✅ 已保存到: {filepath}")
                print(f"\n{'='*60}")
                print(f"标题: {content.title}")
                print(f"作者: {content.author}")
                print(f"平台: {content.platform}")
                print(f"字数: {content.content_length}")
                print(f"{'='*60}")
                print(f"\n{content.content_markdown[:3000]}")
                if len(content.content_markdown) > 3000:
                    print(f"\n... (共{content.content_length}字)")
            else:
                print(f"❌ 未找到标题为「{args.title}」的文章")
        await agent.close()
        return

    if not urls:
        parser.print_help()
        return

    try:
        results = await agent.fetch_batch(urls)
        for url, content in zip(urls, results):
            if content and not args.no_save:
                agent.save_to_file(content)
            elif content:
                print(f"\n{content.title}")
                print(f"{'='*40}")
                print(content.content_markdown[:2000])

        # 统计
        success = sum(1 for r in results if r and not r.is_truncated)
        print(f"\n总计: {len(urls)}篇, 成功{success}篇, 失败{len(urls)-success}篇")
    finally:
        await agent.close()


if __name__ == "__main__":
    asyncio.run(main())
