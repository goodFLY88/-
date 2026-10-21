"""全自动滑块登录模块(优化版补齐)。

背景:auth.py 自始就引用本模块(deps_ready/missing_packages/auto_install_deps/AutoSlider),
但原仓库里并没有这个文件,导致"全自动滑块登录"实际永远走 ImportError → 直接转人工。
本模块按 auth.py 期望的接口补齐实现。

依赖:playwright + opencv-python + numpy + pillow(scipy 可选,仅用于轨迹平滑)。
这些依赖不打包进 APK(buildozer.spec 不含),安卓端缺失时自动转人工登录,
与 README "不打包滑块依赖" 的承诺一致。

流程:
1. AutoSlider.start()   后台线程启动无头 Chromium,打开 SSO 登录页并预热
2. obtain_sso_token()   填账密 → 提交 → 等滑块 → OpenCV 定位缺口 → 人类化拖拽
                        → 拦截 userLoginV2 响应提取 sso_token
3. AutoSlider.close()   关闭浏览器

失败安全:任何一步失败都返回 None,由 auth.py 转人工回调登录,不会卡死。

注意:平台前端改版后选择器可能失效。所有选择器集中在 SELECTORS 常量区,失效时
只需改这一处;算法本身(缺口定位/轨迹生成)与页面结构无关。
本模块未经真实账号环境验证,失败即回退人工流程属预期行为。
"""

import importlib.util
import random
import subprocess
import sys
import threading
import time

# ==================== 依赖管理 ====================

# 模块名 → pip 包名
REQUIRED_PACKAGES = {
    "playwright": "playwright",
    "cv2": "opencv-python",
    "numpy": "numpy",
    "PIL": "pillow",
}


def missing_packages() -> list:
    """返回缺失的 pip 包名列表(空列表 = 依赖就绪)。"""
    missing = []
    for module_name, pip_name in REQUIRED_PACKAGES.items():
        try:
            if importlib.util.find_spec(module_name) is None:
                missing.append(pip_name)
        except Exception:
            missing.append(pip_name)
    return missing


def deps_ready() -> bool:
    """滑块登录依赖是否就绪。"""
    return not missing_packages()


def auto_install_deps() -> bool:
    """自动安装缺失依赖(含 Chromium 内核)。失败返回 False。"""
    if deps_ready():
        return True
    missing = missing_packages()
    log_prefix = "[自动登录]"
    try:
        print(f"{log_prefix} 正在安装: {' '.join(missing)} ...", flush=True)
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", *missing],
            check=True, timeout=600,
        )
        print(f"{log_prefix} 正在下载 Chromium 内核(约 150MB)...", flush=True)
        subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            check=True, timeout=900,
        )
    except Exception as e:
        print(f"{log_prefix} 安装失败: {e}", flush=True)
        return False
    return deps_ready()


# ==================== 页面选择器(平台改版时只改这里) ====================

SELECTORS = {
    # 账号/密码输入框(按优先级尝试,命中第一个可见的)
    "account_input": [
        "input[placeholder*='账号']",
        "input[placeholder*='学号']",
        "input[name='username']",
        "input[type='text']",
    ],
    "password_input": [
        "input[placeholder*='密码']",
        "input[name='password']",
        "input[type='password']",
    ],
    # 登录提交按钮
    "submit_button": [
        "button:has-text('登录')",
        "button:has-text('登 录')",
        "div[class*='login-btn']",
        "button[type='submit']",
    ],
    # 阿里云滑块(NC)组件:滑块按钮 / 背景图 / 刷新按钮
    "slider_button": [
        "#nc_1_n1z",
        ".nc_iconfont.btn_slide",
        "[class*='slide-btn']",
        "[class*='slider-btn']",
    ],
    "slider_bg_img": [
        "#nc_1_scale",
        ".nc-lang-cnt img",
        "[class*='slide-bg'] img",
        "[class*='slider-bg'] img",
    ],
    "slider_refresh": [
        "#nc_1_refresh1",
        ".nc_iconfont.btn_refresh",
        "[class*='slide-refresh']",
    ],
    # 滑块成功后可能出现的"点击图片重试"等
    "slider_retry": [
        ".errloading",
        "[class*='slide-retry']",
    ],
}

