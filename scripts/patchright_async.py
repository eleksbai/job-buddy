"""Patchright 异步脚本 —— 打开 BOSS 首页，保持浏览器常驻直到手动中断。

启动参数与 scripts/patchright_sync.py 保持一致，额外硬编码代理配置。
适合在本地直接运行后观察页面、网络请求或手动调试。
不要有 input，退出请使用 Ctrl+C。

Ipython 中要拉起主循环
%autoawait asyncio
ipython 在shell是不在携程环境里面的
只有在执行await才会进入携程环境里面。

"""

from __future__ import annotations

import asyncio
from pathlib import Path

from patchright.async_api import Response, async_playwright

PROFILE_DIR = Path("~/code/job-buddy/data/chrome_profile").expanduser()
HOME_URL = "https://www.zhipin.com/"

# 代理配置（硬编码）
PROXY = {
    "server": "http://127.0.0.1:8080",
    # "username": "",
    # "password": "",
}


async def on_response(response: Response) -> None:
    url = response.url
    # 只看接口请求，避免图片/css/js太多
    if "list.json" not in url:
        return
    print("=" * 80)
    print("URL:", url)
    print("STATUS:", response.status)

    try:
        data = await response.json()
        print("JSON:", data)
    except Exception:
        try:
            text = await response.text()
            print("TEXT:", text[:1000])
        except Exception as exc:
            print("READ ERROR:", exc)


async def add_listener(page):
    page.on("response", on_response)


async def main() -> None:
    profile_dir = PROFILE_DIR.resolve()
    profile_dir.mkdir(parents=True, exist_ok=True)

    playwright = await async_playwright().start()
    context = None
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        channel="chrome",
        headless=False,
        slow_mo=300,
        no_viewport=True,
        proxy=PROXY,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ],
    )

    page = context.pages[0] if context.pages else await context.new_page()
    await page.goto(HOME_URL)
    # 这个监听时间无法在这里加
    # page.on("response", on_response)
    # await add_listener(page)
    await page.goto(HOME_URL)
    """
    page.locator("div.c-expect-select > a.synthesis").click()

      div.job-info > div.job-title

      page.locator('div.job-info > div.job-title')
      page.locator('div.job-info > div.job-title')
      page.locator("div.job-info > div.job-title").nth(2).click()

    """


    # 保持浏览器常驻，便于手动调试。退出请 Ctrl+C。
    # await asyncio.Event().wait()


if __name__ == "__main__":
    asyncio.run(main())
