# -*- coding: utf-8 -*-
"""
ZCCSA 探测成功率监控与引擎权重动态调整
- 维护各引擎24小时内的成功/失败/平均耗时统计
- 实时计算成功率，按成功率倒序排列引擎执行顺序
- 支持权重手动调整和自动衰减
"""
import json
import logging
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent))
import config

logger = logging.getLogger(__name__)


@dataclass
class EngineStats:
    """单个引擎统计"""
    name: str
    success: int = 0
    failure: int = 0
    bypass: int = 0
    total_duration_ms: float = 0.0
    total_requests: int = 0
    last_run: float = 0.0
    last_success: float = 0.0
    history: List[Dict] = field(default_factory=list)  # 最近N次结果
    current_weight: float = 0.0
    # ZCCSA-Auto 新增字段
    total_score_sum: int = 0       # 内容质量得分累计
    best_score: int = 0            # 历史最佳得分
    last_score: int = 0            # 最近一次得分
    avg_score: float = 0.0         # 平均内容得分
    consecutive_failures: int = 0  # 连续失败次数
    consecutive_successes: int = 0 # 连续成功次数
    tried_in_session: bool = False # 本次会话是否已尝试过

    @property
    def total_runs(self) -> int:
        return self.success + self.failure

    @property
    def success_rate(self) -> float:
        if self.total_runs == 0:
            return 0.5  # 未知引擎默认50%
        return self.success / self.total_runs

    @property
    def bypass_rate(self) -> float:
        if self.total_runs == 0:
            return 0.0
        return self.bypass / self.total_runs

    @property
    def avg_duration_ms(self) -> float:
        if self.success + self.failure == 0:
            return 0.0
        return self.total_duration_ms / max(self.total_runs, 1)


