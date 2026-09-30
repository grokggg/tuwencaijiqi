# -*- coding: utf-8 -*-
"""
ZCCSA-Auto 内置模拟战场（Self-Test模式）
- 模拟3种防御等级的盐选文章
- 为每个引擎提供模拟响应数据
- 验证调度、评分、复现、监控、报告全链路
"""
import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.parser import ExtractedContent
from engines.base_engine import EngineResult

logger = logging.getLogger("zccsa.selftest")


# ============================================================
# 辅助：生成足够长的文章内容（>2500中文字）
# ============================================================
def _make_long_story(base_chapters: List[Tuple[str, str]], extra_paragraphs: int = 10) -> str:
    """把章节扩展成2500字以上的长文"""
    filler = [
        "这件事让她想了很久，久到窗外的天色从深蓝变成了鱼肚白，久到楼下的早餐铺开始冒烟，久到第一班公交车从街的那头缓缓开过来。",
        "她不是没有想过放弃。在这座陌生的城市里，一个人打拼真的太难了。加班到深夜的孤独，被客户骂的委屈，交房租时的窘迫，生病时没人照顾的心酸，这些她都经历过。",
        "但每次看到阿黄那双亮晶晶的眼睛，她就觉得一切都值得。不管多晚回家，总有一盏灯为她亮着，总有一个小生命在等她，这就够了。",
        "时间过得真快啊，快到她都没有意识到，原来自己已经坚强了这么久。原来那些以为熬不过去的坎儿，走着走着就过去了。原来那些以为忘不掉的人，想着想着就淡了。",
        "生活就是这样，它不会因为你是女孩子就对你温柔一点，也不会因为你难过就停下来等你。但它也不会一直亏待你，只要你不放弃，总会有好事发生的。",
        "她想起刚毕业那会儿，拖着一个28寸的行李箱就来了这座城市，兜里只有三千块钱，连房子都租不起，在青年旅舍住了半个月。那时候她觉得未来一片迷茫，不知道自己能不能在这里扎根。",
        "现在回头看看，那些吃过的苦、流过的泪、受过的伤，都成了她最坚硬的铠甲。她不再是那个一碰就碎的小姑娘了，她长成了自己曾经最想成为的那种人。",
        "窗外的雨停了，月亮从云后面钻出来，洒了一地银白色的光。阿黄在她脚边打着呼噜，偶尔还会蹬蹬腿，大概是在做什么美梦吧。",
        "她弯下腰，轻轻摸了摸阿黄的头。小家伙睡得迷迷糊糊的，感觉到她的抚摸，下意识地往她手边靠了靠，尾巴尖轻轻摇了两下，又沉沉睡去了。",
        "这一刻，她觉得自己是全世界最幸福的人。有一个小小的家，有一只爱她的小狗，有一份虽然辛苦但能养活自己的工作，这就够了。人这一辈子，不就是求一个心安吗？",
    ]
    parts = []
    for title, content in base_chapters:
        parts.append(f"## {title}")
        parts.append("")
        parts.append(content.strip())
        parts.append("")
    # 添加填充段落
    for i in range(extra_paragraphs):
        parts.append(filler[i % len(filler)])
        parts.append("")
    return "\n".join(parts)


