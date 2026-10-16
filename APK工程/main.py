# -*- coding: utf-8 -*-
"""ICVE 安卓版（KivyMD）—— 参考桌面版布局：控制台/刷课/答题/签到/账号管理"""
import re
import threading

from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from kivymd.uix.list import MDList, OneLineListItem, TwoLineListItem
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.label import MDLabel

from zjy_client import ZjyClient, SSO_BASE
from auth import _exchange_token
from speed_course import run_speed_course
from answer import get_course_exams_list, run_auto_answer_all_task
from sign import get_signs, batch_sign
from accounts import load_accounts, list_accounts, save_account, delete_account

from kivy.core.text import LabelBase
LabelBase.register(name="Roboto",
                   fn_regular="NotoSansSC.ttf",
                   fn_bold="NotoSansSC.ttf",
                   fn_italic="NotoSansSC.ttf",
                   fn_bolditalic="NotoSansSC.ttf")

LOGIN_URL = f"{SSO_BASE}/h5/?mode=simple&source=15&redirect=http://127.0.0.1:9527#/login"
STATUS_MAP = {"0": "未签到", "1": "已签到", "2": "迟到", "3": "请假", "4": "病假", "5": "事假"}


def make_toolbar(title, on_menu=None):
    return MDTopAppBar(title=title)


class LoginScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "login"
        self.app = app
        root = BoxLayout(orientation="vertical")
        root.add_widget(MDTopAppBar(title="智慧职教 · 登录"))
        scroll = ScrollView()
        box = BoxLayout(orientation="vertical", padding=20, spacing=20, size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        box.add_widget(MDLabel(text="① 用浏览器打开链接登录：", theme_text_color="Primary", size_hint_y=None, height=40))
        self.link_label = MDLabel(text=LOGIN_URL, size_hint_y=None, height=70, theme_text_color="Secondary")
        box.add_widget(self.link_label)
        copy_btn = MDRaisedButton(text="复制链接", size_hint=(1, None), height=50)
        copy_btn.bind(on_release=lambda *_: self.copy_link())
        box.add_widget(copy_btn)
        box.add_widget(MDLabel(text="② 复制地址栏网址粘贴到这里：", theme_text_color="Primary", size_hint_y=None, height=40))
        self.input = MDTextField(hint_text="粘贴 token 网址", size_hint_y=None, height=60)
        box.add_widget(self.input)
        paste_btn = MDRaisedButton(text="粘贴", size_hint=(1, None), height=50)
        paste_btn.bind(on_release=lambda *_: self.do_paste())
        box.add_widget(paste_btn)
        self.status = MDLabel(text="尚未登录", theme_text_color="Error", size_hint_y=None, height=40)
        box.add_widget(self.status)
        btn = MDRaisedButton(text="登 录", size_hint=(1, None), height=50)
        btn.bind(on_release=lambda *_: self.do_login())
        box.add_widget(btn)
        box.add_widget(MDLabel(text="—— 已保存账号 ——", theme_text_color="Secondary", size_hint_y=None, height=40))
        self.acc_list = MDList()
        box.add_widget(self.acc_list)
        scroll.add_widget(box)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self):
        self.acc_list.clear_widgets()
        for name, info in list_accounts():
            item = TwoLineListItem(text=f"👤 {name}", secondary_text=f"学号 {info.get('userName','?')}")
            item.bind(on_release=lambda x, n=name, i=info: self.login_saved(n, i))
            self.acc_list.add_widget(item)

    def copy_link(self):
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(LOGIN_URL)
        self.status.text = "链接已复制"

    def do_paste(self):
        from kivy.core.clipboard import Clipboard
        self.input.text = Clipboard.paste().strip()
        self.status.text = "已粘贴，点登录"

    def do_login(self):
        raw = self.input.text.strip()
        m = re.search(r"token=([^&#\s]+)", raw)
        if not m:
            self.status.text = "没找到 token"
            return
        self.status.text = "登录中..."
        sso = m.group(1)
        def work():
            client = _exchange_token(sso)
            Clock.schedule_once(lambda dt: self._on_login(client, sso), 0)
        threading.Thread(target=work, daemon=True).start()

    def login_saved(self, name, info):
        tok = info.get("token", ""); sso = info.get("ssoToken", "")
        if not tok:
            self.status.text = "Token 为空"
            return
        self.status.text = f"验证 {name}..."
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
                    Clock.schedule_once(lambda dt: setattr(self.status, "text", "Token 已失效"), 0)
            except Exception as e:
                Clock.schedule_once(lambda dt: setattr(self.status, "text", f"失败: {e}"), 0)
        threading.Thread(target=work, daemon=True).start()

    def _on_login(self, client, sso=""):
        if client:
            self.app.client = client
            if sso: save_account(client, sso)
            self.app.goto("dashboard")
        else:
            self.status.text = "登录失败"


class DashboardScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "dashboard"
        self.app = app
        root = BoxLayout(orientation="vertical")
        root.add_widget(MDTopAppBar(title="智慧职教控制台"))
        scroll = ScrollView()
        box = BoxLayout(orientation="vertical", padding=20, spacing=15, size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        self.welcome = MDLabel(text="", theme_text_color="Primary", size_hint_y=None, height=60)
        box.add_widget(self.welcome)
        for label, target in [
            ("📚 我的课程", "courses"),
            ("⚡ 一键刷课", "speed"),
            ("✍️ 自动答题", "answer"),
            ("✅ 签到改签", "sign"),
            ("👥 账号管理", "accounts"),
        ]:
            b = MDRaisedButton(text=label, size_hint=(1, None), height=60)
            b.bind(on_release=lambda x, t=target: self.app.goto(t))
            box.add_widget(b)
        box.add_widget(MDLabel(text="", size_hint_y=None, height=20))
        logout = MDFlatButton(text="退出登录", size_hint=(1, None), height=50)
        logout.bind(on_release=lambda *_: self.app.goto("login"))
        box.add_widget(logout)
        scroll.add_widget(box)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self):
        if self.app.client and self.app.client.user_info:
            u = self.app.client.user_info
            self.welcome.text = f"欢迎 {u.get('nickName','')}\n学号 {u.get('userName','')}"


class AccountsScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "accounts"
        self.app = app
        root = BoxLayout(orientation="vertical")
        root.add_widget(make_toolbar("账号管理"))
        back = MDFlatButton(text="← 返回控制台", size_hint=(1, None), height=40)
        back.bind(on_release=lambda *_: self.app.goto("dashboard"))
        root.add_widget(back)
        scroll = ScrollView()
        self.list = MDList()
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self):
        self.list.clear_widgets()
        for name, info in list_accounts():
            current = "（当前）" if (self.app.client and self.app.client.user_info.get("nickName") == name) else ""
            item = TwoLineListItem(text=f"👤 {name} {current}", secondary_text=f"学号 {info.get('userName','?')}  点删除")
            item.bind(on_release=lambda x, n=name: self.del_acc(n))
            self.list.add_widget(item)
        back = MDRaisedButton(text="返回控制台", size_hint=(1, None), height=50)
        back.bind(on_release=lambda *_: self.app.goto("dashboard"))
        self.list.add_widget(back)

    def del_acc(self, name):
        delete_account(name)
        self.on_pre_enter()


