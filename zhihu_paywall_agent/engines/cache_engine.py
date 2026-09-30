# -*- coding: utf-8 -*-
"""
cache_engine.py - 缓存引擎

基于URL和文章ID的本地缓存，避免重复请求。
使用JSON格式存储，支持过期时间。
"""
import json
import logging
import time
import hashlib
from typing import Optional, Dict
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

import config
from core.parser import ParsedContent, extract_article_id

logger = logging.getLogger(__name__)


class CacheEngine:
    """
    缓存引擎。优先检查本地缓存，如果存在且未过期则直接返回。
    """

    name = "cache_engine"

    def __init__(self, cache_dir: Optional[Path] = None, ttl_hours: int = 72):
        self.cache_dir = cache_dir or config.CACHE_DIR
        self.ttl_seconds = ttl_hours * 3600
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _cache_key(self, url: str, ids: Dict[str, str]) -> str:
        """生成缓存键"""
        # 优先用文章ID
        for key in ["article_id", "section_id", "answer_id", "post_id", "share_code"]:
            if ids.get(key):
                return f"{key}_{ids[key]}"
        # 用URL的hash
        return "url_" + hashlib.md5(url.encode()).hexdigest()

    def _cache_path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    async def fetch(self, url: str) -> Optional[ParsedContent]:
        """从缓存读取内容"""
        ids = extract_article_id(url)
        key = self._cache_key(url, ids)
        path = self._cache_path(key)

        if not path.exists():
            logger.debug(f"缓存未命中: {key}")
            return None

        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached_time = data.get("cached_at", 0)

            # 检查过期
            if time.time() - cached_time > self.ttl_seconds:
                logger.debug(f"缓存已过期: {key}")
                path.unlink(missing_ok=True)
                return None

            content = ParsedContent(
                title=data.get("title", ""),
                author=data.get("author", ""),
                content_html=data.get("content_html", ""),
                content_markdown=data.get("content_markdown", ""),
                images=data.get("images", []),
                original_url=data.get("original_url", url),
                platform=data.get("platform", ""),
                is_truncated=data.get("is_truncated", True),
                content_length=data.get("content_length", 0),
            )

            if content.content_length >= config.MIN_CONTENT_LENGTH:
                logger.info(f"缓存命中: {key} ({content.content_length}字)")
                return content
            else:
                logger.debug(f"缓存内容不完整: {key}")
                return None

        except Exception as e:
            logger.warning(f"读取缓存失败: {e}")
            return None

    def save(self, url: str, content: ParsedContent):
        """保存内容到缓存"""
        ids = extract_article_id(url)
        key = self._cache_key(url, ids)
        path = self._cache_path(key)

        try:
            data = {
                "title": content.title,
                "author": content.author,
                "content_html": content.content_html,
                "content_markdown": content.content_markdown,
                "images": content.images,
                "original_url": content.original_url or url,
                "platform": content.platform,
                "is_truncated": content.is_truncated,
                "content_length": content.content_length,
                "cached_at": time.time(),
            }
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug(f"缓存已保存: {key}")
        except Exception as e:
            logger.warning(f"保存缓存失败: {e}")

    def clear(self, url: str = None):
        """清除缓存"""
        if url:
            ids = extract_article_id(url)
            key = self._cache_key(url, ids)
            path = self._cache_path(key)
            path.unlink(missing_ok=True)
        else:
            for f in self.cache_dir.glob("*.json"):
                f.unlink()
            logger.info("已清除所有缓存")

    def get_stats(self) -> Dict:
        """获取缓存统计"""
        files = list(self.cache_dir.glob("*.json"))
        total_size = sum(f.stat().st_size for f in files)
        return {
            "cache_count": len(files),
            "total_size_bytes": total_size,
            "cache_dir": str(self.cache_dir),
        }
