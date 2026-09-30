#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
编排器 - 协调所有引擎，实现失败-学习-重试循环
"""
import asyncio
import time
import json
import os
from typing import List, Dict, Optional

from core.http_engine import HTTPEngine
from core.content_parser import ContentParser
from engines.novel_scanner import NovelScanner
from engines.search_osint import SearchOSINT
from engines.zhihu_api import ZhihuAPI


class Orchestrator:
    """多引擎编排器，自适应策略选择"""

    def __init__(self, config: dict):
        self.config = config
        self.http = HTTPEngine(config.get("HTTP", {}))
        self.parser = ContentParser()
        self.all_results = []
        self.iteration_log = []
        self.learned_facts = {
            "working_sources": [],
            "failed_sources": [],
            "new_content_found": [],
            "total_chapters": config.get("TARGET", {}).get("known_chapters", 5),
        }

    async def run(self, max_iterations: int = 3) -> Dict:
        """运行完整管线"""
        print("=" * 60)
        print("知乎付费文章内容获取系统 v2.0")
        print(f"目标文章: {self.config.get('TARGET', {}).get('title', 'N/A')}")
        print(f"文章ID: {self.config.get('TARGET', {}).get('article_id', 'N/A')}")
        print("=" * 60)

        best_content = None
        best_score = 0

        for iteration in range(1, max_iterations + 1):
            print(f"\n{'='*40}")
            print(f"迭代 #{iteration}")
            print(f"{'='*40}")

            iteration_results = []

            # 阶段1: 小说站扫描（已知最有效）
            print("\n--- 阶段1: 小说站扫描 ---")
            novel_engine = NovelScanner(self.http, self.config)
            novel_results = await novel_engine.run()
            iteration_results.extend(novel_results)
            self._update_learned_facts(novel_results, "novel_scanner")

            # 阶段2: 搜索引擎OSINT
            print("\n--- 阶段2: 搜索引擎OSINT ---")
            search_engine = SearchOSINT(self.http, self.config)
            search_results = await search_engine.run()
            iteration_results.extend(search_results)
            self._update_learned_facts(search_results, "search_osint")

            # 阶段3: 知乎API（通常失败，但值得一试）
            # 跳过 - 已知返回404
            # if iteration == 1:
            #     print("\n--- 阶段3: 知乎API探测 ---")
            #     api_engine = ZhihuAPI(self.http, self.config)
            #     api_results = await api_engine.run()
            #     iteration_results.extend(api_results)
            #     self._update_learned_facts(api_results, "zhihu_api")

            # 汇总结果
            self.all_results.extend(iteration_results)

            # 评估当前最佳内容
            current_best = self._find_best_content()
            if current_best:
                score = current_best.get("char_count", 0)
                print(f"\n当前最佳: {score}字, 来源={current_best.get('source', 'N/A')}")
                if score > best_score:
                    best_score = score
                    best_content = current_best

            # 记录迭代日志
            self.iteration_log.append({
                "iteration": iteration,
                "results_count": len(iteration_results),
                "best_score": best_score,
                "learned": dict(self.learned_facts),
            })

            # 检查是否已有足够内容
            if best_score > 5000:
                print(f"\n已获取 {best_score} 字内容，达到阈值。")
                break

            # 学习并调整策略
            if iteration < max_iterations:
                self._learn_and_adjust(iteration)

        # 最终内容聚合
        final_content = self._aggregate_content()

        return {
            "best_content": best_content,
            "aggregated_content": final_content,
            "all_results": self.all_results,
            "iteration_log": self.iteration_log,
            "learned_facts": self.learned_facts,
            "http_stats": self.http.get_stats(),
        }

    def _update_learned_facts(self, results: List[Dict], engine_name: str):
        """从结果中学习"""
        if results:
            self.learned_facts["working_sources"].append(engine_name)
            for r in results:
                if r.get("confidence", 0) > 0.5:
                    content = r.get("content", "")
                    # 检查是否有新内容
                    known_content = " ".join([x.get("content", "") for x in self.all_results])
                    if content not in known_content:
                        self.learned_facts["new_content_found"].append({
                            "source": r.get("source", ""),
                            "char_count": r.get("char_count", 0),
                            "snippet": content[:100],
                        })
        else:
            self.learned_facts["failed_sources"].append(engine_name)

    def _find_best_content(self) -> Optional[Dict]:
        """找到字数最多的有效内容"""
        if not self.all_results:
            return None

        best = max(self.all_results, key=lambda x: x.get("char_count", 0))
        if best.get("char_count", 0) > 100:
            return best
        return None

    def _learn_and_adjust(self, iteration: int):
        """根据学习结果调整策略"""
        print(f"\n--- 学习与调整 ---")
        print(f"工作来源: {self.learned_facts['working_sources']}")
        print(f"失败来源: {self.learned_facts['failed_sources']}")
        if self.learned_facts["new_content_found"]:
            print(f"新内容发现: {len(self.learned_facts['new_content_found'])} 条")
            for nc in self.learned_facts["new_content_found"][-3:]:
                print(f"  [{nc['source']}] {nc['char_count']}字: {nc['snippet'][:50]}...")

    def _aggregate_content(self) -> str:
        """聚合所有来源的内容"""
        if not self.all_results:
            return ""

        # 按来源分组
        kepue_chapters = sorted(
            [r for r in self.all_results if "kepue" in r.get("source", "")],
            key=lambda x: x.get("chapter", 0)
        )

        # 其他来源的内容
        other_content = [r for r in self.all_results if "kepue" not in r.get("source", "")]

        # 合并内容
        lines = []
        seen_paragraphs = set()

        # 先放kepue的章节（按顺序）
        for r in kepue_chapters:
            ch = r.get("chapter", 0)
            if ch > 0:
                lines.append(f"\n## 第{ch}章\n")
            content = r.get("content", "")
            for para in content.split("\n\n"):
                para = para.strip()
                if para and para not in seen_paragraphs:
                    seen_paragraphs.add(para)
                    lines.append(para)

        # 再放其他来源的额外内容
        if other_content:
            lines.append("\n## 补充内容（来自其他来源）\n")
            for r in other_content:
                content = r.get("content", "")
                source = r.get("source", "unknown")
                for para in content.split("\n\n"):
                    para = para.strip()
                    if para and para not in seen_paragraphs:
                        seen_paragraphs.add(para)
                        lines.append(para)

        return "\n\n".join(lines)


def save_results(result: dict, output_dir: str):
    """保存结果"""
    os.makedirs(output_dir, exist_ok=True)

    # 保存聚合内容
    aggregated = result.get("aggregated_content", "")
    if aggregated:
        path = os.path.join(output_dir, "aggregated_content.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(aggregated)
        print(f"\n聚合内容已保存: {path}")

    # 保存JSON结果
    path = os.path.join(output_dir, "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({
            "best_content": {
                "source": result.get("best_content", {}).get("source", ""),
                "char_count": result.get("best_content", {}).get("char_count", 0),
                "confidence": result.get("best_content", {}).get("confidence", 0),
            } if result.get("best_content") else None,
            "all_results": [
                {
                    "source": r.get("source", ""),
                    "chapter": r.get("chapter", 0),
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "char_count": r.get("char_count", 0),
                    "confidence": r.get("confidence", 0),
                    "content_preview": r.get("content", "")[:200],
                }
                for r in result.get("all_results", [])
            ],
            "iteration_log": result.get("iteration_log", []),
            "learned_facts": result.get("learned_facts", {}),
            "http_stats": result.get("http_stats", {}),
        }, f, ensure_ascii=False, indent=2)
    print(f"详细结果已保存: {path}")
