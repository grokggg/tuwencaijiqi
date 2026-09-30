# -*- coding: utf-8 -*-
"""
ZPE vNext - 引擎基类
所有攻击引擎继承此类
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config
from core.http_client import HttpClient, cn_count
from core.parser import ContentParser


@dataclass
class EngineResult:
    """引擎执行结果"""
    engine_name: str
    success: bool = False
    bypass_found: bool = False
    bypass_method: str = ""
    content: str = ""
    title: str = ""
    source_url: str = ""
    word_count: int = 0
    confidence: float = 0.0
    chapters: List[Tuple[str, str]] = field(default_factory=list)
    discovered_urls: List[str] = field(default_factory=list)
    error: str = ""
    details: Dict[str, Any] = field(default_factory=dict)


class BaseEngine(ABC):
    """引擎基类"""
    
    name: str = "base"
    description: str = ""
    priority: int = 50  # 1-100，越高越先执行
    
    def __init__(self, http_client: HttpClient, parser: ContentParser):
        self.http = http_client
        self.parser = parser
        self.logger = logging.getLogger(f"engine.{self.name}")
        self.learnings: Dict[str, Any] = {}  # 学习到的经验
    
    @abstractmethod
    async def run(self, context: Dict[str, Any]) -> EngineResult:
        """
        执行引擎
        context: 包含目标信息、之前引擎的结果等
        """
        pass
    
    def update_learnings(self, key: str, value: Any):
        """更新学习经验"""
        self.learnings[key] = value
    
    def create_result(self) -> EngineResult:
        """创建结果对象"""
        return EngineResult(engine_name=self.name)
