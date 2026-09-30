#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ZPE vNext - 知乎付费内容提取工具 vNext
主入口文件
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from orchestrator import main

if __name__ == "__main__":
    asyncio.run(main())