class EngineMonitor:
    """
    引擎监控器：统计各引擎表现，动态调整执行权重。
    """

    MAX_HISTORY = 100  # 每个引擎保留最近100条历史
    STATS_FILE = config.MONITOR_STATS_FILE

    def __init__(self):
        self._stats: Dict[str, EngineStats] = {}
        self._initialized = False
        self._load()

    def _load(self) -> None:
        """从磁盘加载统计数据"""
        if self.STATS_FILE.exists():
            try:
                data = json.loads(self.STATS_FILE.read_text(encoding='utf-8'))
                for name, sdata in data.get("engines", {}).items():
                    es = EngineStats(
                        name=name,
                        success=sdata.get("success", 0),
                        failure=sdata.get("failure", 0),
                        bypass=sdata.get("bypass", 0),
                        total_duration_ms=sdata.get("total_duration_ms", 0),
                        total_requests=sdata.get("total_requests", 0),
                        last_run=sdata.get("last_run", 0),
                        last_success=sdata.get("last_success", 0),
                        current_weight=sdata.get("current_weight",
                                       config.ENGINE_WEIGHTS.get(name, 50)),
                    )
                    # 只保留24小时内的历史
                    cutoff = time.time() - config.MONITOR_WINDOW_HOURS * 3600
                    es.history = [h for h in sdata.get("history", [])
                                  if h.get("ts", 0) > cutoff]
                    self._stats[name] = es
                self._initialized = True
                logger.info(f"加载监控数据: {len(self._stats)} 个引擎")
            except Exception as e:
                logger.warning(f"加载监控数据失败: {e}")
                self._init_defaults()
        else:
            self._init_defaults()

    def _init_defaults(self) -> None:
        """初始化默认引擎统计"""
        from engines import (RenderBypassEngine, CDNCacheEngine, APIEndpointScanner,
                            PartnerTokenEngine, SnapshotEngine, RenderDiffEngine,
                            ThirdPartyTokenEngine, OpenAPIEnumEngine,
                            SearchEngineCrawlerEngine, TokenHarvester)
        default_engines = [
            TokenHarvester,             # 权重60
            ThirdPartyTokenEngine,      # 权重90
            SearchEngineCrawlerEngine,  # 权重80
            RenderBypassEngine,         # 权重85
            CDNCacheEngine,             # 权重80
            OpenAPIEnumEngine,          # 权重75
            RenderDiffEngine,           # 权重70
            APIEndpointScanner,         # 权重60
            PartnerTokenEngine,         # 权重50
            SnapshotEngine,             # 权重40
        ]
        for eng_cls in default_engines:
            self._stats[eng_cls.name] = EngineStats(
                name=eng_cls.name,
                current_weight=eng_cls.default_weight,
            )
        self._initialized = True

    # _adjust_weight, record_result, get_engine_order 等方法已移至ZCCSA-Auto决策支持区块

    def get_stats(self) -> Dict[str, Any]:
        """获取所有引擎统计数据（用于报告）"""
        result = {
            "engines": {},
            "summary": {"total_engines": len(self._stats),
                        "total_runs": 0, "total_bypasses": 0},
        }
        for name, stats in self._stats.items():
            result["engines"][name] = {
                "success": stats.success,
                "failure": stats.failure,
                "bypass": stats.bypass,
                "success_rate": round(stats.success_rate, 3),
                "bypass_rate": round(stats.bypass_rate, 3),
                "avg_duration_ms": round(stats.avg_duration_ms, 0),
                "current_weight": round(stats.current_weight, 1),
                "last_run": stats.last_run,
                "last_success": stats.last_success,
            }
            result["summary"]["total_runs"] += stats.total_runs
            result["summary"]["total_bypasses"] += stats.bypass
        return result

    def set_weight(self, engine_name: str, weight: float) -> None:
        """手动设置引擎权重"""
        if engine_name in self._stats:
            self._stats[engine_name].current_weight = max(
                config.WEIGHT_MIN, min(config.WEIGHT_MAX, weight))
            self._save()

    def reset_stats(self, engine_name: Optional[str] = None) -> None:
        """重置统计数据"""
        if engine_name:
            if engine_name in self._stats:
                self._stats[engine_name] = EngineStats(
                    name=engine_name,
                    current_weight=config.ENGINE_WEIGHTS.get(engine_name, 50),
                )
        else:
            self._stats.clear()
            self._init_defaults()
        self._save()

    def _save(self) -> None:
        """持久化到磁盘"""
        try:
            data = {
                "saved_at": time.time(),
                "window_hours": config.MONITOR_WINDOW_HOURS,
                "engines": {name: asdict(stats) for name, stats in self._stats.items()},
            }
            self.STATS_FILE.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            logger.debug(f"保存监控数据失败: {e}")

    # ============================================================
    # ZCCSA-Auto 新增：决策支持方法
    # ============================================================

    def record_score(self, engine_name: str, score: int) -> None:
        """记录引擎返回内容的质量得分（0-100，来自validator）"""
        if engine_name not in self._stats:
            self._stats[engine_name] = EngineStats(name=engine_name)
        stats = self._stats[engine_name]
        stats.last_score = score
        stats.total_score_sum += score
        if score > stats.best_score:
            stats.best_score = score
        if stats.success + stats.failure > 0:
            stats.avg_score = stats.total_score_sum / (stats.success + stats.failure)
        self._save()

    def start_session(self) -> None:
        """开始新的审计会话，重置会话级状态"""
        for stats in self._stats.values():
            stats.tried_in_session = False

    def mark_tried(self, engine_name: str) -> None:
        """标记引擎在本次会话中已尝试过"""
        if engine_name in self._stats:
            self._stats[engine_name].tried_in_session = True

    def record_result(self, engine_name: str, success: bool,
                      bypass_found: bool = False,
                      duration_ms: float = 0.0,
                      request_count: int = 0,
                      error: str = "",
                      score: int = 0) -> None:
        """记录一次引擎运行结果（扩展版：支持score参数和连续失败跟踪）"""
        if engine_name not in self._stats:
            self._stats[engine_name] = EngineStats(name=engine_name)
        stats = self._stats[engine_name]
        now = time.time()

        if success:
            stats.success += 1
            stats.last_success = now
            stats.consecutive_successes += 1
            stats.consecutive_failures = 0
        else:
            stats.failure += 1
            stats.consecutive_failures += 1
            stats.consecutive_successes = 0

        if bypass_found:
            stats.bypass += 1

        # 记录得分
        if score > 0:
            stats.last_score = score
            stats.total_score_sum += score
            if score > stats.best_score:
                stats.best_score = score
            if stats.success + stats.failure > 0:
                stats.avg_score = stats.total_score_sum / (stats.success + stats.failure)

        stats.total_duration_ms += duration_ms
        stats.total_requests += request_count
        stats.last_run = now

        # 添加历史
        stats.history.append({
            "ts": now,
            "success": success,
            "bypass": bypass_found,
            "duration_ms": duration_ms,
            "score": score,
            "error": error[:100] if error else "",
        })
        if len(stats.history) > self.MAX_HISTORY:
            stats.history = stats.history[-self.MAX_HISTORY:]

        # 动态调整权重
        self._adjust_weight(engine_name, success, bypass_found, score)
        # 持久化
        self._save()

    def _adjust_weight(self, engine_name: str, success: bool,
                       bypass_found: bool, score: int = 0) -> None:
        """根据结果动态调整权重（增强版：考虑score）"""
        stats = self._stats[engine_name]
        w = stats.current_weight

        if bypass_found:
            # 发现绕过：权重大幅提升
            w *= config.WEIGHT_RECOVERY_FACTOR ** 2
            if score >= 90:
                w *= 1.2  # 高质量内容额外奖励
        elif success and score >= 90:
            w *= config.WEIGHT_RECOVERY_FACTOR ** 1.5
        elif success:
            w *= config.WEIGHT_RECOVERY_FACTOR
        elif stats.consecutive_failures >= 3:
            # 连续失败3次以上，加速衰减
            w *= config.WEIGHT_DECAY_FACTOR ** 2
        else:
            w *= config.WEIGHT_DECAY_FACTOR

        w = max(config.WEIGHT_MIN, min(config.WEIGHT_MAX, w))
        stats.current_weight = w

    def get_engine_order(self, exclude_tried: bool = False) -> List[str]:
        """
        获取按权重降序排列的引擎名称列表
        :param exclude_tried: 排除本次会话已尝试过的引擎
        """
        scored = []
        for name, stats in self._stats.items():
            if exclude_tried and stats.tried_in_session:
                continue
            # 综合评分
            score = stats.current_weight
            score += stats.success_rate * 30
            score += stats.bypass_rate * 100
            score += stats.avg_score * 0.3  # 历史平均得分
            if stats.best_score >= 90:
                score += 20  # 曾经获得过高分，优先
            if stats.avg_duration_ms > 10000:
                score -= 20
            if stats.consecutive_failures >= 2:
                score -= 15  # 连续失败惩罚
            scored.append((name, score))

        scored.sort(key=lambda x: -x[1])
        return [name for name, _ in scored]

    def get_next_engine(self, exclude_tried: bool = True) -> Optional[str]:
        """获取推荐的下一个要执行的引擎"""
        order = self.get_engine_order(exclude_tried=exclude_tried)
        return order[0] if order else None

    def get_decision_snapshot(self) -> Dict[str, Any]:
        """获取当前决策快照（供orchestrator思考日志使用）"""
        snapshot = {
            "engines": {},
            "untried": [],
            "tried": [],
            "best_engine": None,
            "best_score": 0,
            "recommendation": "",
        }
        best_name = None
        best_score = 0
        for name, stats in self._stats.items():
            s = {
                "weight": round(stats.current_weight, 1),
                "success_rate": round(stats.success_rate, 2),
                "bypass_rate": round(stats.bypass_rate, 2),
                "best_score": stats.best_score,
                "last_score": stats.last_score,
                "consecutive_failures": stats.consecutive_failures,
                "tried": stats.tried_in_session,
                "avg_duration_ms": round(stats.avg_duration_ms, 0),
            }
            snapshot["engines"][name] = s
            if stats.tried_in_session:
                snapshot["tried"].append(name)
            else:
                snapshot["untried"].append(name)
            if stats.best_score > best_score:
                best_score = stats.best_score
                best_name = name

        snapshot["best_engine"] = best_name
        snapshot["best_score"] = best_score

        # 生成建议
        if best_score >= 90:
            snapshot["recommendation"] = "found_complete_content"
        elif not snapshot["untried"]:
            snapshot["recommendation"] = "all_engines_exhausted"
        elif best_score >= 70:
            snapshot["recommendation"] = "partial_content_found_try_others"
        else:
            snapshot["recommendation"] = "continue_probing"

        return snapshot

    def boost_engine(self, engine_name: str, factor: float = 1.5) -> None:
        """手动提升某个引擎的权重（orchestrator决策使用）"""
        if engine_name in self._stats:
            w = self._stats[engine_name].current_weight
            self._stats[engine_name].current_weight = min(
                config.WEIGHT_MAX, w * factor)
            self._save()

    def suppress_engine(self, engine_name: str, factor: float = 0.5) -> None:
        """手动降低某个引擎的权重"""
        if engine_name in self._stats:
            w = self._stats[engine_name].current_weight
            self._stats[engine_name].current_weight = max(
                config.WEIGHT_MIN, w * factor)
            self._save()


# 全局单例
_monitor_instance: Optional[EngineMonitor] = None


def get_monitor() -> EngineMonitor:
    """获取全局监控器单例"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = EngineMonitor()
    return _monitor_instance
