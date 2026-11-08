# -*- coding: utf-8 -*-
"""ICVE 安卓版（KivyMD）—— 桌面版布局：侧边抽屉导航 + 独立功能页

优化版修订记录(相对原 APK工程/main.py):
1. 退出登录现在会真正清除会话(原来只切页面,账号状态灯仍显示已登录)
2. goto() 不再重复触发 on_pre_enter(原来 sm.current 切换 + 手动调用 → 课程列表加载两遍)
3. 功能页增加未登录保护(原来未登录点进去静默显示空列表)
4. 账号删除增加二次确认(原来点一下即删)
5. "我的课程"页改为只读浏览(原来按钮是"开始刷课",与刷课页重复且文不对题)
6. 签到类型/状态映射统一改用 sign.SIGN_TYPE_MAP / SIGN_STATUS_MAP
   (原文件内自带一份与 zjy_client 分支矛盾的映射:2/3 类型互换)
7. custom_sign 工作线程补 try/except(原来异常时线程静默死亡)
8. 刷课接入 progress_cb,日志实时显示阶段进度
9. 自动监听签到:统一类型映射 + client 掉线保护 + on_stop 时停止
10. 登录成功后清空输入框
"""

import re
import sys
import threading
import time

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from kivymd.uix.list import MDList, OneLineListItem, TwoLineListItem
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.label import MDLabel
from kivymd.uix.dialog import MDDialog
from kivymd.uix.card import MDCard
from kivymd.uix.navigationdrawer import MDNavigationDrawer, MDNavigationLayout

from zjy_client import ZjyClient, SSO_BASE
from auth import _exchange_token
from speed_course import run_speed_course
from answer import get_course_exams_list, run_auto_answer_all_task
from sign import (get_signs, batch_sign, do_sign_action,
                  SIGN_TYPE_MAP, SIGN_STATUS_MAP)
from accounts import list_accounts, save_account, delete_account

from kivy.core.text import LabelBase
LabelBase.register(name="Roboto",
                   fn_regular="NotoSansSC.ttf",
                   fn_bold="NotoSansSC.ttf",
                   fn_italic="NotoSansSC.ttf",
                   fn_bolditalic="NotoSansSC.ttf")


def _patch_pil_rectangle():
    """兼容 kivymd 1.0.2 阴影绘制的负坐标 bug（治本）。

    kivymd 1.0.2 的 elevation.py __draw_shadow__ 在按钮 radius 超过半宽时
    算出 x1 < x0 的矩形，2024+ 的 Pillow 严格校验后直接
    ValueError: x1 must be greater than or equal to x0。

    重要：kivymd 传的是**两点式**坐标 [(x0, y0), (x1, y1)]，
    早期补丁只认 4 元素扁平式（len(xy)==4），判断失败后直接 raise，
    等于补丁从未生效——真机日志每帧刷这个 ValueError，Clock 里抛异常
    会把布局卡在半途（表现为头部被压扁、控件尺寸不对）。这里两种
    写法都归一化，并且兜底绝不向外抛。
    """
    try:
        from PIL import ImageDraw
    except ImportError:
        return
    _orig = ImageDraw.ImageDraw.rectangle

    def _norm(xy):
        """归一化为两点式并保证 x1>=x0, y1>=y0（int 化，避免截断反转）。"""
        if not isinstance(xy, (list, tuple)):
            return None
        try:
            if len(xy) == 4 and not isinstance(xy[0], (list, tuple)):
                x0, y0, x1, y1 = xy
            elif len(xy) >= 2 and isinstance(xy[0], (list, tuple)):
                (x0, y0), (x1, y1) = xy[0], xy[1]
            else:
                return None
            x0, y0, x1, y1 = int(x0), int(y0), int(x1), int(y1)
            return [(x0, y0), (max(x1, x0), max(y1, y0))]
        except Exception:
            return None

    def _safe_rectangle(self, xy, *args, **kwargs):
        try:
            return _orig(self, xy, *args, **kwargs)
        except ValueError:
            pass
        except Exception:
            return None
        fixed = _norm(xy)
        try:
            return _orig(self, fixed if fixed else [(0, 0), (0, 0)],
                         *args, **kwargs)
        except Exception:
            return None

    ImageDraw.ImageDraw.rectangle = _safe_rectangle


_patch_pil_rectangle()

APP_VERSION = "v1.3.13"


def _append_diag(text):
    """把诊断行追加到崩溃日志（/sdcard 优先，失败退回当前目录）。"""
    for p in ("/sdcard/icve_crash.log", "icve_crash.log"):
        try:
            with open(p, "a", encoding="utf-8") as f:
                f.write(text + "\n")
            return
        except Exception:
            continue

# ==================== 统一视觉规范（Galaxy 现代风格） ====================
# 主色（现代蓝）
PRIMARY = [0.23, 0.51, 0.96, 1]        # 主蓝 #3B82F6
PRIMARY_DARK = [0.17, 0.40, 0.85, 1]   # 深蓝 #2B6BD9
BG = [0.933, 0.945, 0.965, 1]          # 柔和冷调浅灰 #EEF1F6
CARD_BG = [1, 1, 1, 1]                  # 卡片纯白
SEPARATOR = [0.86, 0.88, 0.91, 1]      # 柔和分割线 #DBE0E8
TEXT_MAIN = [0.11, 0.13, 0.17, 1]      # 主文字（带冷调，非纯黑）#1C212B
TEXT_SUB = [0.45, 0.49, 0.55, 1]       # 次级文字 #737D8C
GREEN = [0.20, 0.70, 0.40, 1]          # 成功绿 #33B366
RED = [0.92, 0.27, 0.24, 1]            # 失败红 #EB453D
ORANGE = [0.96, 0.62, 0.14, 1]         # 警告橙 #F59E24
CARD_RADIUS = [dp(20), dp(20), dp(20), dp(20)]         # 卡片大圆角
BTN_RADIUS = [dp(14), dp(14), dp(14), dp(14)]          # 按钮圆角


def topbar(title, app=None):
    """iOS 风格顶栏：白底、黑字、hairline 分割线。"""
    bar = MDTopAppBar(title=title)
    bar.md_bg_color = CARD_BG
    bar.specific_text_color = TEXT_MAIN
    bar.elevation = 0
    if app is not None:
        bar.right_action_items = [["menu", lambda *_: app.nav_drawer.set_state("open")]]
    return bar


def menu_button(app):
    b = MDFlatButton(text="菜单", size_hint=(None, None), size=(dp(80), dp(35)), pos_hint={"left": 1})
    b.bind(on_release=lambda *_: app.nav_drawer.set_state("open"))
    return b


def section_label(text):
    """区块小标题。"""
    return MDLabel(text=text, theme_text_color="Custom", text_color=TEXT_SUB,
                   size_hint_y=None, height=dp(28), padding=(dp(16), dp(4)))


def _round_bg(w, color=None, radius=None):
    """给任意容器加圆角底（MDBoxLayout 本身不支持 radius，只能 canvas 画）。

    返回 (Color指令, RoundedRectangle)，调用方可改颜色实现选中态。
    """
    from kivy.graphics import Color, RoundedRectangle
    color = color or CARD_BG
    radius = radius or CARD_RADIUS
    with w.canvas.before:
        c = Color(*color)
        rect = RoundedRectangle(pos=w.pos, size=w.size, radius=radius)

    def _sync(*_):
        rect.pos = w.pos
        rect.size = w.size

    w.bind(pos=_sync, size=_sync)
    return c, rect


def make_card(**kw):
    """统一卡片容器（圆角白底）。自适应高度用 MDBoxLayout，可点击用 MDCard。

    MDCard 的 height 不会随内容自动撑开（真机实测导致内容互相重叠挤压），
    所以：
    - 自适应高度卡片 → MDBoxLayout（bind minimum_height + canvas 圆角底）
    - 可点击卡片（需 on_release）→ MDCard（固定 height，自带 radius）
    通过 clickable 参数区分。
    """
    clickable = kw.pop("clickable", False)
    height = kw.pop("height", None)
    padding = kw.pop("padding", (16, 14, 16, 14))
    if clickable:
        # 可点击：MDCard 固定高度（必须有明确 height）
        if height is None:
            height = 64
        card = MDCard(size_hint=(1, None), height=height,
                      md_bg_color=CARD_BG, radius=CARD_RADIUS,
                      elevation=0, padding=padding, **kw)
        return card
    # 自适应高度：MDBoxLayout + 圆角 canvas 底（md_bg_color 设透明，
    # 否则会同时画出方块背景，圆角外面露出直角）
    card = MDBoxLayout(orientation="vertical", size_hint_y=None,
                       md_bg_color=[1, 1, 1, 0], padding=padding, **kw)
    if height is not None:
        card.height = height
    else:
        card.bind(minimum_height=card.setter("height"))
    _round_bg(card)
    return card


