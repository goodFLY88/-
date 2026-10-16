# -*- coding: utf-8 -*-
"""ICVE 安卓版（KivyMD）—— 登录 / 课程 / 刷课 / 答题 / 签到"""
import re
import threading

from kivy.clock import Clock
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivymd.app import MDApp
from kivymd.uix.screen import MDScreen
from kivymd.uix.screenmanager import MDScreenManager
from kivymd.uix.list import MDList, OneLineListItem
from kivymd.uix.button import MDRaisedButton, MDFlatButton
from kivymd.uix.textfield import MDTextField
from kivymd.uix.toolbar import MDTopAppBar
from kivymd.uix.label import MDLabel
from kivymd.uix.menu import MDDropdownMenu

from zjy_client import ZjyClient, SSO_BASE
from auth import _exchange_token
from speed_course import run_speed_course
from answer import get_course_exams_list, run_auto_answer_all_task
from sign import get_signs, one_click_sign

# 注册中文字体（KivyMD 默认用 Roboto，映射到思源黑体避免中文方块）
from kivy.core.text import LabelBase
LabelBase.register(name="Roboto",
                   fn_regular="NotoSansSC.ttf",
                   fn_bold="NotoSansSC.ttf",
                   fn_italic="NotoSansSC.ttf",
                   fn_bolditalic="NotoSansSC.ttf")

LOGIN_URL = f"{SSO_BASE}/h5/?mode=simple&source=15&redirect=http://127.0.0.1:9527#/login"


class LoginScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "login"
        self.app = app

        root = BoxLayout(orientation="vertical")
        root.add_widget(MDTopAppBar(title="智慧职教 · 登录"))

        scroll = ScrollView()
        box = BoxLayout(orientation="vertical", padding=20, spacing=20,
                        size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))

        box.add_widget(MDLabel(
            text="① 用手机浏览器打开下方链接并登录：",
            theme_text_color="Primary", size_hint_y=None, height=40))

        self.link_label = MDLabel(text=LOGIN_URL, size_hint_y=None,
                                  height=70, theme_text_color="Secondary")
        box.add_widget(self.link_label)
        copy_btn = MDRaisedButton(text="复制链接", size_hint=(1, None), height=50)
        copy_btn.bind(on_release=lambda *_: self.copy_link())
        box.add_widget(copy_btn)

        box.add_widget(MDLabel(
            text="② 登录后复制浏览器地址栏网址，粘贴到这里：",
            theme_text_color="Primary", size_hint_y=None, height=40))

        self.input = MDTextField(hint_text="粘贴 token 网址",
                                size_hint_y=None, height=60)
        box.add_widget(self.input)
        paste_btn = MDRaisedButton(text="粘贴", size_hint=(1, None), height=50)
        paste_btn.bind(on_release=lambda *_: self.do_paste())
        box.add_widget(paste_btn)

        self.status = MDLabel(text="尚未登录", theme_text_color="Error",
                             size_hint_y=None, height=40)
        box.add_widget(self.status)

        btn = MDRaisedButton(text="登 录", size_hint=(1, None), height=50)
        btn.bind(on_release=lambda *_: self.do_login())
        box.add_widget(btn)

        scroll.add_widget(box)
        root.add_widget(scroll)
        self.add_widget(root)

    def copy_link(self):
        from kivy.core.clipboard import Clipboard
        Clipboard.copy(LOGIN_URL)
        self.status.text = "链接已复制，去浏览器粘贴打开登录"

    def do_paste(self):
        from kivy.core.clipboard import Clipboard
        self.input.text = Clipboard.paste().strip()
        self.status.text = "已粘贴，点登录"

    def do_login(self):
        raw = self.input.text.strip()
        m = re.search(r"token=([^&#\s]+)", raw)
        if not m:
            self.status.text = "没找到 token，请复制登录后地址栏的完整网址"
            return
        self.status.text = "登录中..."
        token = m.group(1)

        def work():
            client = _exchange_token(token)
            Clock.schedule_once(lambda dt: self._on_login(client), 0)

        threading.Thread(target=work, daemon=True).start()

    def _on_login(self, client):
        if client:
            self.app.client = client
            self.status.text = f"欢迎 {client.user_info.get('nickName', '')}"
            self.app.goto("courses")
        else:
            self.status.text = "登录失败，token 可能过期，重试"


class CourseScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "courses"
        self.app = app
        self.courses = []
        box = BoxLayout(orientation="vertical")
        box.add_widget(MDTopAppBar(title="我的课程"))
        scroll = ScrollView()
        self.list = MDList()
        scroll.add_widget(self.list)
        box.add_widget(scroll)
        self.add_widget(box)

    def on_pre_enter(self):
        self.list.clear_widgets()
        self.list.add_widget(OneLineListItem(text="加载中..."))

        def work():
            try:
                self.courses = self.app.client.get_my_courses()
            except Exception as e:
                self.courses = []
                print("拉课程失败:", e)
            Clock.schedule_once(lambda dt: self._show(), 0)

        threading.Thread(target=work, daemon=True).start()

    def _show(self):
        self.list.clear_widgets()
        if not self.courses:
            self.list.add_widget(OneLineListItem(text="（没有课程或拉取失败）"))
            return
        for c in self.courses:
            item = OneLineListItem(
                text=f"[{c.get('_courseType','?')}] {c.get('courseName','?')}")
            item.bind(on_release=lambda x, course=c: self.app.open_course(course))
            self.list.add_widget(item)


class RunScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "run"
        self.app = app
        self.course = None
        box = BoxLayout(orientation="vertical")
        box.add_widget(MDTopAppBar(title="课程操作"))

        btns = BoxLayout(size_hint=(1, None), height=50, spacing=8)
        for label, key in [("刷课", "speed"), ("答题", "answer"), ("签到补签", "sign")]:
            b = MDRaisedButton(text=label)
            b.bind(on_release=lambda x, k=key: self.run_task(k))
            btns.add_widget(b)
        box.add_widget(btns)

        self.log = MDLabel(text="", size_hint_y=None, markup=True,
                           halign="left", valign="top", theme_text_color="Primary")
        self.log.bind(texture_size=lambda w, s: setattr(w, "height", s[1]))
        sv = ScrollView()
        sv.add_widget(self.log)
        box.add_widget(sv)
        self.add_widget(box)

    def set_course(self, course):
        self.course = course
        self.log.text = f"[b]{course.get('courseName','')}[/b]\n"

    def append(self, text):
        self.log.text += text + "\n"

    def run_task(self, key):
        if not self.course:
            return
        c = self.course
        ctype = c.get("_courseType", "SPOC")
        cid = c.get("classId", ""); ciid = c.get("courseInfoId", ""); coid = c.get("courseId", "")

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
                    done = 0
                    for s in signs:
                        if str(s.get("myStatus", "0")) == "0":
                            r = one_click_sign(self.app.client, s)
                            if r.get("success"):
                                done += 1
                    Clock.schedule_once(lambda dt: self.append(f">> 补签完成，成功 {done} 条"), 0)
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
        # 全局覆盖 KivyMD 所有字体样式为中文字体
        for k in list(self.theme_cls.font_styles.keys()):
            self.theme_cls.font_styles[k][0] = "NotoSansSC.ttf"
        sm = MDScreenManager()
        self.login = LoginScreen(self)
        self.courses = CourseScreen(self)
        self.run = RunScreen(self)
        for s in (self.login, self.courses, self.run):
            sm.add_widget(s)
        self.sm = sm
        sm.current = "login"
        return sm

    def show(self, name):
        self.sm.current = name
        if name == "courses":
            self.courses.on_pre_enter()

    def goto(self, name):
        self.show(name)

    def open_course(self, course):
        self.run.set_course(course)
        self.show("run")


if __name__ == "__main__":
    ICVEApp().run()
