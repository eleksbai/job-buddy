import asyncio
from patchright.async_api import async_playwright

async def main():
    playwright = await async_playwright().start()


    # 启动浏览器 最强反爬配置
    browser = await playwright.chromium.launch(
        channel="chrome",
        headless=False,
        slow_mo=300,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--start-maximized"
        ]
    )

    # 创建上下文+页面
    context = await browser.new_context(no_viewport=True)
    page = await context.new_page()

    # 访问页面
    await page.goto("https://www.baidu.com")

    # 输入搜索
    await page.fill("#chat-textarea", "patchright 异步使用")
    await page.click("#chat-submit-button")

    # 等待加载
    await page.wait_for_timeout(2000)

    # 获取标题
    title = await page.evaluate("document.title", isolated_context=True)
    print("页面标题：", title)

    # 截图
    await page.screenshot(path="async_screenshot.png")

    # 关闭
    await browser.close()

if __name__ == "__main__":
    asyncio.run(main())