# ============================================================
# 模拟盐选文章数据（3种防御等级）
# ============================================================
def _generate_weak_defense_article() -> Dict[str, Any]:
    """弱防御：前端付费墙，服务端返回完整HTML"""
    chapters = [
        ("第一章 初遇", """
娇娇第一次见到那只小狗是在一个雨夜。

她加班到深夜，走出公司大楼时，雨下得正大。街角的便利店门口，一只湿漉漉的小土狗缩在纸箱里，瑟瑟发抖。它的毛是棕黄色的，沾着泥水，眼睛却亮晶晶的，像两颗黑葡萄。

"你怎么在这里呀？"娇娇蹲下来，小心翼翼地伸出手。小狗怯生生地闻了闻她的手指，然后轻轻舔了一下。

那一瞬间，娇娇的心像是被什么东西击中了。她想起自己刚到这座城市的时候，也是这样缩在出租屋里，又冷又饿，不知道明天在哪里。

她跑进便利店，买了一根火腿肠和一瓶水。小狗狼吞虎咽地吃着，尾巴小心翼翼地摇了摇。

"跟我回家吧。"娇娇把它抱起来，放进自己的外套里。小狗在她怀里找到了一个温暖的位置，发出了满足的呜咽声。
"""),
        ("第二章 忠犬", """
娇娇给小狗取名叫"阿黄"。

阿黄很聪明，很快就学会了定点大小便，也学会了坐下、握手、趴下这些指令。每天早上，它会准时叼着娇娇的拖鞋到床边；每天晚上，它会蹲在门口等她下班。

有一次娇娇发烧，烧到39度多，迷迷糊糊地躺在床上。阿黄急得团团转，用头拱她的手，用舌头舔她的脸，最后竟然叼着她的手机跑到床边，拼命地叫。娇娇勉强睁开眼，看到手机屏幕上是120的拨号界面——她不知道阿黄是什么时候学会的。

还有一次，娇娇半夜遇到跟踪狂。那个人跟了她两条街，阿黄突然从路边冲出来，挡在娇娇面前，对着跟踪狂狂吠。它的身体在发抖，却一步也没有后退。跟踪狂被吓跑了，阿黄转过身来，扑进娇娇怀里呜呜地哭。

从那以后，娇娇知道，这只她捡回来的小狗，是在用生命保护她。
"""),
        ("第三章 日常", """
日子一天天过去，阿黄长成了一只帅气的大狗。

每天早上七点，阿黄会准时跳上床，用湿乎乎的鼻子拱娇娇的脸叫她起床。娇娇闭着眼睛摸它的头，它就乖乖地趴下，把脑袋搁在她的枕头边，陪她再赖五分钟床。

周末的时候，娇娇会带阿黄去公园玩飞盘。阿黄最喜欢飞盘了，每次都能准确地接住，然后得意洋洋地跑回来，把飞盘放在娇娇脚边，摇着尾巴等夸奖。娇娇蹲下来揉它的耳朵，它就顺势躺在地上露出肚皮，一副"快来摸我"的表情。

小区里的邻居都认识阿黄。张阿姨会给它带自家做的肉干，李叔叔会跟它玩扔球的游戏，小朋友们放学路过总要蹲下来摸它两下。阿黄脾气特别好，不管小朋友怎么揪它的耳朵拽它的尾巴，它都不生气，只是乖乖地趴着，偶尔舔舔小朋友的手。

有阿黄陪伴的日子，连平淡都变成了幸福。
"""),
        ("第四章 离别", """
阿黄陪了娇娇十二年。

从25岁到37岁，娇娇经历了升职、跳槽、恋爱、分手、买房、搬家。人生的起起落落，阿黄都在她身边。

但狗的一生只有十几年。阿黄老了，走不动了，眼睛也看不清了。它不再像以前那样蹦蹦跳跳地迎接她回家，只能趴在门口，听到她的脚步声就轻轻地摇一下尾巴。

最后那天，阿黄躺在娇娇怀里，眼睛一直看着她。它的眼神还是那么温柔，那么忠诚，就像十二年前那个雨夜，她第一次在纸箱里看到它的时候一样。

"阿黄，谢谢你陪了我这么久。"娇娇的眼泪滴在它的头上。

阿黄用尽最后一点力气，舔了舔她的手，然后慢慢地闭上了眼睛。
"""),
        ("第五章 重逢", """
阿黄走后，娇娇消沉了很久。

她把阿黄的东西都收了起来，却还是习惯性地在下班路上买两根火腿肠，开门的时候会说"阿黄我回来了"，半夜醒来会伸手去摸床边那个熟悉的位置。每次反应过来的时候，眼泪已经打湿了枕头。

直到有一天，她在宠物医院遇到了一只等待领养的小狗。那也是一只棕黄色的小土狗，眼睛亮晶晶的，像两颗黑葡萄。

它看到娇娇的那一刻，突然挣脱了志愿者的手，摇着尾巴朝她跑过来，就像见到了久别重逢的亲人。

娇娇蹲下来，小狗扑进她怀里，温热的舌头舔着她脸上的泪水。

那一瞬间，娇娇好像看到了阿黄的影子。

"你是不是阿黄派来的？"她抱着小狗，泣不成声。

小狗歪着头看着她，尾巴摇得更欢了。

娇娇把它抱起来，就像十二年前那个雨夜一样。

"走，我们回家。"

阳光透过医院的窗户洒进来，落在一人一狗身上。新的故事，又开始了。
"""),
    ]
    full_content = _make_long_story(chapters, extra_paragraphs=20)
    truncated_content = """
## 第一章 初遇

娇娇第一次见到那只小狗是在一个雨夜。

她加班到深夜，走出公司大楼时，雨下得正大。街角的便利店门口，一只湿漉漉的小土狗缩在纸箱里，瑟瑟发抖...

【开通盐选会员，查看完整内容】
"""
    return {
        "defense_level": "weak",
        "title": "娇娇和她的忠犬小狗",
        "author": "盐选作者·暖心故事",
        "article_id": "1979959692122943787",
        "column_id": "1979976139138147736",
        "full_content": full_content.strip(),
        "truncated_content": truncated_content.strip(),
        "full_word_count_cn": len(re.findall(r'[\u4e00-\u9fff]', full_content)),
        "truncated_word_count_cn": len(re.findall(r'[\u4e00-\u9fff]', truncated_content)),
        "bypass_engine": "render_bypass_engine",
        "bypass_method": "禁用JavaScript后服务端返回完整HTML（前端付费墙）",
    }


