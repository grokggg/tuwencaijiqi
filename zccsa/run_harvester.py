# -*- coding: utf-8 -*-
"""
独立运行Token Harvester V2 - 全自动逆向采集
"""
import asyncio
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(name)s] %(levelname)s: %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)

sys.path.insert(0, str(Path(__file__).parent))

from engines.token_harvester import TokenHarvesterV2 as TokenHarvester, HARVESTED_TOKENS_FILE


async def main():
    print("=" * 60)
    print("ZCCSA Token Harvester V2 - 全自动逆向采集")
    print("=" * 60)
    print()

    harvester = TokenHarvester()

    # 检查可选依赖
    pw = "可用" if harvester._playwright_available else "未安装（pip install playwright && playwright install chromium）"
    ag = "可用" if harvester._androguard_available else "未安装（pip install androguard）"
    print(f"  Playwright动态分析: {pw}")
    print(f"  Androguard反编译: {ag}")
    print()

    # 执行完整采集
    content, metadata = await harvester.execute("")

    print()
    print("=" * 60)
    print("采集完成！")
    print(f"  成功: {metadata['success']}")
    print(f"  耗时: {metadata['duration_ms']:.0f}ms")
    print(f"  请求数: {metadata['request_count']}")
    details = metadata.get('details', {})
    print(f"  Token总数: {details.get('total_tokens', 0)}")
    print(f"  本次新增: {details.get('new_tokens', 0)}")
    print(f"  经验证有效: {details.get('validated_tokens', 0)}")
    print(f"  版本: {details.get('version', 'v2')}")
    print(f"  输出文件: {details.get('output_file', '')}")
    if details.get('sources_searched'):
        print("  采集渠道:")
        for src in details['sources_searched']:
            print(f"    - {src}")
    print()

    if content:
        print("-" * 60)
        print(content.content_text)
        print("-" * 60)

    # 读取保存的文件确认
    if HARVESTED_TOKENS_FILE.exists():
        import json
        tokens = json.loads(HARVESTED_TOKENS_FILE.read_text(encoding='utf-8'))
        validated = [t for t in tokens if t.get('validated')]
        print(f"\n已保存 {len(tokens)} 个候选Token到 {HARVESTED_TOKENS_FILE}")
        print(f"其中经验证有效: {len(validated)} 个")
        if validated:
            print("\n*** 有效Token预览:")
            for i, t in enumerate(validated[:5]):
                vi = t.get('validation_info', {})
                print(f"  {i+1}. [{t['source']}] {t['token'][:16]}... "
                      f"({vi.get('cn_words', 0)}字 via {vi.get('header', '')})")


if __name__ == "__main__":
    asyncio.run(main())
