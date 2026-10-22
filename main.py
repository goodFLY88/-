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

    kivymd 1.0.2 的 elevation.py __draw_shadow__ 在按钮 radius 超过
    半宽时算出 x1 < x0 的矩形，2024+ 的 Pillow 对 ImageDraw.rectangle
    严格校验，直接 ValueError（真机实测：MDRaisedButton 半径变化 →
    阴影重绘 → 崩溃）。kivymd 1.2.0 重构阴影系统才修掉，但我们锁
    1.0.2（1.1.1/1.2.0 无 wheel 装不上），只能在这里把负坐标 clamp
    回合法值——阴影照样画，只是极少数越界场景少画一个像素。
    """
    try:
        from PIL import ImageDraw
    except ImportError:
        return
    _orig = ImageDraw.ImageDraw.rectangle

    def _safe_rectangle(self, xy, *args, **kwargs):
        try:
            return _orig(self, xy, *args, **kwargs)
        except ValueError:
            if not (isinstance(xy, (list, tuple)) and len(xy) == 4):
                raise
            x0, y0, x1, y1 = xy
            x1 = max(x1, x0)
            y1 = max(y1, y0)
            return _orig(self, [x0, y0, x1, y1], *args, **kwargs)

    ImageDraw.ImageDraw.rectangle = _safe_rectangle


_patch_pil_rectangle()

# ==================== 统一视觉规范 ====================
# 主色（蓝色系）
PRIMARY = [0.13, 0.59, 0.95, 1]        # 主蓝 #2196F3
PRIMARY_DARK = [0.08, 0.45, 0.78, 1]   # 深蓝
BG = [0.96, 0.97, 0.98, 1]              # 页面浅灰底
CARD_BG = [1, 1, 1, 1]                  # 卡片白
TEXT_MAIN = [0.15, 0.17, 0.2, 1]        # 主文字深灰
TEXT_SUB = [0.5, 0.55, 0.6, 1]          # 次级文字灰
GREEN = [0.2, 0.7, 0.35, 1]             # 成功绿
RED = [0.9, 0.25, 0.2, 1]               # 失败红
ORANGE = [0.95, 0.6, 0.1, 1]            # 警告橙


def topbar(title, app=None):
    bar = MDTopAppBar(title=title)
    bar.md_bg_color = PRIMARY
    bar.specific_text_color = [1, 1, 1, 1]
    bar.elevation = 4
    if app is not None:
        bar.right_action_items = [["menu", lambda *_: app.nav_drawer.set_state("open")]]
    return bar


def menu_button(app):
    b = MDFlatButton(text="菜单", size_hint=(None, None), size=(80, 35), pos_hint={"left": 1})
    b.bind(on_release=lambda *_: app.nav_drawer.set_state("open"))
    return b


def section_label(text):
    """区块小标题。"""
    return MDLabel(text=text, theme_text_color="Custom", text_color=TEXT_SUB,
                   size_hint_y=None, height=28, padding=(16, 4))


def make_card(**kw):
    """统一卡片容器。自适应高度用 MDBoxLayout，可点击用 MDCard。

    MDCard 的 height 不会随内容自动撑开（真机实测导致内容互相重叠挤压），
    所以：
    - 自适应高度卡片 → MDBoxLayout（bind minimum_height）
    - 可点击卡片（需 on_release）→ MDCard（固定 height）
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
                      md_bg_color=CARD_BG, radius=[12, 12, 12, 12],
                      elevation=0, padding=padding, **kw)
        return card
    # 自适应高度：MDBoxLayout
    card = MDBoxLayout(orientation="vertical", size_hint_y=None,
                       md_bg_color=CARD_BG, padding=padding, **kw)
    if height is not None:
        card.height = height
    else:
        card.bind(minimum_height=card.setter("height"))
    return card


LOGIN_URL = f"{SSO_BASE}/h5/?mode=simple&source=15&redirect=http://127.0.0.1:9527#/login"