def primary_button(text, height=dp(50), bg=None, **kw):
    """Galaxy 风格统一按钮：圆角、饱满、语义配色。"""
    btn = MDRaisedButton(text=text, size_hint=(1, None), height=height,
                         radius=BTN_RADIUS, md_bg_color=bg or PRIMARY, **kw)
    return btn


class TapRow(MDBoxLayout):
    """列表行容器（不处理触摸）。

    为什么不用 OneLineListItem / TwoLineListItem：它们是 ButtonBehavior，
    on_touch_down 会 grab 触摸，嵌在 ScrollView 里时滚动手势被吞掉
    （真机两次实测：换 MDDialog→ModalView 都没用，问题在行本身）。
    触摸判定统一交给 TapScrollView。
    """

    def __init__(self, on_tap=None, **kw):
        super().__init__(**kw)
        self.on_tap = on_tap
        self.size_hint_y = None
        self.padding = (dp(14), dp(10), dp(14), dp(10))
        self.spacing = dp(2)
        # 圆角卡片底（不抢触摸，纯绘制）
        self._bg_color, self._bg_rect = _round_bg(
            self, color=CARD_BG, radius=[dp(16), dp(16), dp(16), dp(16)])
        # 高度随内容自适应（中文字体放大时不挤压）
        self.bind(minimum_height=self.setter("height"))
        self.height = dp(72)

    def set_selected(self, flag):
        """选中态：浅蓝底 + 略深边框感。"""
        if flag:
            self._bg_color.rgba = [0.898, 0.933, 0.992, 1]   # #E5EEFD
        else:
            self._bg_color.rgba = CARD_BG


class TapScrollView(ScrollView):
    """可滚动 + 可点击行的 ScrollView。

    滚动和点击的冲突处理：按下时记录坐标，移动超过阈值标记为"滚动过"，
    抬起时若没移动过，就把起点坐标交给对应的行触发点击。
    这样既不抢触摸（滚动正常），又能精确响应点按。
    """

    def __init__(self, **kw):
        super().__init__(**kw)
        self.tap_rows = []
        self._down = None
        self._moved = False

    def _row_at(self, x, y):
        """把窗口坐标换算成内容坐标后找命中的行。

        关键：Kivy 的 ScrollView 滚动靠画布平移，子控件的 .y **不会**
        随滚动更新（实测：滚动前后 row[0].y 完全相同）。所以不能直接
        row.collide_point()，否则滑过之后再点就会命中错误的行
        （真机反馈"点击选择的课程不对"）。

        用 row.y - inner.y 求行相对内容底部的偏移：两者都是绝对坐标且
        不随滚动变化，差值精确，且不依赖行被嵌套了几层容器。
        """
        if not self.tap_rows or not self.children:
            return None
        inner = self.children[0]
        if inner.height > self.height:
            offset = (inner.height - self.height) * self.scroll_y
        else:
            offset = 0
        cy = offset + (y - self.y)
        for row in self.tap_rows:
            rel = row.y - inner.y
            if row.x <= x <= row.right and rel <= cy <= rel + row.height:
                return row
        return None

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self._down = (touch.x, touch.y, time.time())
            self._moved = False
        return super().on_touch_down(touch)

    def on_touch_move(self, touch):
        if self._down and not self._moved:
            x, y, _ = self._down
            if abs(touch.x - x) > dp(12) or abs(touch.y - y) > dp(12):
                self._moved = True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        res = super().on_touch_up(touch)
        d = self._down
        moved = self._moved
        self._down = None
        if d and not moved and time.time() - d[2] < 1.2:
            row = self._row_at(d[0], d[1])
            if row is not None and getattr(row, "on_tap", None):
                row.on_tap()
        return res


LOGIN_URL = f"{SSO_BASE}/h5/?mode=simple&source=15&redirect=http://127.0.0.1:9527#/login"


class SidebarMenu(BoxLayout):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.orientation = "vertical"
        self.padding = 0
        self.spacing = 0
        self.app = app
        from kivymd.uix.label import MDIcon
        # 顶部账号区（Galaxy 风格：主色背景 + 白色头像与文字）
        header = MDBoxLayout(size_hint_y=None, height=dp(140),
                             md_bg_color=PRIMARY, padding=(dp(20), dp(20), dp(20), dp(16)))
        self.avatar = MDIcon(icon="account-circle", theme_text_color="Custom",
                             text_color=[1, 1, 1, 1], size_hint=(None, None),
                             size=(dp(56), dp(56)), pos_hint={"center_x": 0.5})
        header.add_widget(self.avatar)
        self.name_label = MDLabel(text="未登录", theme_text_color="Custom",
                                  text_color=[1, 1, 1, 1], font_style="Subtitle1",
                                  halign="center", size_hint_y=None, height=dp(30))
        header.add_widget(self.name_label)
        self.stu_label = MDLabel(text="登录后显示学号", theme_text_color="Custom",
                                 text_color=[0.88, 0.92, 0.98, 1], halign="center",
                                 size_hint_y=None, height=dp(22))
        header.add_widget(self.stu_label)
        self.add_widget(header)
        # 菜单内容
        content = BoxLayout(orientation="vertical", padding=(dp(5), dp(10), dp(5), dp(10)), spacing=dp(1))
        content.add_widget(section_label("主功能"))
        for icon, label, target in [
            ("view-dashboard", "控制台", "dashboard"),
            ("play-circle", "一键刷课", "speed"),
            ("file-check", "自动答题", "answer"),
            ("calendar-check", "签到改签", "sign"),
            ("book-open-variant", "我的课程", "courses"),
        ]:
            content.add_widget(self._nav_item(icon, label, target))
        content.add_widget(section_label("系统"))
        for icon, label, target in [
            ("account-multiple", "账号管理", "accounts"),
            ("logout", "退出登录", "logout"),
        ]:
            content.add_widget(self._nav_item(icon, label, target))
        self.add_widget(content)

    def _nav_item(self, icon, label, target):
        from kivymd.uix.list import OneLineIconListItem
        from kivymd.uix.list import IconLeftWidget
        item = OneLineIconListItem(text=label, text_color=TEXT_MAIN)
        item.add_widget(IconLeftWidget(icon=icon, theme_text_color="Custom",
                                       text_color=PRIMARY))
        item.bind(on_release=lambda x, t=target: self._nav(t))
        return item

    def _nav(self, target):
        self.app.nav_drawer.set_state("close")
        if target == "logout":
            self.app.logout()
        else:
            self.app.goto(target)

    def refresh(self):
        if self.app.client and self.app.client.user_info:
            u = self.app.client.user_info
            self.name_label.text = u.get("nickName", "同学")
            self.stu_label.text = f"学号 {u.get('userName', '')}"
            self.avatar.icon = "account-circle"
        else:
            self.name_label.text = "未登录"
            self.stu_label.text = "登录后显示学号"
            self.avatar.icon = "account-circle-outline"


class LoginScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "login"
        self.app = app
        root = MDBoxLayout(orientation="vertical", md_bg_color=BG)

        # 状态栏占位条：高度由系统 inset 决定（初始 0），蓝底与标题栏连成
        # 一体，避免 inset 补偿后顶部露出一条突兀的浅灰空带。
        self.status_strip = MDBoxLayout(size_hint_y=None, height=0,
                                        md_bg_color=PRIMARY)
        root.add_widget(self.status_strip)

        # 顶部 LOGO 区（左图标 + 右两行文字）
        # 两个坑（真机 2K 屏实测）：
        # 1) MDIcon 在 __init__ 里强制 size_hint=(None,None)、size=texture_size，
        #    写 size_hint=(1,None), height=dp(64) 会被覆盖 → 图标缩成小点；
        # 2) 中文字体 H6(24sp) 实际行高 > 26dp，固定 26 会让标题溢出压住副标题
        #    （截图里两行文字叠在一起）。标题给 36dp、副标题 22dp。
        # 注意：这里必须用**固定高度**，不能用 adaptive_height。
        # MDIcon 在 __init__ 里 size=texture_size（此时还是 0），
        # adaptive_height 会在那一刻把 hrow/head 算成 0（只剩 padding），
        # 真机表现为蓝条被压到 ~30px、副标题溢出到蓝条外与标题重叠。
        head = MDBoxLayout(orientation="vertical", size_hint_y=None, height=dp(108),
                           md_bg_color=PRIMARY, padding=(dp(20), dp(18), dp(20), dp(18)))
        from kivymd.uix.label import MDIcon
        hrow = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(72),
                           spacing=dp(14))
        logo = MDIcon(icon="school", theme_text_color="Custom",
                      text_color=[1, 1, 1, 1], size_hint=(None, None),
                      size=(dp(44), dp(44)), pos_hint={"center_y": 0.5})
        hrow.add_widget(logo)
        # 用**单个** MDLabel + markup 做两行标题：一个控件不可能出现
        # 两行互相叠压（两 label 方案在真机上反复叠字，见 11-05 截图）。
        # 注意：markup 的 [size=n] 也是**像素**，必须传 dp 后的值，
        # 否则在 density 3.75 的真机上副标题只有 13px（截图里几乎看不见）。
        _sub_px = int(dp(15))
        htxt = MDLabel(
            text=("智慧职教 · 学习助手\n"
                  f"[color=#dbe6ff][size={_sub_px}]"
                  "登录 · 刷课 · 答题 · 签到[/size][/color]"),
            markup=True, theme_text_color="Custom", text_color=[1, 1, 1, 1],
            font_style="H6", halign="left", valign="middle",
            size_hint=(1, None), height=dp(72))
        htxt.bind(width=lambda w, x: setattr(w, "text_size", (x, w.height)))
        hrow.add_widget(htxt)
        head.add_widget(hrow)
        root.add_widget(head)
        # 供运行时几何自检（真机布局问题靠日志定位，不靠肉眼估）
        self.head = head
        self.hrow = hrow
        self.htxt = htxt

        scroll = ScrollView()
        box = BoxLayout(orientation="vertical", padding=18, spacing=dp(14), size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        # 顶部弹性留白：2K 长屏上内容只占上部 1/4，上下等分留白让内容垂直居中
        self._top_pad = MDBoxLayout(size_hint_y=None, height=dp(0))
        box.add_widget(self._top_pad)

        # —— 已保存账号（一键登录，最常用，放最上面）——
        box.add_widget(section_label("已保存账号 · 点一下即登录"))
        self.acc_list = MDList()
        box.add_widget(self.acc_list)

        box.add_widget(MDLabel(text="—— 或 新账号登录 ——", theme_text_color="Custom",
                               text_color=TEXT_SUB, halign="center",
                               size_hint_y=None, height=dp(30)))

        # 登录链接卡片
        link_card = make_card(spacing=dp(8))
        link_card.add_widget(MDLabel(text="① 复制下方链接，到浏览器打开登录", theme_text_color="Custom",
                                     text_color=TEXT_MAIN, size_hint_y=None, height=dp(28)))
        self.link_label = MDLabel(text=LOGIN_URL, theme_text_color="Custom",
                                  text_color=PRIMARY_DARK, size_hint_y=None, height=dp(40),
                                  text_size=(None, None))
        # 自适应高度：URL 长文本自动换行，避免文字溢出与上下重叠（真机实测问题）
        self.link_label.bind(
            texture_size=lambda w, s: setattr(w, "height", max(s[1], 40)))
        self.link_label.bind(
            width=lambda w, x: setattr(w, "text_size", (x, None)))
        link_card.add_widget(self.link_label)
        copy_btn = primary_button("复制登录链接", height=dp(46))
        copy_btn.bind(on_release=lambda *_: self.copy_link())
        link_card.add_widget(copy_btn)
        box.add_widget(link_card)

        # 粘贴 token 卡片
        paste_card = make_card(spacing=dp(8))
        paste_card.add_widget(MDLabel(text="② 浏览器登录后，复制地址栏网址粘贴到下面", theme_text_color="Custom",
                                      text_color=TEXT_MAIN, size_hint_y=None, height=dp(28)))
        self.input = MDTextField(hint_text="粘贴 token 网址", size_hint_y=None, height=dp(54),
                                 mode="rectangle", radius=[dp(12), dp(12), dp(12), dp(12)],
                                 line_color_normal=SEPARATOR,
                                 line_color_focus=PRIMARY,
                                 fill_color_normal=[0.949, 0.957, 0.976, 1],
                                 fill_color_focus=[0.929, 0.945, 0.976, 1],
                                 hint_text_color_normal=[0.55, 0.58, 0.63, 1])
        paste_card.add_widget(self.input)
        row = MDBoxLayout(orientation="horizontal", spacing=dp(10), size_hint_y=None, height=dp(46))
        paste_btn = primary_button("粘贴", height=dp(46), bg=PRIMARY_DARK)
        paste_btn.bind(on_release=lambda *_: self.do_paste())
        row.add_widget(paste_btn)
        login_btn = primary_button("登 录", height=dp(46))
        login_btn.bind(on_release=lambda *_: self.do_login())
        row.add_widget(login_btn)
        paste_card.add_widget(row)
        box.add_widget(paste_card)

        self.status = MDLabel(text="尚未登录", theme_text_color="Custom",
                              text_color=TEXT_SUB, halign="center",
                              size_hint_y=None, height=dp(36))
        box.add_widget(self.status)

        # 功能亮点（长屏上填充空白，同时说明 App 能做什么）
        feat = make_card(spacing=dp(10), padding=(dp(16), dp(16), dp(16), dp(16)))
        feat.add_widget(MDLabel(text="支持功能", theme_text_color="Custom",
                                text_color=TEXT_SUB, font_style="Caption",
                                size_hint_y=None, height=dp(22)))
        prow = MDBoxLayout(orientation="horizontal", size_hint_y=None,
                           height=dp(44), spacing=dp(8))
        for name in ["一键刷课", "自动答题", "签到改签"]:
            pill = MDBoxLayout(md_bg_color=[0, 0, 0, 0], size_hint=(1, None),
                               height=dp(44), padding=(dp(0), dp(11), dp(0), dp(11)))
            _round_bg(pill, color=[0.906, 0.937, 0.988, 1],
                      radius=[dp(12), dp(12), dp(12), dp(12)])
            pill.add_widget(MDLabel(text=name, theme_text_color="Custom",
                                    text_color=PRIMARY_DARK, font_style="Caption",
                                    halign="center"))
            prow.add_widget(pill)
        feat.add_widget(prow)
        box.add_widget(feat)

        # 底部等分留白（与顶部配对 → 内容垂直居中）
        self._bot_pad = MDBoxLayout(size_hint_y=None, height=dp(0))
        box.add_widget(self._bot_pad)

        scroll.add_widget(box)
        root.add_widget(scroll)

        # 垂直居中：上下留白各取 (视口 - 内容高) 的一半
        def _recenter(*_):
            base = (box.minimum_height - self._top_pad.height
                    - self._bot_pad.height)
            extra = max(0.0, scroll.height - base)
            half = round(extra * 0.5)
            if abs(half - self._top_pad.height) > 1:
                self._top_pad.height = half
                self._bot_pad.height = half

        box.bind(minimum_height=_recenter)
        scroll.bind(height=_recenter)

        # 页脚固定在屏幕底部（放 ScrollView 外，长屏不会留大片空白）
        footer = MDLabel(text=f"{APP_VERSION} · 智慧职教工具　|　仅供学习辅助",
                         theme_text_color="Custom",
                         text_color=[0.72, 0.75, 0.80, 1], halign="center",
                         size_hint_y=None, height=dp(44))
        root.add_widget(footer)
        self.add_widget(root)

    def on_pre_enter(self):
        self.acc_list.clear_widgets()
        for name, info in list_accounts():
            item = TwoLineListItem(text=f"{name}", secondary_text=f"学号 {info.get('userName','?')}")
            item.bind(on_release=lambda x, n=name, i=info: self.login_saved(n, i))
            self.acc_list.add_widget(item)
        if not list_accounts():
            self.acc_list.add_widget(OneLineListItem(
                text="暂无保存账号，请用下方链接登录", theme_text_color="Secondary"))

    def copy_link(self):
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(LOGIN_URL)
        self.status.text = "链接已复制，去浏览器粘贴打开"
        self.status.text_color = GREEN

    def do_paste(self):
        from kivy.core.clipboard import Clipboard
        self.input.text = Clipboard.paste().strip()
        self.status.text = "已粘贴，点「登 录」"
        self.status.text_color = TEXT_SUB

    def do_login(self):
        raw = self.input.text.strip()
        m = re.search(r"token=([^&#\s]+)", raw)
        if not m:
            self.status.text = "没找到 token，请确认粘贴的是完整网址"
            self.status.text_color = RED
            return
        self.status.text = "登录中..."
        self.status.text_color = ORANGE
        sso = m.group(1)
        def work():
            client = None
            try:
                client = _exchange_token(sso)
            except Exception as e:
                # 注意:先格式化成字符串再进 lambda —— except 块结束后 e 会被删除,
                # lambda 里直接引用会在回调时 NameError
                err = f"登录异常: {e}"
                Clock.schedule_once(lambda dt: setattr(self.status, "text", err), 0)
                Clock.schedule_once(lambda dt: setattr(self.status, "text_color", RED), 0)
            Clock.schedule_once(lambda dt: self._on_login(client, sso), 0)
        threading.Thread(target=work, daemon=True).start()

    def login_saved(self, name, info):
        tok = info.get("token", ""); sso = info.get("ssoToken", "")
        if not tok:
            self.status.text = "Token 为空"
            self.status.text_color = RED
            return
        self.status.text = f"验证 {name}..."
        self.status.text_color = ORANGE
        def work():
            try:
                c = ZjyClient(sso_token=sso or None)
                ok = c.apply_token(tok)
                if not ok and sso:
                    c = ZjyClient(sso_token=sso)
                    ok = c.refresh_token_from_sso()
                    if ok: save_account(c, sso)
                if ok:
                    Clock.schedule_once(lambda dt: self._on_login(c, sso), 0)
                else:
                    delete_account(name)
                    Clock.schedule_once(lambda dt: setattr(self.status, "text", "Token 已失效，请重新登录"), 0)
                    Clock.schedule_once(lambda dt: setattr(self.status, "text_color", RED), 0)
            except Exception as e:
                err = f"失败: {e}"
                Clock.schedule_once(lambda dt: setattr(self.status, "text", err), 0)
                Clock.schedule_once(lambda dt: setattr(self.status, "text_color", RED), 0)
        threading.Thread(target=work, daemon=True).start()

    def _on_login(self, client, sso=""):
        if client:
            self.app.client = client
            # 新会话必须清缓存：否则沿用上一个账号的课程/签到记录
            try:
                client.clear_cache()
            except Exception:
                pass
            if sso: save_account(client, sso)
            self.input.text = ""
            self.status.text = "登录成功"
            self.status.text_color = GREEN
            self.app.goto("dashboard")
        else:
            self.status.text = "登录失败"
            self.status.text_color = RED


class DashboardScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "dashboard"
        self.app = app
        root = MDBoxLayout(orientation="vertical", md_bg_color=BG)
        root.add_widget(topbar("控制台", app))
        scroll = ScrollView()
        box = BoxLayout(orientation="vertical", padding=16, spacing=dp(12), size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))

        # 欢迎卡片（自适应高度，label 给足中文安全高度）
        self.welcome_card = make_card(spacing=dp(4))
        self.welcome = MDLabel(text="", theme_text_color="Custom", text_color=TEXT_MAIN,
                               font_style="H6", size_hint_y=None, height=dp(36))
        self.welcome_card.add_widget(self.welcome)
        self.welcome_sub = MDLabel(text="", theme_text_color="Custom", text_color=TEXT_SUB,
                                   size_hint_y=None, height=dp(28))
        self.welcome_card.add_widget(self.welcome_sub)
        box.add_widget(self.welcome_card)

        box.add_widget(section_label("快捷功能"))

        # 功能入口统一包进卡片，恢复 galaxy 卡片层次（避免裸列显得像旧版）
        func_card = make_card(padding=(dp(8), dp(6), dp(8), dp(6)))
        for label, desc, target in [
            ("我的课程", "浏览已选课程", "courses"),
            ("一键刷课", "自动刷完课程视频", "speed"),
            ("自动答题", "拉取作业并自动作答", "answer"),
            ("签到改签", "补签或修改签到状态", "sign"),
            ("账号管理", "管理已保存的账号", "accounts"),
        ]:
            item = TwoLineListItem(text=label, secondary_text=desc,
                                   theme_text_color="Primary",
                                   secondary_theme_text_color="Secondary")
            item.bind(on_release=lambda x, t=target: self.app.goto(t))
            func_card.add_widget(item)
        box.add_widget(func_card)

        scroll.add_widget(box)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self):
        if self.app.client and self.app.client.user_info:
            u = self.app.client.user_info
            self.welcome.text = f"你好，{u.get('nickName','同学')}"
            self.welcome_sub.text = f"学号 {u.get('userName','')} · 已登录"
        else:
            self.welcome.text = "尚未登录"
            self.welcome_sub.text = "请先到登录页登录"


class AccountsScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "accounts"
        self.app = app
        root = MDBoxLayout(orientation="vertical", md_bg_color=BG)
        root.add_widget(topbar("账号管理", app))
        scroll = ScrollView()
        box = BoxLayout(orientation="vertical", padding=16, spacing=dp(12), size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        box.add_widget(section_label("已保存账号 · 点击删除"))
        self.list = MDList()
        box.add_widget(self.list)
        back = primary_button("返回控制台", height=dp(48))
        back.bind(on_release=lambda *_: self.app.goto("dashboard"))
        box.add_widget(back)
        scroll.add_widget(box)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self):
        self.list.clear_widgets()
        current_name = ""
        if self.app.client and self.app.client.user_info:
            current_name = self.app.client.user_info.get("nickName", "")
        accounts = list_accounts()
        if not accounts:
            self.list.add_widget(OneLineListItem(
                text="暂无保存账号", theme_text_color="Secondary"))
        for name, info in accounts:
            current = "（当前）" if current_name == name else ""
            item = TwoLineListItem(text=f"{name} {current}", secondary_text=f"学号 {info.get('userName','?')}")
            item.bind(on_release=lambda x, n=name: self.del_acc(n))
            self.list.add_widget(item)

    def del_acc(self, name):
        # 二次确认,避免误触即删
        def _confirm():
            delete_account(name)
            self.on_pre_enter()
        dialog = MDDialog(
            title="删除账号",
            text=f"确定删除已保存的账号「{name}」？\n删除后需重新登录。",
            buttons=[
                MDFlatButton(text="取消", on_release=lambda *_: dialog.dismiss()),
                MDFlatButton(text="删除", text_color=[0.9, 0.25, 0.2, 1],
                             on_release=lambda *_: (dialog.dismiss(), _confirm())),
            ],
        )
        dialog.open()


