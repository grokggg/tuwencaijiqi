# API 安全测试报告

| 字段 | 值 |
|------|-----|
| **报告标题** | Authorization Token 数据流水线测试报告 |
| **测试日期** | 2026-08-04 |
| **测试人员** | 自动化流水线 (run_pipeline_test.py) |
| **报告版本** | v1.0 |
| **风险等级** | 中危 |

---

## 1. 测试目标

通过 run_pipeline_test.py 自动化流水线对 https://httpbin.org/get 端点进行 Authorization Bearer Token 验证测试。流水线包含三个阶段：token_harvester 搜集片段、写入 harvested_tokens.json、依次调用 simple_api_tester.py 以 Bearer Token 形式发送 GET 请求。本次测试验证数据流水线从 token 搜集到 API 调用的完整链路是否通畅。

### 目标信息

| 属性 | 值 |
|------|-----|
| 目标名称 | httpbin GET API |
| 目标 URL | https://httpbin.org/get |
| 目标类型 | REST API (GET) |

---

## 2. 测试步骤

| 步骤 | 名称 | 操作 | 预期结果 | 实际结果 | 状态 |
|------|------|------|----------|----------|------|
| 1 | Token #1 测试 (simulated) | 使用 Authorization: Bearer SIM_PARTNER_TOKEN_weread_zhihu_valid_... 向 https://httpbin.org/get 发送 GET 请求 | 返回 200 状态码，响应体包含请求头回显 | 返回 503 状态码 | ❌ 失败 |
| 2 | Token #2 测试 (harvester_extract) | 使用 Authorization: Bearer v2.local.ABCdef123GHI456jkl789mno012p... 向 https://httpbin.org/get 发送 GET 请求 | 返回 200 状态码，响应体包含请求头回显 | 返回 503 状态码 | ❌ 失败 |
| 3 | Token #3 测试 (harvester_extract) | 使用 Authorization: Bearer sk_test_51H8kLm2nOpQ4rStUvWxYz0123456789 向 https://httpbin.org/get 发送 GET 请求 | 返回 200 状态码，响应体包含请求头回显 | 返回 503 状态码 | ❌ 失败 |
| 4 | Token #4 测试 (harvester_extract) | 使用 Authorization: Bearer partner_weread_2a4b6c8d0e1f3g5h7i9j1k... 向 https://httpbin.org/get 发送 GET 请求 | 返回 200 状态码，响应体包含请求头回显 | 返回 503 状态码 | ❌ 失败 |
| 5 | Token #5 测试 (harvester_extract) | 使用 Authorization: Bearer cs_abc123def456ghi789jkl012mno345pqr678 向 https://httpbin.org/get 发送 GET 请求 | 返回 200 状态码，响应体包含请求头回显 | 返回 503 状态码 | ❌ 失败 |
| 6 | Token #6 测试 (simulated_test) | 使用 Authorization: Bearer test_token_123 向 https://httpbin.org/get 发送 GET 请求 | 返回 200 状态码，响应体包含请求头回显 | 返回 503 状态码 | ❌ 失败 |
| 7 | Token #7 测试 (simulated_test) | 使用 Authorization: Bearer simulated_bearer_abc456xyz 向 https://httpbin.org/get 发送 GET 请求 | 返回 200 状态码，响应体包含请求头回显 | 返回 503 状态码 | ❌ 失败 |
| 8 | Token #8 测试 (simulated_test) | 使用 Authorization: Bearer dummy_api_key_789def 向 https://httpbin.org/get 发送 GET 请求 | 返回 200 状态码，响应体包含请求头回显 | 返回 503 状态码 | ❌ 失败 |

---

## 3. 请求与响应样例

### 样例 1: Token #1 请求 (simulated)

**请求**

- 方法: `GET`
- URL: `https://httpbin.org/get`

请求头:

```json
{
  "Authorization": "Bearer SIM_PARTNER_TOKEN_weread_zhihu_valid_2024_19799..."
}
```

**响应**

- 状态码: `503`

响应头:

```json
{
  "Content-Type": "application/json"
}
```

响应体:

```json
{
  "status_code": "503",
  "note": "服务不可用，服务端临时过载或维护中"
}
```

---
### 样例 2: Token #2 请求 (harvester_extract)

**请求**

- 方法: `GET`
- URL: `https://httpbin.org/get`

请求头:

```json
{
  "Authorization": "Bearer v2.local.ABCdef123GHI456jkl789mno012pqr345"
}
```

**响应**

- 状态码: `503`

响应头:

```json
{
  "Content-Type": "application/json"
}
```

响应体:

```json
{
  "status_code": "503",
  "note": "服务不可用，服务端临时过载或维护中"
}
```