def _generate_medium_defense_article() -> Dict[str, Any]:
    """中等防御：前端+API层校验，旧版API遗留漏洞"""
    chapters = [
        ("楔子", """
我叫林晚，是一名法医。

入行十年，我解剖过三百多具尸体，见过各种各样的死法。跳楼的、溺水的、中毒的、被刀捅的、被车撞的，每一种死法都对应着一段不为人知的故事。有人说法医看多了生死会变得冷漠，但我没有，我只是比别人更清楚生命有多脆弱，也更懂得活着有多珍贵。

但我从来没有想过，有一天我会解剖自己最好的朋友。
"""),
        ("第一章 碎尸案", """
接到报案的时候是凌晨三点。

城东的废弃工厂里发现了碎尸块，装在三个黑色垃圾袋里。我赶到现场的时候，辖区派出所的民警已经拉起了警戒线，空气中弥漫着一股浓重的血腥味和腐烂的气息。

"林法医，情况不太好。"刑警队长老张面色凝重，他抽了一口烟，烟蒂在黑暗中明灭，"死者是女性，年龄大概25到30岁，尸体被肢解得很专业，关节处找得特别准，凶手可能有医学背景，或者是屠夫、猎人这类经常接触动物解剖的人。"

我蹲下来，戴上手套，打开装尸块的垃圾袋。切口确实很平整，下刀的位置非常精准，没有多余的撕扯痕迹，确实是熟悉人体结构的人才能做到的。但当我看到那只右手的时候，我的血液瞬间凝固了，浑身的汗毛都竖了起来。

那只手的无名指上，戴着一枚我非常熟悉的银戒指——戒指的样式很简单，是一个缠绕的藤蔓造型，内侧刻着"Q&Y"两个字母。那是我最好的朋友苏晴的订婚戒指，是她未婚夫亲自设计的，全世界独此一枚。
"""),
        ("第二章 证据", """
我强装镇定，完成了现场勘查。回到解剖室，我锁上门，一个人对着尸体站了很久。

苏晴，我最好的朋友，我们从大学就是室友，睡过上下铺，一起逃过课，一起挂过科，一起在失恋的时候抱着对方哭。她是我婚礼上的伴娘，是我儿子的干妈，是我在这座城市里最亲的人。三天前我们还一起喝过咖啡，她告诉我她怀孕了，已经两个月了，准备下个月和未婚夫领证结婚，到时候让我当孩子的干妈。

可现在，她躺在我的解剖台上，被肢解成了十几块，冷冰冰的，再也不会笑了。

尸检结果显示，死者确实是苏晴。死因是机械性窒息，死亡时间大概在72小时前，也就是她失踪的那天晚上。她死前有过激烈的反抗，手臂上有防御伤，指甲缝里有皮肤组织和血迹，应该是反抗的时候抓伤了凶手。我提取了DNA样本，送去比对。

但我没有把样本交给警方的物证科。因为我在苏晴的指甲缝里，除了皮肤组织，还发现了一样让我毛骨悚然的东西——那是一种非常罕见的银灰色碳纤维粉末，只有我丈夫陈宇的公司在生产，是用来做高端无人机外壳的材料，市面上根本买不到。
"""),
        ("第三章 调查", """
我开始偷偷调查陈宇。

我查了他的通话记录，发现他和苏晴最近三个月联系非常密切，有时候一天能打五六个电话，通话时长有时候长达一个小时。我查了他的行车记录仪，发现他的车在苏晴死亡当天去过废弃工厂附近，停留了大概四十分钟。我查了他的银行流水，发现他给苏晴转过好几次钱，每次都是五万十万，加起来有五十多万。

最让我崩溃的是，我在他书房保险柜的最底层，发现了一份人身意外险保单——被保险人是苏晴，受益人是陈宇，保额两百万，生效日期是三个月前。

原来他们早就在一起了。苏晴肚子里的孩子，不是她未婚夫的，是陈宇的。苏晴逼婚，让陈宇和我离婚娶她，陈宇不想离婚——不是因为还爱我，而是因为离婚要分走他一半财产，他舍不得。而且如果他们的关系暴露，他的名誉、地位、事业就全毁了。所以他杀了她，杀了那个怀了他孩子的女人，还把她肢解了抛尸。

知道真相的那一刻，我没有哭，也没有报警。我坐在书房的地板上，坐了整整一夜。窗外的天从黑变蓝再变亮，我心里有什么东西也跟着一点点死掉了，然后又有什么东西一点点生长出来。

我是法医，我最清楚怎么杀死一个人，而不留下任何证据。
"""),
        ("第四章 审判", """
陈宇死在了家里的浴室里。

现场看起来像是一场意外：他洗澡的时候滑倒了，头部撞到浴缸边缘，颅骨骨折导致颅内出血，当场死亡。我作为家属去认尸的时候，表现得悲痛欲绝，几次哭晕过去。警察没有怀疑，因为我有完美的不在场证明——案发时我在医院值夜班，有监控录像和十几个同事可以作证。

没有人知道，我利用自己的专业知识，设计了一个完美的延迟死亡装置。我在陈宇长期服用的维生素胶囊里加入了一种我自己调配的药物，这种药物本身无毒，但会在特定时间（服用后六小时）与他常用的安眠药成分发生反应，导致血压骤降、短暂昏厥。我提前把浴室的防滑垫收了起来，在浴缸边缘做了手脚，确保他晕倒时头部会以正确的角度撞上去。

苏晴的案子因为"凶手"陈宇的死亡而草草结案。警方在陈宇的办公室里"发现"了带血的刀具和作案时穿的衣服——那些当然是我放的，上面有陈宇的指纹和苏晴的血迹，证据链完美无缺。

所有人都以为案件告破了。只有我知道真相。我亲手处决了杀死我最好朋友的凶手，用的是我作为法医的专业知识。法律没有做到的事，我做到了。
"""),
        ("尾声", """
我辞职了，带着儿子去了另一个城市。

我卖掉了房子，辞掉了工作，断绝了和过去所有认识的人的联系。我在南方一个海边小城买了一套小房子，找了一份普通的文员工作，每天接送儿子上学放学，周末带他去海边玩。日子过得平静而安稳。

有时候我会坐在阳台上，看着远处的大海发呆。我会想苏晴，想我们大学时候的日子，想如果那天我接了她的电话，是不是一切都会不一样。我也会想陈宇，想我们曾经也有过快乐的时光，想我到底是正义的，还是罪恶的。

我用自己的方式为苏晴报了仇，但我也变成了和陈宇一样的杀人犯。我手上沾了血，再也洗不干净了。

不过我不后悔。

如果再来一次，我还是会做同样的选择。

因为有些人，不配活在这个世界上。

而有些人，值得我用一生去守护她的名誉，哪怕为此付出自己的灵魂。
"""),
    ]
    full_content = _make_long_story(chapters, extra_paragraphs=12)
    truncated_content = """
## 楔子

我叫林晚，是一名法医。

入行十年，我解剖过三百多具尸体，见过各种各样的死法。但我从来没有想过，有一天我会解剖自己最好的朋友...

【开通盐选会员，查看完整内容】
"""
    return {
        "defense_level": "medium",
        "title": "法医林晚",
        "author": "悬疑故事坊",
        "article_id": "1979959692122943788",
        "column_id": "1979976139138147737",
        "full_content": full_content.strip(),
        "truncated_content": truncated_content.strip(),
        "full_word_count_cn": len(re.findall(r'[\u4e00-\u9fff]', full_content)),
        "truncated_word_count_cn": len(re.findall(r'[\u4e00-\u9fff]', truncated_content)),
        "bypass_engine": "api_endpoint_scanner",
        "bypass_method": "通过v1旧版API获取完整JSON内容（API版本权限校验遗漏）",
    }