class SignPickScreen(MDScreen):
    """选择签到记录（整页列表）。

    为什么不再用弹窗：MDDialog / ModalView 里套 ScrollView 在真机上
    始终滑不动（连换两种容器 + 修好触摸抢占都不行）。整页滚动是 Kivy
    最可靠的场景，所以改成独立页面。
    """

    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "signpick"
        self.app = app
        self.items = []
        self.ctx = ("", "", "")

        root = MDBoxLayout(orientation="vertical", md_bg_color=BG)
        root.add_widget(topbar("选择签到记录", app))
        self.hint = MDLabel(text="", theme_text_color="Custom", text_color=TEXT_SUB,
                            size_hint_y=None, height=dp(44),
                            padding=(dp(16), dp(12)))
        root.add_widget(self.hint)

        self.list = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(2),
                              padding=(0, dp(4), 0, dp(4)))
        self.list.bind(minimum_height=self.list.setter("height"))
        self.scroll = TapScrollView(do_scroll_x=False)
        self.scroll.add_widget(self.list)
        root.add_widget(self.scroll)

        back = primary_button("返回", height=dp(46), bg=SEPARATOR)
        back.text_color = TEXT_MAIN
        back.bind(on_release=lambda *_: app.goto("sign"))
        pad = MDBoxLayout(size_hint_y=None, height=dp(60), padding=(dp(16), dp(6)))
        pad.add_widget(back)
        root.add_widget(pad)
        self.add_widget(root)

    def load(self, items, ctx):
        self.items = items
        self.ctx = ctx
        self.hint.text = (f"{APP_VERSION} · 共 {len(items)} 条 · "
                          "上下滑动选择，点一条改签")
        self.list.clear_widgets()
        self.scroll.tap_rows = []
        for s in items:
            st = str(s.get("myStatus", "0"))
            st_label = SIGN_STATUS_MAP.get(st, st)
            row = TapRow(on_tap=lambda sig=s: self.pick(sig))
            row.add_widget(MDLabel(
                text=f"{s.get('teachDate','')}  {s.get('teachTitle','?')}",
                theme_text_color="Custom", text_color=TEXT_MAIN,
                size_hint_y=None, height=dp(30)))
            row.add_widget(MDLabel(
                text=f"当前状态：{st_label}  —— 点击改签",
                theme_text_color="Custom", text_color=TEXT_SUB,
                font_style="Caption", size_hint_y=None, height=dp(26)))
            self.list.add_widget(row)
            self.scroll.tap_rows.append(row)
        self.scroll.scroll_y = 1

    def pick(self, sign):
        """选中某条记录 → 回到签到页并弹出状态选择（纯按钮，无需滚动）。"""
        self.app.screens["sign"]._pick_sign_status(sign)


