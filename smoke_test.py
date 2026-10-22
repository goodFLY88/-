# -*- coding: utf-8 -*-
"""GUI 冒烟测试：启动 App 并逐个切页，抓 on_pre_enter / build 的异常。
在 ICVE-Toolkit 目录下运行：
    python smoke_test.py
Kivy 要求 App.run() 与所有 UI 操作都在主线程，切页用 Clock 分步调度。
"""
import os
import sys

os.environ.setdefault("KIVY_NO_ARGS", "1")

from kivy.clock import Clock

from main import ICVEApp

PAGES = ["dashboard", "accounts", "courses", "speed", "answer", "sign", "login"]
FAILED = []


class SmokeApp(ICVEApp):
    def on_start(self):
        super().on_start()
        Clock.schedule_once(self._next_page, 1.0)

    def _next_page(self, dt):
        try:
            if PAGES:
                page = PAGES.pop(0)
                print(f"[smoke] goto {page}")
                self.goto(page)
                Clock.schedule_once(self._next_page, 0.4)
            else:
                print("[smoke] all pages OK")
                self.stop()
        except Exception:
            import traceback
            FAILED.append(traceback.format_exc())
            self.stop()


if __name__ == "__main__":
    app = SmokeApp()
    app.run()
    if FAILED:
        print("==== SMOKE TEST FAILED ====")
        for e in FAILED:
            print(e)
        sys.exit(1)
    print("==== SMOKE TEST PASSED: build + 7 pages navigation OK ====")