class SidebarMenu(BoxLayout):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.orientation = "vertical"
        self.padding = 0
        self.spacing = 0
        self.app = app
        from kivymd.uix.label import MDIcon
        # 顶部账号区（头像 + 昵称 + 学号）
        header = MDBoxLayout(size_hint_y=None, height=140,
                             md_bg_color=PRIMARY, padding=(20, 20, 20, 16))
        self.avatar = MDIcon(icon="account-circle", theme_text_color="Custom",
                             text_color=[1, 1, 1, 1], size_hint=(None, None),
                             size=(56, 56), pos_hint={"center_x": 0.5})
        header.add_widget(self.avatar)
        self.name_label = MDLabel(text="未登录", theme_text_color="Custom",
                                  text_color=[1, 1, 1, 1], font_style="Subtitle1",
                                  halign="center", size_hint_y=None, height=30)
        header.add_widget(self.name_label)
        self.stu_label = MDLabel(text="登录后显示学号", theme_text_color="Custom",
                                 text_color=[0.85, 0.9, 0.98, 1], halign="center",
                                 size_hint_y=None, height=22)
        header.add_widget(self.stu_label)
        self.add_widget(header)
        # 菜单内容
        content = BoxLayout(orientation="vertical", padding=(5, 10, 5, 10), spacing=1)
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

        # 顶部 LOGO 区
        head = MDBoxLayout(orientation="vertical", size_hint_y=None, height=150,
                           md_bg_color=PRIMARY, padding=(24, 0, 24, 0))
        from kivymd.uix.label import MDIcon
        logo = MDIcon(icon="school", theme_text_color="Custom",
                      text_color=[1, 1, 1, 1], size_hint=(1, None), height=64)
        head.add_widget(logo)
        head.add_widget(MDLabel(text="智慧职教 · 学习助手", theme_text_color="Custom",
                                text_color=[1, 1, 1, 1], font_style="H5",
                                halign="center", size_hint_y=None, height=34))
        head.add_widget(MDLabel(text="登录 · 刷课 · 答题 · 签到", theme_text_color="Custom",
                                text_color=[0.85, 0.9, 0.98, 1], halign="center",
                                size_hint_y=None, height=22))
        root.add_widget(head)

        scroll = ScrollView()
        box = BoxLayout(orientation="vertical", padding=18, spacing=14, size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))

        # —— 已保存账号（一键登录，最常用，放最上面）——
        box.add_widget(section_label("已保存账号 · 点一下即登录"))
        self.acc_list = MDList()
        box.add_widget(self.acc_list)

        box.add_widget(MDLabel(text="—— 或 新账号登录 ——", theme_text_color="Custom",
                               text_color=TEXT_SUB, halign="center",
                               size_hint_y=None, height=30))

        # 登录链接卡片
        link_card = make_card(spacing=8)
        link_card.add_widget(MDLabel(text="① 复制下方链接，到浏览器打开登录", theme_text_color="Custom",
                                     text_color=TEXT_MAIN, size_hint_y=None, height=28))
        self.link_label = MDLabel(text=LOGIN_URL, theme_text_color="Custom",
                                  text_color=PRIMARY_DARK, size_hint_y=None, height=40,
                                  text_size=(None, None))
        # 自适应高度：URL 长文本自动换行，避免文字溢出与上下重叠（真机实测问题）
        self.link_label.bind(
            texture_size=lambda w, s: setattr(w, "height", max(s[1], 40)))
        self.link_label.bind(
            width=lambda w, x: setattr(w, "text_size", (x, None)))
        link_card.add_widget(self.link_label)
        copy_btn = MDRaisedButton(text="复制登录链接", size_hint=(1, None), height=46,
                                  md_bg_color=PRIMARY)
        copy_btn.bind(on_release=lambda *_: self.copy_link())
        link_card.add_widget(copy_btn)
        box.add_widget(link_card)

        # 粘贴 token 卡片
        paste_card = make_card(spacing=8)
        paste_card.add_widget(MDLabel(text="② 浏览器登录后，复制地址栏网址粘贴到下面", theme_text_color="Custom",
                                      text_color=TEXT_MAIN, size_hint_y=None, height=28))
        self.input = MDTextField(hint_text="粘贴 token 网址", size_hint_y=None, height=54,
                                 mode="line", line_color_normal=PRIMARY,
                                 line_color_focus=PRIMARY)
        paste_card.add_widget(self.input)
        row = MDBoxLayout(orientation="horizontal", spacing=10, size_hint_y=None, height=46)
        paste_btn = MDRaisedButton(text="粘贴", size_hint=(1, None), height=46,
                                   md_bg_color=PRIMARY_DARK)
        paste_btn.bind(on_release=lambda *_: self.do_paste())
        row.add_widget(paste_btn)
        login_btn = MDRaisedButton(text="登 录", size_hint=(1, None), height=46,
                                   md_bg_color=PRIMARY)
        login_btn.bind(on_release=lambda *_: self.do_login())
        row.add_widget(login_btn)
        paste_card.add_widget(row)
        box.add_widget(paste_card)

        self.status = MDLabel(text="尚未登录", theme_text_color="Custom",
                              text_color=TEXT_SUB, halign="center",
                              size_hint_y=None, height=36)
        box.add_widget(self.status)
        scroll.add_widget(box)
        root.add_widget(scroll)
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
        box = BoxLayout(orientation="vertical", padding=16, spacing=12, size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))

        # 欢迎卡片（自适应高度，label 给足中文安全高度）
        self.welcome_card = make_card(spacing=4)
        self.welcome = MDLabel(text="", theme_text_color="Custom", text_color=TEXT_MAIN,
                               font_style="H6", size_hint_y=None, height=36)
        self.welcome_card.add_widget(self.welcome)
        self.welcome_sub = MDLabel(text="", theme_text_color="Custom", text_color=TEXT_SUB,
                                   size_hint_y=None, height=28)
        self.welcome_card.add_widget(self.welcome_sub)
        box.add_widget(self.welcome_card)

        box.add_widget(section_label("快捷功能"))

        # 功能入口（KivyMD 原生 TwoLineListItem，内部布局已调好，
        # 避免手搓卡片在中文字体下高度溢出导致文字重叠）
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
            box.add_widget(item)

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
        box = BoxLayout(orientation="vertical", padding=16, spacing=12, size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        box.add_widget(section_label("已保存账号 · 点击删除"))
        self.list = MDList()
        box.add_widget(self.list)
        back = MDRaisedButton(text="返回控制台", size_hint=(1, None), height=48,
                              md_bg_color=PRIMARY)
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
        root = MDBoxLayout(orientation="vertical", md_bg_color=BG)
        root.add_widget(topbar(title, app))
        # 副标题
        root.add_widget(MDLabel(text=subtitle, theme_text_color="Custom", text_color=TEXT_SUB,
                                size_hint_y=None, height=40, padding=(16, 8)))
        # 区块：选择课程
        root.add_widget(section_label("选择课程"))
        # 课程列表
        self.list = MDList()
        scroll = ScrollView(size_hint_y=0.3)
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        # 区块：操作
        root.add_widget(section_label("操作"))
        # 操作按钮
        self.action_btn = MDRaisedButton(text=action_label, size_hint=(1, None), height=50,
                                         md_bg_color=PRIMARY)
        self.action_btn.bind(on_release=lambda *_: self.do_action())
        root.add_widget(self.action_btn)
        if action_key == "sign":
            self.custom_btn = MDRaisedButton(text="自定义改签", size_hint=(1, None), height=46,
                                             md_bg_color=[0.9, 0.9, 0.9, 1])
            self.custom_btn.text_color = [0.15, 0.15, 0.15, 1]
            self.custom_btn.bind(on_release=lambda *_: self.custom_sign())
            root.add_widget(self.custom_btn)
            self.monitor_btn = MDRaisedButton(text="启动自动监听签到", size_hint=(1, None), height=46,
                                              md_bg_color=GREEN)
            self.monitor_btn.bind(on_release=lambda *_: self.toggle_monitor())
            root.add_widget(self.monitor_btn)
            self._monitoring = False
            self._monitor_thread = None
        # 区块：日志
        root.add_widget(section_label("运行日志"))
        # 日志（卡片内，白底）
        self.log = MDLabel(text="选择课程后点按钮开始", size_hint_y=None, markup=True,
                           halign="left", valign="top", theme_text_color="Custom",
                           text_color=TEXT_MAIN, padding=(12, 10))
        self.log.bind(texture_size=lambda w, s: setattr(w, "height", max(s[1], 150)))
        log_card = make_card(padding=(4, 4, 4, 4))
        log_card.add_widget(self.log)
        self.log.bind(texture_size=lambda w, s: setattr(log_card, "height", max(s[1] + 8, 150)))
        sv = ScrollView(size_hint_y=1)
        sv.add_widget(log_card)
        root.add_widget(sv)
        self.add_widget(root)

    def on_pre_enter(self):
        # 未登录保护:功能页不允许在未登录状态使用
        if not self.app.client or not self.app.client.user_info:
            self.append("!! 请先登录")
            Clock.schedule_once(lambda dt: self.app.goto("login"), 0)
            return
        self.list.clear_widgets()
        self.list.add_widget(OneLineListItem(text="加载课程中..."))
        def work():
            try:
                self.courses = self.app.client.get_my_courses() or []
            except Exception:
                self.courses = []
            Clock.schedule_once(lambda dt: self.show_courses(), 0)
        threading.Thread(target=work, daemon=True).start()

    def show_courses(self):
        self.list.clear_widgets()
        if not self.courses:
            self.list.add_widget(OneLineListItem(text="(未找到课程)", theme_text_color="Secondary"))
            return
        for c in self.courses:
            ctype = c.get('_courseType', '?')
            item = TwoLineListItem(
                text=c.get('courseName', '?'),
                secondary_text=self._course_type_label(ctype),
            )
            item.bind(on_release=lambda x, course=c: self.select_course(course))
            self.list.add_widget(item)

    def _course_type_label(self, ctype):
        m = {"SPOC": "SPOC · 校内课程", "MOOC": "MOOC · 慕课", "ZYK": "资源库课程"}
        return m.get(str(ctype), str(ctype))

    def select_course(self, course):
        self.selected_course = course
        self.log.text = f"[b][color=2196F3]已选：{course.get('courseName','')}[/color][/b]\n"

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
            # 只读浏览页:重新拉取课程列表
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
            self.monitor_btn.md_bg_color = [0.2, 0.7, 0.3, 1]
            self.append(">> 已停止自动监听")
        else:
            if not self.app.client or not self.app.client.user_info:
                self.append("!! 请先登录")
                return
            self._monitoring = True
            self.monitor_btn.text = "停止监听"
            self.monitor_btn.md_bg_color = [0.9, 0.3, 0.2, 1]
            self.append(">> 启动自动监听（每30秒扫描所有课程）")
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
                    signs = get_signs(self.app.client, cid, ciid, coid)
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
            # 等待30秒(可被停止信号打断)
            for _ in range(30):
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
        layout = BoxLayout(orientation="vertical", spacing=2, size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))
        layout.add_widget(MDLabel(text="选择签到记录（括号内为当前状态）：",
                                  theme_text_color="Secondary", size_hint_y=None, height=35))
        self._sign_ctx = (cid, ciid, coid)
        for s in items:
            st = str(s.get("myStatus", "0"))
            st_label = SIGN_STATUS_MAP.get(st, st)
            item = TwoLineListItem(
                text=f"{s.get('teachDate','')}  {s.get('teachTitle','?')}",
                secondary_text=f"当前状态：{st_label}  —— 点击改签",
            )
            item.bind(on_release=lambda x, sig=s: self._pick_sign_status(sig))
            layout.add_widget(item)
        self._dialog = MDDialog(title="自定义改签", type="custom", content_cls=layout)
        self._dialog.open()

    def _pick_sign_status(self, sign):
        if getattr(self, "_dialog", None): self._dialog.dismiss()
        layout = BoxLayout(orientation="vertical", spacing=8, size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))
        layout.add_widget(MDLabel(text=f"{sign.get('teachTitle','')}", theme_text_color="Primary",
                                 size_hint_y=None, height=35))
        layout.add_widget(MDLabel(text="改为：", theme_text_color="Secondary",
                                 size_hint_y=None, height=30))
        from kivy.uix.gridlayout import GridLayout
        grid = GridLayout(cols=2, spacing=8, size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for st, label in SIGN_STATUS_MAP.items():
            btn = MDRaisedButton(text=label, size_hint=(1, None), height=50)
            btn.bind(on_release=lambda x, s=sign, st=st: self._do_custom_sign(s, st))
            grid.add_widget(btn)
        layout.add_widget(grid)
        cancel = MDFlatButton(text="取消", size_hint=(1, None), height=40)
        cancel.bind(on_release=lambda *_: self._dialog.dismiss())
        layout.add_widget(cancel)
        self._dialog = MDDialog(title="选择改签状态", type="custom", content_cls=layout)
        self._dialog.open()

    def _do_custom_sign(self, sign, status_type):
        if getattr(self, "_dialog", None): self._dialog.dismiss()
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
        for s in (self.login, self.dashboard, self.accounts, self.courses, self.speed, self.answer, self.sign):
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
                        "sign": self.sign}
        sm.current = "login"
        return self.nav_layout

    def on_start(self):
        Clock.schedule_once(lambda dt: self._set_status_bar_color(), 1.0)

    def on_resume(self):
        Clock.schedule_once(lambda dt: self._set_status_bar_color(), 0.3)

    def on_stop(self):
        # 退出时停止所有监听线程
        for s in self.screens.values():
            if hasattr(s, "stop_monitor"):
                s.stop_monitor()

    def _set_status_bar_color(self):
        try:
            from android import mActivity
            from jnius import autoclass
            Color = autoclass("android.graphics.Color")
            mActivity.getWindow().setStatusBarColor(Color.parseColor("#2196F3"))
        except Exception as e:
            try:
                self.login.status.text = f"状态栏设置失败: {e}"
            except Exception:
                pass

    def goto(self, name):
        self.sidebar.refresh()
        if self.sm.current == name:
            # 同一页再次进入:ScreenManager 不会重发 on_pre_enter,手动刷新
            self.screens[name].on_pre_enter()
        else:
            self.sm.current = name  # 框架会自动触发目标页 on_pre_enter(只一次)

    def logout(self):
        """退出登录:清会话 → 停监听 → 回登录页。"""
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
