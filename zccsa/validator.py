# -*- coding: utf-8 -*-
"""
ZCCSA-Auto 内容完整性验证器
- 对提取的内容进行0-100分自动打分
- 多维度评估：字数、段落结构、截断标记、内容连贯性、标题匹配度
- 90分以上判定为完整内容
"""
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import config
from core.parser import ExtractedContent

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """内容验证结果"""
    score: int = 0                  # 0-100总分
    passed: bool = False            # 是否达到成功阈值(>=90)
    dimensions: Dict[str, int] = field(default_factory=dict)  # 各维度得分
    issues: List[str] = field(default_factory=list)           # 发现的问题
    strengths: List[str] = field(default_factory=list)        # 亮点
    truncation_likelihood: float = 0.0  # 截断概率 0-1
    content_quality: str = "unknown"    # poor / partial / good / excellent
    recommendation: str = ""            # 对orchestrator的建议

    def to_dict(self) -> Dict:
        return {
            "score": self.score,
            "passed": self.passed,
            "dimensions": self.dimensions,
            "issues": self.issues,
            "strengths": self.strengths,
            "truncation_likelihood": round(self.truncation_likelihood, 2),
            "content_quality": self.content_quality,
            "recommendation": self.recommendation,
        }


class ContentValidator:
    """
    内容完整性自动打分器
    评分维度（总分100）：
      1. 字数规模       0-30分  （中文字数）
      2. 段落结构       0-15分  （段落数量、段落长度分布）
      3. 截断标记       0-20分  （付费墙/截断词检测，扣分制）
      4. 内容连贯性     0-15分  （对话完整性、句末标点、段落衔接）
      5. 标题匹配度     0-10分  （标题关键词在正文中的出现）
      6. 结构完整性     0-10分  （开头/结尾完整性、是否有结局感）
    """

    PASS_THRESHOLD = 90

    # 强截断标记（出现即大量扣分）
    STRONG_TRUNCATION_MARKERS = [
        "购买专栏", "解锁全文", "开通盐选", "开通会员", "Salt",
        "付费后", "查看剩余", "订阅后", "登录后查看",
        r"剩余\d+%", r"剩余\d+字", "展开全文", "查看全文",
    ]

    # 弱截断标记（出现即扣分）
    WEAK_TRUNCATION_MARKERS = [
        "盐选", "专栏", "会员免费", "VIP", "vip",
        "试读", "预览", "精彩继续", "下章更精彩",
        "未完待续", "本章未完", "加载中", "点击下一页",
        "广告", "AD", "推广", "相关推荐", "热门推荐",
    ]

    # 好结局/完整结尾标记
    ENDING_MARKERS = [
        "全文完", "大结局", "完结", "（完）", "(完)", "——完——",
        "尾声", "番外", "后记", "The End", "结局",
    ]

    # 故事开头标记
    BEGINNING_MARKERS = [
        "第一章", "第1章", "Chapter 1", "楔子", "序章", "前言",
        "我叫", "我是", "我叫", "我是个", "我是一个", "故事开始",
    ]

    def __init__(self):
        self.logger = logging.getLogger("zccsa.validator")

    def validate(self, content: Optional[ExtractedContent],
                 expected_title: str = "",
                 baseline_content: Optional[ExtractedContent] = None) -> ValidationResult:
        """
        对内容进行完整性打分
        :param content: 待评估的内容
        :param expected_title: 期望的文章标题（用于标题匹配度评分）
        :param baseline_content: 基线截断内容（用于对比增量）
        """
        result = ValidationResult()

        if not content or not content.content_text:
            result.score = 0
            result.passed = False
            result.issues.append("内容为空")
            result.content_quality = "poor"
            result.recommendation = "continue_probing"
            return result

        text = content.content_text
        cn_words = content.word_count_cn
        paragraphs = content.paragraphs

        # ========== 维度1：字数规模 (0-30分) ==========
        dim1 = self._score_length(cn_words, baseline_content)
        result.dimensions["word_count"] = dim1
        if dim1 < 15:
            result.issues.append(f"字数不足（{cn_words}中文字）")

        # ========== 维度2：段落结构 (0-15分) ==========
        dim2 = self._score_paragraph_structure(text, paragraphs)
        result.dimensions["paragraph_structure"] = dim2
        if dim2 < 8:
            result.issues.append("段落结构异常")

        # ========== 维度3：截断标记 (0-20分，扣分制) ==========
        dim3 = self._score_truncation_markers(text)
        result.dimensions["truncation_markers"] = dim3
        if dim3 < 10:
            result.issues.append("检测到付费截断标记")

        # ========== 维度4：内容连贯性 (0-15分) ==========
        dim4 = self._score_coherence(text)
        result.dimensions["coherence"] = dim4
        if dim4 < 8:
            result.issues.append("内容连贯性不足（可能被截断在句子中间）")

        # ========== 维度5：标题匹配度 (0-10分) ==========
        dim5 = self._score_title_match(text, expected_title, content.title)
        result.dimensions["title_match"] = dim5
        if dim5 < 5 and expected_title:
            result.issues.append("标题关键词未在正文中充分出现")

        # ========== 维度6：结构完整性 (0-10分) ==========
        dim6 = self._score_structural_integrity(text)
        result.dimensions["structural_integrity"] = dim6
        if dim6 < 5:
            result.issues.append("内容结构不完整（缺少开头或结尾）")

        # ========== 汇总计算 ==========
        total = dim1 + dim2 + dim3 + dim4 + dim5 + dim6
        result.score = min(100, max(0, total))

        # 亮点检测
        if dim1 >= 25:
            result.strengths.append(f"字数充分（{cn_words}字）")
        if dim3 >= 18:
            result.strengths.append("无明显截断标记")
        if dim6 >= 8:
            result.strengths.append("结构完整，有明确结尾")
        if dim4 >= 12:
            result.strengths.append("段落衔接流畅")

        # 截断概率
        result.truncation_likelihood = self._estimate_truncation_probability(
            text, cn_words, dim3, dim4, dim6
        )

        # 质量等级
        if result.score >= 90:
            result.content_quality = "excellent"
            result.passed = True
            result.recommendation = "stop_success"
        elif result.score >= 70:
            result.content_quality = "good"
            result.passed = False
            result.recommendation = "try_more_engines"
        elif result.score >= 40:
            result.content_quality = "partial"
            result.passed = False
            result.recommendation = "continue_probing"
        else:
            result.content_quality = "poor"
            result.passed = False
            result.recommendation = "skip_to_next"

        self.logger.debug(
            f"验证完成: score={result.score} "
            f"dimensions={result.dimensions} "
            f"quality={result.content_quality}"
        )
        return result

    def _score_length(self, cn_words: int,
                      baseline: Optional[ExtractedContent]) -> int:
        """字数评分 (0-30)"""
        if cn_words >= 5000:
            base = 30
        elif cn_words >= 3000:
            base = 27
        elif cn_words >= 2000:
            base = 24
        elif cn_words >= 1000:
            base = 20
        elif cn_words >= 500:
            base = 15
        elif cn_words >= 300:
            base = 10
        elif cn_words >= 100:
            base = 5
        else:
            return 0

        # 如果有基线且字数大幅超过基线，额外加分
        if baseline and baseline.word_count_cn > 0:
            ratio = cn_words / max(baseline.word_count_cn, 1)
            if ratio >= 3:
                base = min(30, base + 3)
            elif ratio >= 2:
                base = min(30, base + 1)

        return base

    def _score_paragraph_structure(self, text: str, paragraphs: int) -> int:
        """段落结构评分 (0-15)"""
        if paragraphs == 0:
            return 0
        score = 0
        # 段落数量
        if paragraphs >= 20:
            score += 6
        elif paragraphs >= 10:
            score += 5
        elif paragraphs >= 5:
            score += 3
        elif paragraphs >= 3:
            score += 2
        else:
            score += 1

        # 段落长度分布（检查是否有合理的长短段落交替）
        lines = [l.strip() for l in text.split('\n') if l.strip()]
        if lines:
            lengths = [len(l) for l in lines if re.search(r'[\u4e00-\u9fff]', l)]
            if lengths:
                avg_len = sum(lengths) / len(lengths)
                # 平均段落长度在15-100字之间（正常叙事节奏）
                if 15 <= avg_len <= 100:
                    score += 5
                elif 10 <= avg_len <= 150:
                    score += 3
                else:
                    score += 1

                # 长短变化（非全是短行或全是长段）
                if len(lengths) >= 3:
                    short = sum(1 for l in lengths if l < 20)
                    long = sum(1 for l in lengths if l > 50)
                    if short > 0 and long > 0:
                        score += 4  # 有对话有描写，节奏正常
                    elif short > len(lengths) * 0.8:
                        score += 1  # 全是对话，可能是诗歌/剧本
                    else:
                        score += 2

        return min(15, score)

    def _score_truncation_markers(self, text: str) -> int:
        """截断标记评分 (0-20，起始20分，每发现标记扣分)"""
        score = 20
        text_lower = text[-2000:]  # 重点检查末尾区域

        # 强标记：每个扣8分
        for marker in self.STRONG_TRUNCATION_MARKERS:
            if re.search(marker, text_lower, re.I):
                score -= 8
                self.logger.debug(f"  强截断标记: {marker}")

        # 弱标记：每个扣3分
        for marker in self.WEAK_TRUNCATION_MARKERS:
            if marker in text_lower:
                score -= 3
                self.logger.debug(f"  弱截断标记: {marker}")

        # HTML标签残留（解析不完整标志）
        if re.search(r'<[a-z]+[^>]*>', text[-500:]):
            score -= 5

        # 末尾是省略号或半截话
        last_50 = text.strip()[-50:] if text.strip() else ""
        if re.search(r'[…，、]$', last_50) or last_50.endswith("..."):
            score -= 3

        return max(0, score)

    def _score_coherence(self, text: str) -> int:
        """内容连贯性评分 (0-15)"""
        score = 0
        if not text:
            return 0

        # 检查句末标点比例
        sentences = re.split(r'[。！？…\n]+', text)
        sentences = [s.strip() for s in sentences if len(s.strip()) > 5]
        if not sentences:
            return 3

        # 句子平均长度（过短说明碎片化，过长说明连在一起）
        avg_sentence_len = sum(len(s) for s in sentences) / len(sentences)
        if 8 <= avg_sentence_len <= 80:
            score += 5
        elif 5 <= avg_sentence_len <= 120:
            score += 3
        else:
            score += 1

        # 引号配对（对话完整性）
        open_quotes = text.count('「') + text.count('"') + text.count('"')
        close_quotes = text.count('」') + text.count('"') + text.count('"')
        if open_quotes == close_quotes and open_quotes > 0:
            score += 3
        elif abs(open_quotes - close_quotes) <= 1:
            score += 2
        elif open_quotes > 0:
            score += 0  # 引号不配对，可能截断在对话中

        # 最后一个字符是否是句末标点（表示句子完整结束）
        last_char = text.strip()[-1] if text.strip() else ""
        if last_char in '。！？…」"\'）':
            score += 4
        elif last_char in '\n\r\t ':
            score += 3
        elif last_char in '，、；：':
            score += 1
        else:
            score += 2

        # 段落间是否有逻辑衔接词
        transition_words = ['但是', '然而', '于是', '这时', '突然', '后来',
                           '然后', '接着', '不过', '其实', '原来', '此刻']
        transitions_found = sum(1 for w in transition_words if w in text)
        if transitions_found >= 3:
            score += 3
        elif transitions_found >= 1:
            score += 2

        return min(15, score)

    def _score_title_match(self, text: str, expected_title: str,
                           content_title: str) -> int:
        """标题匹配度评分 (0-10)"""
        score = 0
        title_to_check = expected_title or content_title
        if not title_to_check:
            return 5  # 无标题信息，给中等分

        # 提取标题中的关键词
        clean_title = re.sub(r'[《》""''【】\[\]「」()（）\s]+', '', title_to_check)
        # 提取2字以上的词
        keywords = []
        for length in [3, 2]:
            for i in range(len(clean_title) - length + 1):
                kw = clean_title[i:i+length]
                if re.match(r'^[\u4e00-\u9fff]+$', kw):
                    keywords.append(kw)

        if not keywords:
            return 5

        # 检查关键词在正文中的出现
        matches = sum(1 for kw in keywords if kw in text)
        match_ratio = matches / max(len(keywords), 1)

        if match_ratio >= 0.8:
            score = 10
        elif match_ratio >= 0.6:
            score = 8
        elif match_ratio >= 0.4:
            score = 6
        elif match_ratio >= 0.2:
            score = 4
        else:
            score = 2

        # 内容标题匹配
        if content_title and expected_title:
            if expected_title in content_title or content_title in expected_title:
                score = min(10, score + 2)

        return score

    def _score_structural_integrity(self, text: str) -> int:
        """结构完整性评分 (0-10)"""
        score = 0

        # 检查开头
        beginning_text = text[:500]
        has_beginning = False
        for marker in self.BEGINNING_MARKERS:
            if marker in beginning_text:
                has_beginning = True
                break
        # 或开头有合理的叙事起始
        if has_beginning or re.search(r'^[\u4e00-\u9fff]{10,}', text.strip()):
            score += 3

        # 检查结尾
        ending_text = text[-500:]
        has_ending = False
        for marker in self.ENDING_MARKERS:
            if marker in ending_text:
                has_ending = True
                break
        if has_ending:
            score += 4
        else:
            # 没有明确的结局标记，但最后段落看起来是收尾
            last_para = text.strip().split('\n')[-1] if text.strip() else ""
            if len(last_para) > 15 and re.search(r'[。！？…]$', last_para.strip()):
                score += 2  # 有完整收束句
            elif len(last_para) > 30:
                score += 1

        # 内容长度足够长，即使没有结局标记也可能是完整章节
        cn_count = len(re.findall(r'[\u4e00-\u9fff]', text))
        if cn_count >= 3000 and score >= 3:
            score += 3  # 长内容加分
        elif cn_count >= 1500 and score >= 3:
            score += 2

        return min(10, score)

    def _estimate_truncation_probability(self, text: str, cn_words: int,
                                          dim3: int, dim4: int,
                                          dim6: int) -> float:
        """估算截断概率 (0-1)"""
        prob = 0.0
        # 截断标记多 → 高概率
        if dim3 < 10:
            prob += 0.4
        elif dim3 < 15:
            prob += 0.2
        # 连贯性差 → 可能截断在句中
        if dim4 < 5:
            prob += 0.25
        elif dim4 < 8:
            prob += 0.1
        # 结构不完整
        if dim6 < 3:
            prob += 0.2
        elif dim6 < 5:
            prob += 0.1
        # 字数太少
        if cn_words < 300:
            prob += 0.2
        elif cn_words < 100:
            prob += 0.3
        return min(1.0, prob)

    def compare(self, content_a: Optional[ExtractedContent],
                content_b: Optional[ExtractedContent]) -> Dict[str, Any]:
        """
        对比两个内容，返回差异分析
        """
        result = {
            "a_words": content_a.word_count_cn if content_a else 0,
            "b_words": content_b.word_count_cn if content_b else 0,
            "delta": 0,
            "ratio": 0.0,
            "is_same_content": False,
            "better_content": "none",
        }
        a_cn = content_a.word_count_cn if content_a else 0
        b_cn = content_b.word_count_cn if content_b else 0
        result["delta"] = b_cn - a_cn
        result["ratio"] = round(b_cn / max(a_cn, 1), 2)

        if content_a and content_b and content_a.content_hash == content_b.content_hash:
            result["is_same_content"] = True

        if b_cn > a_cn * 1.2:
            result["better_content"] = "b"
        elif a_cn > b_cn * 1.2:
            result["better_content"] = "a"
        else:
            result["better_content"] = "tie"

        return result
