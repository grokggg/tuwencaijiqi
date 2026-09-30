#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
知乎付费文章内容获取系统 - 主入口
"""
import asyncio
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import TARGET, HTTP, USER_AGENTS, OUTPUT_DIR, DATA_DIR, ORCHESTRATOR
from orchestrator import Orchestrator, save_results
from core.content_parser import ContentParser


async def main():
    """主函数"""
    # 合并配置
    config = {
        "TARGET": TARGET,
        "HTTP": HTTP,
        "USER_AGENTS": USER_AGENTS,
        "OUTPUT_DIR": OUTPUT_DIR,
        "DATA_DIR": DATA_DIR,
        "ORCHESTRATOR": ORCHESTRATOR,
    }

    # 运行编排器
    orchestrator = Orchestrator(config)
    result = await orchestrator.run(max_iterations=ORCHESTRATOR.get("max_iterations", 3))

    # 保存结果
    save_results(result, OUTPUT_DIR)

    # 打印摘要
    print("\n" + "=" * 60)
    print("执行摘要")
    print("=" * 60)
    stats = result.get("http_stats", {})
    print(f"HTTP请求: 总{stats.get('total', 0)}, 成功{stats.get('success', 0)}, 失败{stats.get('fail', 0)}, 重试{stats.get('retries', 0)}")
    print(f"所有结果: {len(result.get('all_results', []))} 条")

    best = result.get("best_content")
    if best:
        print(f"最佳内容: {best.get('char_count', 0)}字, 来源={best.get('source', 'N/A')}, 置信度={best.get('confidence', 0):.2f}")
    else:
        print("未获取到有效内容")

    learned = result.get("learned_facts", {})
    if learned.get("new_content_found"):
        print(f"\n新发现内容: {len(learned['new_content_found'])} 条")
        for nc in learned["new_content_found"]:
            print(f"  [{nc['source']}] {nc['char_count']}字: {nc['snippet'][:60]}...")

    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