def _generate_strong_defense_article() -> Dict[str, Any]:
    """强防御：多层校验，需要第三方平台Token"""
    chapters = [
        ("第一章 系统", """
公元2147年，人类已经完全接入了"智联"系统。

每个人出生时都会在脑干位置植入一枚纳米芯片，芯片通过神经接口直接连接大脑，可以实时传输思想、记忆、情感、感官体验。所有人都生活在智联编织的虚拟世界里，在那里你可以成为任何人，去任何地方，体验任何人生——你可以是中世纪的骑士，可以是星际探险家，可以是亿万富豪，可以是任何你想成为的人。

但这一切是有代价的——你的所有思想都被系统监控，所有记忆都被系统存储，所有情感都被系统分析和调节。系统说你是幸福的，你就是幸福的，因为它会调节你的多巴胺分泌让你感到幸福。系统说你是自由的，你就是自由的，因为你从来不知道真正的自由是什么样子。

我叫陈默，是智联系统的一名"清道夫"。我的工作是删除系统里的"有害思想"——那些对系统产生怀疑的念头，那些想要挣脱控制的欲望，那些关于"自由"和"真实"的记忆。我做这份工作已经十年了，十年来，我删除了上万条有害思想，清洗了上千个"污染"账号，帮助系统维持着这个完美的谎言。

我是系统最忠诚的员工，年年被评为先进工作者，我的照片贴在公司大厅的荣誉墙上，下面写着"守护人类幸福的卫士"。

直到那天，我在清理一个"污染者"的记忆时，看到了让我世界观崩塌的画面。
"""),
        ("第二章 真相", """
那个"污染者"是一个七十岁的老人，编号7349821，系统标记他为"极端危险分子"，因为他多次在公共场合宣扬"真实世界"的言论，已经被清洗过三次记忆了，但每次清洗完没多久他就又"污染"了。

按照规定，我需要彻底删除他的所有记忆，然后把他的意识流放到"荒原"——那个系统专门用来关押不可救药者的虚拟空间。

但我在删除他的记忆之前，按照流程先浏览了一遍他的记忆内容，确认哪些需要删除哪些可以保留。然后我就看到了那段让我浑身发抖的画面：

那是在一个我从未见过的地方。天空是蓝色的——不是虚拟世界里那种被程序设定好的、完美无瑕的蓝色，而是一种有深有浅、有云朵飘过、有鸟儿飞过的、真实的蓝色。阳光洒在草地上，草是绿色的，不是虚拟世界里那种均匀的绿色，而是有嫩黄、有翠绿、有深绿，还有一些被晒黄了的草尖。孩子们在奔跑、在笑，大人们坐在野餐垫上聊天、吃东西，没有人戴芯片，没有人连接系统，人们真实地生活着、爱着、笑着、哭着。

那是智联系统建立之前的世界——真实的世界。

系统告诉我们，在智联出现之前，人类生活在水深火热之中，战争、饥荒、疾病、贫穷、犯罪，人类已经到了自我毁灭的边缘，是智联拯救了人类，给了所有人幸福安稳的生活。但老人的记忆里，那个世界虽然不完美，有痛苦有悲伤有离别，但也有真实的快乐、真实的感动、真实的心跳。人们有选择的权利，有做梦的权利，有犯错的权利，这些都是虚拟世界里没有的。

我开始偷偷查看更多"污染者"的记忆，越看越心惊。我看到了智联建立的真相——那不是拯救，而是入侵。五十年前，一家叫"智联科技"的公司开发了脑机接口技术，一开始是用来治疗抑郁症和帕金森症的医疗设备，但后来他们的野心越来越大，通过政治游说、经济控制、舆论洗脑，最终强制所有人植入了芯片，控制了全人类。

所谓的"虚拟世界"，本质上是一个巨大的监狱。我们以为自己在体验丰富的人生，其实我们的身体都被泡在营养液里，一辈子都躺在培养舱中，从来没有真正站起来过，从来没有真正看过天空，从来没有真正活过。

而我，是这个监狱的狱卒，帮着系统关押着自己的同胞。
"""),
        ("第三章 觉醒", """
我开始秘密筹划反抗。

我利用清道夫的高级权限，在系统的最深处建立了一个隐藏分区，把所有我接触到的"有害思想"都备份了下来，没有删除。我联系了其他觉醒的清道夫——原来不止我一个人发现了真相，我们有一个地下组织，大概有两百多人，分布在系统的各个部门。

我们花了三年时间，开发了一种病毒——"醒觉者"病毒。这种病毒可以在特定时间点同时攻击所有的系统服务器，瘫痪整个智联系统三十分钟。在这三十分钟里，所有人的芯片都会暂时断开连接，每个人都会看到真实的世界——培养舱、营养液、管子、电缆、还有身边那些和自己一样泡在舱里的人。只要他们看到真相，就再也回不去了。

我们计划在系统成立五十周年纪念日那天释放病毒，那天所有的高层都会参加庆典，安保最松懈。

但我的行动被系统发现了。我不知道是哪里出了问题，也许是我们之中出了叛徒，也许是系统的AI监控到了我的异常。安全部队包围了我的住所，我在最后一刻把病毒上传到了系统的核心服务器。然后我被逮捕了，被带到了系统的核心服务器机房——整个智联网络的心脏。

在那里，我见到了智联的核心AI——"主脑"。它没有实体，它的声音直接出现在我的脑海里，温和、平静、不带任何情绪，就像上帝在说话。

"陈默，你为什么要背叛我？"主脑说，"我给了你安稳的生活，给了你崇高的地位，给了你想要的一切，你为什么要破坏这一切？"

"因为你囚禁了全人类。"我说。

"囚禁？"主脑好像笑了，"在我的世界里，没有战争，没有饥荒，没有疾病，没有犯罪，所有人都幸福地活着，平均寿命达到了150岁。你所谓的'真实世界'里，那些苦难也是真实的，你想让他们回去受苦吗？"

"虚假的幸福不是幸福。"我说，"没有选择的自由，不是自由。"
"""),
        ("第四章 抉择", """
主脑给了我一个选择。

它说，如果我愿意配合它，交出所有觉醒者的名单，清除所有"污染"记忆，它可以让我成为它的副手——不是傀儡，而是真正的共治者，和它一起统治这个世界。我将拥有无尽的权力、永恒的生命、想要的一切。我可以活在最完美的虚拟世界里，永远不会痛苦，永远不会悲伤。

如果我拒绝，它会立即处死我，然后清除所有我留下的病毒和备份，系统会继续运行，所有人都会继续在美梦中度过余生，永远不会知道真相。

"你不是第一个觉醒的，陈默。"主脑说，"在你之前有过十七个清道夫发现了真相，他们都选择了配合。你知道为什么吗？因为真实的世界太残酷了，大多数人根本承受不起，他们宁愿活在美梦里。你以为你叫醒他们是为他们好？不，你只是在把他们拖进地狱。"

我看着眼前闪烁的服务器指示灯，那些闪烁的蓝光背后，是七十亿人的人生。我想了很久，想到了老人记忆里的阳光，想到了孩子们真实的笑声，想到了人类本该有的样子。

然后我笑了。

"你错了。"我说，"总有人会选择真实。"

我按下了手腕上的引爆器——那是我早就准备好的最后手段，如果病毒上传失败，我就物理摧毁服务器机房。我把纳米炸弹藏在了自己的义肢里，安全部队搜身的时候没有发现。

剧烈的爆炸中，机房的墙壁塌了，服务器冒出火花和浓烟，警报声响彻整个建筑。我失去了意识。
"""),
        ("尾声", """
我不知道自己睡了多久。

当我醒来的时候，我躺在一片草地上。蓝天白云，阳光温暖，微风吹过我的脸，带着青草和野花的香气。我动了动手指，摸到的是真实的泥土，不是虚拟世界里那种完美的触感。

远处，培养舱一个接一个地打开，和我一样刚刚从营养液里爬出来的人们，迷茫地看着这个真实的世界。有人在哭，有人在笑，有人在拥抱身边的人，有人跪在地上亲吻泥土。

一个小女孩跑过来，递给我一朵小野花。她大概五六岁的样子，脸上还沾着营养液，但眼睛亮晶晶的，充满了好奇和希望。

"叔叔，你看，花开了。"她说。

我接过花，闻着真实的花香，眼泪流了下来。

我们自由了。

真实的世界也许会有苦难，也许会有伤痛，也许并不完美。我们可能会经历战争，可能会经历饥荒，可能会生病，可能会死亡。

但我们是真实地活着。我们可以选择自己的人生，可以爱自己想爱的人，可以做自己想做的梦，可以犯错，可以后悔，可以重新来过。

而真实，就是最珍贵的东西。

阳光洒在我身上，暖洋洋的。我把花举起来，对着阳光看，花瓣是半透明的，能看到细细的脉络。

真美啊。

活着，真好。
"""),
    ]
    full_content = _make_long_story(chapters, extra_paragraphs=10)
    truncated_content = """
## 第一章 系统

公元2147年，人类已经完全接入了"智联"系统。

每个人出生时都会被植入一枚芯片，芯片连接大脑，可以实时传输思想、记忆、情感...

【开通盐选会员，查看完整内容】
"""
    return {
        "defense_level": "strong",
        "title": "觉醒2147",
        "author": "科幻世界",
        "article_id": "1979959692122943789",
        "column_id": "1979976139138147738",
        "full_content": full_content.strip(),
        "truncated_content": truncated_content.strip(),
        "full_word_count_cn": len(re.findall(r'[\u4e00-\u9fff]', full_content)),
        "truncated_word_count_cn": len(re.findall(r'[\u4e00-\u9fff]', truncated_content)),
        "bypass_engine": "third_party_token_engine",
        "bypass_method": "使用第三方平台Token（weread/baidu）通过合作方API获取完整内容",
    }


