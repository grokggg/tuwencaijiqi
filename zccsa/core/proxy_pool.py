# -*- coding: utf-8 -*-
"""
ZCCSA 代理IP池管理与轮换
- 支持从文件加载代理列表
- 支持健康检查和失败剔除
- 按权重/成功率轮换
"""
import logging
import random
import time
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
import config

logger = logging.getLogger(__name__)


@dataclass
class ProxyEntry:
    """代理条目"""
    url: str
    protocol: str = "http"  # http / https / socks5
    success: int = 0
    failure: int = 0
    last_used: float = 0.0
    avg_latency: float = 0.0
    cooldown_until: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success + self.failure
        return self.success / total if total > 0 else 0.5

    @property
    def is_available(self) -> bool:
        return time.time() >= self.cooldown_until


class ProxyPool:
    """代理IP池"""

    def __init__(self, proxy_file: Optional[str] = None):
        self._proxies: List[ProxyEntry] = []
        self._current_idx: int = 0
        if proxy_file:
            self.load_from_file(proxy_file)

    def load_from_file(self, filepath: str) -> int:
        """
        从文件加载代理列表，支持格式：
        - http://user:pass@host:port
        - host:port
        - socks5://host:port
        返回加载数量
        """
        path = Path(filepath)
        if not path.exists():
            logger.warning(f"代理文件不存在: {filepath}")
            return 0
        loaded = 0
        for line in path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            entry = self._parse_proxy_line(line)
            if entry:
                self._proxies.append(entry)
                loaded += 1
        logger.info(f"从 {filepath} 加载了 {loaded} 个代理")
        return loaded

    def _parse_proxy_line(self, line: str) -> Optional[ProxyEntry]:
        """解析单行代理配置"""
        line = line.strip()
        protocol = "http"
        if line.startswith("socks5://"):
            protocol = "socks5"
        elif line.startswith("https://"):
            protocol = "https"
        elif line.startswith("http://"):
            protocol = "http"
        elif "://" not in line:
            line = f"http://{line}"
        # 简单校验格式
        if "://" in line:
            return ProxyEntry(url=line, protocol=protocol)
        return None

    def add_proxy(self, url: str, protocol: str = "http") -> None:
        """手动添加代理"""
        self._proxies.append(ProxyEntry(url=url, protocol=protocol))

    def get_proxy(self, strategy: str = "random") -> Optional[ProxyEntry]:
        """
        获取一个可用代理
        :param strategy: random / round_robin / best_rate
        """
        available = [p for p in self._proxies if p.is_available]
        if not available:
            return None

        if strategy == "random":
            return random.choice(available)
        elif strategy == "round_robin":
            proxy = available[self._current_idx % len(available)]
            self._current_idx += 1
            return proxy
        elif strategy == "best_rate":
            return max(available, key=lambda p: (p.success_rate, -p.avg_latency))
        else:
            return random.choice(available)

    def mark_success(self, proxy_url: str, latency: float = 0) -> None:
        """标记代理使用成功"""
        for p in self._proxies:
            if p.url == proxy_url:
                p.success += 1
                p.last_used = time.time()
                if latency > 0:
                    if p.avg_latency == 0:
                        p.avg_latency = latency
                    else:
                        p.avg_latency = p.avg_latency * 0.7 + latency * 0.3
                return

    def mark_failure(self, proxy_url: str) -> None:
        """标记代理使用失败，触发冷却"""
        for p in self._proxies:
            if p.url == proxy_url:
                p.failure += 1
                p.last_used = time.time()
                # 连续失败则加长冷却时间
                recent_failures = min(p.failure, 5)
                p.cooldown_until = time.time() + (30 * (2 ** recent_failures))
                return

    @property
    def size(self) -> int:
        return len(self._proxies)

    @property
    def available_count(self) -> int:
        return sum(1 for p in self._proxies if p.is_available)

    def get_stats(self) -> Dict:
        """获取代理池统计"""
        return {
            "total": len(self._proxies),
            "available": self.available_count,
            "by_protocol": {
                proto: sum(1 for p in self._proxies if p.protocol == proto)
                for proto in ["http", "https", "socks5"]
            }
        }
