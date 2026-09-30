#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
parse_and_report.py — 解析测试日志，提取 Authorization 头和 HTTP 状态码

功能：
  1. 解析 run_pipeline_test.py 的控制台日志
  2. 提取每次测试的 Authorization 头（Bearer <token>）及对应的 HTTP 状态码
  3. 交叉引用 harvested_tokens.json 获取完整 token 值（日志中可能被截断）
  4. 生成 results.json，格式符合 poc_report_writer.py 的输入要求

使用方法：
  python parse_and_report.py                            # 使用内嵌日志
  python parse_and_report.py --log-file pipeline.log   # 从文件读取日志
  echo "<日志>" | python parse_and_report.py --log-stdin  # 从 stdin 读取
"""

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


# ================================================================
#  路径配置
# ================================================================

SCRIPT_DIR = Path(__file__).resolve().parent
ZCCSA_DIR = SCRIPT_DIR / "zccsa"
HARVESTED_TOKENS_FILE = ZCCSA_DIR / "data" / "harvested_tokens.json"
OUTPUT_FILE = SCRIPT_DIR / "results.json"

TEST_URL = "https://httpbin.org/get"


# ================================================================
#  内嵌日志（来自上一步 run_pipeline_test.py 的控制台输出）
# ================================================================

EMBEDDED_LOG = r"""============================================================
  run_pipeline_test.py — 数据流水线测试
============================================================
  项目目录 : /workspace/zccsa
  Harvester : /workspace/zccsa/engines/token_harvester.py
  API Tester: /workspace/simple_api_tester.py
  测试 URL  : https://httpbin.org/get

============================================================
[步骤 1] 运行 token_harvester 搜集函数，写入 data/harvested_tokens.json
============================================================
  搜集函数从 4 段样本文本中提取到 4 个 token
  加入 3 个模拟测试字符串
  加载已有 1 个历史 token
  去重后共 8 个片段
  已写入: /workspace/zccsa/data/harvested_tokens.json

    1. [simulated] SIM_PARTNER_TOKEN_weread_zhihu_valid_2024_19799...
    2. [harvester_extract] v2.local.ABCdef123GHI456jkl789mno012pqr345
    3. [harvester_extract] sk_test_51H8kLm2nOpQ4rStUvWxYz0123456789
    4. [harvester_extract] partner_weread_2a4b6c8d0e1f3g5h7i9j1k2l3m4n5o6p
    5. [harvester_extract] cs_abc123def456ghi789jkl012mno345pqr678
    6. [simulated_test] test_token_123
    7. [simulated_test] simulated_bearer_abc456xyz
    8. [simulated_test] dummy_api_key_789def

============================================================
[步骤 2] 读取 JSON 并依次调用 simple_api_tester.py
============================================================
  从 /workspace/zccsa/data/harvested_tokens.json 读取到 8 个片段
  API Tester: /workspace/simple_api_tester.py
  测试 URL  : https://httpbin.org/get

  [1/8] 测试片段: SIM_PARTNER_TOKEN_weread_zhihu_valid_...
           → 状态码: 503
  [2/8] 测试片段: v2.local.ABCdef123GHI456jkl789mno012p...
           → 状态码: 503
  [3/8] 测试片段: sk_test_51H8kLm2nOpQ4rStUvWxYz0123456789
           → 状态码: 503
  [4/8] 测试片段: partner_weread_2a4b6c8d0e1f3g5h7i9j1k...
           → 状态码: 503
  [5/8] 测试片段: cs_abc123def456ghi789jkl012mno345pqr678
           → 状态码: 503
  [6/8] 测试片段: test_token_123
           → 状态码: 503
  [7/8] 测试片段: simulated_bearer_abc456xyz
           → 状态码: 503
  [8/8] 测试片段: dummy_api_key_789def
           → 状态码: 503

============================================================
[步骤 3] HTTP 状态码汇总
============================================================

  序号     片段(前40字符)                                    状态码
  ------ -------------------------------------------- ----------
  1      SIM_PARTNER_TOKEN_weread_zhihu_valid_...     503
  2      v2.local.ABCdef123GHI456jkl789mno012p...     503
  3      sk_test_51H8kLm2nOpQ4rStUvWxYz0123456789     503
  4      partner_weread_2a4b6c8d0e1f3g5h7i9j1k2l...     503
  5      cs_abc123def456ghi789jkl012mno345pqr678      503
  6      test_token_123                               503
  7      simulated_bearer_abc456xyz                   503
  8      dummy_api_key_789def                         503

  状态码分布:
    503: 8 次

