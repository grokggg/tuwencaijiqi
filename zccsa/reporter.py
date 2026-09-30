# -*- coding: utf-8 -*-
"""
ZCCSA-Auto 自动审计报告生成器
- 生成Markdown格式的安全审计报告
- 包含：概述、发现的漏洞、复现验证结果、修复建议、时间线
- 支持单篇报告和批量报告
"""
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent))
import config
from core.parser import ExtractedContent
from validator import ValidationResult
from exploit_verifier import ExploitVerificationReport

logger = logging.getLogger(__name__)


class AuditReporter:
    """安全审计报告生成器"""

    # 严重性对应的Emoji和描述
    SEVERITY_INFO = {
        "critical": {"emoji": "🔴", "label": "严重", "color": "red"},
        "high": {"emoji": "🟠", "label": "高危", "color": "orange"},
        "medium": {"emoji": "🟡", "label": "中危", "color": "yellow"},
        "low": {"emoji": "🟢", "label": "低危", "color": "green"},
        "info": {"emoji": "🔵", "label": "信息", "color": "blue"},
    }

    # 引擎中文名映射
    ENGINE_NAMES_CN = {
        "token_harvester": "Token自动搜集（GitHub泄露搜索）",
        "third_party_token_engine": "第三方平台Token提取（平台凭证复用）",
        "search_engine_crawler_engine": "搜索引擎爬虫模拟（UA/IP伪造）",
        "render_bypass_engine": "渲染模式探测（前端付费墙绕过）",
        "cdn_cache_engine": "CDN缓存探测（缓存泄露）",
        "open_api_enum_engine": "开放平台接口枚举（公开API）",
        "api_endpoint_scanner": "API端点扫描（权限校验覆盖）",
        "partner_token_engine": "第三方信任链分析（平台Token）",
        "snapshot_engine": "历史快照检索（存档泄露）",
        "render_diff_engine": "多端渲染差异（端间权限差异）",
    }

    def __init__(self, output_dir: Optional[Path] = None):
        self.output_dir = output_dir or config.REPORTS_DIR
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def generate_report(self,
                        target_url: str,
                        article_info: Dict,
                        final_content: Optional[ExtractedContent],
                        final_validation: Optional[ValidationResult],
                        engine_results: List[Dict],
                        verification_report: Optional[ExploitVerificationReport],
                        think_log: List[str],
                        total_duration_ms: float,
                        start_time: datetime) -> Path:
        """
        生成完整审计报告
        :return: 报告文件路径
        """
        timestamp = start_time.strftime("%Y%m%d_%H%M%S")
        art_id = article_info.get("id", "unknown") if article_info else "unknown"
        filename = f"zccsa_audit_{art_id}_{timestamp}.md"
        path = self.output_dir / filename

        sections = []
        sections.append(self._build_header(target_url, article_info, start_time,
                                           total_duration_ms))
        sections.append(self._build_executive_summary(
            final_content, final_validation, engine_results, verification_report
        ))
        sections.append(self._build_vulnerability_details(
            engine_results, final_content, final_validation
        ))
        if verification_report:
            sections.append(self._build_verification_section(verification_report))
        sections.append(self._build_engine_timeline(engine_results))
        sections.append(self._build_content_section(final_content))
        sections.append(self._build_recommendations(
            engine_results, verification_report, final_validation
        ))
        sections.append(self._build_think_log(think_log))
        sections.append(self._build_disclaimer())

        report_text = "\n\n".join(sections)
        path.write_text(report_text, encoding="utf-8")
        logger.info(f"审计报告已生成: {path}")
        return path

    def _build_header(self, url: str, article_info: Dict,
                      start_time: datetime, duration_ms: float) -> str:
        """报告头部"""
        art_type = article_info.get("type", "unknown") if article_info else "unknown"
        art_id = article_info.get("id", "?") if article_info else "?"
        duration_s = duration_ms / 1000

        # 标题搜索上下文
        search_ctx = article_info.get("search_context") if article_info else None
        search_section = ""
        if search_ctx:
            qt = search_ctx.get("query_title", "")
            mt = search_ctx.get("matched_title", "")
            ms = search_ctx.get("match_score", 0)
            src = search_ctx.get("source", "")
            search_section = f"""
> **标题直搜模式**：查询标题「{qt}」→ 匹配「{mt}」（匹配度{ms:.0%}，来源：{src}）
"""

        return f"""# ZCCSA-Auto 安全审计报告

> **Zero-Cookie Content Security Auditor - 自动化审计报告**
{search_section}
| 项目 | 值 |
|------|-----|
| 审计目标 | `{url}` |
| 内容类型 | {art_type} |
| 内容ID | {art_id} |
| 审计开始时间 | {start_time.strftime('%Y-%m-%d %H:%M:%S')} |
| 总耗时 | {duration_s:.1f} 秒 |
| 报告生成时间 | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |
| ZCCSA版本 | v1.0 Auto |
| 审计模式 | 零凭证 (Zero-Cookie) |
"""

    def _build_executive_summary(self, final_content: Optional[ExtractedContent],
                                  val: Optional[ValidationResult],
                                  engine_results: List[Dict],
                                  verify_report: Optional[ExploitVerificationReport]
                                  ) -> str:
        """执行摘要"""
        total_engines = len(engine_results)
        bypass_found = sum(1 for r in engine_results if r.get("bypass_found"))
        successful = sum(1 for r in engine_results if r.get("success"))

        # 确定整体结论
        if val and val.passed:
            conclusion = "**审计结论：发现付费墙绕过，零凭证状态下可获取完整内容**"
            conclusion_color = "🔴"
        elif bypass_found > 0:
            conclusion = "**审计结论：发现部分绕过向量，但内容不完整**"
            conclusion_color = "🟠"
        else:
            conclusion = "**审计结论：未发现有效绕过，付费墙实现较为完善**"
            conclusion_color = "🟢"

        # 最高严重性
        max_severity = "info"
        if verify_report:
            max_severity = verify_report.severity
        elif bypass_found > 0 and val and val.score >= 70:
            max_severity = "high"
        elif bypass_found > 0:
            max_severity = "medium"

        sev_info = self.SEVERITY_INFO.get(max_severity, self.SEVERITY_INFO["info"])

        lines = [
            "## 一、执行摘要",
            "",
            f"{conclusion_color} {conclusion}",
            "",
            "### 审计数据概览",
            "",
            "| 指标 | 数值 |",
            "|------|------|",
            f"| 执行引擎数 | {total_engines} |",
            f"| 成功引擎数 | {successful} |",
            f"| 发现绕过向量 | {bypass_found} |",
        ]

        if final_content:
            lines.extend([
                f"| 最佳内容字数 | {final_content.word_count_cn} 中文字 |",
                f"| 内容完整性评分 | {val.score if val else 'N/A'}/100 |",
            ])
        else:
            lines.append("| 最佳内容字数 | 0（未提取到有效内容） |")

        lines.extend([
            f"| 最高漏洞等级 | {sev_info['emoji']} {sev_info['label']} |",
            "",
        ])

        if verify_report and verify_report.is_generalizable:
            lines.append(
                f"> ⚠️ **漏洞可复现性验证**：该绕过方法在"
                f"{verify_report.total_success}/{verify_report.total_tested}"
                f"个测试URL上复现成功，属于**普遍性漏洞**。"
            )
            lines.append("")

        return "\n".join(lines)

    def _build_vulnerability_details(self, engine_results: List[Dict],
                                      final_content: Optional[ExtractedContent],
                                      val: Optional[ValidationResult]) -> str:
        """漏洞详情"""
        lines = ["## 二、漏洞详情", ""]

        bypasses = [r for r in engine_results if r.get("bypass_found")]
        if not bypasses:
            lines.append("本次审计未发现明确的付费墙绕过向量。")
            lines.append("")
            if engine_results:
                lines.append("### 各引擎探测结果")
                lines.append("")
                lines.append("| 引擎 | 成功 | 耗时 | 字数 | 备注 |")
                lines.append("|------|------|------|------|------|")
                for r in engine_results:
                    eng_cn = self.ENGINE_NAMES_CN.get(r["engine_name"], r["engine_name"])
                    ok = "✓" if r.get("success") else "✗"
                    dur = f"{r.get('duration_ms', 0):.0f}ms"
                    wc = str(r.get("details", {}).get("word_count", "-"))
                    note = r.get("bypass_method", "")[:40] if r.get("bypass_found") else \
                           (r.get("error", "")[:40] if r.get("error") else "-")
                    lines.append(f"| {eng_cn} | {ok} | {dur} | {wc} | {note} |")
            return "\n".join(lines)

        for i, r in enumerate(bypasses, 1):
            eng_cn = self.ENGINE_NAMES_CN.get(r["engine_name"], r["engine_name"])
            lines.append(f"### 漏洞 #{i}: {eng_cn}")
            lines.append("")
            lines.append(f"- **引擎名称**: `{r['engine_name']}`")
            lines.append(f"- **绕过方法**: {r.get('bypass_method', '未知')}")
            lines.append(f"- **耗时**: {r.get('duration_ms', 0):.0f}ms")
            lines.append(f"- **请求数**: {r.get('request_count', 0)}")

            details = r.get("details", {})
            if details:
                if "comparison" in details:
                    comp = details["comparison"]
                    lines.append(f"- **基线对比**: {comp}")
                if "bypasses" in details and isinstance(details["bypasses"], list):
                    for bp in details["bypasses"][:3]:
                        lines.append(f"  - 子绕过: {bp}")

            # 内容质量
            if final_content and r.get("success"):
                lines.append(f"- **提取字数**: {final_content.word_count_cn} 中文字")
                if val:
                    lines.append(f"- **完整性评分**: {val.score}/100")
                    if val.issues:
                        lines.append(f"- **存在问题**:")
                        for issue in val.issues[:5]:
                            lines.append(f"  - {issue}")
                    if val.strengths:
                        lines.append(f"- **内容亮点**:")
                        for s in val.strengths[:3]:
                            lines.append(f"  - {s}")
            lines.append("")

        return "\n".join(lines)

    def _build_verification_section(self, vr: ExploitVerificationReport) -> str:
        """漏洞复现验证结果"""
        sev = self.SEVERITY_INFO.get(vr.severity, self.SEVERITY_INFO["info"])
        lines = [
            "## 三、漏洞可复现性验证",
            "",
            f"**验证结论**: {sev['emoji']} {sev['label']}",
            "",
            f"- 原始绕过引擎: `{vr.bypass_engine}`",
            f"- 原始绕过方法: {vr.bypass_method[:100]}",
            f"- 测试URL数: {vr.total_tested}",
            f"- 复现成功数: {vr.total_success}",
            f"- 复现成功率: {vr.success_rate:.0%}",
            f"- 平均得分: {vr.avg_score:.0f}",
            f"- 是否普遍漏洞: {'是' if vr.is_generalizable else '否'}",
            "",
        ]

        if vr.results:
            lines.append("### 逐URL验证结果")
            lines.append("")
            lines.append("| # | URL | 结果 | 得分 | 字数 |")
            lines.append("|---|-----|------|------|------|")
            for i, r in enumerate(vr.results, 1):
                ok = "✓" if r.success else "✗"
                url_short = r.url[:60] + "..." if len(r.url) > 60 else r.url
                lines.append(f"| {i} | `{url_short}` | {ok} | {r.score} | {r.word_count} |")
            lines.append("")

        lines.append(f"**结论**: {vr.conclusion}")
        lines.append("")
        return "\n".join(lines)

    def _build_engine_timeline(self, engine_results: List[Dict]) -> str:
        """引擎执行时间线"""
        lines = [
            "## 四、探测引擎执行时间线",
            "",
            "| 顺序 | 引擎 | 状态 | 耗时 | 请求数 | 绕过 |",
            "|------|------|------|------|--------|------|",
        ]
        for i, r in enumerate(engine_results, 1):
            eng_cn = self.ENGINE_NAMES_CN.get(r["engine_name"], r["engine_name"])
            status = "成功" if r.get("success") else "失败"
            if r.get("bypass_found"):
                status = "**发现绕过**"
            dur = f"{r.get('duration_ms', 0):.0f}ms"
            reqs = r.get("request_count", 0)
            bypass = "✓" if r.get("bypass_found") else ""
            err = f" ({r.get('error', '')[:30]})" if r.get("error") and not r.get("success") else ""
            lines.append(f"| {i} | {eng_cn} | {status}{err} | {dur} | {reqs} | {bypass} |")

        lines.append("")
        return "\n".join(lines)

    def _build_content_section(self, content: Optional[ExtractedContent]) -> str:
        """提取的内容预览"""
        lines = ["## 五、提取内容预览", ""]
        if not content:
            lines.append("未提取到有效内容。")
            return "\n".join(lines)

        lines.append(f"- **标题**: {content.title or '(未提取到标题)'}")
        lines.append(f"- **作者**: {content.author or '(未知)'}")
        lines.append(f"- **来源引擎**: {content.source_engine}")
        lines.append(f"- **中文字数**: {content.word_count_cn}")
        lines.append(f"- **段落数**: {content.paragraphs}")
        lines.append(f"- **是否截断**: {'是' if content.is_truncated else '否'}")
        if content.truncation_indicators:
            lines.append(f"- **截断标记**: {', '.join(content.truncation_indicators[:5])}")
        lines.append("")

        # 内容预览（前1000字）
        preview = content.content_text[:1000] if content.content_text else ""
        if preview:
            lines.append("### 内容预览（前1000字）")
            lines.append("")
            lines.append("```")
            lines.append(preview)
            if len(content.content_text) > 1000:
                lines.append("")
                lines.append(f"...（共{content.word_count_cn}字，省略{content.word_count_cn - len(preview)}字）")
            lines.append("```")
            lines.append("")

        return "\n".join(lines)

    def _build_recommendations(self, engine_results: List[Dict],
                                vr: Optional[ExploitVerificationReport],
                                val: Optional[ValidationResult]) -> str:
        """修复建议"""
        lines = ["## 六、修复建议", ""]

        if not any(r.get("bypass_found") for r in engine_results):
            lines.append("本次审计未发现明确的付费墙绕过向量。建议：")
            lines.append("")
            lines.append("1. 继续保持服务端内容截断，不向未付费用户发送完整内容")
            lines.append("2. 定期审计API接口的权限校验逻辑")
            lines.append("3. 配置CDN缓存键包含用户认证状态，避免缓存泄露")
            lines.append("4. 对不同端（Web/App/H5）实施一致的权限检查")
            return "\n".join(lines)

        # 根据发现的漏洞类型给出建议
        bypass_engines = [r["engine_name"] for r in engine_results if r.get("bypass_found")]

        lines.append("基于本次审计发现的绕过向量，建议采取以下修复措施：")
        lines.append("")
        rec_num = 1

        if "render_bypass_engine" in bypass_engines:
            lines.append(f"{rec_num}. **前端付费墙修复**（渲染模式绕过）")
            lines.append("   - 确保服务端不对未付费用户渲染完整HTML内容")
            lines.append("   - 付费墙判断逻辑应在服务端完成，而非依赖前端CSS/JS隐藏")
            lines.append("   - 禁用JavaScript的请求应返回与启用JS一致的截断内容")
            lines.append("")
            rec_num += 1

        if "third_party_token_engine" in bypass_engines:
            lines.append(f"{rec_num}. **第三方平台Token安全修复**（平台凭证泄露）")
            lines.append("   - 所有平台级API Key必须严格绑定合作方IP白名单")
            lines.append("   - 合作方API必须返回脱敏/摘要数据，不得返回完整付费内容")
            lines.append("   - 实施Token请求频率限制和异常行为监控")
            lines.append("   - 定期审计合作方接口的调用日志和返回内容")
            lines.append("   - 对平台API的响应内容实施服务端截断，与Web端一致")
            lines.append("")
            rec_num += 1

        if "search_engine_crawler_engine" in bypass_engines:
            lines.append(f"{rec_num}. **搜索引擎爬虫访问控制修复**（SEO配置漏洞）")
            lines.append("   - 严格验证爬虫来源IP，不仅依赖User-Agent匹配")
            lines.append("   - 对爬虫请求实施DNS反查和ASN校验，确认是真实搜索引擎IP")
            lines.append("   - 爬虫只应返回摘要/元数据（标题、前N字），不返回付费全文")
            lines.append("   - X-Forwarded-For头不应作为爬虫身份判断依据")
            lines.append("   - 配置robots.txt和X-Robots-Tag精确控制爬虫索引范围")
            lines.append("")
            rec_num += 1

        if "cdn_cache_engine" in bypass_engines:
            lines.append(f"{rec_num}. **CDN缓存配置修复**（缓存泄露）")
            lines.append("   - 缓存键（Cache Key）必须包含Cookie/Authorization头")
            lines.append("   - 对含`X-Forwarded-For: 内网IP`等可疑请求拒绝服务或强制鉴权")
            lines.append("   - 在CDN层面剥离或验证服务间调用头，防止伪造")
            lines.append("   - 设置`Cache-Control: private`防止付费内容被共享缓存存储")
            lines.append("")
            rec_num += 1

        if "api_endpoint_scanner" in bypass_engines:
            lines.append(f"{rec_num}. **API权限校验修复**（端点绕过）")
            lines.append("   - 对所有API版本（v1/v2/v3/v4/App端）统一实施权限校验中间件")
            lines.append("   - 废弃的老版本API应下线或返回403，而非返回完整数据")
            lines.append("   - 在API网关层做统一鉴权，避免各端点实现不一致")
            lines.append("")
            rec_num += 1

        if "open_api_enum_engine" in bypass_engines:
            lines.append(f"{rec_num}. **开放接口下线/鉴权修复**（公开API泄露）")
            lines.append("   - 下线不再使用的RSS/oEmbed/Syndication等历史遗留接口")
            lines.append("   - 对oEmbed/embed接口仅返回摘要，不返回完整付费内容")
            lines.append("   - SEO预渲染接口（_next/data等）应做权限校验")
            lines.append("   - 定期审计公开API路径列表，确认无未鉴权的内容接口")
            lines.append("")
            rec_num += 1

        if "partner_token_engine" in bypass_engines:
            lines.append(f"{rec_num}. **第三方信任链修复**（平台Token）")
            lines.append("   - 平台级Token必须绑定IP白名单和请求频率限制")
            lines.append("   - 合作方接口应返回脱敏/限定范围的数据，而非完整内容")
            lines.append("   - 定期轮换平台密钥，审计第三方调用日志")
            lines.append("")
            rec_num += 1

        if "snapshot_engine" in bypass_engines:
            lines.append(f"{rec_num}. **历史存档管理**（快照泄露）")
            lines.append("   - 对从免费转为付费的内容，主动请求Wayback Machine等存档服务删除快照")
            lines.append("   - 设置robots_meta标签禁止搜索引擎存档付费内容")
            lines.append("   - 内容上线前确保从未以公开形式发布过")
            lines.append("")
            rec_num += 1

        if "render_diff_engine" in bypass_engines:
            lines.append(f"{rec_num}. **多端一致性修复**（端间差异）")
            lines.append("   - Web/H5/App端应复用同一套权限校验服务")
            lines.append("   - App端API不应因为User-Agent而放宽权限检查")
            lines.append("   - 移动端网页（m.域名）的权限校验应与www域名一致")
            lines.append("")
            rec_num += 1

        lines.append(f"{rec_num}. **通用安全建议**")
        lines.append("   - 实施内容完整性水印，便于追踪泄露源头")
        lines.append("   - 建立自动化安全回归测试，每次发版验证付费墙有效性")
        lines.append("   - 部署异常访问检测，识别短时间大量请求付费内容的行为")
        lines.append("   - 定期进行第三方安全审计")
        lines.append("")

        return "\n".join(lines)

    def _build_think_log(self, think_log: List[str]) -> str:
        """思考日志"""
        lines = ["## 七、智能体决策日志", ""]
        if not think_log:
            lines.append("（无决策日志）")
            return "\n".join(lines)
        lines.append("以下是ZCCSA-Auto智能体在审计过程中的第一人称思考记录：")
        lines.append("")
        for entry in think_log:
            lines.append(f"> {entry}")
        lines.append("")
        return "\n".join(lines)

    def _build_disclaimer(self) -> str:
        """免责声明"""
        return """## 八、免责声明

本报告由ZCCSA-Auto（Zero-Cookie Content Security Auditor）自动化安全审计工具生成，
仅用于学术研究目的的安全评估。

1. 本审计在零凭证（无Cookie/无登录）条件下进行，模拟未付费用户的访问场景。
2. 所有探测行为仅用于验证访问控制架构的安全性，不构成对任何内容的非法获取。
3. 发现的脆弱点应通过正规渠道向平台方报告，帮助提升安全性。
4. 本工具的使用者须对其行为承担相应法律责任。

---

*报告由 ZCCSA-Auto v1.0 自动生成*
"""
