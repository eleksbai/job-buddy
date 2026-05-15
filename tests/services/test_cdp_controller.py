import asyncio

from job_buddy.core.boss import CdpBrowserController, CdpStatusResult
from job_buddy.core.config import Settings


class FakeController(CdpBrowserController):
    def __init__(self) -> None:
        super().__init__(Settings())
        self.running = False

    async def get_status(self) -> CdpStatusResult:
        return CdpStatusResult(
            running=self.running,
            port=9222,
            cdp_url="http://127.0.0.1:9222",
            browser="Chrome" if self.running else None,
            websocket_url="ws://127.0.0.1:9222/devtools/browser/demo" if self.running else None,
            pid=1234 if self.running else None,
            message="CDP 在线" if self.running else "CDP 未运行",
        )

    async def start_browser(self) -> CdpStatusResult:
        self.running = True
        return await self.get_status()

    async def stop_browser(self) -> CdpStatusResult:
        self.running = False
        return await self.get_status()


def test_fake_cdp_controller_toggles_status():
    controller = FakeController()

    stopped = asyncio.run(controller.get_status())
    started = asyncio.run(controller.start_browser())
    stopped_again = asyncio.run(controller.stop_browser())

    assert stopped.running is False
    assert started.running is True
    assert stopped_again.running is False