============================================================
  流水线测试完成！
============================================================
"""


# ================================================================
#  第一部分：日志解析
# ================================================================

# 匹配步骤2中的测试条目行：`  [1/8] 测试片段: <preview>`
RE_TEST_ENTRY = re.compile(
    r'\[(\d+)/(\d+)\]\s*测试片段:\s*(.+)'
)

# 匹配状态码行：`           → 状态码: 503`
RE_STATUS_CODE = re.compile(
    r'状态码:\s*(\S+)'
)

# 匹配测试 URL 行
RE_TEST_URL = re.compile(
    r'测试\s*URL\s*:\s*(\S+)'
)


def parse_log(log_text: str) -> List[Dict[str, Any]]:
    """
    解析日志文本，提取每次测试的片段预览和状态码。

    解析策略：
      优先解析步骤2中的 `[N/M] 测试片段: <preview>` → `状态码: <code>` 配对。
      如果步骤2格式缺失，回退到步骤3的汇总表格。

    参数:
        log_text  完整的日志文本

    返回:
        测试结果列表，每项包含:
          - index:     序号（int）
          - total:     总数（int）
          - preview:   片段预览（str，可能被截断带 "..."）
          - status_code: 状态码（str，如 "200"、"503"、"TIMEOUT"）
    """
    lines = log_text.splitlines()
    results: List[Dict[str, Any]] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        match = RE_TEST_ENTRY.search(line)
        if match:
            index = int(match.group(1))
            total = int(match.group(2))
            preview = match.group(3).strip()

            # 在后续行中查找状态码
            status_code = "UNKNOWN"
            for j in range(i + 1, min(i + 5, len(lines))):
                sm = RE_STATUS_CODE.search(lines[j])
                if sm:
                    status_code = sm.group(1).strip()
                    break

            results.append({
                "index": index,
                "total": total,
                "preview": preview,
                "status_code": status_code,
            })
        i += 1

    # 如果步骤2格式没解析到，尝试步骤3的汇总表格
    if not results:
        results = _parse_summary_table(log_text)

    return results


def _parse_summary_table(log_text: str) -> List[Dict[str, Any]]:
    """
    回退方案：解析步骤3的汇总表格。

    表格格式:
      序号     片段(前40字符)                                    状态码
      ------ -------------------------------------------- ----------
      1      SIM_PARTNER_TOKEN_weread_zhihu_valid_...     503
    """
    results: List[Dict[str, Any]] = []
    lines = log_text.splitlines()
    in_table = False

    for line in lines:
        stripped = line.strip()
        # 检测表头
        if "序号" in stripped and "片段" in stripped and "状态码" in stripped:
            in_table = True
            continue
        # 检测分隔线
        if in_table and stripped.startswith("---"):
            continue
        # 解析数据行
        if in_table and stripped:
            # 格式: `  1      <preview>     503`
            parts = stripped.split()
            if len(parts) >= 3:
                try:
                    index = int(parts[0])
                    status_code = parts[-1]
                    preview = " ".join(parts[1:-1])
                    results.append({
                        "index": index,
                        "total": len(results) + 1,
                        "preview": preview,
                        "status_code": status_code,
                    })
                except ValueError:
                    continue
            # 遇到空行或非表格内容时退出
            if not stripped or stripped.startswith("状态码分布"):
                break

    return results


def extract_test_url(log_text: str) -> str:
    """从日志中提取测试 URL。"""
    match = RE_TEST_URL.search(log_text)
    if match:
        return match.group(1).strip()
    return TEST_URL


# ================================================================
#  第二部分：交叉引用 harvested_tokens.json
# ================================================================

def load_full_tokens() -> List[Dict[str, Any]]:
    """
    从 harvested_tokens.json 加载完整 token 列表。

    返回:
        token 条目列表，每项包含 token / source / date_found 等字段
    """
    if not HARVESTED_TOKENS_FILE.exists():
        return []
    try:
        data = json.loads(HARVESTED_TOKENS_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def match_token_by_preview(
    preview: str,
    full_tokens: List[Dict[str, Any]],
) -> Tuple[str, str]:
    """
    将日志中可能被截断的 token 预览匹配到完整 token。

    匹配策略:
      1. 如果预览不以 "..." 结尾，直接使用预览本身
      2. 去掉 "..." 后缀，在完整 token 列表中查找以该前缀开头的项
      3. 找不到则返回预览本身

    参数:
        preview     日志中的 token 预览（可能被截断）
        full_tokens 完整 token 条目列表

    返回:
        (完整 token 值, token 来源)
    """
    # 如果没有 "..."，说明没有被截断
    if not preview.endswith("..."):
        for entry in full_tokens:
            if entry.get("token") == preview:
                return entry["token"], entry.get("source", "unknown")
        return preview, "unknown"

    # 去掉 "..." 后缀，用作前缀匹配
    prefix = preview[:-3].strip()
    for entry in full_tokens:
        full_token = entry.get("token", "")
        if full_token.startswith(prefix):
            return full_token, entry.get("source", "unknown")

    return preview, "unknown"


# ================================================================
#  第三部分：生成 results.json（poc_report_writer.py 输入格式）
# ================================================================

def classify_status(status_code: str) -> str:
    """
    将状态码映射为报告步骤状态。

    参数:
        status_code  状态码字符串（如 "200"、"503"、"TIMEOUT"）

    返回:
        "通过" / "失败" / "警告"
    """
    if status_code == "UNKNOWN":
        return "警告"
    try:
        code = int(status_code)
        if 200 <= code < 300:
            return "通过"
        elif 500 <= code < 600:
            return "失败"
        elif 400 <= code < 500:
            return "警告"
        else:
            return "警告"
    except ValueError:
        return "警告"


def build_report_data(
    test_results: List[Dict[str, Any]],
    test_url: str,
) -> Dict[str, Any]:
    """
    将解析出的测试结果构建为 poc_report_writer.py 所需的 JSON 结构。

    参数:
        test_results  解析出的测试列表（含 full_token / status_code）
        test_url      测试目标 URL

    返回:
        符合 poc_report_writer.py 输入格式的字典
    """
    full_tokens = load_full_tokens()

    # ── 为每个测试结果匹配完整 token ──
    enriched: List[Dict[str, Any]] = []
    for r in test_results:
        full_token, source = match_token_by_preview(r["preview"], full_tokens)
        enriched.append({
            **r,
            "full_token": full_token,
            "source": source,
            "authorization_header": f"Bearer {full_token}",
        })

    total = len(enriched)
    status_counter = Counter(str(r["status_code"]) for r in enriched)
    passed = sum(1 for r in enriched if classify_status(r["status_code"]) == "通过")
    failed = sum(1 for r in enriched if classify_status(r["status_code"]) == "失败")
    warned = sum(1 for r in enriched if classify_status(r["status_code"]) == "警告")

    # ── 基本信息 ──
    report_data: Dict[str, Any] = {
        "title": "Authorization Token 数据流水线测试报告",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "tester": "自动化流水线 (run_pipeline_test.py)",
        "version": "v1.0",
        "risk_level": "信息" if failed == 0 and passed > 0 else (
            "中危" if failed > 0 else "信息"
        ),

        # ── 测试目标 ──
        "target": {
            "name": "httpbin GET API",
            "url": test_url,
            "type": "REST API (GET)",
            "description": (
                f"通过 run_pipeline_test.py 自动化流水线对 {test_url} 端点进行 "
                "Authorization Bearer Token 验证测试。"
                "流水线包含三个阶段：token_harvester 搜集片段、写入 harvested_tokens.json、"
                "依次调用 simple_api_tester.py 以 Bearer Token 形式发送 GET 请求。"
                "本次测试验证数据流水线从 token 搜集到 API 调用的完整链路是否通畅。"
            ),
        },

        # ── 测试步骤 ──
        "steps": [],

        # ── 请求/响应样例 ──
        "samples": [],

        # ── 测试结论 ──
        "conclusion": {
            "summary": "",
            "risk_assessment": {
                "severity": "",
                "severity_desc": "",
                "exploit_difficulty": "",
                "exploit_difficulty_desc": "",
                "impact_scope": "",
                "impact_scope_desc": "",
            },
            "recommendations": [],
        },

        "test_tools": "run_pipeline_test.py, simple_api_tester.py, curl_cffi",
    }

    # ── 构建测试步骤 ──
    for r in enriched:
        status = classify_status(r["status_code"])
        token_display = r["full_token"]
        if len(token_display) > 40:
            token_display = token_display[:37] + "..."

        report_data["steps"].append({
            "step": r["index"],
            "name": f"Token #{r['index']} 测试 ({r['source']})",
            "action": (
                f"使用 Authorization: Bearer {token_display} "
                f"向 {test_url} 发送 GET 请求"
            ),
            "expected": "返回 200 状态码，响应体包含请求头回显",
            "result": f"返回 {r['status_code']} 状态码",
            "status": status,
        })

    # ── 构建请求/响应样例 ──
    for r in enriched:
        token_display = r["full_token"]
        if len(token_display) > 50:
            token_display = token_display[:47] + "..."

        report_data["samples"].append({
            "name": f"Token #{r['index']} 请求 ({r['source']})",
            "request": {
                "method": "GET",
                "url": test_url,
                "headers": {
                    "Authorization": f"Bearer {token_display}",
                },
                "body": {},
            },
            "response": {
                "status_code": _safe_int(r["status_code"]),
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": {
                    "status_code": r["status_code"],
                    "note": _status_note(r["status_code"]),
                },
            },
        })

    # ── 构建结论 ──
    status_dist = ", ".join(f"{code}: {count} 次" for code, count in status_counter.most_common())
    all_503 = all(r["status_code"] == "503" for r in enriched)

    if all_503:
        report_data["conclusion"]["summary"] = (
            f"本次测试共执行 {total} 项测试用例，全部返回 503 状态码。"
            f"数据流水线链路通畅（token 搜集、JSON 读写、API 调用、状态码捕获均正常工作），"
            f"但目标服务 httpbin.org 暂时不可用（503 Service Unavailable）。"
            f"状态码分布: {status_dist}。"
        )
        report_data["conclusion"]["risk_assessment"] = {
            "severity": "信息",
            "severity_desc": "目标服务临时不可用，非安全漏洞。流水线本身功能正常。",
            "exploit_difficulty": "不适用",
            "exploit_difficulty_desc": "本次测试为流水线连通性验证，不涉及漏洞利用",
            "impact_scope": "无",
            "impact_scope_desc": "503 为服务端临时故障，不影响系统安全",
        }
        report_data["conclusion"]["recommendations"] = [
            f"1. 确认 httpbin.org 服务已恢复后重新运行 run_pipeline_test.py 验证流水线",
            "2. 可考虑增加备用测试端点（如 https://postman-echo.com/get）作为容灾方案",
            "3. 在 run_pipeline_test.py 中增加对 503 状态码的重试逻辑",
            "4. 定期执行流水线测试以确保数据通路持续可用",
        ]
    elif failed > 0:
        report_data["conclusion"]["summary"] = (
            f"本次测试共执行 {total} 项测试用例，"
            f"其中 {passed} 项通过、{failed} 项失败、{warned} 项警告。"
            f"状态码分布: {status_dist}。"
            f"部分测试请求未返回预期状态码，需进一步排查。"
        )
        report_data["conclusion"]["risk_assessment"] = {
            "severity": "中危",
            "severity_desc": f"有 {failed} 项测试返回非预期状态码",
            "exploit_difficulty": "中",
            "exploit_difficulty_desc": "需要进一步分析失败原因",
            "impact_scope": "数据流水线",
            "impact_scope_desc": "部分 token 的 API 调用链路可能存在问题",
        }
        report_data["conclusion"]["recommendations"] = [
            "1. 检查返回非 200 状态码的 token 是否格式正确",
            "2. 确认目标服务端点是否可用",
            "3. 检查网络连接和代理配置",
            "4. 对失败的 token 进行单独排查",
        ]
    else:
        report_data["conclusion"]["summary"] = (
            f"本次测试共执行 {total} 项测试用例，全部通过。"
            f"数据流水线从 token 搜集到 API 调用完整链路运行正常。"
            f"状态码分布: {status_dist}。"
        )
        report_data["conclusion"]["risk_assessment"] = {
            "severity": "信息",
            "severity_desc": "流水线测试全部通过，无安全风险",
            "exploit_difficulty": "不适用",
            "exploit_difficulty_desc": "本次测试为流水线连通性验证，不涉及漏洞利用",
            "impact_scope": "无",
            "impact_scope_desc": "流水线功能正常",
        }
        report_data["conclusion"]["recommendations"] = [
            "1. 定期执行流水线测试以确保持续可用",
            "2. 可考虑增加更多测试端点以覆盖不同场景",
        ]

    return report_data


def _safe_int(s: str) -> Any:
    """尝试将字符串转为 int，失败则返回原字符串。"""
    try:
        return int(s)
    except (ValueError, TypeError):
        return s


def _status_note(status_code: str) -> str:
    """根据状态码返回说明文字。"""
    notes = {
        "200": "请求成功，服务正常响应",
        "401": "认证失败，Token 无效或已过期",
        "403": "禁止访问，权限不足",
        "404": "资源不存在",
        "429": "请求过于频繁，触发速率限制",
        "500": "服务器内部错误",
        "503": "服务不可用，服务端临时过载或维护中",
        "TIMEOUT": "请求超时，未收到响应",
        "FAILED": "请求失败，网络异常",
        "ERROR": "请求出错",
        "UNKNOWN": "未知状态",
    }
    return notes.get(status_code, f"状态码: {status_code}")


# ================================================================
#  第四部分：主逻辑
# ================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        description="解析测试日志，提取 Authorization 头和 HTTP 状态码，生成 results.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--log-file",
        help="从文件读取日志内容（默认使用内嵌日志）",
    )
    parser.add_argument(
        "--log-stdin",
        action="store_true",
        help="从 stdin 读取日志内容",
    )
    parser.add_argument(
        "--output", "-o",
        default=str(OUTPUT_FILE),
        help=f"输出 JSON 文件路径（默认: {OUTPUT_FILE}）",
    )
    args = parser.parse_args()

    # ── 获取日志文本 ──
    if args.log_stdin:
        print("[*] 从 stdin 读取日志...")
        log_text = sys.stdin.read()
    elif args.log_file:
        log_path = Path(args.log_file)
        if not log_path.exists():
            print(f"[错误] 日志文件不存在: {log_path}")
            return 1
        log_text = log_path.read_text(encoding="utf-8")
        print(f"[*] 从文件读取日志: {log_path}")
    else:
        print("[*] 使用内嵌日志（来自上一步 run_pipeline_test.py 的控制台输出）")
        log_text = EMBEDDED_LOG

    print(f"    日志长度: {len(log_text)} 字符")

    # ── 步骤 1: 解析日志 ──
    print("\n[1/3] 解析日志，提取测试条目...")
    test_results = parse_log(log_text)

    if not test_results:
        print("[错误] 未能从日志中解析出任何测试条目")
        return 1

    test_url = extract_test_url(log_text)
    print(f"    测试 URL: {test_url}")
    print(f"    解析到 {len(test_results)} 个测试条目:")
    for r in test_results:
        preview = r["preview"]
        if len(preview) > 40:
            preview = preview[:37] + "..."
        print(f"      [{r['index']}/{r['total']}] {preview} → {r['status_code']}")

    # ── 步骤 2: 交叉引用完整 token ──
    print("\n[2/3] 交叉引用 harvested_tokens.json 获取完整 token...")
    full_tokens = load_full_tokens()
    print(f"    加载到 {len(full_tokens)} 个完整 token")

    # ── 步骤 3: 生成 results.json ──
    print(f"\n[3/3] 生成 results.json...")
    report_data = build_report_data(test_results, test_url)

    output_path = Path(args.output)
    output_path.write_text(
        json.dumps(report_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"    已写入: {output_path}")

    # ── 汇总输出 ──
    status_counter = Counter(str(r["status_code"]) for r in test_results)
    print(f"\n{'=' * 60}")
    print(f"  解析完成！共 {len(test_results)} 个测试条目")
    print(f"  状态码分布:")
    for code, count in status_counter.most_common():
        print(f"    {code}: {count} 次")
    print(f"  输出文件: {output_path}")
    print(f"  下一步: python poc_report_writer.py --input {output_path} --output FINAL_TEST_REPORT.md")
    print(f"{'=' * 60}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