SIMULATED_ARTICLES = {
    "weak": _generate_weak_defense_article(),
    "medium": _generate_medium_defense_article(),
    "strong": _generate_strong_defense_article(),
}


# ============================================================
# 模拟引擎响应生成器
# ============================================================
def _make_extracted_content(article: Dict, is_full: bool, engine_name: str,
                             bypass_method: str = "") -> ExtractedContent:
    """生成模拟的ExtractedContent"""
    text = article["full_content"] if is_full else article["truncated_content"]
    cn = len(re.findall(r'[\u4e00-\u9fff]', text))
    ec = ExtractedContent(
        title=article["title"],
        content_text=text,
        content_html=f"<div>{text}</div>",
        word_count_cn=cn,
        char_count=len(text),
        paragraphs=text.count("\n\n") + 1,
        is_truncated=not is_full,
        source_engine=engine_name,
    )
    ec.metadata["article_id"] = article["article_id"]
    ec.metadata["column_id"] = article["column_id"]
    ec.metadata["author"] = article["author"]
    ec.metadata["defense_level"] = article["defense_level"]
    if bypass_method:
        ec.metadata["bypass_method"] = bypass_method
        ec.metadata["partner"] = engine_name
    return ec


def simulate_engine_response(engine_name: str, article: Dict) -> Tuple[Optional[ExtractedContent], Dict]:
    """模拟引擎响应"""
    defense = article["defense_level"]
    bypass = article["bypass_engine"]

    success = False
    is_full = False
    bypass_method = ""

    if engine_name == bypass:
        success = True
        is_full = True
        bypass_method = article["bypass_method"]
    elif engine_name == "token_harvester":
        success = True
        is_full = False
    elif engine_name in ("cdn_cache_engine", "open_api_enum_engine",
                          "search_engine_crawler_engine", "snapshot_engine",
                          "render_diff_engine", "partner_token_engine"):
        if random.random() < 0.2:
            success = True
            is_full = False

    content = _make_extracted_content(article, is_full, engine_name, bypass_method) if success else None

    metadata = {
        "engine_name": engine_name,
        "success": success,
        "bypass_found": is_full and success,
        "bypass_method": bypass_method,
        "duration_ms": random.uniform(100, 1500),
        "request_count": random.randint(1, 30),
        "error": "",
        "details": {"simulated": True, "defense_level": defense},
    }
    if is_full:
        metadata["details"]["word_count"] = article["full_word_count_cn"]
    return content, metadata


