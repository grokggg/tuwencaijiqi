# ZCCSA - Zero-Cookie Content Security Auditor

**零凭证内容付费墙安全评估工具（学术研究原型）**

> **重要声明**：本工具仅用于学术研究目的的安全评估，帮助内容平台发现并修复其访问控制架构中的脆弱点。所有探测行为须在授权环境下进行，不得用于未经授权的商业数据抓取。

---

## 研究目标

在零凭证（Zero-Cookie）约束下，系统性探测知乎盐选付费内容的渲染机制、CDN缓存策略、API权限校验边界及第三方生态信任链，以验证服务端截断型付费墙的实际安全性。

## 系统架构

```
zccsa/
├── scheduler.py              # 调度中心：URL输入 → 策略路由 → 结果聚合
├── engines/                  # 探测引擎集群
│   ├── render_bypass_engine.py    # 渲染模式探测：JS启用/禁用DOM差异
│   ├── cdn_cache_engine.py        # CDN缓存探测：Header变异Fuzzing
│   ├── partner_token_engine.py    # 第三方合作平台信任链分析
│   ├── api_endpoint_scanner.py    # API端点扫描：历史API权限校验覆盖
│   ├── snapshot_engine.py         # 历史快照检索：Wayback Machine+缓存
│   └── render_diff_engine.py      # 多端渲染差异分析：Web/App/H5对比
├── core/                     # 核心组件
│   ├── session_manager.py    # curl_cffi会话+TLS指纹伪装(Chrome 120)
│   ├── header_fuzzer.py      # 请求头变异Fuzzer
│   ├── proxy_pool.py         # 代理IP池管理
│   └── parser.py             # 多格式内容提取与对比分析
├── monitor.py                # 探测成功率监控 + 引擎权重动态调整
├── data/                     # 缓存Payload库、代理IP列表、端点配置
├── reports/                  # 评估报告输出目录
├── config.py                 # 全局配置
└── requirements.txt          # 依赖
```

## 探测引擎说明

| 引擎 | 默认权重 | 探测原理 |
|------|---------|---------|
| render_bypass_engine | 100 | 对比启用/禁用JS时的DOM差异，检测前端CSS/JS隐藏付费墙 |
| api_endpoint_scanner | 90 | 测试v1/v2/v3/v4/App端API的权限校验覆盖完整性 |
| cdn_cache_engine | 80 | Header Fuzzing：内网IP伪装、服务间调用头、CDN缓存控制 |
| render_diff_engine | 70 | 对比PC Web / 移动H5 / iOS App / Android App / M站响应差异 |
| snapshot_engine | 60 | Wayback Machine + Archive.ph + 搜索引擎缓存查询历史快照 |
| partner_token_engine | 50 | 分析微信读书、百度、头条等合作方信任链 |

## 安装

```bash
# 安装Python依赖
pip install -r requirements.txt

# 安装Playwright浏览器（render_bypass_engine需要）
playwright install chromium
```

## 使用方法

### 交互模式
```bash
python scheduler.py
```

### 单篇分析
```bash
python scheduler.py "https://www.zhihu.com/market/paid_column/xxx/section/yyy"
```

### 详细日志模式
```bash
python scheduler.py -v "https://www.zhihu.com/market/paid_column/xxx/section/yyy"
```

### 批量分析
```bash
python scheduler.py -f urls.txt --output-dir ./reports/
```

### 授权环境对比实验
```bash
# 使用Cookie文件进行有凭证对比实验
python scheduler.py -c cookies.txt "https://www.zhihu.com/..."
```

### 查看引擎统计
```bash
python scheduler.py --stats
```

## 输出说明

每次评估会在`reports/`目录下生成两类文件：

1. **JSON报告** (`zccsa_report_<id>_<timestamp>.json`)：包含完整的探测结果、每个引擎的响应状态、绕过向量详情、引擎统计等结构化数据。

2. **Markdown内容** (`content_<id>_<timestamp>.md`)：若成功提取到内容，则保存为可读的Markdown格式，标注绕过方法和来源引擎。

## 核心技术特性

### TLS指纹伪装
使用`curl_cffi`库伪装Chrome 120的TLS握手指纹（JA3/JA4），避免因TLS特征被识别为非浏览器客户端。

### 请求头Fuzzing
覆盖多种变异类型：
- 内网IP伪装（X-Forwarded-For、X-Real-IP等8种IP头 × 15个内网地址）
- 服务间调用头（X-Zhihu-Service、X-Internal-Request等）
- CDN缓存控制（Cache-Control变异、CDN厂商特定头）
- 来源伪造（微信读书、微信公众号、搜索引擎等）
- 高价值组合向量

### 自适应权重调度
基于24小时滑动窗口的成功率/绕过率统计，动态调整引擎执行顺序，成功率高的引擎优先执行，失败引擎权重自动衰减。

### 多格式内容解析
支持selectolax（高性能）和BeautifulSoup双解析器，自动识别HTML/JSON响应，启发式正文提取，Markdown格式输出。

## 法律与伦理声明

```
本工具原型仅用于学术研究和安全评估教学目的。使用者应当：
1. 仅在自有账号授权环境下进行测试
2. 不得用于任何商业目的或大规模数据采集
3. 不得公开传播或利用发现的脆弱点进行恶意行为
4. 发现脆弱点应通过正规渠道向平台方报告
```

## 学术引用

如在学术研究中使用本工具，请引用：
```
Zero-Cookie Content Security Auditor (ZCCSA):
A Framework for Analyzing Paywall Access Control Architectures
```
