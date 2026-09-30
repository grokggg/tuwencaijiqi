import requests
import re

COOKIES = {}  # 先不填Cookie试一次
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 Zhihu/9.28.0",
    "Referer": "https://www.zhihu.com/",
}

target_url = "https://oia.zhihu.com/km_paid_content/share?km_pst=3AYY8ESOBxAnZmkzyr8r5Xkyk-QmglmuP1pNme3a7WkfGwPf_vuVLXJepqOCUXwRXHIs-8r6rSVeXtiTWBS39f78mVXJA00nsoJ45UHK5Xx-2n4%3D&share_code=RMmzFvaqNgvU&utm_psn=2067376697343844450"

# 从URL提取km_pst和share_code
km_pst = re.search(r'km_pst=([^&]+)', target_url).group(1)
share_code = re.search(r'share_code=([^&]+)', target_url).group(1)

# 尝试调用API
api_url = "https://oia.zhihu.com/km_paid_content/api/content"
params = {
    "km_pst": km_pst,
    "share_code": share_code,
}
session = requests.Session()
resp = session.get(api_url, params=params, headers=HEADERS, timeout=15)
print(f"API状态码: {resp.status_code}")
print(f"返回内容: {resp.text[:1000]}")
