"""Patchright 同步脚本 —— 打开 BOSS 首页，等待用户确认后退出。

启动参数与 PatchrightEngine.init() 保持一致，额外硬编码代理配置。
"""

import asyncio
from pathlib import Path
from patchright.sync_api import sync_playwright

PROFILE_DIR = Path('~/code/job-buddy/data/chrome_profile').expanduser()
HOME_URL = "https://www.zhipin.com/"

# 代理配置（硬编码）
PROXY = {
	"server": "http://127.0.0.1:8080",
	# "username": "",
	# "password": "",
}

profile_dir = PROFILE_DIR.resolve()
profile_dir.mkdir(parents=True, exist_ok=True)

playwright = sync_playwright().start()

context = playwright.chromium.launch_persistent_context(
	user_data_dir=str(profile_dir),
	channel="chrome",
	# ignore_https_errors=True, # 无效，在浏览器手动导入证书
	headless=False,
	slow_mo=300,
	no_viewport=True,
	proxy=PROXY,
	args=[
		"--disable-blink-features=AutomationControlled",
		"--start-maximized",
	],
)

page = context.pages[0] if context.pages else context.new_page()
page.goto(HOME_URL)
# page.wait_for_load_state("domcontentloaded")

# ── DOM 提取示例 ──────────────────────────────────────────
# # 提取页面全局变量 _PAGE
# page_data = page.evaluate("() => window._PAGE")
# print(page_data)
#
# # 获取页面标题
# title = page.evaluate("document.title")
# print("页面标题:", title)
#
# # 提取内联脚本中的 JSON 数据
# inline_scripts = page.evaluate(
#     """() => Array.from(document.scripts)
#         .filter(s => !s.src)
#         .map(s => s.textContent)
#     """
# )
# import re
# for script_text in inline_scripts:
#     match = re.search(r"_PAGE\s*=\s*({.*?})\s*###", script_text, re.S)
#     if match:
#         print(match.group(1))
#         break

# ── JSON 请求示例（在浏览器上下文中发送 fetch）────────────
# # 搜索职位
# result = page.evaluate(
#     """
#     async () => {
#         const resp = await fetch(
#             "https://www.zhipin.com/wapi/zpgeek/search/joblist.json?query=Python&page=1",
#             {
#                 method: "GET",
#                 credentials: "include",
#                 headers: {
#                     "Accept": "application/json, text/plain, */*",
#                     "X-Requested-With": "XMLHttpRequest",
#                 },
#                 referrer: "https://www.zhipin.com/web/geek/job",
#             },
#         );
#         return await resp.json();
#     }
#     """
# )
# print(result)
#
# # 获取好友列表
# friends = page.evaluate(
#     """
#     async () => {
#         const resp = await fetch(
#             "https://www.zhipin.com/wapi/zprelation/friend/getGeekFriendList.json?page=1",
#             {
#                 method: "GET",
#                 credentials: "include",
#                 headers: {
#                     "Accept": "application/json, text/plain, */*",
#                     "X-Requested-With": "XMLHttpRequest",
#                 },
#                 referrer: "https://www.zhipin.com/web/geek/chat",
#             },
#         );
#         return await resp.json();
#     }
#     """
# )
# print(friends)
#
# # 获取聊天历史
# messages = page.evaluate(
#     """
#     async () => {
#         const resp = await fetch(
#             "https://www.zhipin.com/wapi/zpchat/geek/historyMsg?gid=xxx&securityId=xxx&page=1&c=20&src=0",
#             {
#                 method: "GET",
#                 credentials: "include",
#                 headers: {
#                     "Accept": "application/json, text/plain, */*",
#                     "X-Requested-With": "XMLHttpRequest",
#                 },
#                 referrer: "https://www.zhipin.com/web/geek/chat",
#             },
#         );
#         return await resp.json();
#     }
#     """
# )
# print(messages)

input("按 Enter 退出...")
