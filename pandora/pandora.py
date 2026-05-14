chromium_launch_other = dict(args=["--disable-blink-features=AutomationControlled"],
                             ignore_default_args=["--enable-automation"])
init_script = """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.navigator.chrome = {runtime: {}};
        Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
        Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
        """

chromium_launch_other = dict()
init_script = ''
