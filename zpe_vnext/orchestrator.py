# -*- coding: utf-8 -*-
"""
ZPE vNext - 编排器
实现失败-学习-重试循环，协调所有引擎
"""
import asyncio
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any, Tuple

import sys
sys.path.insert(0, str(Path(__file__).parent))
import config
from core.http_client import HttpClient, cn_count
from core.parser import ContentParser
from engines.base_engine import EngineResult

# 导入所有引擎
from engines.search_osint_engine import SearchOSINTEngine
from engines.novel_site_engine import NovelSiteEngine
from engines.api_fuzz_engine import ApiFuzzEngine
from engines.deep_chapter_engine import DeepChapterEngine


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S'
)
logger = logging.getLogger("orchestrator")


class Orchestrator:
    """攻击编排器 - 失败-学习-重试循环"""
    
    def __init__(self):
        self.http = HttpClient()
        self.parser = ContentParser()
        self.best_content = ""
        self.best_word_count = 0
        self.best_source = ""
        self.best_method = ""
        self.all_contents: List[Tuple[str, str]] = []  # (source, content)
        self.discovered_urls: List[str] = []
        self.discovered_chapters: List[Tuple[str, str]] = []
        self.iteration_log: List[Dict] = []
        self.successful_methods: List[str] = []
        self.failed_methods: List[str] = []
        
        # 按优先级排序的引擎列表
        self.engine_classes = [
            DeepChapterEngine,   # 优先级95 - 先试试已知路径深度爬取
            SearchOSINTEngine,   # 优先级100 - OSINT发现
            NovelSiteEngine,     # 优先级90 - 小说站扫描
            ApiFuzzEngine,       # 优先级80 - API探测
        ]
    
    async def run(self) -> Dict[str, Any]:
        """运行主循环"""
        start_time = time.time()
        final_result = {
            "success": False,
            "content": "",
            "word_count": 0,
            "iterations": 0,
            "method": "",
            "report": "",
        }
        
        logger.info("="*70)
        logger.info("ZPE vNext - 知乎付费内容提取工具启动")
        logger.info(f"目标文章: {config.TARGET['title']} (ID: {config.TARGET['article_id']})")
        logger.info(f"主角: {', '.join(config.TARGET['main_characters'])}")
        logger.info("="*70)
        
        for iteration in range(1, config.MAX_ITERATIONS + 1):
            logger.info(f"\n{'#'*70}")
            logger.info(f"# 迭代 {iteration}/{config.MAX_ITERATIONS}")
            logger.info(f"{'#'*70}")
            
            iter_start = time.time()
            iter_result = {
                "iteration": iteration,
                "engines_run": [],
                "best_word_count": self.best_word_count,
                "new_content_found": False,
            }
            
            # 构建上下文（包含之前学到的信息）
            context = self._build_context(iteration)
            
            # 运行引擎
            for engine_cls in self.engine_classes:
                engine = engine_cls(self.http, self.parser)
                engine_name = engine.name
                
                logger.info(f"\n--- 运行引擎: {engine_name} ({engine.description}) ---")
                
                try:
                    result: EngineResult = await engine.run(context)
                    
                    iter_result["engines_run"].append({
                        "name": engine_name,
                        "success": result.success,
                        "bypass_found": result.bypass_found,
                        "word_count": result.word_count,
                        "confidence": result.confidence,
                        "method": result.bypass_method,
                    })
                    
                    # 收集发现的URL和章节
                    if result.discovered_urls:
                        for url in result.discovered_urls:
                            if url not in self.discovered_urls:
                                self.discovered_urls.append(url)
                    
                    if result.chapters:
                        seen = set(u for _, u in self.discovered_chapters)
                        for title, url in result.chapters:
                            if url not in seen:
                                self.discovered_chapters.append((title, url))
                    
                    # 处理内容
                    if result.success and result.content:
                        self.all_contents.append((engine_name, result.content))
                        
                        if result.word_count > self.best_word_count:
                            self.best_content = result.content
                            self.best_word_count = result.word_count
                            self.best_source = result.source_url
                            self.best_method = result.bypass_method or engine_name
                            iter_result["new_content_found"] = True
                            
                            logger.info(f"  ✓ 发现更好内容: {result.word_count} 字 (置信度: {result.confidence:.2f})")
                            logger.info(f"    来源: {result.source_url}")
                            if result.bypass_method:
                                logger.info(f"    方法: {result.bypass_method}")
                        
                        if result.bypass_found:
                            self.successful_methods.append(result.bypass_method)
                    
                    # 学习：如果引擎失败，记录失败原因
                    if not result.success:
                        self.failed_methods.append(engine_name)
                    
                    # 检查是否已经获取足够内容
                    if self.best_word_count >= config.COMPLETE_CONTENT_MIN_WORDS:
                        logger.info(f"\n*** 已获取超过 {config.COMPLETE_CONTENT_MIN_WORDS} 字内容，判定为完整！ ***")
                        break
                        
                except Exception as e:
                    logger.error(f"  ✗ 引擎 {engine_name} 执行出错: {e}", exc_info=True)
                    iter_result["engines_run"].append({
                        "name": engine_name,
                        "success": False,
                        "error": str(e),
                    })
            
            iter_result["time"] = time.time() - iter_start
            iter_result["total_word_count"] = self.best_word_count
            self.iteration_log.append(iter_result)
            
            logger.info(f"\n--- 迭代 {iteration} 总结 ---")
            logger.info(f"  总字数: {self.best_word_count}")
            logger.info(f"  发现URL: {len(self.discovered_urls)}")
            logger.info(f"  发现章节: {len(self.discovered_chapters)}")
            logger.info(f"  耗时: {iter_result['time']:.1f}秒")
            
            # 检查是否成功
            if self.best_word_count >= config.COMPLETE_CONTENT_MIN_WORDS:
                logger.info("\n" + "="*70)
                logger.info("成功获取完整内容!")
                logger.info("="*70)
                break
            
            # 如果没有新内容，调整策略
            if not iter_result["new_content_found"] and iteration < config.MAX_ITERATIONS:
                logger.info("\n本轮未发现新内容，调整策略进入下一轮...")
                await asyncio.sleep(1)
        
        # 合并所有来源的内容
        if self.all_contents:
            logger.info("\n合并所有来源内容以获得最完整版本...")
            self.best_content = self.parser.merge_contents(self.all_contents)
            self.best_word_count = cn_count(self.best_content)
        
        # 生成最终结果
        elapsed = time.time() - start_time
        
        final_result["success"] = self.best_word_count > 500
        final_result["content"] = self.best_content
        final_result["word_count"] = self.best_word_count
        final_result["method"] = self.best_method
        final_result["iterations"] = len(self.iteration_log)
        final_result["time_elapsed"] = elapsed
        final_result["sources_found"] = len(self.all_contents)
        final_result["urls_discovered"] = len(self.discovered_urls)
        final_result["chapters_found"] = len(self.discovered_chapters)
        
        # 保存结果
        await self._save_results(final_result)
        
        # 生成报告
        final_result["report"] = self._generate_report(final_result)
        
        await self.http.close()
        
        return final_result
    
    def _build_context(self, iteration: int) -> Dict[str, Any]:
        """构建上下文（包含学习到的信息）"""
        return {
            "iteration": iteration,
            "best_word_count": self.best_word_count,
            "best_content": self.best_content,
            "discovered_urls": list(self.discovered_urls),
            "chapters": list(self.discovered_chapters),
            "successful_methods": list(self.successful_methods),
            "failed_methods": list(self.failed_methods),
        }
    
    async def _save_results(self, result: Dict[str, Any]):
        """保存结果到文件"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # 保存Markdown全文
        md_content = f"""# {config.TARGET['title']}