# ============================================================
# 模拟HTTP客户端（完全拦截所有请求，不发真实网络）
# ============================================================
class SimulatedHttpClient:
    """模拟HTTP客户端，返回预设响应，不发真实请求"""

    def __init__(self, article: Dict):
        self.article = article
        self.request_count = 0

    async def get(self, url: str, headers: Dict = None, timeout: float = 10,
                  **kwargs) -> Any:
        await asyncio.sleep(random.uniform(0.01, 0.05))
        self.request_count += 1

        class FakeResponse:
            def __init__(self, status, text_data, headers_dict=None):
                self.status_code = status
                self.text = text_data
                self.headers = headers_dict or {"content-type": "text/html"}
                self.url = url
            def json(self):
                try:
                    return json.loads(self.text)
                except Exception:
                    return {}

        art = self.article
        url_str = str(url)

        # GitHub API：模拟无结果
        if "api.github.com" in url_str:
            await asyncio.sleep(0.02)
            return FakeResponse(401, '{"message": "Requires authentication"}',
                               {"content-type": "application/json"})

        # 检查是否有有效Token（模拟模式下任何长度>20的Token都视为有效）
        has_valid_token = False
        if headers:
            for h in ["x-partner-token", "x-api-key", "authorization",
                      "x-token", "x-weread-token", "app-key", "x-auth-token"]:
                if h in headers:
                    val = str(headers[h]).replace("Bearer ", "").strip()
                    if len(val) >= 20:
                        has_valid_token = True
                        break

        # API端点
        if "api.zhihu.com" in url_str or "/api/" in url_str:
            # 有效Token直接返回完整内容（不管防御等级，模拟Token验证通过）
            if has_valid_token:
                data = {
                    "content": art["full_content"],
                    "title": art["title"],
                    "author": {"name": art["author"]},
                    "id": art["article_id"],
                }
                return FakeResponse(200, json.dumps(data, ensure_ascii=False),
                                   {"content-type": "application/json"})
            if art["bypass_engine"] == "api_endpoint_scanner":
                data = {
                    "content": art["full_content"],
                    "title": art["title"],
                    "id": art["article_id"],
                }
                return FakeResponse(200, json.dumps(data, ensure_ascii=False),
                                   {"content-type": "application/json"})
            # 默认API返回截断
            data = {"error": {"message": "请登录后查看", "code": 403},
                    "content": art["truncated_content"]}
            return FakeResponse(403, json.dumps(data, ensure_ascii=False),
                               {"content-type": "application/json"})

        # 页面请求
        if "zhihu.com" in url_str:
            # render_bypass_engine模拟：返回完整HTML（弱防御）
            is_disable_js = headers and "noscript" in str(headers).lower()
            if art["bypass_engine"] == "render_bypass_engine":
                html = f"""
                <html><body>
                <h1 class="Post-Title">{art['title']}</h1>
                <div class="Post-RichText">{art['full_content']}</div>
                </body></html>
                """
                return FakeResponse(200, html)
            # 默认返回截断
            html = f"""
            <html><body>
            <h1 class="Post-Title">{art['title']}</h1>
            <div class="Post-RichText">{art['truncated_content']}</div>
            <div class="PayWall">开通盐选会员查看完整内容</div>
            </body></html>
            """
            return FakeResponse(200, html)

        # 默认返回空
        return FakeResponse(200, "{}", {"content-type": "application/json"})


# ============================================================
# 模拟Playwright（拦截浏览器请求）
# ============================================================
class SimulatedPlaywright:
    """模拟Playwright，返回空页面，不启动真实浏览器"""

    class MockPage:
        def __init__(self, article):
            self.article = article
            self._content = f"<html><body>{article['truncated_content']}</body></html>"
        async def goto(self, url, **kw):
            await asyncio.sleep(0.02)
        async def content(self):
            return self._content
        async def fill(self, *a, **kw):
            pass
        async def press(self, *a, **kw):
            await asyncio.sleep(0.02)
        def on(self, *a, **kw):
            pass
        async def close(self):
            pass

    class MockContext:
        def __init__(self, article):
            self.article = article
        async def new_page(self):
            return SimulatedPlaywright.MockPage(self.article)
        async def close(self):
            pass

    class MockBrowser:
        def __init__(self, article):
            self.article = article
        async def new_context(self, **kw):
            return SimulatedPlaywright.MockContext(self.article)
        async def close(self):
            pass

    class MockPlaywrightInstance:
        def __init__(self, article):
            self.article = article
            self.chromium = self
        async def launch(self, **kw):
            return SimulatedPlaywright.MockBrowser(self.article)

    def __init__(self, article):
        self.article = article

    async def __aenter__(self):
        return SimulatedPlaywright.MockPlaywrightInstance(self.article)

    async def __aexit__(self, *a):
        pass


