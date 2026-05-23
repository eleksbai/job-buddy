"""Patchright 同步脚本 —— 打开 BOSS 首页，等待用户确认后退出。

启动参数与 PatchrightEngine.init() 保持一致，额外硬编码代理配置。
在pycharm 的python控制台运行就可以获取到对应变量。
不要有input

"""
from random import random

from pathlib import Path
from patchright.sync_api import sync_playwright

from job_buddy.boss.config import URL_JOB_LIST_BY_SCROLL

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
# def on_response(response):
#     url = response.url
#     # 只看接口请求，避免图片/css/js太多
#     if "list.json" not in url:
#         return
#     print("=" * 80)
#     print("URL:", url)
#     print("STATUS:", response.status)
#
#     try:
#         data = response.json()
#         print("JSON:", data)
#     except Exception:
#         try:
#             text = response.text()
#             print("TEXT:", text[:1000])
#         except Exception as e:
#             print("READ ERROR:", e)

def on_response(response) -> None:
    if URL_JOB_LIST_BY_SCROLL not in response.url:
        return
    data = response.json()
    print(data)


"""


page.on("response", on_response)
page.mouse.wheel(0, 1000 + random() * 1000)

"""

# # 提取页面全局变量 _PAGE
# html = page.content()
# Path("data/c.html").write_text(html, encoding="utf-8")
#  获取推荐列表
# page.locator("div.c-expect-select > a.synthesis").click()
# 获取第2个职位
# page.locator("div.c-expect-select > div.expect-list.has-add.no-part > a").count()
# page.locator("div.c-expect-select > div.expect-list.has-add.no-part > a").nth(1).click()
# div.c-expect-select > div.expect-list.has-add.no-part > a:nth-child(2)
# # 提取页面全局变量 _PAGE
# page_data = page.evaluate("() => window._PAGE")
# print(page_data)
#
# # 获取页面标题
# title = page.evaluate("document.title")
# print("页面标题:", title)

# 获取页面高度
# page.evaluate( "document.body.scrollHeight" )
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
if __name__ == '__main__':
    input("按 Enter 退出...")