class CourseSelectScreen(MDScreen):
    """基础页：课程列表 + 日志区，子类定义操作"""
    def __init__(self, app, name, title, action_label, action_key, **kw):
        super().__init__(**kw)
        self.name = name
        self.app = app
        self.action_key = action_key
        self.courses = []
        self.selected_course = None
        root = BoxLayout(orientation="vertical")
        root.add_widget(make_toolbar(title, on_menu=lambda: self.app.goto("dashboard")))
        back = MDFlatButton(text="← 返回控制台", size_hint=(1, None), height=40)
        back.bind(on_release=lambda *_: self.app.goto("dashboard"))
        root.add_widget(back)
        # 课程列表
        self.list = MDList()
        scroll = ScrollView(size_hint_y=0.4)
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        # 操作按钮
        self.action_btn = MDRaisedButton(text=action_label, size_hint=(1, None), height=50)
        self.action_btn.bind(on_release=lambda *_: self.do_action())
        root.add_widget(self.action_btn)
        # 日志
        self.log = MDLabel(text="选择课程后点按钮开始", size_hint_y=None, markup=True,
                           halign="left", valign="top", theme_text_color="Primary", padding=(10, 10))
        self.log.bind(texture_size=lambda w, s: setattr(w, "height", max(s[1], 100)))
        sv = ScrollView()
        sv.add_widget(self.log)
        root.add_widget(sv)
        self.add_widget(root)

    def on_pre_enter(self):
        self.list.clear_widgets()
        self.list.add_widget(OneLineListItem(text="加载课程中..."))
        def work():
            try:
                self.courses = self.app.client.get_my_courses()
            except Exception as e:
                self.courses = []
            Clock.schedule_once(lambda dt: self.show_courses(), 0)
        threading.Thread(target=work, daemon=True).start()

    def show_courses(self):
        self.list.clear_widgets()
        for c in self.courses:
            item = OneLineListItem(text=f"[{c.get('_courseType','?')}] {c.get('courseName','?')}")
            item.bind(on_release=lambda x, course=c: self.select_course(course))
            self.list.add_widget(item)

    def select_course(self, course):
        self.selected_course = course
        self.log.text = f"[b]已选: {course.get('courseName','')}[/b]\n"

    def append(self, text):
        self.log.text += text + "\n"

    def do_action(self):
        if not self.selected_course:
            self.append("!! 请先选择课程")
            return
        c = self.selected_course
        ctype = c.get("_courseType", "SPOC")
        cid = c.get("classId", ""); ciid = c.get("courseInfoId", ""); coid = c.get("courseId", "")
        key = self.action_key

        def work():
            try:
                if key == "speed":
                    Clock.schedule_once(lambda dt: self.append(">> 开始刷课..."), 0)
                    run_speed_course(self.app.client, c, "all")
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
                        mark = "✅" if st == "1" else ("⬜" if st == "0" else "⚠️")
                        Clock.schedule_once(lambda dt, s=s, st=st, mark=mark: self.append(
                            f"{mark} [{s.get('teachDate','')}] {s.get('teachTitle','?')} {STATUS_MAP.get(st,st)}"), 0)
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
                Clock.schedule_once(lambda dt: self.append(f"!! 出错: {e}"), 0)
        threading.Thread(target=work, daemon=True).start()


class ICVEApp(MDApp):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.client = None

    def build(self):
        self.theme_cls.theme_style = "Light"
        self.theme_cls.primary_palette = "Blue"
        for k in list(self.theme_cls.font_styles.keys()):
            self.theme_cls.font_styles[k][0] = "NotoSansSC.ttf"
        sm = MDScreenManager()
        self.login = LoginScreen(self)
        self.dashboard = DashboardScreen(self)
        self.accounts = AccountsScreen(self)
        self.courses = CourseSelectScreen(self, "courses", "我的课程", "开始刷课", "speed")
        self.speed = CourseSelectScreen(self, "speed", "一键刷课", "开始刷课", "speed")
        self.answer = CourseSelectScreen(self, "answer", "自动答题", "拉取并作答", "answer")
        self.sign = CourseSelectScreen(self, "sign", "签到改签", "拉取并补签", "sign")
        for s in (self.login, self.dashboard, self.accounts, self.courses, self.speed, self.answer, self.sign):
            sm.add_widget(s)
        self.sm = sm
        sm.current = "login"
        return sm

    def show(self, name):
        self.sm.current = name
        if name == "dashboard":
            self.dashboard.on_pre_enter()
        elif name == "accounts":
            self.accounts.on_pre_enter()
        elif name in ("courses", "speed", "answer", "sign"):
            screen = getattr(self, name)
            screen.on_pre_enter()
        elif name == "login":
            self.login.on_pre_enter()

    def goto(self, name):
        self.show(name)


if __name__ == "__main__":
    ICVEApp().run()
