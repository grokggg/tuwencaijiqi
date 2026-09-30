# -*- coding: utf-8 -*-
"""
monitor.py - 引擎成功率监控与自适应权重

记录各引擎的成功/失败/耗时统计，实时计算成功率，
调度中心据此动态调整引擎执行顺序。
"""
import json
import time
import logging
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field, asdict
from collections import defaultdict

import config

logger = logging.getLogger(__name__)


@dataclass
class EngineStats:
    """单个引擎的统计数据"""
    name: str
    success_count: int = 0
    fail_count: int = 0
    total_time: float = 0.0  # 总耗时（秒）
    last_success: float = 0.0
    last_failure: float = 0.0
    last_error: str = ""
    weight: float = 100.0

    @property
    def total_count(self) -> int:
        return self.success_count + self.fail_count

    @property
    def success_rate(self) -> float:
        if self.total_count == 0:
            return self.weight / 100.0  # 初始值
        return self.success_count / self.total_count

    @property
    def avg_time(self) -> float:
        if self.success_count == 0:
            return float('inf')
        return self.total_time / self.success_count


class Monitor:
    """
    引擎监控器。
    维护各引擎统计，支持JSON持久化，提供成功率驱动的权重排序。
    """

    def __init__(self, stats_file: Optional[Path] = None):
        self.stats_file = stats_file or config.MONITOR_FILE
        self._stats: Dict[str, EngineStats] = {}
        self._lock = threading.Lock()
        self._load()

    def _load(self):
        """从文件加载统计数据"""
        if self.stats_file.exists():
            try:
                data = json.loads(self.stats_file.read_text(encoding="utf-8"))
                for name, stats in data.items():
                    self._stats[name] = EngineStats(
                        name=name,
                        success_count=stats.get("success_count", 0),
                        fail_count=stats.get("fail_count", 0),
                        total_time=stats.get("total_time", 0.0),
                        last_success=stats.get("last_success", 0.0),
                        last_failure=stats.get("last_failure", 0.0),
                        last_error=stats.get("last_error", ""),
                        weight=stats.get("weight", config.ENGINE_INITIAL_WEIGHTS.get(name, 50.0)),
                    )
                logger.info(f"加载监控数据: {len(self._stats)} 个引擎")
            except Exception as e:
                logger.warning(f"加载监控数据失败: {e}")

        # 初始化缺失的引擎
        for name, init_weight in config.ENGINE_INITIAL_WEIGHTS.items():
            if name not in self._stats:
                self._stats[name] = EngineStats(name=name, weight=init_weight)

    def _save(self):
        """保存统计数据到文件"""
        try:
            data = {name: {
                "success_count": s.success_count,
                "fail_count": s.fail_count,
                "total_time": s.total_time,
                "last_success": s.last_success,
                "last_failure": s.last_failure,
                "last_error": s.last_error,
                "weight": s.weight,
            } for name, s in self._stats.items()}
            self.stats_file.parent.mkdir(parents=True, exist_ok=True)
            self.stats_file.write_text(
                json.dumps(data, indent=2, ensure_ascii=False),
                encoding="utf-8"
            )
        except Exception as e:
            logger.warning(f"保存监控数据失败: {e}")

    def record_success(self, engine_name: str, elapsed: float):
        """记录一次成功"""
        with self._lock:
            if engine_name not in self._stats:
                init_w = config.ENGINE_INITIAL_WEIGHTS.get(engine_name, 50.0)
                self._stats[engine_name] = EngineStats(name=engine_name, weight=init_w)
            s = self._stats[engine_name]
            s.success_count += 1
            s.total_time += elapsed
            s.last_success = time.time()
            # 成功时略微提升权重
            s.weight = min(s.weight * 1.05, 150.0)
            self._save()
            logger.info(f"[{engine_name}] 成功 (耗时{elapsed:.1f}s, 成功率{s.success_rate:.0%})")

    def record_failure(self, engine_name: str, error: str = "", elapsed: float = 0.0):
        """记录一次失败"""
        with self._lock:
            if engine_name not in self._stats:
                init_w = config.ENGINE_INITIAL_WEIGHTS.get(engine_name, 50.0)
                self._stats[engine_name] = EngineStats(name=engine_name, weight=init_w)
            s = self._stats[engine_name]
            s.fail_count += 1
            s.last_failure = time.time()
            s.last_error = error[:200] if error else ""
            # 失败时降低权重
            s.weight *= config.WEIGHT_DECAY
            if s.success_rate < config.MIN_SUCCESS_RATE and s.total_count > 5:
                s.weight *= 0.5  # 成功率过低时大幅降权
            self._save()
            logger.info(f"[{engine_name}] 失败: {error[:80]} (成功率{s.success_rate:.0%})")

    def get_ranked_engines(self) -> List[Tuple[str, float]]:
        """
        按有效权重（成功率 × 基础权重 / 平均耗时因子）排序引擎。
        返回 [(engine_name, effective_weight), ...] 按权重降序。
        """
        with self._lock:
            ranked = []
            for name, s in self._stats.items():
                # 有效权重 = 基础权重 × 成功率 × 速度因子
                rate = s.success_rate if s.total_count > 0 else 0.5
                speed_factor = 1.0
                if s.avg_time < float('inf'):
                    speed_factor = min(5.0, 10.0 / max(s.avg_time, 1.0))
                effective = s.weight * rate * speed_factor
                ranked.append((name, effective))

            ranked.sort(key=lambda x: x[1], reverse=True)
            return ranked

    def get_stats(self, engine_name: str) -> Optional[EngineStats]:
        """获取指定引擎的统计"""
        return self._stats.get(engine_name)

    def get_all_stats(self) -> Dict[str, EngineStats]:
        return dict(self._stats)

    def reset_stats(self, engine_name: Optional[str] = None):
        """重置统计数据"""
        with self._lock:
            if engine_name:
                if engine_name in self._stats:
                    init_w = config.ENGINE_INITIAL_WEIGHTS.get(engine_name, 50.0)
                    self._stats[engine_name] = EngineStats(name=engine_name, weight=init_w)
            else:
                for name in list(self._stats.keys()):
                    init_w = config.ENGINE_INITIAL_WEIGHTS.get(name, 50.0)
                    self._stats[name] = EngineStats(name=name, weight=init_w)
            self._save()

    def summary(self) -> str:
        """生成统计摘要字符串"""
        lines = ["=== 引擎监控摘要 ==="]
        for name, weight in self.get_ranked_engines():
            s = self._stats.get(name)
            if s:
                lines.append(
                    f"  {name:25s} | 权重={weight:6.1f} | "
                    f"成功率={s.success_rate:.0%} ({s.success_count}/{s.total_count}) | "
                    f"平均耗时={s.avg_time:.1f}s"
                )
        return "\n".join(lines)