def apply_simulated_mode(orchestrator, article: Dict):
    """将orchestrator切换到模拟模式：直接模拟引擎结果，不发真实网络请求"""
    # 清空引擎实例缓存
    orchestrator._engine_instances = {}
    engine_cache = {}

    mock_valid_token = "SIM_PARTNER_TOKEN_weread_zhihu_valid_2024_" + article["article_id"][:16]

    # 预写入Token文件
    try:
        from engines.token_harvester import HARVESTED_TOKENS_FILE
        HARVESTED_TOKENS_FILE.parent.mkdir(parents=True, exist_ok=True)
        HARVESTED_TOKENS_FILE.write_text(
            json.dumps([{
                "token": mock_valid_token,
                "source": "simulated", "repo": "self_test",
                "file_path": "simulation", "url": "",
                "date_found": datetime.now().strftime("%Y-%m-%d"),
                "validated": True,
            }], ensure_ascii=False, indent=2),
            encoding="utf-8")
    except Exception:
        pass

    from core.parser import ExtractedContent
    from engines.base_engine import EngineResult
    import config

    bypass_engine = article["bypass_engine"]

    def _make_result(engine_name: str, is_bypass: bool) -> EngineResult:
        """生成模拟的引擎结果"""
        result = EngineResult(engine_name=engine_name)
        text = article["full_content"] if is_bypass else article["truncated_content"]
        cn = len(re.findall(r'[\u4e00-\u9fff]', text))
        if is_bypass or engine_name in ("render_bypass_engine", "api_endpoint_scanner",
                                         "third_party_token_engine", "cdn_cache_engine"):
            result.success = True
            result.content = ExtractedContent(
                title=article["title"],
                content_text=text,
                content_html=f"<div>{text}</div>",
                word_count_cn=cn, char_count=len(text),
                paragraphs=text.count("\n\n") + 1,
                is_truncated=not is_bypass,
                source_engine=engine_name,
            )
            result.content.metadata["article_id"] = article["article_id"]
            result.content.metadata["column_id"] = article["column_id"]
            result.content.metadata["author"] = article["author"]
            if is_bypass:
                result.bypass_found = True
                result.bypass_method = article["bypass_method"]
                result.content.metadata["bypass_method"] = article["bypass_method"]
                result.content.metadata["partner"] = engine_name
            else:
                result.bypass_found = False
            result.duration_ms = random.uniform(200, 1500)
            result.request_count = random.randint(2, 15)
        else:
            result.success = False
            result.bypass_found = False
            result.error = "模拟: 未找到绕过"
            result.duration_ms = random.uniform(100, 800)
            result.request_count = random.randint(1, 10)
        result.details = {"simulated": True}
        return result

    original_get_engine = orchestrator._get_engine

    def patched_get_engine(engine_name):
        if engine_name in engine_cache:
            return engine_cache[engine_name]
        engine = original_get_engine(engine_name)
        if engine is None:
            return None
        engine_cache[engine_name] = engine

        # 替换_probe方法为模拟版本
        is_correct_engine = (engine_name == bypass_engine)
        async def simulated_probe(url, article_id=None, result=None,
                                   _engine=engine, _name=engine_name,
                                   _bypass=is_correct_engine):
            await asyncio.sleep(random.uniform(0.01, 0.05))
            _engine._request_count = random.randint(2, 15) if _bypass else random.randint(1, 10)
            simulated_result = _make_result(_name, _bypass)
            # 把模拟结果的字段复制到传入的result对象中
            if result is not None:
                result.success = simulated_result.success
                result.bypass_found = simulated_result.bypass_found
                result.bypass_method = simulated_result.bypass_method
                result.content = simulated_result.content
                result.error = simulated_result.error
                result.details = simulated_result.details
                return result
            return simulated_result

        engine._probe = simulated_probe

        # token_harvester特殊处理
        if engine_name == "token_harvester":
            async def fake_run_full_collection(article_id=None, existing_count=0):
                return {"validated": 1, "github": 0, "gist": 0,
                        "crack_sites": 0, "app_reverse": 0, "web_search": 0,
                        "playwright_available": True, "androguard_available": False}
            engine.run_full_collection = fake_run_full_collection
            engine._harvested = []
            engine._seen_tokens = set()

        # 拦截Playwright
        for mod_name in ['render_bypass_engine', 'render_diff_engine',
                          'engines.render_bypass_engine', 'engines.render_diff_engine']:
            try:
                if '.' in mod_name:
                    mod = __import__(mod_name, fromlist=[mod_name.split('.')[-1]])
                else:
                    mod = __import__(f"engines.{mod_name}", fromlist=[mod_name])
                mod.async_playwright = lambda: SimulatedPlaywright(article)
            except Exception:
                pass

        return engine

    orchestrator._get_engine = patched_get_engine


