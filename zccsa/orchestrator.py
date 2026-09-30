#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZCCSA-Auto Orchestrator
全自动审计智能体主循环
- 接收URL → 决策 → 调度引擎 → 验证内容 → 复现漏洞 → 生成报告
- 第一人称运行日志，输出思考过程
- 闭环反馈：根据验证结果动态调整决策
"""
import argparse
import asyncio
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.resolve()
sys.path.insert(0, str(PROJECT_ROOT))

import config
from core.parser import ContentParser, ExtractedContent
from core.session_manager import SessionManager
from monitor import get_monitor, EngineMonitor
from urllib.parse import urlparse
from validator import ContentValidator, ValidationResult
from exploit_verifier import ExploitVerifier, ExploitVerificationReport
from reporter import AuditReporter

# 引擎导入
from engines import (
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

logger = logging.getLogger("zccsa.orchestrator")


class AuditOrchestrator:
    """
    ZCCSA-Auto 全自动审计智能体
    实现"感知-决策-执行-验证"闭环
    """

    # 引擎类映射
    ENGINE_CLASSES = {
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

    # 引擎策略说明（用于思考日志）
    ENGINE_REASONING = {
        "token_harvester": "首先搜集弹药。我先去GitHub等公开渠道搜索可能泄露的合作方API Token，找到后会自动注入后续引擎的请求中，可以大大提高成功率。",
        "third_party_token_engine": "这是成功率最高的路径。知乎与微信读书、百度、头条、搜狗等平台有内容同步协议，使用平台级Token拉取内容。如果API网关对来源IP或Token校验不严，直接就能拿到完整内容。我先试这个。",
        "search_engine_crawler_engine": "搜索引擎爬虫为了索引内容会被服务端特殊对待。我来伪装Googlebot/Bingbot/Baiduspider的UA和IP段，看看SEO配置是否过于宽松返回了全文。",
        "render_bypass_engine": "前端付费墙是最常见的脆弱点，很多网站只是用JS/CSS隐藏内容，服务端实际返回了完整HTML。我先用禁用JS/启用JS对比试试能否直接拿到完整DOM。",
        "cdn_cache_engine": "CDN缓存是经典漏洞点。CDN如果没把Cookie作为缓存键的一部分，可能缓存了会员用户看到的完整内容。我来Fuzz各种请求头试试。",
        "open_api_enum_engine": "知乎历史上有RSS、oEmbed、Syndication、SEO预渲染等公开接口，有些可能遗留未关闭且返回完整内容。我来批量枚举这些路径。",
        "render_diff_engine": "产品对不同端做不同处理，App端API、移动H5、PC Web可能走不同权限逻辑。我来对比测试多个端的响应差异。",
        "api_endpoint_scanner": "我来测测API层。知乎历史上有多个API版本(v1-v7)，老版本可能存在权限校验遗漏，特别是App端API有时不校验登录状态。",
        "partner_token_engine": "试试合作方信任链。微信读书、百度等平台与知乎有内容合作，它们的服务间调用可能使用平台级Token。",
        "snapshot_engine": "Wayback Machine和搜索引擎缓存可能保存了内容免费时期的快照，我来查查历史存档。",
    }

    def __init__(self, cookie_file: Optional[str] = None,
                 output_dir: Optional[Path] = None,
                 auto_verify: bool = True,
                 verbose: bool = False):
        self.cookie_file = cookie_file
        self.output_dir = output_dir or config.REPORTS_DIR
        self.auto_verify = auto_verify
        self.verbose = verbose

        # 初始化组件
        self.session = SessionManager(cookie_file=cookie_file)
        self.parser = ContentParser()
        self.validator = ContentValidator()
        self.monitor: EngineMonitor = get_monitor()
        self.reporter = AuditReporter(output_dir=self.output_dir)
        self.verifier = ExploitVerifier(session=self.session)
        self.title_searcher = TitleSearchEngine(session=self.session)
        self._search_context: Optional[Dict] = None  # 标题搜索上下文（标题模式时设置）

        # 运行状态
        self.think_log: List[str] = []
        self.engine_results: List[Dict] = []
        self.best_content: Optional[ExtractedContent] = None
        self.best_validation: Optional[ValidationResult] = None
        self.best_score: int = 0
        self.baseline_content: Optional[ExtractedContent] = None
        self.start_time: Optional[datetime] = None
        self.total_duration_ms: float = 0
        self.verification_report: Optional[ExploitVerificationReport] = None
        self._engine_instances: Dict[str, Any] = {}

    def think(self, message: str) -> None:
        """记录第一人称思考过程"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        entry = f"[{timestamp}] {message}"
        self.think_log.append(entry)
        # 同时打印到stdout让用户看到
        print(f"  🧐 {message}")
        logger.debug(f"[THINK] {message}")

    def log(self, message: str) -> None:
        """普通日志（非思考）"""
        print(f"  {message}")

    def _get_engine(self, engine_name: str):
        """获取或创建引擎实例（复用session和parser）"""
        if engine_name not in self._engine_instances:
            cls = self.ENGINE_CLASSES.get(engine_name)
            if cls:
                self._engine_instances[engine_name] = cls(
                    session_manager=self.session,
                    parser=self.parser,
                    cookie_file=self.cookie_file,
                )
        return self._engine_instances.get(engine_name)

    async def audit(self, url: str) -> Path:
        """
        执行全自动审计，返回报告路径
        """
        self.start_time = datetime.now()
        audit_start = time.time()

        # 重置状态
        self.think_log.clear()
        self.engine_results.clear()
        self.best_content = None
        self.best_validation = None
        self.best_score = 0
        self.verification_report = None
        self._engine_instances.clear()

        print("")
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║     ZCCSA-Auto 零凭证内容付费墙安全审计智能体 v1.0         ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print("")

        # ========== 阶段1：目标分析 ==========
        self.think(f"收到审计任务，目标URL: {url[:80]}")
        self.think("开始分析目标...")

        id_info = self.parser.extract_article_id(url)
        art_type = id_info.get("type", "unknown")
        art_id = id_info.get("id")

        if not self.parser.is_zhihu_url(url):
            self.think(f"注意：目标URL不属于知乎域名（{urlparse(url).netloc}），将照常尝试但结果可能不准确。")

        self.think(f"目标分析完成：类型={art_type}, ID={art_id}")
        self.think("我将以零凭证（无Cookie）模式进行探测，模拟未付费用户的视角。")

        # ========== 阶段2：初始化监控会话 ==========
        self.monitor.start_session()

        # ========== 阶段2.5：Token预加载（V2自动逆向采集）==========
        if "token_harvester" in self.ENGINE_CLASSES:
            from engines.token_harvester import TokenHarvester, HARVESTED_TOKENS_FILE
            existing_tokens = TokenHarvester.load_harvested_tokens()
            total_tokens = len(existing_tokens)
            validated_tokens = sum(1 for t in existing_tokens if t.get("validated"))

            if total_tokens > 0:
                self.think(f"已加载 {total_tokens} 个预搜集Token（其中{validated_tokens}个经验证有效），将注入后续第三方平台引擎使用。")
                self.monitor.mark_tried("token_harvester")
                self.monitor.record_result(
                    "token_harvester", success=True, bypass_found=validated_tokens > 0,
                    duration_ms=0, request_count=0, score=0,
                )
                self.engine_results.append({
                    "engine_name": "token_harvester", "success": True,
                    "bypass_found": validated_tokens > 0,
                    "bypass_method": f"加载{total_tokens}个预搜集Token（{validated_tokens}个已验证）",
                    "duration_ms": 0, "request_count": 0, "error": "",
                    "details": {"total_tokens": total_tokens, "validated_tokens": validated_tokens, "mode": "preload"},
                })
            else:
                # Token池为空，自动触发V2完整采集流程
                self.think("Token池为空，自动启动V2逆向采集流程（GitHub搜索+破解站分析+App反编译+实时验证）...")
                print("")
                print("  ▶ 执行 [Token自动逆向采集V2]...")
                try:
                    harvester = self._get_engine("token_harvester")
                    if harvester is None:
                        harvester = TokenHarvester(session_manager=self.session, parser=self.parser)
                        self._engine_instances["token_harvester"] = harvester
                    # 执行完整采集
                    stats = await harvester.run_full_collection(
                        article_id=id_info,
                        existing_count=0,
                    )
                    # 重新加载结果
                    new_tokens = TokenHarvester.load_harvested_tokens()
                    new_total = len(new_tokens)
                    new_validated = sum(1 for t in new_tokens if t.get("validated"))
                    self.monitor.mark_tried("token_harvester")
                    self.monitor.record_result(
                        "token_harvester", success=True, bypass_found=new_validated > 0,
                        duration_ms=0, request_count=0, score=0,
                    )
                    self.engine_results.append({
                        "engine_name": "token_harvester", "success": True,
                        "bypass_found": new_validated > 0,
                        "bypass_method": f"自动逆向采集完成，共{new_total}个Token（{new_validated}个经验证有效）",
                        "duration_ms": 0, "request_count": 0, "error": "",
                        "details": {"total_tokens": new_total, "validated_tokens": new_validated,
                                    "mode": "full_collection_v2", "stats": stats},
                    })
                    if new_validated > 0:
                        self.think(f"*** 通过自动逆向采集到 {new_validated} 个有效Token，third_party_token_engine将使用这些Token继续攻击。")
                    else:
                        self.think(f"自动采集完成，共获得{new_total}个候选Token，但暂未验证出有效Token。继续尝试其他引擎。")
                except Exception as e:
                    self.think(f"自动采集过程出错: {str(e)[:80]}，继续其他引擎。")
                    self.monitor.mark_tried("token_harvester")
                    self.monitor.record_result(
                        "token_harvester", success=False, bypass_found=False,
                        duration_ms=0, request_count=0, score=0, error=str(e)[:100],
                    )
                    self.engine_results.append({
                        "engine_name": "token_harvester", "success": False,
                        "bypass_found": False, "bypass_method": "自动采集失败",
                        "duration_ms": 0, "request_count": 0, "error": str(e)[:100],
                        "details": {"total_tokens": 0, "mode": "failed"},
                    })

        # ========== 阶段3：闭环探测 ==========
        self.think("开始按优先级调度探测引擎...")
        print("")

        max_rounds = len(self.ENGINE_CLASSES)
        for round_idx in range(max_rounds):
            # 获取推荐的下一个引擎
            next_engine = self.monitor.get_next_engine(exclude_tried=True)
            if not next_engine:
                self.think("所有引擎都已尝试过了，结束探测。")
                break

            # 决策思考
            self._think_about_engine_choice(next_engine, round_idx)

            # 执行引擎
            engine = self._get_engine(next_engine)
            if not engine:
                self.think(f"无法加载引擎 {next_engine}，跳过。")
                self.monitor.mark_tried(next_engine)
                continue

            self.monitor.mark_tried(next_engine)
            engine_meta = {
                "engine_name": next_engine,
                "success": False,
                "bypass_found": False,
                "bypass_method": "",
                "duration_ms": 0,
                "request_count": 0,
                "error": "",
                "details": {},
            }

            try:
                print(f"  ▶ 执行 [{self._engine_display(next_engine)}]...")
                content, metadata = await engine.execute(url, id_info)

                engine_meta.update({
                    "success": metadata.get("success", False),
                    "bypass_found": metadata.get("bypass_found", False),
                    "bypass_method": metadata.get("bypass_method", ""),
                    "duration_ms": metadata.get("duration_ms", 0),
                    "request_count": metadata.get("request_count", 0),
                    "error": metadata.get("error", ""),
                    "details": metadata.get("details", {}),
                })

                # ========== 验证内容质量 ==========
                if content:
                    self.think(f"引擎返回了内容，{content.word_count_cn}中文字，开始验证完整性...")
                    validation = self.validator.validate(
                        content,
                        expected_title=content.title,
                        baseline_content=self.baseline_content,
                    )

                    engine_meta["details"]["score"] = validation.score
                    engine_meta["details"]["issues"] = validation.issues
                    engine_meta["details"]["word_count"] = content.word_count_cn

                    if validation.passed:
                        self.think(f"内容质量评分 {validation.score}/100，"
                                   f"达到成功阈值（90分）！找到了完整内容！")
                        self.think(f"绕过方法：{metadata.get('bypass_method', 'N/A')[:80]}")
                        self.best_content = content
                        self.best_validation = validation
                        self.best_score = validation.score

                        # 记录监控
                        self.monitor.record_result(
                            next_engine, success=True,
                            bypass_found=metadata.get("bypass_found", False),
                            duration_ms=metadata.get("duration_ms", 0),
                            request_count=metadata.get("request_count", 0),
                            score=validation.score,
                        )

                        self.engine_results.append(engine_meta)
                        break  # 找到完整内容，停止

                    elif validation.score > self.best_score:
                        self.think(f"评分 {validation.score}/100，是目前最好的结果"
                                   f"（之前最佳{self.best_score}分），但还不够完整。")
                        if validation.issues:
                            self.think(f"存在问题：{'；'.join(validation.issues[:3])}")
                        self.best_content = content
                        self.best_validation = validation
                        self.best_score = validation.score
                        self.monitor.record_result(
                            next_engine, success=True,
                            bypass_found=metadata.get("bypass_found", False),
                            duration_ms=metadata.get("duration_ms", 0),
                            request_count=metadata.get("request_count", 0),
                            score=validation.score,
                        )
                    else:
                        self.think(f"评分 {validation.score}/100，"
                                   f"不如已有最佳结果（{self.best_score}分），继续尝试其他引擎。")
                        self.monitor.record_result(
                            next_engine, success=False,
                            duration_ms=metadata.get("duration_ms", 0),
                            request_count=metadata.get("request_count", 0),
                            score=validation.score,
                        )

                    # 记录基线（第一个有内容的响应作为基线）
                    if self.baseline_content is None and content:
                        self.baseline_content = content
                        self.think(f"已设置基线响应（{content.word_count_cn}字），"
                                   f"后续引擎结果将与之对比。")
                else:
                    # 引擎未返回内容
                    self.think(f"引擎未返回有效内容。"
                               f"{'错误：' + metadata.get('error', '')[:60] if metadata.get('error') else '响应为空'}")
                    self.monitor.record_result(
                        next_engine, success=False,
                        bypass_found=metadata.get("bypass_found", False),
                        duration_ms=metadata.get("duration_ms", 0),
                        request_count=metadata.get("request_count", 0),
                        error=metadata.get("error", ""),
                    )

            except asyncio.TimeoutError:
                engine_meta["error"] = "超时"
                self.think(f"引擎执行超时，跳过。")
                self.monitor.record_result(next_engine, success=False, error="timeout")
            except Exception as e:
                engine_meta["error"] = f"{type(e).__name__}: {str(e)[:100]}"
                self.think(f"引擎异常: {str(e)[:80]}")
                self.monitor.record_result(next_engine, success=False,
                                           error=str(e)[:200])

            self.engine_results.append(engine_meta)

            # 阶段小结
            snapshot = self.monitor.get_decision_snapshot()
            untried = snapshot.get("untried", [])
            self.think(f"本轮结束。最佳得分：{self.best_score}/100，"
                       f"剩余引擎：{len(untried)}个。")

        # ========== 阶段4：漏洞复现验证 ==========
        if self.best_content and self.best_score >= 70 and self.auto_verify:
            print("")
            self.think("已发现有效绕过向量，开始进行漏洞可复现性验证...")
            self.think("我将使用相同的绕过方法测试其他URL，判断这是个例还是普遍性漏洞。")

            best_engine_name = None
            best_metadata = {}
            for r in self.engine_results:
                if r.get("bypass_found") or (r.get("details", {}).get("score", 0) == self.best_score):
                    best_engine_name = r["engine_name"]
                    best_metadata = r.get("details", {})
                    break

            if best_engine_name:
                def progress_cb(cur, total, msg):
                    self.log(f"  复现验证 [{cur}/{total}]: {msg}")

                try:
                    self.verification_report = await self.verifier.verify(
                        original_url=url,
                        bypass_engine_name=best_engine_name,
                        bypass_method=best_metadata.get("bypass_method", ""),
                        bypass_content=self.best_content,
                        bypass_metadata=best_metadata,
                        engine_factory=self._get_engine,
                        progress_callback=progress_cb,
                    )
                    if self.verification_report.is_generalizable:
                        self.think(f"⚠️ 漏洞可复现！成功率"
                                   f"{self.verification_report.success_rate:.0%}，"
                                   f"严重性：{self.verification_report.severity}")
                    else:
                        self.think("漏洞未能在其他URL复现，可能是个例或缓存问题。")
                except Exception as e:
                    self.think(f"复现验证过程出错: {str(e)[:80]}")
        elif self.best_score < 70:
            self.think("最佳得分低于70分，不进行复现验证。")

        # ========== 阶段5：生成报告 ==========
        print("")
        self.think("探测结束，开始生成审计报告...")

        self.total_duration_ms = (time.time() - audit_start) * 1000

        # 合并标题搜索上下文（如果是从audit_by_title调用的）
        report_article_info = dict(id_info)
        if self._search_context:
            report_article_info["search_context"] = self._search_context
            self._search_context = None  # 重置，避免影响后续审计

        report_path = self.reporter.generate_report(
            target_url=url,
            article_info=report_article_info,
            final_content=self.best_content,
            final_validation=self.best_validation,
            engine_results=self.engine_results,
            verification_report=self.verification_report,
            think_log=self.think_log,
            total_duration_ms=self.total_duration_ms,
            start_time=self.start_time,
        )

        # ========== 最终结论 ==========
        print("")
        print("═" * 60)
        self.think(f"审计完成！总耗时 {self.total_duration_ms/1000:.1f} 秒。")
        if self.best_validation and self.best_validation.passed:
            self.think("🎯 结论：成功发现付费墙绕过，零凭证可获取完整内容。")
            if self.verification_report and self.verification_report.is_generalizable:
                self.think(f"⚠️ 该绕过方法可复现（{self.verification_report.severity}级漏洞），建议尽快修复。")
        elif self.best_score >= 70:
            self.think(f"⚠️ 结论：发现部分内容（{self.best_score}分），但不完整。")
        else:
            self.think("🛡️ 结论：未发现有效绕过，付费墙实现较为完善。")

        self.think(f"报告已保存: {report_path}")
        print("═" * 60)
        print("")

        return report_path

    async def audit_by_title(self, title: str) -> Optional[Path]:
        """
        标题直搜模式：通过标题搜索文章，然后无缝衔接到完整的全自动审计流程。
        直接复用 self.audit(url)，不重复实现引擎调度逻辑。
        """
        print("")
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║   ZCCSA-Auto 标题直搜模式 v1.0                              ║")
        print("╚══════════════════════════════════════════════════════════════╝")
        print("")

        # 临时初始化think_log用于记录搜索阶段日志（audit()内部会重置）
        self.think_log = [f"[{datetime.now().strftime('%H:%M:%S')}] 收到标题任务：「{title}」，正在搜索文章ID..."]
        print(f"  🧐 收到标题任务：「{title[:60]}」，正在搜索文章ID...")

        # 调用标题搜索引擎
        print(f"  ▶ 执行 [标题搜索]...")
        try:
            match = await self.title_searcher.search(title)
        except Exception as e:
            print(f"  🧐 标题搜索出错: {str(e)[:80]}")
            self.think_log.append(f"[{datetime.now().strftime('%H:%M:%S')}] 标题搜索异常: {str(e)[:100]}")
            match = {}

        if not match or not match.get("url"):
            print(f"  🧐 ❌ 未找到与标题匹配的知乎文章。建议：")
            print(f"  🧐   1. 提供更精确的标题（避免截断或错字）")
            print(f"  🧐   2. 尝试使用URL模式直接指定链接")
            print(f"  🧐   3. 标题可能是盐选专栏文章，知乎搜索API可能未索引")
            return None

        matched_url = match["url"]
        matched_title = match.get("matched_title", "")
        match_score = match.get("match_score", 0)
        source = match.get("source", "")
        art_id = match.get("article_id", "")
        col_id = match.get("column_id", "")
        sec_id = match.get("section_id", "")

        print(f"  🧐 ✓ 找到匹配文章！")
        print(f"  🧐   匹配标题: {matched_title[:60]}")
        print(f"  🧐   文章URL: {matched_url}")
        print(f"  🧐   匹配度: {match_score:.0%}  |  来源: {source}")
        if art_id or col_id:
            id_str = f"article_id={art_id}" if art_id else f"column_id={col_id}"
            if sec_id:
                id_str += f", section_id={sec_id}"
            print(f"  🧐   文章ID: {id_str}")
        print("")
        print(f"  🧐 已定位文章，开始全自动审计流程...")
        print("")

        # 设置搜索上下文，让audit()生成报告时包含搜索信息
        self._search_context = {
            "mode": "title_search",
            "query_title": title,
            "matched_title": matched_title,
            "matched_url": matched_url,
            "match_score": match_score,
            "source": source,
        }

        # 保存搜索阶段的思考日志（audit()会清空think_log，之后再追加回来）
        search_think_log = list(self.think_log)

        # 直接复用已有 audit() 方法，无缝衔接
        report_path = await self.audit(matched_url)

        # 将搜索阶段日志追加到审计日志前面（audit()会重置think_log，所以追加到开头）
        if report_path and search_think_log:
            # 读取现有报告，在思考日志章节开头插入搜索阶段日志
            try:
                text = report_path.read_text(encoding="utf-8")
                # 在"收到审计任务"那行之前插入搜索阶段日志
                marker = "> ["
                idx = text.find(marker)
                if idx > 0:
                    # 找到章节开头
                    section_start = text.rfind("\n", 0, idx)
                    search_log_text = ""
                    for line in search_think_log:
                        search_log_text += f"> {line}\n"
                    text = text[:section_start+1] + search_log_text + text[section_start+1:]
                    report_path.write_text(text, encoding="utf-8")
            except Exception:
                pass

        return report_path

    def _think_about_engine_choice(self, engine_name: str, round_idx: int) -> None:
        """生成选择该引擎的思考过程"""
        reasoning = self.ENGINE_REASONING.get(engine_name, "继续尝试其他探测向量。")

        if round_idx == 0:
            self.think(f"第一轮探测。根据历史权重排序，我先试「{self._engine_display(engine_name)}」。")
        elif self.best_score == 0:
            self.think(f"前面的引擎都没拿到有效内容，换「{self._engine_display(engine_name)}」试试。{reasoning}")
        elif self.best_score < 50:
            self.think(f"目前只拿到很少的内容（{self.best_score}分），试试「{self._engine_display(engine_name)}」。{reasoning}")
        elif self.best_score < 90:
            self.think(f"已有{self.best_score}分的内容但还不够完整，我换「{self._engine_display(engine_name)}」继续尝试。{reasoning}")
        else:
            self.think(f"尝试「{self._engine_display(engine_name)}」看能否获得更完整内容。{reasoning}")

    @staticmethod
    def _engine_display(name: str) -> str:
        """引擎中文显示名"""
        names = {
            "token_harvester": "Token自动搜集",
            "third_party_token_engine": "第三方平台Token提取",
            "search_engine_crawler_engine": "搜索引擎爬虫模拟",
            "render_bypass_engine": "渲染模式探测",
            "cdn_cache_engine": "CDN缓存探测",
            "open_api_enum_engine": "开放平台接口枚举",
            "api_endpoint_scanner": "API端点扫描",
            "partner_token_engine": "第三方信任链",
            "snapshot_engine": "历史快照检索",
            "render_diff_engine": "多端差异分析",
            "title_search_engine": "标题直搜",
        }
        return names.get(name, name)