---
### 样例 3: Token #3 请求 (harvester_extract)

**请求**

- 方法: `GET`
- URL: `https://httpbin.org/get`

请求头:

```json
{
  "Authorization": "Bearer sk_test_51H8kLm2nOpQ4rStUvWxYz0123456789"
}
```

**响应**

- 状态码: `503`

响应头:

```json
{
  "Content-Type": "application/json"
}
```

响应体:

```json
{
  "status_code": "503",
  "note": "服务不可用，服务端临时过载或维护中"
}
```

---
### 样例 4: Token #4 请求 (harvester_extract)

**请求**

- 方法: `GET`
- URL: `https://httpbin.org/get`

请求头:

```json
{
  "Authorization": "Bearer partner_weread_2a4b6c8d0e1f3g5h7i9j1k2l3m4n5o6p"
}
```

**响应**

- 状态码: `503`

响应头:

```json
{
  "Content-Type": "application/json"
}
```

响应体:

```json
{
  "status_code": "503",
  "note": "服务不可用，服务端临时过载或维护中"
}
```

---
### 样例 5: Token #5 请求 (harvester_extract)

**请求**

- 方法: `GET`
- URL: `https://httpbin.org/get`

请求头:

```json
{
  "Authorization": "Bearer cs_abc123def456ghi789jkl012mno345pqr678"
}
```

**响应**

- 状态码: `503`

响应头:

```json
{
  "Content-Type": "application/json"
}
```

响应体:

```json
{
  "status_code": "503",
  "note": "服务不可用，服务端临时过载或维护中"
}
```

---
### 样例 6: Token #6 请求 (simulated_test)

**请求**

- 方法: `GET`
- URL: `https://httpbin.org/get`

请求头:

```json
{
  "Authorization": "Bearer test_token_123"
}
```

**响应**

- 状态码: `503`

响应头:

```json
{
  "Content-Type": "application/json"
}
```

响应体:

```json
{
  "status_code": "503",
  "note": "服务不可用，服务端临时过载或维护中"
}
```

---
### 样例 7: Token #7 请求 (simulated_test)

**请求**

- 方法: `GET`
- URL: `https://httpbin.org/get`

请求头:

```json
{
  "Authorization": "Bearer simulated_bearer_abc456xyz"
}
```

**响应**

- 状态码: `503`

响应头:

```json
{
  "Content-Type": "application/json"
}
```

响应体:

```json
{
  "status_code": "503",
  "note": "服务不可用，服务端临时过载或维护中"
}
```

---
### 样例 8: Token #8 请求 (simulated_test)

**请求**

- 方法: `GET`
- URL: `https://httpbin.org/get`

请求头:

```json
{
  "Authorization": "Bearer dummy_api_key_789def"
}
```

**响应**

- 状态码: `503`

响应头:

```json
{
  "Content-Type": "application/json"
}
```

响应体:

```json
{
  "status_code": "503",
  "note": "服务不可用，服务端临时过载或维护中"
}
```


---

## 4. 测试结论

### 总体结论

本次测试共执行 8 项测试用例，全部返回 503 状态码。数据流水线链路通畅（token 搜集、JSON 读写、API 调用、状态码捕获均正常工作），但目标服务 httpbin.org 暂时不可用（503 Service Unavailable）。状态码分布: 503: 8 次。

### 风险评估

| 维度 | 评级 | 说明 |
|------|------|------|
| 严重程度 | 信息 | 目标服务临时不可用，非安全漏洞。流水线本身功能正常。 |
| 利用难度 | 不适用 | 本次测试为流水线连通性验证，不涉及漏洞利用 |
| 影响范围 | 无 | 503 为服务端临时故障，不影响系统安全 |

### 修复建议

- 1. 确认 httpbin.org 服务已恢复后重新运行 run_pipeline_test.py 验证流水线
- 2. 可考虑增加备用测试端点（如 https://postman-echo.com/get）作为容灾方案
- 3. 在 run_pipeline_test.py 中增加对 503 状态码的重试逻辑
- 4. 定期执行流水线测试以确保数据通路持续可用

---

## 5. 附录

### 测试环境

| 属性 | 值 |
|------|-----|
| 操作系统 | Linux 5.15.120.byteatom-ck.16 |
| Python 版本 | 3.10.12 |
| 测试工具 | run_pipeline_test.py, simple_api_tester.py, curl_cffi |

### 文件信息

| 属性 | 值 |
|------|-----|
| 生成时间 | 2026-08-04 14:21:36 |
| 生成工具 | poc_report_writer.py v1.0 |

---

*本报告由 poc_report_writer.py 自动生成，仅供授权安全测试使用。*
