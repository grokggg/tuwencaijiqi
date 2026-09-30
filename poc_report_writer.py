#!/usr/bin/env python3
"""
poc_report_writer.py — API 安全测试报告自动化生成工具

功能：
  1. 读取 JSON 输入文件（包含测试目标、步骤、请求/响应样例、结论）
  2. 填充 Markdown 模板，生成最终的 API_SECURITY_TEST_REPORT.md

使用方法：
  python poc_report_writer.py --input report_data.json
  python poc_report_writer.py --input report_data.json --output ./output/REPORT.md
  python poc_report_writer.py --sample   # 生成默认 JSON 样例文件

JSON 输入格式见 sample_report_data.json
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ================================================================
#  第一部分：Markdown 模板
# ================================================================

REPORT_TEMPLATE = """\
# API 安全测试报告

| 字段 | 值 |
|------|-----|
| **报告标题** | {title} |
| **测试日期** | {date} |
| **测试人员** | {tester} |
| **报告版本** | {version} |
| **风险等级** | {risk_level} |

---

## 1. 测试目标

{target_description}

### 目标信息

| 属性 | 值 |
|------|-----|
| 目标名称 | {target_name} |
| 目标 URL | {target_url} |
| 目标类型 | {target_type} |

---

## 2. 测试步骤

{steps_content}

---

## 3. 请求与响应样例

{samples_content}

---

## 4. 测试结论

### 总体结论

{conclusion_summary}

### 风险评估

| 维度 | 评级 | 说明 |
|------|------|------|
| 严重程度 | {risk_severity} | {risk_severity_desc} |
| 利用难度 | {exploit_difficulty} | {exploit_difficulty_desc} |
| 影响范围 | {impact_scope} | {impact_scope_desc} |

### 修复建议

{recommendations}

---

## 5. 附录

### 测试环境

| 属性 | 值 |
|------|-----|
| 操作系统 | {os_info} |
| Python 版本 | {python_version} |
| 测试工具 | {test_tools} |

### 文件信息

| 属性 | 值 |
|------|-----|
| 生成时间 | {generated_at} |
| 生成工具 | poc_report_writer.py v1.0 |

---

