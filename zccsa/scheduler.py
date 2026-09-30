#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZCCSA - Zero-Cookie Content Security Auditor
调度中心：URL输入 → 策略路由 → 结果聚合

使用方式:
    # 交互模式
    python scheduler.py

    # 单篇分析
    python scheduler.py "https://www.zhihu.com/market/paid_column/xxx/section/yyy"

    # 批量分析
    python scheduler.py -f urls.txt --output-dir ./reports/

重要声明：
    本工具仅用于学术研究目的的安全评估，帮助内容平台发现并修复其
    访问控制架构中的脆弱点。所有探测行为须在授权环境下进行，不得用于
    未经授权的商业数据抓取。
"""
import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# 确保项目根目录在sys.path中
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

import config
from core.parser import ContentParser, ExtractedContent
from core.session_manager import SessionManager
from monitor import get_monitor, EngineMonitor

# 引擎导入
from engines import (
    BaseEngine, EngineResult,
    RenderBypassEngine,
    CDNCacheEngine,
    APIEndpointScanner,
    PartnerTokenEngine,
    SnapshotEngine,
    RenderDiffEngine,
    ThirdPartyTokenEngine,
    OpenAPIEnumEngine,
    SearchEngineCrawlerEngine,
    TokenHarvester,
    TitleSearchEngine,
)


# ============================================================
# 日志配置
# ============================================================
def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # 降低第三方库日志级别
    for noisy in ["httpx", "curl_cffi", "playwright", "urllib3"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


logger = logging.getLogger("zccsa.scheduler")


# ============================================================
# 引擎注册与工厂
# ============================================================
ENGINE_REGISTRY = {
    "token_harvester": TokenHarvester,
    "third_party_token_engine": ThirdPartyTokenEngine,
    "search_engine_crawler_engine": SearchEngineCrawlerEngine,
    "render_bypass_engine": RenderBypassEngine,
    "cdn_cache_engine": CDNCacheEngine,
    "open_api_enum_engine": OpenAPIEnumEngine,
    "render_diff_engine": RenderDiffEngine,
    "api_endpoint_scanner": APIEndpointScanner,
    "partner_token_engine": PartnerTokenEngine,
    "snapshot_engine": SnapshotEngine,
}


class AuditScheduler:
    """
    ZCCSA调度中心
    - 接收URL
    - 解析文章ID
    - 按引擎权重依次调度，任一引擎返回有效内容即停止
    - 记录统计
    - 聚合结果
    """

    def __init__(self, cookie_file: Optional[str] = None,
                 output_dir: Optional[Path] = None,
                 verbose: bool = False):
        self.cookie_file = cookie_file
        self.output_dir = output_dir or config.REPORTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.verbose = verbose
        self.parser = ContentParser()
        self.monitor: EngineMonitor = get_monitor()
        self.session = SessionManager(cookie_file=cookie_file)
        self.title_searcher = TitleSearchEngine(session=self.session)

        logger.info("=" * 60)
        logger.info("ZCCSA - Zero-Cookie Content Security Auditor")
        logger.info("零凭证内容付费墙安全评估工具 v1.0")
        logger.info("=" * 60)
        logger.info(f"输出目录: {self.output_dir}")
        logger.info(f"Cookie文件: {self.cookie_file or '无（零凭证模式）'}")
        logger.info(f"已注册引擎: {len(ENGINE_REGISTRY)} 个")

    async def audit(self, url: str) -> Dict[str, Any]:
        """
        对单个URL执行安全评估
        """
        start_time = time.time()
        logger.info("")
        logger.info(f"{'='*60}")
        logger.info(f"开始评估: {url[:80]}")
        logger.info(f"{'='*60}")

        # 1. 解析URL
        id_info = self.parser.extract_article_id(url)
        logger.info(f"文章类型: {id_info['type']}, ID: {id_info['id']}, "
                    f"专栏ID: {id_info['column_id']}")

        # 2. 验证URL
        if not self.parser.is_zhihu_url(url):
            logger.warning("目标URL不属于知乎域名，仍将尝试探测")

        # 3. 按权重获取引擎执行顺序
        engine_order = self.monitor.get_engine_order()
        engine_order = [n for n in engine_order if n in ENGINE_REGISTRY]
        logger.info(f"引擎执行顺序: {' → '.join(engine_order)}")

        # 4. 依次调度引擎
        results: List[EngineResult] = []
        final_result: Optional[EngineResult] = None
        bypasses_found = []

        for idx, engine_name in enumerate(engine_order, 1):
            engine_cls = ENGINE_REGISTRY[engine_name]
            engine = engine_cls(
                session_manager=self.session,
                parser=self.parser,
                cookie_file=self.cookie_file,
            )

            logger.info("")
            logger.info(f"[{idx}/{len(engine_order)}] 引擎: {engine.name} ({engine.description})")
            logger.info(f"{'-'*50}")

            try:
                result = await engine.run(url, id_info)
                results.append(result)

                # 记录监控
                self.monitor.record_result(
                    engine_name=engine_name,
                    success=result.success,
                    bypass_found=result.bypass_found,
                    duration_ms=result.duration_ms,
                    request_count=result.request_count,
                    error=result.error,
                )

                if result.bypass_found:
                    bypasses_found.append(result)
                    logger.info(f"  ⚠ 发现绕过! {result.bypass_method[:80]}")

                # 判断是否找到有效完整内容
                if result.content and self._is_complete_enough(result.content):
                    final_result = result
                    logger.info(f"  ✓ 获取到有效内容 ({result.content.word_count_cn} 字)，停止后续引擎")
                    break

            except Exception as e:
                logger.error(f"  引擎异常: {e}")
                self.monitor.record_result(
                    engine_name=engine_name, success=False,
                    duration_ms=(time.time()-start_time)*1000,
                    error=str(e)[:200],
                )

        # 5. 结果聚合
        total_duration = (time.time() - start_time) * 1000
        audit_report = self._build_report(
            url=url, id_info=id_info,
            results=results, final_result=final_result,
            bypasses_found=bypasses_found,
            total_duration=total_duration,
        )

        # 6. 保存报告
        report_path = self._save_report(audit_report)
        if final_result and final_result.content:
            self._save_content_markdown(final_result.content, audit_report)

        # 7. 打印摘要
        self._print_summary(audit_report, report_path)
        return audit_report

    async def fetch_by_title(self, title: str) -> Dict[str, Any]:
        """
        仅通过标题获取付费内容。
        流程：标题搜索 → 定位URL → 直接调用 self.audit(url) 复用完整引擎链。
        """
        logger.info("")
        logger.info(f"{'='*60}")
        logger.info(f"标题直搜模式: {title[:60]}")
        logger.info(f"{'='*60}")

        # 阶段1：标题搜索定位URL
        logger.info("")
        logger.info("[标题搜索] 通过标题定位文章...")
        print(f"  ▶ 执行 [标题搜索]...")

        try:
            match = await self.title_searcher.search(title)
        except Exception as e:
            logger.error(f"标题搜索异常: {e}")
            match = {}

        if not match or not match.get("url"):
            logger.error("  ✗ 未找到与标题匹配的知乎文章")
            print("  ✗ 未找到与标题匹配的知乎文章。建议提供更精确的标题或使用URL模式。")
            return {
                "zccsa_version": "1.0",
                "mode": "title_search",
                "query_title": title,
                "audit_time": datetime.now().isoformat(),
                "error": "未找到匹配的文章",
                "search_failed": True,
            }

        url = match["url"]
        matched_title = match.get("matched_title", "")
        match_score = match.get("match_score", 0)
        source = match.get("source", "")
        logger.info(f"  ✓ 找到匹配: {matched_title[:60]}")
        logger.info(f"    URL: {url}")
        logger.info(f"    匹配度: {match_score:.0%} | 来源: {source}")
        print(f"  ✓ 找到匹配文章: {matched_title[:60]}")
        print(f"    URL: {url}")
        print(f"    匹配度: {match_score:.0%} | 来源: {source}")
        print("")
        logger.info("[内容探测] 复用完整引擎链进行内容获取...")

        # 阶段2：直接复用已有的 audit(url) 完整流程
        audit_report = await self.audit(url)

        # 补充标题搜索元信息
        audit_report["mode"] = "title_search"
        audit_report["query_title"] = title
        audit_report["search_match"] = match
        return audit_report

    def _is_complete_enough(self, content: ExtractedContent) -> bool:
        """判断内容是否足够完整，可作为最终结果"""
        # 完整内容：非截断 + 超过阈值
        if not content.is_truncated and content.word_count_cn >= config.MIN_CONTENT_LENGTH:
            return True
        # 非常长的内容也视为成功
        if content.word_count_cn >= config.COMPLETE_CONTENT_LENGTH:
            return True
        return False

    def _build_report(self, url: str, id_info: Dict,
                      results: List[EngineResult],
                      final_result: Optional[EngineResult],
                      bypasses_found: List[EngineResult],
                      total_duration: float) -> Dict[str, Any]:
        """构建最终评估报告"""
        report = {
            "zccsa_version": "1.0",
            "audit_time": datetime.now().isoformat(),
            "target_url": url,
            "article_info": id_info,
            "zero_cookie_mode": self.cookie_file is None,
            "total_duration_ms": round(total_duration, 0),
            "summary": {
                "engines_run": len(results),
                "engines_succeeded": sum(1 for r in results if r.success),
                "bypasses_found": len(bypasses_found),
                "final_success": final_result is not None,
                "final_engine": final_result.engine_name if final_result else None,
                "final_word_count": (final_result.content.word_count_cn
                                     if final_result and final_result.content else 0),
            },
            "bypasses": [
                {
                    "engine": r.engine_name,
                    "method": r.bypass_method,
                    "word_count": r.content.word_count_cn if r.content else 0,
                }
                for r in bypasses_found
            ],
            "engine_results": [r.to_dict() for r in results],
            "engine_stats": self.monitor.get_stats(),
        }
        if final_result and final_result.content:
            report["final_content"] = {
                "title": final_result.content.title,
                "author": final_result.content.author,
                "word_count_cn": final_result.content.word_count_cn,
                "paragraphs": final_result.content.paragraphs,
                "truncated": final_result.content.is_truncated,
                "source_engine": final_result.engine_name,
                "source_url": final_result.content.url,
            }
        return report

    def _save_report(self, report: Dict) -> Path:
        """保存JSON格式报告"""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        art_id = report["article_info"].get("id", "unknown")
        filename = f"zccsa_report_{art_id}_{ts}.json"
        path = self.output_dir / filename
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        logger.info(f"JSON报告已保存: {path}")
        return path

    def _save_content_markdown(self, content: ExtractedContent,
                                report: Dict) -> Optional[Path]:
        """保存提取的内容为Markdown"""
        try:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            art_id = report["article_info"].get("id", "unknown")
            filename = f"content_{art_id}_{ts}.md"
            path = self.output_dir / filename
            md = self.parser.to_markdown_report(content, include_meta=True)
            # 添加审计头
            audit_header = (
                f"> **ZCCSA安全评估提取内容**\n"
                f"> 发现引擎: {content.source_engine}\n"
                f"> 绕过方式: {report['bypasses'][0]['method'] if report['bypasses'] else '直接提取'}\n"
                f"> 评估时间: {report['audit_time']}\n\n"
                f"---\n\n"
            )
            path.write_text(audit_header + md, encoding='utf-8')
            logger.info(f"Markdown内容已保存: {path}")
            return path
        except Exception as e:
            logger.error(f"保存Markdown失败: {e}")
            return None

    def _print_summary(self, report: Dict, report_path: Path) -> None:
        """打印评估摘要"""
        s = report["summary"]
        print("")
        print("=" * 60)
        print("ZCCSA 评估结果摘要")
        print("=" * 60)
        print(f"目标URL: {report['target_url'][:70]}")
        print(f"零凭证模式: {'是' if report['zero_cookie_mode'] else '否'}")
        print(f"引擎运行: {s['engines_run']} 个，成功 {s['engines_succeeded']} 个")
        print(f"发现绕过: {s['bypasses_found']} 个")
        print(f"总耗时: {report['total_duration_ms']:.0f}ms")
        print("")

        if report["bypasses"]:
            print("发现的付费墙绕过向量:")
            for i, bp in enumerate(report["bypasses"], 1):
                print(f"  [{i}] {bp['engine']}: {bp['method'][:100]}")
            print("")

        if s["final_success"]:
            fc = report["final_content"]
            print(f"最终提取内容:")
            print(f"  标题: {fc['title'][:60]}")
            print(f"  字数: {fc['word_count_cn']} 中文字")
            print(f"  截断: {'是' if fc['truncated'] else '否'}")
            print(f"  来源引擎: {fc['source_engine']}")
            print(f"  来源URL: {fc['source_url'][:70]}")
        else:
            print("未能提取到有效完整内容。")
            print("可能原因：1) 付费墙实现较为完善  2) 需要更强的探测向量")

        print("")
        print(f"详细报告: {report_path}")
        print("=" * 60)

    def _print_title_summary(self, report: Dict, report_path: Path, match: Dict) -> None:
        """打印标题搜索模式的评估摘要（match为dict格式）"""
        s = report["summary"]
        print("")
        print("=" * 60)
        print("ZCCSA 标题直搜结果摘要")
        print("=" * 60)
        print(f"查询标题: {report.get('query_title', '')[:60]}")
        print(f"匹配标题: {match.get('matched_title', '')[:60]}")
        print(f"匹配文章URL: {match.get('url', '')[:70]}")
        print(f"匹配度: {match.get('match_score', 0):.0%}  |  来源: {match.get('source', '')}")
        print(f"零凭证模式: {'是' if report['zero_cookie_mode'] else '否'}")
        print(f"引擎运行: {s['engines_run']} 个，成功 {s['engines_succeeded']} 个")
        print(f"发现绕过: {s['bypasses_found']} 个")
        print(f"总耗时: {report['total_duration_ms']:.0f}ms")
        print("")

        if report.get("bypasses"):
            print("发现的付费墙绕过向量:")
            for i, bp in enumerate(report["bypasses"], 1):
                print(f"  [{i}] {bp['engine']}: {bp['method'][:100]}")
            print("")

        if s["final_success"]:
            fc = report["final_content"]
            print(f"最终提取内容:")
            print(f"  标题: {fc['title'][:60]}")
            print(f"  字数: {fc['word_count_cn']} 中文字")
            print(f"  截断: {'是' if fc['truncated'] else '否'}")
            print(f"  来源引擎: {fc['source_engine']}")
        else:
            print("未能提取到有效完整内容。")
            if report.get("search_failed"):
                print("原因：标题搜索未能定位到匹配文章。建议提供更精确的标题，或直接使用URL。")
            else:
                print("可能原因：1) 付费墙实现较为完善  2) 需要更强的探测向量")

        print("")
        print(f"详细报告: {report_path}")
        print("=" * 60)


# ============================================================
# 批量处理
# ============================================================
async def run_batch(urls: List[str], **kwargs) -> List[Dict]:
    """批量处理多个URL"""
    scheduler = AuditScheduler(**kwargs)
    results = []
    for url in urls:
        url = url.strip()
        if url and not url.startswith("#"):
            try:
                report = await scheduler.audit(url)
                results.append(report)
            except Exception as e:
                logger.error(f"处理 {url[:50]}... 失败: {e}")
                results.append({"url": url, "error": str(e)})
    return results


def load_urls_from_file(path: str) -> List[str]:
    """从文件加载URL列表"""
    p = Path(path)
    if not p.exists():
        logger.error(f"文件不存在: {path}")
        return []
    return [line.strip() for line in p.read_text(encoding='utf-8').splitlines()
            if line.strip() and not line.strip().startswith("#")]


def load_titles_from_file(path: str) -> List[str]:
    """从文件加载标题列表（每行一个标题）"""
    return load_urls_from_file(path)  # 格式相同，复用


async def run_batch_titles(titles: List[str], **kwargs) -> List[Dict]:
    """批量处理多个标题"""
    scheduler = AuditScheduler(**kwargs)
    results = []
    for title in titles:
        title = title.strip()
        if title and not title.startswith("#"):
            try:
                report = await scheduler.fetch_by_title(title)
                results.append(report)
            except Exception as e:
                logger.error(f"处理标题 '{title[:30]}...' 失败: {e}")
                results.append({"query_title": title, "error": str(e)})
    return results


def fetch_by_title_sync(title: str, **kwargs) -> Dict:
    """
    同步入口：仅通过标题获取付费内容
    供外部模块/脚本调用，无需手动管理事件循环
    """
    async def _run():
        scheduler = AuditScheduler(**kwargs)
        return await scheduler.fetch_by_title(title)
    return asyncio.run(_run())


# ============================================================
# 交互模式
# ============================================================
async def interactive_mode(**kwargs):
    """交互模式"""
    print("")
    print("╔══════════════════════════════════════════════════════════╗")
    print("║   ZCCSA - Zero-Cookie Content Security Auditor          ║")
    print("║   零凭证内容付费墙安全评估工具 v1.0                      ║")
    print("║                                                          ║")
    print("║   仅用于学术研究目的的安全评估                            ║")
    print("║   须在授权环境下使用                                     ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print("")
    print("命令:")
    print("  <URL>          - 分析指定知乎付费内容URL")
    print("  /title <标题>  - 通过文章标题搜索并获取内容")
    print("  /stats         - 查看引擎统计")
    print("  /weight <引擎> <权重> - 手动调整引擎权重")
    print("  /reset         - 重置统计数据")
    print("  /quit          - 退出")
    print("")

    scheduler = AuditScheduler(**kwargs)

    while True:
        try:
            user_input = input("ZCCSA> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见!")
            break

        if not user_input:
            continue
        if user_input in ("/quit", "/exit", "quit", "exit"):
            print("再见!")
            break
        if user_input == "/stats":
            stats = scheduler.monitor.get_stats()
            print("\n引擎统计:")
            print(f"{'引擎名称':<28} {'成功率':>8} {'绕过率':>8} {'平均耗时':>10} {'权重':>8}")
            print("-" * 70)
            for name, s in stats["engines"].items():
                print(f"{name:<28} {s['success_rate']:>7.1%} {s['bypass_rate']:>7.1%} "
                      f"{s['avg_duration_ms']:>8.0f}ms {s['current_weight']:>8.1f}")
            print("")
            continue
        if user_input.startswith("/weight"):
            parts = user_input.split()
            if len(parts) == 3:
                try:
                    w = float(parts[2])
                    scheduler.monitor.set_weight(parts[1], w)
                    print(f"已设置 {parts[1]} 权重为 {w}")
                except ValueError:
                    print("权重需为数字")
            else:
                print("用法: /weight <引擎名> <权重>")
            continue
        if user_input == "/reset":
            scheduler.monitor.reset_stats()
            print("统计已重置")
            continue
        if user_input.startswith("/title "):
            title = user_input[7:].strip()
            if title:
                try:
                    await scheduler.fetch_by_title(title)
                except Exception as e:
                    print(f"错误: {e}")
            else:
                print("用法: /title <文章标题>")
            continue
        if user_input.startswith("http"):
            try:
                await scheduler.audit(user_input)
            except Exception as e:
                print(f"错误: {e}")
        else:
            print(f"未知命令: {user_input}")


# ============================================================
# 主入口
# ============================================================
def main():
    parser = argparse.ArgumentParser(
        description="ZCCSA - Zero-Cookie Content Security Auditor "
                    "(零凭证内容付费墙安全评估工具)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # URL模式
  python scheduler.py "https://www.zhihu.com/market/paid_column/xxx/section/yyy"
  python scheduler.py -f urls.txt -o ./reports/
  python scheduler.py -c cookies.txt "https://www.zhihu.com/..."

  # 标题直搜模式（新增）
  python scheduler.py --title "某某盐选专栏文章标题"
  python scheduler.py --titles titles.txt -o ./reports/

  # 交互模式
  python scheduler.py
        """,
    )
    parser.add_argument("url", nargs="?", help="要分析的知乎文章URL")
    parser.add_argument("-f", "--file", help="包含URL列表的文件（每行一个URL）")
    parser.add_argument("-o", "--output-dir", default=str(config.REPORTS_DIR),
                        help="报告输出目录")
    parser.add_argument("-c", "--cookies", help="Cookie文件路径（用于授权环境对比实验）")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志输出")
    parser.add_argument("--stats", action="store_true", help="显示引擎统计后退出")
    parser.add_argument("--reset-stats", action="store_true", help="重置统计数据后退出")
    parser.add_argument("--title", help="标题直搜模式：直接输入文章标题进行搜索和内容获取")
    parser.add_argument("--titles", help="批量标题模式：从文件加载标题列表（每行一个标题）")

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    # 处理统计命令
    if args.stats:
        monitor = get_monitor()
        stats = monitor.get_stats()
        print(json.dumps(stats, ensure_ascii=False, indent=2))
        return
    if args.reset_stats:
        monitor = get_monitor()
        monitor.reset_stats()
        print("统计数据已重置")
        return

    kwargs = {
        "cookie_file": args.cookies,
        "output_dir": Path(args.output_dir),
        "verbose": args.verbose,
    }

    # 确定运行模式
    if args.titles:
        # 批量标题模式
        titles = load_titles_from_file(args.titles)
        if not titles:
            print("未找到有效标题")
            return
        print(f"批量标题模式: 加载了 {len(titles)} 个标题")
        asyncio.run(run_batch_titles(titles, **kwargs))
    elif args.title:
        # 单标题模式
        print(f"标题直搜模式: {args.title[:50]}")
        asyncio.run(run_batch_titles([args.title], **kwargs))
    elif args.file:
        urls = load_urls_from_file(args.file)
        if not urls:
            print("未找到有效URL")
            return
        print(f"批量模式: 加载了 {len(urls)} 个URL")
        asyncio.run(run_batch(urls, **kwargs))
    elif args.url:
        asyncio.run(run_batch([args.url], **kwargs))
    else:
        # 交互模式
        asyncio.run(interactive_mode(**kwargs))


if __name__ == "__main__":
    main()