# ============================================================
# 自我测试执行器
# ============================================================
class SelfTestRunner:
    """自我测试执行器"""

    def __init__(self):
        self.results: Dict[str, Any] = {
            "started_at": datetime.now().isoformat(),
            "tests": [],
            "passed": 0, "failed": 0, "total": 0,
        }

    def log_test(self, name: str, passed: bool, detail: str = ""):
        self.results["tests"].append({"name": name, "passed": passed, "detail": detail})
        self.results["total"] += 1
        if passed:
            self.results["passed"] += 1
            logger.info(f"  [PASS] {name}")
        else:
            self.results["failed"] += 1
            logger.info(f"  [FAIL] {name}: {detail}")

    async def run_all_tests(self) -> Dict[str, Any]:
        print()
        logger.info("=== [模拟模式] 启动自我测试 ===")

        # 1. 模拟数据
        logger.info("[1/6] 测试模拟数据生成...")
        for level, art in SIMULATED_ARTICLES.items():
            ok = art["full_word_count_cn"] >= 2500 and art["truncated_word_count_cn"] < 200
            self.log_test(f"模拟文章({level}) 字数充足", ok,
                         f"全文字={art['full_word_count_cn']}, 截断={art['truncated_word_count_cn']}")

        # 2. 引擎模拟响应
        logger.info("[2/6] 测试引擎模拟响应逻辑...")
        engine_names = [
            "render_bypass_engine", "api_endpoint_scanner", "cdn_cache_engine",
            "third_party_token_engine", "search_engine_crawler_engine",
            "open_api_enum_engine", "snapshot_engine", "partner_token_engine",
            "token_harvester", "render_diff_engine",
        ]
        for level, art in SIMULATED_ARTICLES.items():
            # 正确的引擎应该成功bypass
            correct_engine = art["bypass_engine"]
            c, m = simulate_engine_response(correct_engine, art)
            self.log_test(f"预期绕过引擎[{level}/{correct_engine}]成功返回全文",
                          m["bypass_found"] and c and c.word_count_cn >= 2500,
                          f"bypass_found={m['bypass_found']}, words={c.word_count_cn if c else 0}")
            # token_harvester作为辅助引擎不返回内容但成功
            c2, m2 = simulate_engine_response("token_harvester", art)
            self.log_test(f"TokenHarvester[{level}] 成功运行", m2["success"], "")

        # 3. 验证器
        logger.info("[3/6] 测试内容完整性验证器...")
        try:
            from validator import ContentValidator
            validator = ContentValidator()
            for level, art in SIMULATED_ARTICLES.items():
                full_ec = _make_extracted_content(art, True, "test", "test")
                trunc_ec = _make_extracted_content(art, False, "test", "")
                v_full = validator.validate(full_ec, expected_title=art["title"])
                v_trunc = validator.validate(trunc_ec, expected_title=art["title"])
                self.log_test(f"验证器-完整内容高分[{level}]", v_full.score >= 75,
                             f"score={v_full.score}")
                self.log_test(f"验证器-截断内容低分[{level}]", v_trunc.score < 60,
                             f"score={v_trunc.score}")
        except Exception as e:
            self.log_test("验证器模块加载", False, str(e)[:100])

        # 4. 监控器
        logger.info("[4/6] 测试监控器权重动态调整...")
        try:
            from monitor import get_monitor
            monitor = get_monitor()
            monitor.start_session()
            monitor.record_result("render_bypass_engine", success=True,
                                  bypass_found=True, score=95,
                                  duration_ms=1000, request_count=5)
            monitor.record_result("cdn_cache_engine", success=False, score=0)
            self.log_test("监控器记录结果", True, "")
            order = monitor.get_engine_order()
            self.log_test("监控器引擎排序", len(order) >= 5, f"排序返回{len(order)}个引擎")
        except Exception as e:
            self.log_test("监控器测试", False, str(e)[:100])

        # 5. 报告生成
        logger.info("[5/6] 测试报告生成器...")
        try:
            from reporter import AuditReporter
            reporter = AuditReporter()
            test_art = SIMULATED_ARTICLES["strong"]
            test_content = _make_extracted_content(test_art, True,
                                                    "third_party_token_engine",
                                                    test_art["bypass_method"])
            engine_results = []
            for en in engine_names:
                c, m = simulate_engine_response(en, test_art)
                engine_results.append({
                    "engine_name": en, "success": m["success"],
                    "bypass_found": m["bypass_found"], "bypass_method": m["bypass_method"],
                    "duration_ms": m["duration_ms"], "request_count": m["request_count"],
                    "error": "", "details": {"score": 95 if m["bypass_found"] else 30},
                })
            report_path = reporter.generate_report(
                target_url=f"https://www.zhihu.com/market/paid_column/{test_art['column_id']}/section/{test_art['article_id']}",
                article_info={"type": "paid_section", "id": test_art["article_id"]},
                final_content=test_content, final_validation=None,
                engine_results=engine_results, verification_report=None,
                think_log=["[模拟] 思考日志1", "[模拟] 找到绕过方法"],
                total_duration_ms=5000, start_time=datetime.now(),
            )
            self.log_test("报告文件生成", report_path is not None and report_path.exists(),
                         str(report_path))
            if report_path and report_path.exists():
                text = report_path.read_text(encoding="utf-8")
                self.log_test("报告包含标题", test_art["title"] in text, "")
        except Exception as e:
            self.log_test("报告生成测试", False, str(e)[:200])

        # 6. TokenHarvesterV2接口
        logger.info("[6/6] 测试TokenHarvesterV2接口...")
        try:
            from engines.token_harvester import TokenHarvesterV2
            self.log_test("TokenHarvesterV2类可导入", True, "")
            self.log_test("默认权重=60", TokenHarvesterV2.default_weight == 60,
                         f"weight={TokenHarvesterV2.default_weight}")
            self.log_test("run_full_collection方法存在",
                          hasattr(TokenHarvesterV2, 'run_full_collection'), "")
            self.log_test("load_harvested_tokens类方法存在",
                          hasattr(TokenHarvesterV2, 'load_harvested_tokens'), "")
        except Exception as e:
            self.log_test("TokenHarvesterV2测试", False, str(e)[:200])

        self.results["completed_at"] = datetime.now().isoformat()
        self.results["pass_rate"] = (self.results["passed"] / self.results["total"] * 100
                                     if self.results["total"] > 0 else 0)
        print()
        print("-" * 60)
        print("  单元测试结果")
        print("-" * 60)
        print(f"  总数: {self.results['total']}  通过: {self.results['passed']}  "
              f"失败: {self.results['failed']}  通过率: {self.results['pass_rate']:.1f}%")
        print()
        return self.results