*本报告由 poc_report_writer.py 自动生成，仅供授权安全测试使用。*
"""


# ================================================================
#  第二部分：默认 JSON 样例数据
# ================================================================

DEFAULT_SAMPLE_DATA: Dict[str, Any] = {
    "title": "用户登录接口安全测试报告",
    "date": "2026-08-04",
    "tester": "张三",
    "version": "v1.0",
    "risk_level": "高危",

    "target": {
        "name": "用户认证服务",
        "url": "https://api.example.com/v1/auth/login",
        "type": "REST API (POST)",
        "description": (
            "本次测试针对用户登录接口 /v1/auth/login 进行安全评估。"
            "该接口接收用户名和密码，验证后返回 JWT Token。"
            "测试重点关注认证绕过、注入攻击、信息泄露等安全风险。"
        ),
    },

    "steps": [
        {
            "step": 1,
            "name": "正常登录流程验证",
            "action": "使用合法账号密码发送 POST 请求",
            "expected": "返回 200 状态码和 JWT Token",
            "result": "符合预期",
            "status": "通过",
        },
        {
            "step": 2,
            "name": "SQL 注入测试",
            "action": "在 username 字段注入 ' OR '1'='1",
            "expected": "请求被拒绝，返回错误信息",
            "result": "接口未对输入进行过滤，成功绕过认证",
            "status": "失败",
        },
        {
            "step": 3,
            "name": "暴力破解防护测试",
            "action": "连续发送 100 次错误密码请求",
            "expected": "触发速率限制，返回 429 状态码",
            "result": "前 50 次请求正常返回 401，第 51 次起返回 429",
            "status": "通过",
        },
        {
            "step": 4,
            "name": "密码明文传输检查",
            "action": "抓包检查登录请求是否加密传输密码",
            "expected": "密码字段应经过前端加密或使用 HTTPS 传输",
            "result": "HTTPS 已启用，但密码字段为明文，未做前端加密",
            "status": "警告",
        },
    ],

    "samples": [
        {
            "name": "正常登录请求",
            "request": {
                "method": "POST",
                "url": "https://api.example.com/v1/auth/login",
                "headers": {
                    "Content-Type": "application/json",
                    "User-Agent": "TestClient/1.0",
                },
                "body": {
                    "username": "testuser@example.com",
                    "password": "SecurePass123!",
                },
            },
            "response": {
                "status_code": 200,
                "headers": {
                    "Content-Type": "application/json",
                    "Set-Cookie": "session=abc123; HttpOnly; Secure",
                },
                "body": {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                        "expires_in": 3600,
                    },
                },
            },
        },
        {
            "name": "SQL 注入请求",
            "request": {
                "method": "POST",
                "url": "https://api.example.com/v1/auth/login",
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": {
                    "username": "admin' OR '1'='1",
                    "password": "anything",
                },
            },
            "response": {
                "status_code": 200,
                "headers": {
                    "Content-Type": "application/json",
                },
                "body": {
                    "code": 0,
                    "message": "success",
                    "data": {
                        "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
                        "expires_in": 3600,
                        "user_id": 1,
                        "role": "admin",
                    },
                },
            },
        },
    ],

    "conclusion": {
        "summary": (
            "本次测试共执行 4 项测试用例，其中 2 项通过、1 项失败、1 项警告。"
            "发现 1 个高危漏洞（SQL 注入导致认证绕过）和 1 个中危问题（密码明文传输）。"
            "建议在上线前修复 SQL 注入漏洞，并增加前端密码加密机制。"
        ),
        "risk_assessment": {
            "severity": "高危",
            "severity_desc": "SQL 注入可导致任意账户登录，包括管理员账户",
            "exploit_difficulty": "低",
            "exploit_difficulty_desc": "使用标准 SQL 注入 Payload 即可利用，无需特殊工具",
            "impact_scope": "全系统",
            "impact_scope_desc": "攻击者可获取任意用户权限，影响所有用户数据",
        },
        "recommendations": [
            "1. 对 username 和 password 字段实施严格的输入验证和参数化查询",
            "2. 使用 WAF 规则拦截常见 SQL 注入 Payload",
            "3. 前端密码字段使用 RSA 或 AES 加密后再传输",
            "4. 登录接口增加验证码机制，防止自动化攻击",
            "5. 定期进行安全扫描和渗透测试",
        ],
    },
}


# ================================================================
#  第三部分：数据校验
# ================================================================

class ValidationError(Exception):
    """JSON 数据校验失败时抛出。"""
    pass


def validate_data(data: Dict[str, Any]) -> None:
    """
    校验输入 JSON 数据是否包含必需字段。

    参数:
        data  解析后的 JSON 字典

    异常:
        ValidationError  缺少必需字段时抛出
    """
    required_top_keys = [
        "title", "date", "tester", "version", "risk_level",
        "target", "steps", "samples", "conclusion",
    ]
    for key in required_top_keys:
        if key not in data:
            raise ValidationError(f"缺少必需字段: '{key}'")

    # ── 校验 target ──
    target = data["target"]
    for key in ["name", "url", "type", "description"]:
        if key not in target:
            raise ValidationError(f"'target' 中缺少字段: '{key}'")

    # ── 校验 steps ──
    if not isinstance(data["steps"], list) or len(data["steps"]) == 0:
        raise ValidationError("'steps' 必须是包含至少一个步骤的列表")
    for i, step in enumerate(data["steps"]):
        for key in ["step", "name", "action", "expected", "result", "status"]:
            if key not in step:
                raise ValidationError(f"'steps[{i}]' 中缺少字段: '{key}'")

    # ── 校验 samples ──
    if not isinstance(data["samples"], list) or len(data["samples"]) == 0:
        raise ValidationError("'samples' 必须是包含至少一个样例的列表")
    for i, sample in enumerate(data["samples"]):
        for key in ["name", "request", "response"]:
            if key not in sample:
                raise ValidationError(f"'samples[{i}]' 中缺少字段: '{key}'")

    # ── 校验 conclusion ──
    conclusion = data["conclusion"]
    for key in ["summary", "risk_assessment", "recommendations"]:
        if key not in conclusion:
            raise ValidationError(f"'conclusion' 中缺少字段: '{key}'")

    ra = conclusion["risk_assessment"]
    for key in ["severity", "severity_desc", "exploit_difficulty",
                "exploit_difficulty_desc", "impact_scope", "impact_scope_desc"]:
        if key not in ra:
            raise ValidationError(f"'conclusion.risk_assessment' 中缺少字段: '{key}'")


# ================================================================
#  第四部分：模板渲染
# ================================================================

def render_steps(steps: List[Dict[str, Any]]) -> str:
    """
    将测试步骤列表渲染为 Markdown 格式。

    返回:
        Markdown 格式的步骤内容字符串
    """
    lines: List[str] = []

    # 表格表头
    lines.append("| 步骤 | 名称 | 操作 | 预期结果 | 实际结果 | 状态 |")
    lines.append("|------|------|------|----------|----------|------|")

    for step in steps:
        # 状态用 emoji 标识
        status = step.get("status", "")
        status_icon = {
            "通过": "✅ 通过",
            "失败": "❌ 失败",
            "警告": "⚠️ 警告",
        }.get(status, status)

        lines.append(
            f"| {step['step']} | {step['name']} | {step['action']} "
            f"| {step['expected']} | {step['result']} | {status_icon} |"
        )

    return "\n".join(lines)


def render_json_block(data: Any, indent: int = 2) -> str:
    """
    将 Python 对象格式化为 JSON 代码块。

    参数:
        data    要格式化的数据
        indent  JSON 缩进空格数

    返回:
        ```json ... ``` 格式的字符串
    """
    json_str = json.dumps(data, ensure_ascii=False, indent=indent)
    return f"```json\n{json_str}\n```"


def render_samples(samples: List[Dict[str, Any]]) -> str:
    """
    将请求/响应样例渲染为 Markdown 格式。

    返回:
        Markdown 格式的样例内容字符串
    """
    sections: List[str] = []

    for i, sample in enumerate(samples, 1):
        req = sample["request"]
        resp = sample["response"]

        section = f"### 样例 {i}: {sample['name']}\n"

        # ── 请求 ──
        section += f"\n**请求**\n\n"
        section += f"- 方法: `{req.get('method', 'N/A')}`\n"
        section += f"- URL: `{req.get('url', 'N/A')}`\n"

        if req.get("headers"):
            section += "\n请求头:\n\n"
            section += render_json_block(req["headers"])
            section += "\n"

        if req.get("body"):
            section += "\n请求体:\n\n"
            section += render_json_block(req["body"])
            section += "\n"

        # ── 响应 ──
        section += f"\n**响应**\n\n"
        section += f"- 状态码: `{resp.get('status_code', 'N/A')}`\n"

        if resp.get("headers"):
            section += "\n响应头:\n\n"
            section += render_json_block(resp["headers"])
            section += "\n"

        if resp.get("body"):
            section += "\n响应体:\n\n"
            section += render_json_block(resp["body"])
            section += "\n"

        sections.append(section)

    return "\n---\n".join(sections)


def render_recommendations(recs: List[str]) -> str:
    """
    将修复建议列表渲染为 Markdown 格式。

    返回:
        Markdown 格式的建议内容字符串
    """
    if not recs:
        return "暂无修复建议。"

    lines: List[str] = []
    for rec in recs:
        # 如果建议本身已带编号，直接使用；否则添加编号
        if rec.strip()[:2].rstrip(".").isdigit():
            lines.append(f"- {rec}")
        else:
            lines.append(f"- {rec}")
    return "\n".join(lines)


def render_report(data: Dict[str, Any]) -> str:
    """
    使用数据填充 Markdown 模板，生成完整报告。

    参数:
        data  校验通过的 JSON 数据字典

    返回:
        完整的 Markdown 报告字符串
    """
    target = data["target"]
    conclusion = data["conclusion"]
    risk = conclusion["risk_assessment"]

    # 获取系统信息
    import platform
    os_info = f"{platform.system()} {platform.release()}"
    python_version = platform.python_version()
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    report = REPORT_TEMPLATE.format(
        # 基本信息
        title=data["title"],
        date=data["date"],
        tester=data["tester"],
        version=data["version"],
        risk_level=data["risk_level"],
        # 目标
        target_description=target["description"],
        target_name=target["name"],
        target_url=target["url"],
        target_type=target["type"],
        # 步骤
        steps_content=render_steps(data["steps"]),
        # 样例
        samples_content=render_samples(data["samples"]),
        # 结论
        conclusion_summary=conclusion["summary"],
        risk_severity=risk["severity"],
        risk_severity_desc=risk["severity_desc"],
        exploit_difficulty=risk["exploit_difficulty"],
        exploit_difficulty_desc=risk["exploit_difficulty_desc"],
        impact_scope=risk["impact_scope"],
        impact_scope_desc=risk["impact_scope_desc"],
        recommendations=render_recommendations(conclusion["recommendations"]),
        # 附录
        os_info=os_info,
        python_version=python_version,
        test_tools=data.get("test_tools", "curl_cffi, Postman"),
        generated_at=generated_at,
    )

    return report


# ================================================================
#  第五部分：主逻辑
# ================================================================

def generate_sample_file(output_path: str) -> None:
    """
    生成默认的 JSON 样例文件。

    参数:
        output_path  样例文件输出路径
    """
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(DEFAULT_SAMPLE_DATA, f, ensure_ascii=False, indent=2)
    print(f"[OK] 默认 JSON 样例已生成: {output_path}")


def process_report(input_path: str, output_path: str) -> int:
    """
    主流程：读取 JSON -> 校验 -> 渲染 -> 写入文件。

    参数:
        input_path   输入 JSON 文件路径
        output_path  输出 Markdown 文件路径

    返回:
        0 成功，1 失败
    """
    # ── Step 1: 读取 JSON 文件 ──
    print(f"[1/4] 读取输入文件: {input_path}")
    try:
        with open(input_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"[错误] 文件不存在: {input_path}")
        return 1
    except json.JSONDecodeError as e:
        print(f"[错误] JSON 解析失败: {e}")
        return 1

    print(f"      -> 成功读取 {len(json.dumps(data, ensure_ascii=False))} 字符的 JSON 数据")

    # ── Step 2: 校验数据 ──
    print("[2/4] 校验数据结构...")
    try:
        validate_data(data)
    except ValidationError as e:
        print(f"[错误] 数据校验失败: {e}")
        return 1
    print("      -> 校验通过")

    # ── Step 3: 渲染模板 ──
    print("[3/4] 渲染 Markdown 模板...")
    try:
        report_content = render_report(data)
    except KeyError as e:
        print(f"[错误] 模板渲染失败，缺少键: {e}")
        return 1
    except Exception as e:
        print(f"[错误] 模板渲染失败: {type(e).__name__}: {e}")
        return 1
    print(f"      -> 报告已生成 ({len(report_content)} 字符)")

    # ── Step 4: 写入文件 ──
    print(f"[4/4] 写入输出文件: {output_path}")
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report_content)
    except IOError as e:
        print(f"[错误] 文件写入失败: {e}")
        return 1

    print(f"\n{'=' * 60}")
    print(f"  [OK] 报告已生成: {output_path}")
    print(f"  报告标题: {data['title']}")
    print(f"  测试步骤: {len(data['steps'])} 项")
    print(f"  请求样例: {len(data['samples'])} 个")
    print(f"  风险等级: {data['risk_level']}")
    print(f"{'=' * 60}")

    return 0


def main() -> int:
    """解析命令行参数，执行报告生成流程。"""
    parser = argparse.ArgumentParser(
        description="API 安全测试报告自动化生成工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 使用 JSON 文件生成报告
  python poc_report_writer.py --input report_data.json

  # 指定输出路径
  python poc_report_writer.py -i report_data.json -o ./reports/MY_REPORT.md

  # 生成默认 JSON 样例文件
  python poc_report_writer.py --sample

  # 生成样例并立即用它测试
  python poc_report_writer.py --sample --test
        """,
    )
    parser.add_argument(
        "-i", "--input",
        help="输入 JSON 文件路径",
    )
    parser.add_argument(
        "-o", "--output",
        default="API_SECURITY_TEST_REPORT.md",
        help="输出 Markdown 文件路径（默认: API_SECURITY_TEST_REPORT.md）",
    )
    parser.add_argument(
        "--sample",
        action="store_true",
        help="生成默认 JSON 样例文件 sample_report_data.json",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="使用样例数据立即生成报告（与 --sample 配合使用）",
    )
    args = parser.parse_args()

    # ── 生成样例文件 ──
    if args.sample:
        sample_path = "sample_report_data.json"
        generate_sample_file(sample_path)

        if args.test:
            print()
            return process_report(sample_path, args.output)
        return 0

    # ── 正常流程：从 JSON 生成报告 ──
    if not args.input:
        parser.error("请提供 --input 参数，或使用 --sample 生成样例文件")
        return 1

    return process_report(args.input, args.output)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[中断] 用户取消了操作")
        sys.exit(130)
