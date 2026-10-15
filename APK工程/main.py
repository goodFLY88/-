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

LOGIN_URL = f"{SSO_BASE}/h5/?mode=simple&source=15&redirect=http://127.0.0.1:9527#/login"


class LoginScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "login"
        self.app = app
        box = BoxLayout(orientation="vertical", padding=20, spacing=15)

        box.add_widget(MDTopAppBar(title="智慧职教 · 登录"))
        box.add_widget(MDLabel(
            text="① 用手机浏览器打开下方链接并登录：", theme_text_color="Primary"))
        link = MDTextField(multiline=True, readonly=True)
        link.text = LOGIN_URL
        box.add_widget(link)
        box.add_widget(MDLabel(
            text="② 登录后复制浏览器地址栏整段网址，粘贴到这里：",
            theme_text_color="Primary"))
        self.input = MDTextField(hint_text="粘贴 http://127.0.0.1:9527/?token=... 这串网址",
                                 multiline=True)
        box.add_widget(self.input)
        self.status = MDLabel(text="尚未登录", theme_text_color="Error")
        box.add_widget(self.status)
        btn = MDRaisedButton(text="登 录", size_hint=(1, None), height=50)
        btn.bind(on_release=lambda *_: self.do_login())
        box.add_widget(btn)
        self.add_widget(box)

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

        self.log = Label(size_hint_y=None, halign="left", valign="top",
                         markup=True)
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
        root = BoxLayout()
        self.login = LoginScreen(self)
        self.courses = CourseScreen(self)
        self.run = RunScreen(self)
        for s in (self.login, self.courses, self.run):
            root.add_widget(s)
        self.show("login")
        return root

    def show(self, name):
        for s in (self.login, self.courses, self.run):
            s.opacity = 1 if s.name == name else 0
            s.disabled = s.name != name
        if name == "courses":
            self.courses.on_pre_enter()

    def goto(self, name):
        self.show(name)

    def open_course(self, course):
        self.run.set_course(course)
        self.show("run")


if __name__ == "__main__":
    ICVEApp().run()