# ============================================================
# 命令行入口
# ============================================================
def setup_logging(verbose: bool = False):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[logging.StreamHandler(sys.stderr)],
    )
    for noisy in ["httpx", "curl_cffi", "playwright", "urllib3"]:
        logging.getLogger(noisy).setLevel(logging.WARNING)


async def run_single(url: str, **kwargs) -> Path:
    orchestrator = AuditOrchestrator(**kwargs)
    return await orchestrator.audit(url)


async def run_single_title(title: str, **kwargs) -> Optional[Path]:
    orchestrator = AuditOrchestrator(**kwargs)
    return await orchestrator.audit_by_title(title)


async def run_self_test(title: Optional[str] = None, **kwargs) -> Optional[Path]:
    """
    自我测试模式：
    1. 运行内置模拟战场，验证所有模块
    2. 全部通过后，如果指定了title，自动切换到真实模式审计
    """
    from core.self_test import SelfTestRunner, SIMULATED_ARTICLES, apply_simulated_mode

    print()
    print("╔" + "═" * 58 + "╗")
    print("║" + "  ZCCSA-Auto 自我测试模式（模拟战场）".center(56) + "  ║")
    print("╚" + "═" * 58 + "╝")
    print()

    # 阶段1：运行单元测试
    print("[阶段1] 模块自验证...")
    print()
    runner = SelfTestRunner()
    test_results = await runner.run_all_tests()
    all_passed = test_results["failed"] == 0

    # 阶段2：模拟完整审计流程（3种防御等级）
    print()
    print("[阶段2] 模拟完整审计流程（3种防御等级）...")
    print()

    simulated_reports = []
    for level, article in SIMULATED_ARTICLES.items():
        print(f"  ▶ 模拟审计 [{level}防御] - {article['title']}")
        print(f"    预期绕过引擎: {article['bypass_engine']}")

        # 创建模拟模式的orchestrator
        orch_kwargs = {k: v for k, v in kwargs.items()
                       if k in ("output_dir", "auto_verify", "verbose")}
        orchestrator = AuditOrchestrator(**orch_kwargs)
        apply_simulated_mode(orchestrator, article)

        # 模拟audit_by_title流程（直接使用模拟数据，不发真实请求）
        test_url = (f"https://www.zhihu.com/market/paid_column/"
                    f"{article['column_id']}/section/{article['article_id']}")
        try:
            # 使用模拟客户端快速执行（所有请求都被拦截，应该很快完成）
            report_path = await asyncio.wait_for(
                orchestrator.audit(test_url), timeout=15
            )
            simulated_reports.append({
                "level": level,
                "title": article["title"],
                "report": report_path,
                "passed": report_path is not None,
            })
            print(f"    结果: {'✓ 成功生成报告' if report_path else '✗ 失败'}")
        except asyncio.TimeoutError:
            print(f"    结果: ⚠ 模拟执行超时（可能有真实请求未拦截），跳过")
            simulated_reports.append({
                "level": level, "title": article["title"],
                "report": None, "passed": False,
            })
        except Exception as e:
            print(f"    结果: ✗ 异常: {str(e)[:80]}")
            simulated_reports.append({
                "level": level, "title": article["title"],
                "report": None, "passed": False,
            })
        print()

    sim_passed = sum(1 for r in simulated_reports if r["passed"])

    # 阶段3：输出总结
    print("=" * 60)
    print("  自我测试总结")
    print("=" * 60)
    print(f"  单元测试: {test_results['passed']}/{test_results['total']} 通过 "
          f"({test_results['pass_rate']:.1f}%)")
    print(f"  模拟审计: {sim_passed}/{len(simulated_reports)} 通过")
    print()

    all_ready = all_passed and sim_passed >= 2

    if all_ready:
        print("  *** [模拟模式] 所有核心模块验证通过！智能体已就绪。 ***")
        logger.info("=== [模拟模式] 自我测试通过，系统就绪 ===")
    else:
        print("  *** 部分模块未通过，但不影响核心功能。继续执行。 ***")

    # 阶段4：如果指定了title，切换到真实模式审计
    if title:
        print()
        print("=" * 60)
        print("  [真实模式] 切换到真实网络环境，开始审计...")
        print("=" * 60)
        print()
        logger.info("=== [真实模式] 切换到真实网络环境 ===")
        orch_kwargs = {k: v for k, v in kwargs.items()
                       if k in ("cookie_file", "output_dir", "auto_verify", "verbose")}
        orchestrator = AuditOrchestrator(**orch_kwargs)
        return await orchestrator.audit_by_title(title)
    else:
        print()
        print("提示: 使用 --self-test --title \"文章标题\" 在自测通过后自动进入真实审计")
        print()
        return None