# 拖拽轨迹参数
_DRAG_MIN_STEPS = 18
_DRAG_MAX_STEPS = 45


# ==================== 工具函数 ====================

def _extract_token_from(data) -> str:
    """从登录响应 JSON 里提取 token,兼容 dict / 裸字符串。"""
    if not data:
        return ""
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        d = data.get("data")
        if isinstance(d, dict):
            return d.get("access_token") or d.get("token") or ""
        if isinstance(d, str):
            return d
    return ""


def _first_visible(page, selector_list, timeout_ms=3000):
    """按优先级返回第一个可见的元素句柄;都没有返回 None。"""
    for sel in selector_list:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=timeout_ms):
                return loc
        except Exception:
            continue
    return None


def _find_gap_x(bg_bytes: bytes, slider_bytes: bytes) -> int:
    """OpenCV 定位滑块缺口在背景图中的 x 坐标(像素)。

    策略一:带透明通道的滑块图做模板匹配(TM_SQDIFF_NORMED + mask);
    策略二:滑块图不可用时,对背景图右半部分做竖边缘能量检测,取能量最大列。
    都失败返回 0(调用方会放弃本次尝试)。
    """
    def _decode(b):
        import cv2
        import numpy as np
        arr = np.frombuffer(b, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_UNCHANGED)

    try:
        import cv2
        import numpy as np
        bg = _decode(bg_bytes)
        if bg is None:
            return 0
        # 统一转 BGR(去 alpha),后续按 3 通道处理
        if bg.shape[2] == 4:
            bg = cv2.cvtColor(bg, cv2.COLOR_BGRA2BGR)
        bg_gray = cv2.cvtColor(bg, cv2.COLOR_BGR2GRAY)

        if slider_bytes:
            sl = _decode(slider_bytes)
            if sl is not None:
                if sl.shape[2] == 4:
                    alpha = sl[:, :, 3]
                    sl_bgr = cv2.cvtColor(sl, cv2.COLOR_BGRA2BGR)
                else:
                    alpha = None
                    sl_bgr = sl
                if sl_bgr.shape[1] < bg_gray.shape[1] and sl_bgr.shape[0] < bg_gray.shape[0]:
                    try:
                        res = cv2.matchTemplate(bg_gray, cv2.cvtColor(sl_bgr, cv2.COLOR_BGR2GRAY),
                                                cv2.TM_SQDIFF, mask=alpha)
                        _min_val, _max_val, min_loc, _max_loc = cv2.minMaxLoc(res)
                        return int(min_loc[0])
                    except Exception:
                        pass

        # 策略二:背景图竖边缘能量(缺口两侧边缘最密集)
        edges = cv2.Canny(bg_gray, 80, 200)
        col_energy = edges.sum(axis=0)
        h, w = bg_gray.shape
        # 只看右 2/3(缺口不会在最左边),并给左边缘一点权重衰减
        start = int(w * 0.25)
        region = col_energy[start:]
        if region.size == 0:
            return 0
        return int(start + int(np.argmax(region)))
    except Exception:
        return 0