> 来源: 知乎盐选专栏
> 主角: {', '.join(config.TARGET['main_characters'])}
> 获取方法: {result['method']}
> 总字数: {result['word_count']}
> 获取时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

---

{result['content']}
"""
        
        output_md = config.OUTPUT_DIR / f"{config.TARGET['title']}_{timestamp}.md"
        output_md.write_text(md_content, encoding='utf-8')
        
        # 同时保存一份不带时间戳的最新版本
        latest_md = config.OUTPUT_DIR / f"{config.TARGET['title']}_完整版.md"
        latest_md.write_text(md_content, encoding='utf-8')
        
        # 保存JSON结果
        result_json = {
            "title": config.TARGET["title"],
            "article_id": config.TARGET["article_id"],
            "word_count": result["word_count"],
            "method": result["method"],
            "success": result["success"],
            "iterations": result["iterations"],
            "time_elapsed": result["time_elapsed"],
            "iterations_log": self.iteration_log,
        }
        output_json = config.DATA_DIR / f"result_{timestamp}.json"
        output_json.write_text(json.dumps(result_json, ensure_ascii=False, indent=2), encoding='utf-8')
        
        # 保存报告
        report_md = config.REPORTS_DIR / f"提取报告_{timestamp}.md"
        report_md.write_text(result["report"], encoding='utf-8')
        
        logger.info(f"\n结果已保存:")
        logger.info(f"  全文: {output_md}")
        logger.info(f"  最新: {latest_md}")
        logger.info(f"  报告: {report_md}")
    
    def _generate_report(self, result: Dict[str, Any]) -> str:
        """生成提取报告"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        status = "成功" if result["word_count"] >= config.COMPLETE_CONTENT_MIN_WORDS else \
                 "部分成功" if result["word_count"] > 1000 else "获取失败"
        
        iter_summary = []
        for log in self.iteration_log:
            engines = []
            for e in log.get("engines_run", []):
                if e.get("success"):
                    engines.append(f"{e['name']}({e['word_count']}字)")
                else:
                    engines.append(f"{e['name']}(失败)")
            iter_summary.append(f"  - 迭代{log['iteration']}: {', '.join(engines)} -> {log['total_word_count']}字")
        
        report = f"""# ZPE vNext 提取报告

## 基本信息

- **目标文章**: {config.TARGET['title']}
- **文章ID**: {config.TARGET['article_id']}
- **主角**: {', '.join(config.TARGET['main_characters'])}
- **提取状态**: {status}
- **最终字数**: {result['word_count']} 字
- **迭代次数**: {result['iterations']}
- **耗时**: {result['time_elapsed']:.1f} 秒
- **提取时间**: {timestamp}

## 提取方法

{result['method'] or '多引擎聚合'}

## 迭代过程

{chr(10).join(iter_summary)}

## 来源统计

- 成功内容来源: {result['sources_found']} 个
- 发现URL总数: {result['urls_discovered']} 个
- 发现章节数: {result['chapters_found']} 个

## 内容预览

{result['content'][:1000] if result['content'] else '无内容'}

...

{"(内容已截断，完整内容见输出文件)" if result['word_count'] > 1000 else ""}
"""
        return report


async def main():
    orchestrator = Orchestrator()
    result = await orchestrator.run()
    
    print("\n" + "="*70)
    print("最终结果:")
    print(f"  状态: {'成功' if result['success'] else '失败'}")
    print(f"  字数: {result['word_count']}")
    print(f"  方法: {result['method']}")
    print(f"  迭代: {result['iterations']}轮")
    print("="*70)


if __name__ == "__main__":
    asyncio.run(main())