class CourseSelectScreen(MDScreen):
    """课程选择 + 操作页。

    action_key:
        "speed"   = 一键刷课
        "answer"  = 自动答题
        "sign"    = 签到改签(带自定义改签/自动监听)
        None      = 只读浏览(我的课程)
    """

    def __init__(self, app, name, title, subtitle, action_label, action_key, **kw):
        super().__init__(**kw)
        self.name = name
        self.app = app
        self.action_key = action_key
        self.courses = []
        self.selected_course = None
        self._monitoring = False
        root = MDBoxLayout(orientation="vertical", md_bg_color=BG)
        root.add_widget(topbar(title, app))

        # 单一外层滚动容器：整个页面只有这一个 ScrollView，
        # 课程行/按钮/日志全部平铺，彻底避免嵌套 ScrollView 同方向冲突
        self.course_scroll = TapScrollView(do_scroll_x=False)
        self.list = BoxLayout(orientation="vertical", size_hint_y=None,
                              spacing=dp(2), padding=(0, dp(6), 0, dp(20)))
        self.list.bind(minimum_height=self.list.setter("height"))

        # 副标题
        self.list.add_widget(MDLabel(text=subtitle, theme_text_color="Custom",
                                     text_color=TEXT_SUB, size_hint_y=None,
                                     height=dp(40), padding=(dp(16), dp(8))))
        # 区块：选择课程（课程行放独立容器，刷新时只清这里，不碰按钮/日志）
        self.list.add_widget(section_label("选择课程"))
        self.course_box = BoxLayout(orientation="vertical", size_hint_y=None,
                                    spacing=dp(6), padding=(dp(16), dp(2), dp(16), dp(6)))
        self.course_box.bind(minimum_height=self.course_box.setter("height"))
        self.list.add_widget(self.course_box)

        # 区块：操作
        self.list.add_widget(section_label("操作"))
        op_pad = MDBoxLayout(size_hint_y=None, height=dp(58),
                             padding=(dp(16), dp(4)))
        self.action_btn = primary_button(action_label, height=dp(50))
        self.action_btn.bind(on_release=lambda *_: self.do_action())
        op_pad.add_widget(self.action_btn)
        self.list.add_widget(op_pad)
        if action_key == "sign":
            cp = MDBoxLayout(size_hint_y=None, height=dp(54),
                             padding=(dp(16), dp(4)))
            self.custom_btn = primary_button("自定义改签", height=dp(46), bg=SEPARATOR)
            self.custom_btn.text_color = TEXT_MAIN
            self.custom_btn.bind(on_release=lambda *_: self.custom_sign())
            cp.add_widget(self.custom_btn)
            self.list.add_widget(cp)
            mp = MDBoxLayout(size_hint_y=None, height=dp(54),
                             padding=(dp(16), dp(4)))
            self.monitor_btn = primary_button("启动自动监听签到", height=dp(46), bg=GREEN)
            self.monitor_btn.bind(on_release=lambda *_: self.toggle_monitor())
            mp.add_widget(self.monitor_btn)
            self.list.add_widget(mp)

        # 区块：日志（卡片自适应高度，随外层一起滚动）
        self.list.add_widget(section_label("运行日志"))
        log_wrap = MDBoxLayout(size_hint_y=None, padding=(dp(16), dp(4)))
        log_wrap.bind(minimum_height=log_wrap.setter("height"))
        self.log = MDLabel(text="选择课程后点按钮开始", size_hint_y=None, markup=True,
                           halign="left", valign="top", theme_text_color="Custom",
                           text_color=TEXT_MAIN, padding=(dp(12), dp(10)))
        log_card = make_card(padding=(dp(4), dp(4), dp(4), dp(4)))
        log_card.add_widget(self.log)

        def _fit_log(*_):
            need = max(self.log.texture_size[1] + dp(16), dp(80))
            if abs(self.log.height - need) > 1:
                self.log.height = need
        self.log.bind(texture_size=_fit_log)
        log_wrap.add_widget(log_card)
        self.list.add_widget(log_wrap)

        self.course_scroll.add_widget(self.list)
        root.add_widget(self.course_scroll)
        self.add_widget(root)

    def on_pre_enter(self):
        # 未登录保护:功能页不允许在未登录状态使用
        if not self.app.client or not self.app.client.user_info:
            self.append("!! 请先登录")
            Clock.schedule_once(lambda dt: self.app.goto("login"), 0)
            return
        # 只清课程区！clear_widgets 会连按钮/日志一起清掉（真机踩过）
        self.course_box.clear_widgets()
        self.course_scroll.tap_rows = []
        self.course_box.add_widget(MDLabel(text="加载课程中...", theme_text_color="Custom",
                                           text_color=TEXT_SUB, size_hint_y=None,
                                           height=dp(48), padding=(dp(14), dp(12))))
        def work():
            try:
                self.courses = self.app.client.get_my_courses() or []
            except Exception:
                self.courses = []
            Clock.schedule_once(lambda dt: self.show_courses(), 0)
        threading.Thread(target=work, daemon=True).start()

    def show_courses(self):
        self.course_box.clear_widgets()
        self.course_scroll.tap_rows = []
        if not self.courses:
            self.course_box.add_widget(MDLabel(text="(未找到课程)", theme_text_color="Custom",
                                               text_color=TEXT_SUB, size_hint_y=None,
                                               height=dp(48), padding=(dp(14), dp(12))))
            return
        for c in self.courses:
            ctype = c.get('_courseType', '?')
            row = TapRow(on_tap=lambda course=c: self.select_course(course))
            row._course = c
            row.add_widget(MDLabel(text=c.get('courseName', '?'),
                                   theme_text_color="Custom", text_color=TEXT_MAIN,
                                   size_hint_y=None, height=dp(30)))
            row.add_widget(MDLabel(text=self._course_type_label(ctype),
                                   theme_text_color="Custom", text_color=TEXT_SUB,
                                   font_style="Caption",
                                   size_hint_y=None, height=dp(24)))
            self.course_box.add_widget(row)
            self.course_scroll.tap_rows.append(row)
        Clock.schedule_once(lambda dt: setattr(self.course_scroll, "scroll_y", 1), 0)

    def _course_type_label(self, ctype):
        m = {"SPOC": "SPOC · 校内课程", "MOOC": "MOOC · 慕课", "ZYK": "资源库课程"}
        return m.get(str(ctype), str(ctype))

    def select_course(self, course):
        self.selected_course = course
        # 选中高亮：清掉上一行，给当前行浅蓝底（点击有明确视觉反馈）
        for row in self.course_scroll.tap_rows:
            row.set_selected(getattr(row, "_course", None) is course)
        self.log.text = f"[b][color=3B82F6]已选：{course.get('courseName','')}[/color][/b]\n"
        self.append(f">> 已选课程：{course.get('courseName','')}，请点下方按钮操作")

    def append(self, text):
        # 智能配色：错误红、成功/完成绿、进度蓝、其余灰
        t = text
        if t.startswith("!!") or "失败" in t or "出错" in t:
            color = "E53935"
        elif "成功" in t or "完成" in t or "已签" in t:
            color = "43A047"
        elif t.startswith(">>") or t.startswith("[发现"):
            color = "2196F3"
        else:
            color = "616161"
        self.log.text += f"[color={color}]{t}[/color]\n"

    def do_action(self):
        if not self.selected_course:
            self.append("!! 请先选择课程")
            return
        c = self.selected_course
        ctype = c.get("_courseType", "SPOC")
        cid = c.get("classId",""); ciid = c.get("courseInfoId",""); coid = c.get("courseId","")
        key = self.action_key

        if key is None:
            # 只读浏览页:重新拉取课程列表（手动刷新要忽略缓存）
            try:
                self.app.client.clear_cache()
            except Exception:
                pass
            self.on_pre_enter()
            return

        def _progress(stage, pct):
            Clock.schedule_once(lambda dt: self.append(f">> {stage} ({pct}%)"), 0)

        def work():
            try:
                if key == "speed":
                    Clock.schedule_once(lambda dt: self.append(">> 开始刷课..."), 0)
                    run_speed_course(self.app.client, c, "all", progress_cb=_progress)
                    Clock.schedule_once(lambda dt: self.append(">> 刷课完成"), 0)
                elif key == "answer":
                    Clock.schedule_once(lambda dt: self.append(">> 拉取作业列表..."), 0)
                    get_course_exams_list(self.app.client, cid, ciid, coid, ctype)
                    nick = self.app.client.user_info.get("nickName", "")
                    run_auto_answer_all_task(self.app.client, nick, cid, ciid, coid, ctype)
                    Clock.schedule_once(lambda dt: self.append(">> 答题完成"), 0)
                elif key == "sign":
                    Clock.schedule_once(lambda dt: self.append(">> 拉取签到记录..."), 0)
                    signs = get_signs(self.app.client, cid, ciid, coid)
                    if not signs:
                        Clock.schedule_once(lambda dt: self.append("没有签到活动"), 0)
                        return
                    not_signed = [s for s in signs if str(s.get("myStatus","0")) == "0"]
                    Clock.schedule_once(lambda dt: self.append(
                        f"共 {len(signs)} 条，未签到 {len(not_signed)} 条"), 0)
                    for s in signs:
                        st = str(s.get("myStatus","0"))
                        mark = "[已签]" if st == "1" else ("[未签]" if st == "0" else "[注意]")
                        Clock.schedule_once(lambda dt, s=s, st=st, mark=mark: self.append(
                            f"{mark} [{s.get('teachDate','')}] {s.get('teachTitle','?')} {SIGN_STATUS_MAP.get(st,st)}"), 0)
                    if not not_signed:
                        Clock.schedule_once(lambda dt: self.append("全部已签到"), 0)
                        return
                    Clock.schedule_once(lambda dt: self.append(">> 开始补签..."), 0)
                    result = batch_sign(self.app.client, not_signed, cid, ciid, coid)
                    for d in result.get("details", []):
                        Clock.schedule_once(lambda dt, d=d: self.append(f"  {d['result']}: {d['msg']}"), 0)
                    Clock.schedule_once(lambda dt: self.append(
                        f">> 补签完成：成功 {result.get('success',0)}，失败 {result.get('fail',0)}"), 0)
            except Exception as e:
                err = f"!! 出错: {e}"
                Clock.schedule_once(lambda dt: self.append(err), 0)
        threading.Thread(target=work, daemon=True).start()

    def toggle_monitor(self):
        if self._monitoring:
            self._monitoring = False
            self.monitor_btn.text = "启动自动监听签到"
            self.monitor_btn.md_bg_color = GREEN
            self.append(">> 已停止自动监听")
        else:
            if not self.app.client or not self.app.client.user_info:
                self.append("!! 请先登录")
                return
            self._monitoring = True
            self.monitor_btn.text = "停止监听"
            self.monitor_btn.md_bg_color = RED
            self.append(">> 启动自动监听（每40秒扫描，避免频繁请求）")
            self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
            self._monitor_thread.start()

    def stop_monitor(self):
        """供 App 退出时调用,停止监听线程。"""
        self._monitoring = False

    def _monitor_loop(self):
        seen_signs = set()
        first = True
        while self._monitoring:
            try:
                if not self.app.client or not self.app.client.user_info:
                    Clock.schedule_once(lambda dt: self.append("[监听] 登录已失效，停止监听"), 0)
                    break
                courses = self.app.client.get_my_courses() or []
                for c in courses:
                    cid = c.get("classId",""); ciid = c.get("courseInfoId",""); coid = c.get("courseId","")
                    # 监听只关心"今天有没有新签到"：只看最近 1 天、最多 3 个会话，
                    # 否则每 30 秒对每门课打上百次请求（真机卡顿主因）
                    signs = get_signs(self.app.client, cid, ciid, coid,
                                      max_sessions=3, recent_days=1)
                    for s in signs:
                        key = (cid, s.get("signId"))
                        not_signed = str(s.get("myStatus","0")) == "0"
                        if not_signed and key not in seen_signs:
                            seen_signs.add(key)
                            sign_type = s.get("signType","?")
                            if first:
                                continue
                            Clock.schedule_once(lambda dt, c=c, s=s, t=sign_type: self.append(
                                f"[发现新签到] {c.get('courseName','?')} {SIGN_TYPE_MAP.get(t,t)}签到 {s.get('teachTitle','?')}"), 0)
                            # 自动签
                            not_signed_list = [s]
                            result = batch_sign(self.app.client, not_signed_list, cid, ciid, coid)
                            for d in result.get("details", []):
                                Clock.schedule_once(lambda dt, d=d, c=c: self.append(
                                    f"  {c.get('courseName','?')}: {d['result']} {d['msg']}"), 0)
                first = False
            except Exception as e:
                err = f"[监听] 出错: {e}"
                Clock.schedule_once(lambda dt: self.append(err), 0)
            # 等待40秒(可被停止信号打断)，降低请求频率
            for _ in range(40):
                if not self._monitoring:
                    break
                time.sleep(1)

    def custom_sign(self):
        if not self.selected_course:
            self.append("!! 请先选择课程")
            return
        c = self.selected_course
        cid = c.get("classId",""); ciid = c.get("courseInfoId",""); coid = c.get("courseId","")
        self.append(">> 拉取签到记录...")
        def work():
            try:
                signs = get_signs(self.app.client, cid, ciid, coid)
                if not signs:
                    Clock.schedule_once(lambda dt: self.append("没有签到记录"), 0)
                    return
                Clock.schedule_once(lambda dt: self._show_sign_dialog(signs, cid, ciid, coid), 0)
            except Exception as e:
                err = f"!! 拉取签到记录出错: {e}"
                Clock.schedule_once(lambda dt: self.append(err), 0)
        threading.Thread(target=work, daemon=True).start()

    def _show_sign_dialog(self, items, cid, ciid, coid):
        """打开"选择签到记录"整页。

        弹窗内嵌滚动在真机上始终滑不动（MDDialog / ModalView 都试过），
        整页滚动是 Kivy 最可靠的场景，所以改为跳转独立页面。
        """
        self._sign_ctx = (cid, ciid, coid)
        self.app.screens["signpick"].load(items, self._sign_ctx)
        self.app.goto("signpick")

    def _pick_sign_status(self, sign):
        if getattr(self, "_dialog", None): self._dialog.dismiss()
        layout = BoxLayout(orientation="vertical", spacing=dp(8), size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))
        layout.add_widget(MDLabel(text=f"{sign.get('teachTitle','')}", theme_text_color="Primary",
                                 size_hint_y=None, height=dp(35)))
        layout.add_widget(MDLabel(text="改为：", theme_text_color="Secondary",
                                 size_hint_y=None, height=dp(30)))
        from kivy.uix.gridlayout import GridLayout
        grid = GridLayout(cols=2, spacing=dp(8), size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for st, label in SIGN_STATUS_MAP.items():
            btn = primary_button(label, height=dp(50))
            btn.bind(on_release=lambda x, s=sign, st=st: self._do_custom_sign(s, st))
            grid.add_widget(btn)
        layout.add_widget(grid)
        cancel = MDFlatButton(text="取消", size_hint=(1, None), height=dp(40))
        cancel.bind(on_release=lambda *_: self._cancel_pick())
        layout.add_widget(cancel)
        self._dialog = MDDialog(title="选择改签状态", type="custom", content_cls=layout)
        self._dialog.open()

    def _cancel_pick(self):
        if getattr(self, "_dialog", None):
            self._dialog.dismiss()
        # 从整页选择记录过来时，取消后回到签到页
        if self.app.sm.current == "signpick":
            self.app.goto("sign")

    def _do_custom_sign(self, sign, status_type):
        if getattr(self, "_dialog", None): self._dialog.dismiss()
        # 从整页选择记录过来：执行后回到签到页看日志
        if self.app.sm.current == "signpick":
            self.app.goto("sign")
        cid, ciid, coid = self._sign_ctx
        client = self.app.client
        payload = {
            "classId": cid, "courseId": coid, "courseInfoId": ciid,
            "signId": sign["signId"], "signResultType": status_type,
            "teachId": sign.get("teachId",""),
            "studentId": client.stu_id or "",
            "studentName": client.user_info.get("nickName",""),
            "studentNo": client.user_info.get("userName",""),
            # 关键:带原记录主键 id,让 do_sign_action 走 PUT 更新
            # (改签"已签→未签"必须覆盖原记录,POST 新建覆盖不了)
            "id": sign.get("recordId", ""),
        }
        self.append(f">> 改签为{SIGN_STATUS_MAP.get(status_type,status_type)}...")
        def work():
            try:
                r = do_sign_action(client, payload)
                Clock.schedule_once(lambda dt: self.append(
                    f"  {'成功' if r.get('code')==200 else '失败'}: {r.get('msg','')}"), 0)
            except Exception as e:
                err = f"!! 改签出错: {e}"
                Clock.schedule_once(lambda dt: self.append(err), 0)
        threading.Thread(target=work, daemon=True).start()


class ICVEApp(MDApp):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.client = None

    def build(self):
        self.theme_cls.theme_style = "Light"
        self.theme_cls.primary_palette = "Blue"
        # 确保不进入全屏，让系统自带状态栏（时间/电量/信号）正常显示
        try:
            from kivy.core.window import Window
            Window.fullscreen = False
        except Exception:
            pass
        # 安卓上 Kivy 可能把 density 估小（2K 屏实际 3.5 估成 1.5），
        # 导致所有 dp 尺寸等比缩水：字体变小、标题被压扁、整页"内容很小"。
        # 用系统 DisplayMetrics.density 覆盖（真机截图实测）。
        self._fix_android_density()
        # 中文字体替换：只改文本样式，跳过 "Icon" —— 它是 MDIcon 的图标
        # 字体（materialdesignicons），改成 NotoSansSC 会导致图标渲染成
        # 方框占位符（真机实测：登录页 school 图标、侧边栏图标全变成叉）
        for k in list(self.theme_cls.font_styles.keys()):
            if k == "Icon":
                continue
            self.theme_cls.font_styles[k][0] = "NotoSansSC.ttf"
        sm = MDScreenManager()
        self.login = LoginScreen(self)
        self.dashboard = DashboardScreen(self)
        self.accounts = AccountsScreen(self)
        self.courses = CourseSelectScreen(self, "courses", "我的课程", "选择课程查看详情", "刷新列表", None)
        self.speed = CourseSelectScreen(self, "speed", "一键刷课", "选择课程后自动刷完所有视频", "开始刷课", "speed")
        self.answer = CourseSelectScreen(self, "answer", "自动答题", "选择课程后拉取作业并自动作答", "拉取并作答", "answer")
        self.sign = CourseSelectScreen(self, "sign", "签到改签", "补签或手动修改签到状态", "拉取并补签", "sign")
        self.signpick = SignPickScreen(self)
        for s in (self.login, self.dashboard, self.accounts, self.courses, self.speed,
                  self.answer, self.sign, self.signpick):
            sm.add_widget(s)
        self.nav_drawer = MDNavigationDrawer()
        self.sidebar = SidebarMenu(self)
        self.nav_drawer.add_widget(self.sidebar)
        self.nav_layout = MDNavigationLayout()
        self.nav_layout.add_widget(sm)
        self.nav_layout.add_widget(self.nav_drawer)
        self.sm = sm
        self.screens = {"login": self.login, "dashboard": self.dashboard, "accounts": self.accounts,
                        "courses": self.courses, "speed": self.speed, "answer": self.answer,
                        "sign": self.sign, "signpick": self.signpick}
        sm.current = "login"
        return self.nav_layout

    def _fix_android_density(self):
        """校正 density，让 UI 比例与设计稿（411dp 宽）一致。

        真机 2K 屏实测：Kivy 的 density 可能远小于实际，所有 dp 尺寸等比
        缩水 → 字体小、标题挤成一团。这里双保险：
          1) 读 DisplayMetrics.density（densityDpi/160）作为参考；
          2) 用 Window 实际像素宽 / 411 反推 density —— 保证内容铺满屏宽，
             不依赖厂商上报值（部分 ROM/兼容模式会上报错）。
        诊断同时写入 icve_crash.log（print 在真机不易看到）。
        """
        DESIGN_DP_WIDTH = 411.0
        diag = [f"[boot] version={APP_VERSION}"]
        try:
            from kivy.core.window import Window
            from kivy.metrics import Metrics
            bounds = 1.0 <= Window.width / DESIGN_DP_WIDTH <= 5.0
            derived = round(Window.width / DESIGN_DP_WIDTH, 2) if bounds else None
            diag.append(f"[boot] kivy density={Metrics.density:.2f} "
                        f"window={tuple(Window.size)} derived={derived}")

            real = None
            try:
                from android import mActivity
                dm = mActivity.getResources().getDisplayMetrics()
                real = float(dm.density)
                diag.append(f"[boot] android density={real:.2f} "
                            f"dpi={dm.densityDpi} "
                            f"px={dm.widthPixels}x{dm.heightPixels}")
            except Exception as e:
                diag.append(f"[boot] android metrics unavailable: {e}")

            # 以安卓上报值为主（Kivy 走 SDL 读 DPI 常常偏小），
            # 反推值仅写进诊断：等确认 Window.size 是像素还是 dp 后再启用，
            # 否则可能把 density 反推成 1.0 把 UI 缩得更小。
            target = real if real else derived
            if target and abs(target - Metrics.density) > 0.05:
                Metrics.density = target
                diag.append(f"[boot] density corrected -> {Metrics.density:.2f}")
        except Exception as e:
            diag.append(f"[boot] density probe failed: {e}")
        for line in diag:
            print(line)
        _append_diag("\n".join(diag))

    def on_start(self):
        # 多次重试：首次可能在窗口 attach 之前，状态栏 flag 会被覆盖
        for delay in (1.0, 3.0, 6.0):
            Clock.schedule_once(lambda dt: self._set_status_bar_color(), delay)
        # 状态栏显示后若压住内容（inset>0），给各页面顶部补内边距
        Clock.schedule_once(lambda dt: self._apply_status_bar_inset(), 1.6)
        # 运行时几何自检：把头部实际高度/文字坐标写进日志
        Clock.schedule_once(lambda dt: self._log_geometry(), 2.8)

    def _apply_status_bar_inset(self):
        """系统状态栏若覆盖在内容之上（inset top > 0），把内容整体下移。

        getRootWindowInsets().getSystemWindowInsetTop() 返回"本窗口还需要多少
        顶部内边距"：若窗口已排在状态栏之下则为 0，若窗口延伸到状态栏后面
        则是状态栏高度。据此补 padding，避免标题被状态栏压住。
        """
        if getattr(self, "_inset_applied", False):
            return
        try:
            from android import mActivity
            from kivy.metrics import Metrics
            dv = mActivity.getWindow().getDecorView()
            ins = dv.getRootWindowInsets()
            if ins is None:
                return
            top_px = ins.getSystemWindowInsetTop()
            if not top_px or top_px <= 0:
                _append_diag("[inset] top=0 (窗口已在状态栏之下，无需补偿)")
                self._inset_applied = True
                return
            pad_dp = top_px / Metrics.density
            for name, s in self.screens.items():
                try:
                    # 登录页顶部用蓝色占位条（与标题栏无缝衔接）
                    if name == "login" and hasattr(s, "status_strip"):
                        s.status_strip.height = top_px
                        continue
                    root = s.children[0]
                    p = list(root.padding)
                    # padding 单位是像素，直接加 inset 的像素值
                    root.padding = [p[0], p[1] + top_px, p[2], p[3]]
                except Exception:
                    pass
            self._inset_applied = True
            _append_diag(f"[inset] 补顶部内边距 {pad_dp:.1f}dp (top={top_px}px)")
        except Exception as e:
            _append_diag(f"[inset] 读取失败: {e}")

    def _log_geometry(self):
        """把关键控件实几何写进 icve_crash.log（真机布局问题靠数据定位）。"""
        lines = []
        try:
            from kivy.core.window import Window
            from kivy.metrics import Metrics
            lg = self.login
            lines.append(f"[geom] window={tuple(Window.size)} "
                         f"density={Metrics.density:.2f}")
            for nm in ("head", "hrow", "htxt"):
                w = getattr(lg, nm, None)
                if w is None:
                    continue
                lines.append(f"[geom] {nm}: y={w.y:.0f} h={w.height:.0f} "
                             f"x={w.x:.0f} w={w.width:.0f} "
                             f"tex={getattr(w, 'texture_size', None)}")
        except Exception as e:
            lines.append(f"[geom] fail: {e}")
        try:
            from android import mActivity
            dv = mActivity.getWindow().getDecorView()
            lines.append(f"[geom] decorUi={dv.getSystemUiVisibility()}")
            ins = dv.getRootWindowInsets()
            if ins is not None:
                lines.append(f"[geom] inset top={ins.getSystemWindowInsetTop()} "
                             f"bottom={ins.getSystemWindowInsetBottom()}")
        except Exception as e:
            lines.append(f"[geom] inset fail: {e}")
        for ln in lines:
            print(ln)
        _append_diag("\n".join(lines))

    def on_resume(self):
        Clock.schedule_once(lambda dt: self._set_status_bar_color(), 0.3)

    def on_stop(self):
        # 退出时停止所有监听线程
        for s in self.screens.values():
            if hasattr(s, "stop_monitor"):
                s.stop_monitor()

    def _set_status_bar_color(self):
        """让安卓系统自带状态栏可见（非全屏），并设浅色底 + 深色图标。

        要点：
        1. 清掉 FLAG_FULLSCREEN —— p4a/SDL 默认可能是全屏，只改
           setSystemUiVisibility 不会让状态栏出现（真机实测：仍是全屏）；
        2. 加 FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS，setStatusBarColor 才生效；
        3. 系统 UI flag 只保留 LIGHT_STATUS_BAR（深色图标）。不要用
           LAYOUT_FULLSCREEN/LAYOUT_STABLE —— 会把内容顶到状态栏后面被裁切；
        4. 视图操作必须在安卓 UI 主线程（runOnUiThread），否则抛
           CalledFromWrongThreadException（真机实测会把堆栈糊到界面）。
        """
        try:
            from android import mActivity
            from jnius import autoclass

            # 用数值常量，不依赖 autoclass 找内嵌类（WindowManager$LayoutParams
            # 查找失败会被静默吞掉，导致"改了代码但状态栏还是不出来"）
            FLAG_FULLSCREEN = 1024                    # 0x00000400
            FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS = -2147483648  # 0x80000000 (Java int)
            FLAG_LAYOUT_NO_LIMITS = 512               # 0x00000200 内容铺到系统栏后
            FLAG_LAYOUT_IN_SCREEN = 256               # 0x00000100 同上（旧机型）

            def _apply():
                try:
                    window = mActivity.getWindow()
                    window.clearFlags(FLAG_FULLSCREEN)          # 退出全屏
                    # 清掉"内容延伸到系统栏后面"的布局 flag（沉浸式常见根因）
                    window.clearFlags(FLAG_LAYOUT_NO_LIMITS)
                    window.clearFlags(FLAG_LAYOUT_IN_SCREEN)
                    window.addFlags(FLAG_DRAWS_SYSTEM_BAR_BACKGROUNDS)
                    # 让内容为系统栏留出空间（非沉浸，状态栏独立占位）
                    view = window.getDecorView()
                    try:
                        view.setFitsSystemWindows(True)
                    except Exception:
                        pass
                    # 状态栏底色取主蓝、图标用白色（清掉 LIGHT_STATUS_BAR），
                    # 与页面顶部蓝色标题栏/占位条无缝衔接
                    view.setSystemUiVisibility(0)
                    Color = autoclass("android.graphics.Color")
                    window.setStatusBarColor(Color.parseColor("#3B82F6"))
                    # Android 11+ 再用 WindowInsetsController 主动 show 一次
                    shown = "no-controller"
                    try:
                        InsetsType = autoclass("android.view.WindowInsets$Type")
                        ctrl = window.getInsetsController()
                        if ctrl is not None:
                            ctrl.show(InsetsType.statusBars())
                            shown = "insets-show"
                    except Exception as e:
                        shown = f"insets-skip: {e}"
                    _append_diag(f"[statusbar] applied ({shown})")
                except Exception as e:
                    _append_diag(f"[statusbar] failed: {e}")
                    # 打到 logcat / 崩溃日志，便于定位（不再静默）
                    print("statusbar setup failed:", e)

            # 视图操作必须在 UI 主线程执行
            mActivity.runOnUiThread(_apply)
        except Exception as e:
            print("statusbar setup failed(outer):", e)

    def goto(self, name):
        self.sidebar.refresh()
        if self.sm.current == name:
            # 同一页再次进入:ScreenManager 不会重发 on_pre_enter,手动刷新
            self.screens[name].on_pre_enter()
        else:
            self.sm.current = name  # 框架会自动触发目标页 on_pre_enter(只一次)

    def logout(self):
        """退出登录:清会话 → 停监听 → 回登录页。"""
        if self.client:
            try:
                self.client.clear_cache()
            except Exception:
                pass
        self.client = None
        for s in self.screens.values():
            if hasattr(s, "stop_monitor"):
                s.stop_monitor()
        self.sidebar.refresh()
        self.sm.current = "login"


def _install_crash_logger():
    """闪退自救：把未捕获异常写到手机存储，无 adb 也能定位。

    三个落点：
    1. /sdcard/icve_crash.log   —— 用户可直接文件管理器看到并发回
    2. 应用私有目录 icve_crash.log
    3. stderr（有 adb 时 logcat 也能看到）
    """
    import traceback
    paths = []
    try:
        paths.append("/sdcard/icve_crash.log")
    except Exception:
        pass
    try:
        from android.storage import app_storage_path  # noqa: F401
        paths.append(app_storage_path() + "/icve_crash.log")
    except Exception:
        pass
    paths.append("icve_crash.log")

    def _write(text):
        for p in paths:
            try:
                with open(p, "a", encoding="utf-8") as f:
                    f.write(text)
            except Exception:
                pass

    def _hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        _write(text + "\n")
        sys.stderr.write(text)

    sys.excepthook = _hook

    # Kivy 事件循环内的异常（含 Clock 回调、线程调度）走 ExceptionManager
    try:
        from kivy.base import ExceptionManager, ExceptionHandler

        class CrashLogger(ExceptionHandler):
            def handle_exception(self, inst):
                text = "".join(
                    traceback.format_exception(type(inst), inst, inst.__traceback__))
                _write(text + "\n")
                sys.stderr.write(text)
                # 注意：kivy 2.x 的 ExceptionManagerBase 只有 RAISE(0)/PASS(1)，
                # 没有 1.x 的 RAISE_EXCEPTION（访问它自己就会 AttributeError，
                # 把可恢复异常放大成闪退——真机实测踩过）。
                # 返回 PASS：日志已记录，吞掉异常让 App 继续运行不闪退。
                return ExceptionManager.PASS

        ExceptionManager.add_handler(CrashLogger())
    except Exception:
        pass


if __name__ == "__main__":
    _install_crash_logger()
    ICVEApp().run()