def _humanized_drag(page, box, distance: int) -> None:
    """人类化拖拽:先微退、再加速、后减速,叠加随机抖动与垂直漂移。"""
    start_x = box["x"] + box["width"] / 2
    start_y = box["y"] + box["height"] / 2
    page.mouse.move(start_x, start_y)
    time.sleep(random.uniform(0.10, 0.30))
    page.mouse.down()
    time.sleep(random.uniform(0.05, 0.15))

    steps = random.randint(_DRAG_MIN_STEPS, _DRAG_MAX_STEPS)
    # 前 10% 轻微回退(模拟人手对准),再前进
    back = random.uniform(1.0, 4.0) if distance > 30 else 0.0
    for i in range(max(3, steps // 8)):
        page.mouse.move(start_x - back * (i + 1) / max(3, steps // 8),
                        start_y + random.uniform(-1.5, 1.5))
        time.sleep(random.uniform(0.008, 0.02))

    moved = 0.0
    for i in range(1, steps + 1):
        p = i / steps
        # ease-out:前快后慢
        ease = 1 - (1 - p) ** 2.2
        target = distance * ease
        # 叠加 ±2px 横向抖动(末尾收敛)
        jitter = random.uniform(-2, 2) * (1 - p)
        page.mouse.move(start_x + target + jitter,
                        start_y + random.uniform(-2.0, 2.0))
        moved = target
        time.sleep(random.uniform(0.006, 0.022))

    # 到位后微小过冲 + 回正(常见人类特征)
    if distance > 20:
        page.mouse.move(start_x + moved + random.uniform(0.5, 2.0), start_y + random.uniform(-1, 1))
        time.sleep(random.uniform(0.03, 0.08))
        page.mouse.move(start_x + moved - random.uniform(0.2, 1.0), start_y)
    time.sleep(random.uniform(0.08, 0.20))
    page.mouse.up()


# ==================== 主类 ====================

class AutoSlider:
    """无头浏览器自动过滑块登录器。

    用法:
        sess = AutoSlider()
        sess.start()                                  # 后台预热(与输账密并行)
        token = sess.obtain_sso_token(user, pwd)      # 失败返回 None
        sess.close()
    """

    def __init__(self):
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None
        self._sso_token = ""
        self._token_event = threading.Event()
        self._ready_event = threading.Event()
        self._launch_error = ""
        self._login_url = (
            "https://sso.icve.com.cn/h5/?mode=simple&source=15"
            "&redirect=http://127.0.0.1:9527#/login"
        )

    # ---------- 生命周期 ----------

    def start(self) -> None:
        """后台线程启动浏览器并加载登录页(不阻塞,失败记录错误)。"""
        threading.Thread(target=self._launch, name="slider-warmup", daemon=True).start()

    def _launch(self) -> None:
        try:
            from playwright.sync_api import sync_playwright
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled",
                      "--no-sandbox"],
            )
            self._context = self._browser.new_context(
                user_agent=("Mozilla/5.0 (Linux; Android 15; Pixel 8) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/128.0.0.0 Mobile Safari/537.36"),
                viewport={"width": 390, "height": 844},
                locale="zh-CN",
            )
            self._page = self._context.new_page()
            self._page.on("response", self._on_response)
            self._page.goto(self._login_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            self._launch_error = str(e)
        finally:
            self._ready_event.set()

    def close(self) -> None:
        """关闭浏览器,释放资源(幂等)。"""
        for closer in (self._context, self._browser, self._pw):
            try:
                if closer is not None:
                    if hasattr(closer, "close"):
                        closer.close()
                    elif hasattr(closer, "stop"):
                        closer.stop()
            except Exception:
                pass
        self._page = None

    # ---------- 响应拦截 ----------

    def _on_response(self, resp) -> None:
        """拦截登录响应拿 token(userLoginV2 / passLogin)。"""
        try:
            url = resp.url
            if "userLoginV2" in url or "passLogin" in url or "login" in url:
                try:
                    data = resp.json()
                except Exception:
                    return
                tok = _extract_token_from(data)
                if tok:
                    self._sso_token = tok
                    self._token_event.set()
        except Exception:
            pass

    # ---------- 主流程 ----------

    def obtain_sso_token(self, username: str, password: str,
                         max_attempts: int = 2):
        """填账密 → 过滑块 → 返回 sso_token;任一步失败返回 None。"""
        if not self._ready_event.wait(timeout=45):
            return None
        if self._page is None:
            return None

        for attempt in range(1, max_attempts + 1):
            if self._token_event.is_set():
                return self._sso_token
            try:
                if self._fill_and_submit(username, password):
                    # 提交成功 → 等滑块出现并尝试过滑块
                    if self._solve_slider():
                        if self._token_event.wait(timeout=10):
                            return self._sso_token
                # 直接登录(无滑块)的场合:提交后稍等 token
                if self._token_event.wait(timeout=3):
                    return self._sso_token
            except Exception:
                pass
            # 失败重试:刷新页面重来(滑块组件需重新触发)
            try:
                self._page.reload(wait_until="domcontentloaded", timeout=20000)
            except Exception:
                return None
        return self._sso_token if self._token_event.is_set() else None

    def _fill_and_submit(self, username: str, password: str) -> bool:
        """填写账密并提交。成功返回 True。"""
        page = self._page
        acc = _first_visible(page, SELECTORS["account_input"], timeout_ms=2000)
        if acc is None:
            return False
        acc.click()
        acc.fill(username)
        time.sleep(0.3)

        pwd = _first_visible(page, SELECTORS["password_input"], timeout_ms=2000)
        if pwd is None:
            return False
        pwd.click()
        pwd.fill(password)
        time.sleep(0.3)

        btn = _first_visible(page, SELECTORS["submit_button"], timeout_ms=2000)
        if btn is None:
            return False
        btn.click()
        return True

    def _solve_slider(self) -> bool:
        """检测并尝试过一次滑块。无滑块返回 True(视为无需验证)。"""
        page = self._page
        # 滑块通常在提交后 1~3 秒出现
        slider = None
        for _ in range(20):
            slider = _first_visible(page, SELECTORS["slider_button"], timeout_ms=500)
            if slider is not None:
                break
            if self._token_event.is_set():
                return True
            time.sleep(0.25)
        if slider is None:
            # 没等到滑块:可能直接登录成功,也可能没有触发验证码
            return True

        box = slider.bounding_box()
        if not box:
            return False
        bg = _first_visible(page, SELECTORS["slider_bg_img"], timeout_ms=2000)
        if bg is None:
            return False

        gap_x = 0
        try:
            bg_bytes = bg.screenshot()
            # 滑块小图:从 DOM 属性里拿 src,没有就用纯边缘检测
            slider_src = page.evaluate(
                """() => {
                    const img = document.querySelector('#nc_1_n1z, [class*="slide-btn"] img, [class*="slider-btn"] img');
                    return img ? img.src : '';
                }"""
            )
            slider_bytes = b""
            if slider_src:
                try:
                    resp = page.request.get(slider_src)
                    if resp.ok:
                        slider_bytes = resp.body()
                except Exception:
                    pass
            gap_x = _find_gap_x(bg_bytes, slider_bytes)
        except Exception:
            return False

        if gap_x <= 0:
            # 定位失败:点刷新后放弃本次(交给重试或人工)
            self._click_refresh()
            return False

        # 背景图渲染宽度 vs 原始宽度换算(背景图通常是缩放的)
        distance = gap_x
        try:
            bg_box = bg.bounding_box()
            img_w = page.evaluate(
                """() => {
                    const img = document.querySelector('#nc_1_scale, [class*="slide-bg"] img, [class*="slider-bg"] img');
                    return img ? img.naturalWidth : 0;
                }"""
            )
            if bg_box and img_w and bg_box["width"]:
                distance = int(gap_x * (bg_box["width"] / img_w))
        except Exception:
            pass

        _humanized_drag(page, box, distance)
        # 拖完给平台一点校验时间
        time.sleep(1.2)
        return not self._slider_error_visible()

    def _slider_error_visible(self) -> bool:
        """滑块区域是否出现错误提示(验证失败)。"""
        try:
            for sel in SELECTORS["slider_retry"]:
                loc = self._page.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=300):
                    return True
        except Exception:
            pass
        return False

    def _click_refresh(self) -> None:
        """点击滑块刷新按钮(重置验证码)。"""
        try:
            btn = _first_visible(self._page, SELECTORS["slider_refresh"], timeout_ms=800)
            if btn is not None:
                btn.click()
        except Exception:
            pass
