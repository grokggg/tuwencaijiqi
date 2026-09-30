# -*- coding: utf-8 -*-
"""
ZCCSA 探测引擎基类
所有探测引擎都继承自此基类，统一接口规范。
"""
import asyncio
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from core.parser import ExtractedContent


@dataclass
class EngineResult:
    """引擎探测结果"""
    engine_name: str                           # 引擎名称
    success: bool = False                      # 是否成功获取有效内容
    content: Optional[ExtractedContent] = None # 提取的内容
    bypass_found: bool = False                 # 是否发现付费墙绕过
    bypass_method: str = ""                    # 绕过方法描述
    details: Dict[str, Any] = field(default_factory=dict)  # 详细信息
    duration_ms: float = 0.0                   # 耗时（毫秒）
    url_tested: str = ""                       # 实际测试的URL
    request_count: int = 0                     # 发起的请求数
    error: str = ""                            # 错误信息

    def to_dict(self) -> Dict:
        return {
            "engine": self.engine_name,
            "success": self.success,
            "bypass_found": self.bypass_found,
            "bypass_method": self.bypass_method,
            "duration_ms": self.duration_ms,
            "request_count": self.request_count,
            "content_summary": self.content.to_dict() if self.content else None,
            "error": self.error,
        }


class BaseEngine(ABC):
    """探测引擎抽象基类"""

    name: str = "base_engine"
    description: str = "基类引擎"
    default_weight: int = 50

    def __init__(self, session_manager=None, parser=None, cookie_file: Optional[str] = None):
        self.logger = logging.getLogger(f"zccsa.engine.{self.name}")
        self._session = session_manager
        self._parser = parser
        self._cookie_file = cookie_file
        self._request_count = 0
        self._start_time: float = 0

    async def run(self, url: str, article_id: Optional[Dict] = None) -> EngineResult:
        """
        运行引擎（模板方法）
        :param url: 目标URL
        :param article_id: 解析后的文章ID信息
        """
        self._start_time = time.time()
        self._request_count = 0
        result = EngineResult(engine_name=self.name, url_tested=url)

        try:
            self.logger.info(f"[{self.name}] 开始探测: {url[:80]}")
            result = await self._probe(url, article_id or {}, result)
        except asyncio.TimeoutError:
            result.error = "探测超时"
            self.logger.warning(f"[{self.name}] 探测超时")
        except Exception as e:
            result.error = f"{type(e).__name__}: {str(e)[:200]}"
            self.logger.error(f"[{self.name}] 探测异常: {e}", exc_info=True)
        finally:
            result.duration_ms = (time.time() - self._start_time) * 1000
            result.request_count = self._request_count
            self.logger.info(
                f"[{self.name}] 完成: success={result.success} "
                f"bypass={result.bypass_found} "
                f"duration={result.duration_ms:.0f}ms "
                f"requests={result.request_count}"
            )
        return result

    @abstractmethod
    async def _probe(self, url: str, article_id: Dict,
                     result: EngineResult) -> EngineResult:
        """
        探测逻辑（子类实现）
        """
        raise NotImplementedError

    def _increment_requests(self) -> None:
        """请求计数+1"""
        self._request_count += 1

    def _get_session(self):
        """获取会话管理器（懒加载）"""
        if self._session is None:
            from core.session_manager import SessionManager
            self._session = SessionManager(cookie_file=self._cookie_file)
        return self._session

    def _get_parser(self):
        """获取内容解析器（懒加载）"""
        if self._parser is None:
            from core.parser import ContentParser
            self._parser = ContentParser()
        return self._parser

    @staticmethod
    def _is_complete_content(content: Optional[ExtractedContent]) -> bool:
        """判断内容是否足够完整"""
        if not content:
            return False
        return (not content.is_truncated and
                content.char_count >= 500 and
                content.word_count_cn >= 300)

    @staticmethod
    def _is_significant_content(content: Optional[ExtractedContent]) -> bool:
        """判断是否为有意义的内容（至少超过阈值）"""
        if not content:
            return False
        return content.word_count_cn >= 200

    # ============================================================
    # ZCCSA-Auto: 统一返回格式 (content, metadata)
    # ============================================================
    async def execute(self, url: str, article_id: Optional[Dict] = None
                      ) -> Tuple[Optional[ExtractedContent], Dict[str, Any]]:
        """
        执行引擎探测，返回统一格式 (content, metadata)
        这是ZCCSA-Auto orchestrator使用的标准接口。
        :param url: 目标URL
        :param article_id: 解析后的文章ID信息
        :return: (ExtractedContent或None, 元数据字典)
            metadata 包含:
                - engine_name: 引擎名称
                - success: bool
                - bypass_found: bool
                - bypass_method: str
                - duration_ms: float
                - request_count: int
                - error: str
                - details: dict (引擎特定详情)
        """
        result = await self.run(url, article_id)
        metadata = {
            "engine_name": result.engine_name,
            "success": result.success,
            "bypass_found": result.bypass_found,
            "bypass_method": result.bypass_method,
            "duration_ms": result.duration_ms,
            "request_count": result.request_count,
            "error": result.error,
            "details": result.details,
            "url_tested": result.url_tested,
        }
        return result.content, metadata