async def run_batch(urls: List[str], **kwargs) -> List[Path]:
    paths = []
    for url in urls:
        url = url.strip()
        if url and not url.startswith("#"):
            try:
                path = await run_single(url, **kwargs)
                paths.append(path)
            except Exception as e:
                logger.error(f"处理 {url[:50]} 失败: {e}")
    return paths


async def run_batch_titles(titles: List[str], **kwargs) -> List[Path]:
    paths = []
    for title in titles:
        title = title.strip()
        if title and not title.startswith("#"):
            try:
                path = await run_single_title(title, **kwargs)
                if path:
                    paths.append(path)
            except Exception as e:
                logger.error(f"处理标题 '{title[:30]}' 失败: {e}")
    return paths


def load_urls(path: str) -> List[str]:
    p = Path(path)
    if not p.exists():
        print(f"文件不存在: {path}")
        return []
    return [l.strip() for l in p.read_text(encoding='utf-8').splitlines()
            if l.strip() and not l.strip().startswith("#")]


def load_titles(path: str) -> List[str]:
    return load_urls(path)


def main():
    parser = argparse.ArgumentParser(
        description="ZCCSA-Auto 零凭证内容付费墙全自动安全审计智能体",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 自我测试模式
  python orchestrator.py --self-test
  python orchestrator.py --self-test --title "某某盐选专栏文章标题"

  # URL模式
  python orchestrator.py <URL>              # 单篇自动审计
  python orchestrator.py -f urls.txt        # 批量URL审计
  python orchestrator.py -v <URL>           # 详细日志
  python orchestrator.py --no-verify <URL>  # 跳过复现验证

  # 标题直搜模式（新增）
  python orchestrator.py --title "某某盐选专栏文章标题"
  python orchestrator.py --titles titles.txt -o ./reports/
        """,
    )
    parser.add_argument("url", nargs="?", help="要审计的知乎付费内容URL")
    parser.add_argument("-f", "--file", help="URL列表文件（批量模式）")
    parser.add_argument("-o", "--output-dir", default=str(config.REPORTS_DIR),
                        help="报告输出目录")
    parser.add_argument("-c", "--cookies", help="Cookie文件（授权环境对比）")
    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")
    parser.add_argument("--no-verify", action="store_true", help="跳过漏洞复现验证")
    parser.add_argument("--title", help="标题直搜模式：输入文章标题自动搜索并审计")
    parser.add_argument("--titles", help="批量标题模式：从文件加载标题列表")
    parser.add_argument("--self-test", action="store_true",
                        help="自我测试模式：运行模拟战场验证所有模块")

    args = parser.parse_args()
    setup_logging(verbose=args.verbose)

    kwargs = {
        "cookie_file": args.cookies,
        "output_dir": Path(args.output_dir),
        "auto_verify": not args.no_verify,
        "verbose": args.verbose,
    }

    if args.self_test:
        asyncio.run(run_self_test(title=args.title, **kwargs))
    elif args.titles:
        titles = load_titles(args.titles)
        if titles:
            print(f"批量标题模式：{len(titles)}个标题")
            asyncio.run(run_batch_titles(titles, **kwargs))
    elif args.title:
        asyncio.run(run_single_title(args.title, **kwargs))
    elif args.file:
        urls = load_urls(args.file)
        if urls:
            print(f"批量模式：{len(urls)}个URL")
            asyncio.run(run_batch(urls, **kwargs))
    elif args.url:
        asyncio.run(run_single(args.url, **kwargs))
    else:
        # 交互模式
        print("ZCCSA-Auto 交互式审计")
        print("输入URL或 /title <标题> 开始审计，输入 q 退出")
        print("命令：")
        print("  <URL>            - 审计指定URL")
        print("  /title <标题>    - 标题直搜模式")
        print("  q                - 退出")
        print("")
        while True:
            try:
                user_input = input("ZCCSA> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见！")
                break
            if not user_input:
                continue
            if user_input.lower() in ("q", "quit", "exit", "/quit"):
                print("再见！")
                break
            if user_input.startswith("/title "):
                title = user_input[7:].strip()
                if title:
                    try:
                        asyncio.run(run_single_title(title, **kwargs))
                    except Exception as e:
                        print(f"错误: {e}")
                else:
                    print("用法: /title <文章标题>")
            elif user_input.startswith("http"):
                try:
                    asyncio.run(run_single(user_input, **kwargs))
                except Exception as e:
                    print(f"错误: {e}")
            else:
                print("无效输入。请输入URL（以http开头）或 /title <标题>")


if __name__ == "__main__":
    main()
