# -*- coding: utf-8 -*-
"""ICVE 安卓版 — 层次分明的 KivyMD 界面"""
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
from kivymd.uix.dialog import MDDialog
from kivymd.uix.card import MDCard
from kivymd.uix.navigationdrawer import MDNavigationDrawer, MDNavigationLayout

from zjy_client import ZjyClient, SSO_BASE
from auth import _exchange_token
from speed_course import run_speed_course
from answer import get_course_exams_list, run_auto_answer_all_task
from sign import get_signs, batch_sign, do_sign_action
from accounts import list_accounts, save_account, delete_account

from kivy.core.text import LabelBase
LabelBase.register(name="Roboto",
                   fn_regular="NotoSansSC.ttf",
                   fn_bold="NotoSansSC.ttf",
                   fn_italic="NotoSansSC.ttf",
                   fn_bolditalic="NotoSansSC.ttf")

LOGIN_URL = f"{SSO_BASE}/h5/?mode=simple&source=15&redirect=http://127.0.0.1:9527#/login"
STATUS_MAP = {"0": "未签到", "1": "已签到", "2": "迟到", "3": "请假", "4": "病假", "5": "事假"}

SPACE = 12
SMALL = 8


def section_header(text):
    box = BoxLayout(orientation="vertical", size_hint_y=None, height=38,
                    padding=(SPACE, 4, SPACE, 0), spacing=2)
    box.add_widget(MDLabel(text=text, theme_text_color="Secondary", size_hint_y=None, height=20))
    box.add_widget(BoxLayout(size_hint_y=None, height=1, md_bg_color=[0.85,0.85,0.85,1]))
    return box


def make_card(padding=SPACE):
    card = MDCard(radius=[12, 12, 12, 12], elevation=1, padding=padding)
    box = BoxLayout(orientation="vertical", spacing=SMALL)
    card.add_widget(box)
    card._inner = box
    return card


def topbar(title):
    bar = MDTopAppBar(title=title)
    bar.md_bg_color = [1, 1, 1, 1]
    bar.specific_text_color = [0.15, 0.15, 0.15, 1]
    return bar


def menu_button(app):
    b = MDFlatButton(text="菜单", size_hint=(None, None), size=(70, 32), pos_hint={"left": 1})
    b.bind(on_release=lambda *_: app.nav_drawer.set_state("open"))
    return b


class SidebarMenu(BoxLayout):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.orientation = "vertical"
        self.padding = 0
        self.spacing = 0
        self.app = app
        header = MDCard(size_hint_y=None, height=100,
                        md_bg_color=[0.13, 0.59, 0.95, 1], radius=[0, 0, 0, 0],
                        elevation=0, padding=(SPACE, 15, SPACE, 15))
        hbox = BoxLayout(orientation="vertical", spacing=6)
        hbox.add_widget(MDLabel(text="ICVE 学习助手", theme_text_color="Custom",
                                text_color=[1, 1, 1, 1], size_hint_y=None, height=38))
        hbox.add_widget(MDLabel(text="智慧职教工具", theme_text_color="Custom",
                                text_color=[0.9, 0.9, 0.9, 1], size_hint_y=None, height=22))
        header.add_widget(hbox)
        self.add_widget(header)
        content = BoxLayout(orientation="vertical", padding=(4, 10, 4, 10), spacing=2)
        content.add_widget(MDLabel(text="主功能", theme_text_color="Secondary",
                                   size_hint_y=None, height=28, padding=(12, 0)))
        for label, target in [
            ("控制台", "dashboard"), ("一键刷课", "speed"), ("自动答题", "answer"),
            ("签到改签", "sign"), ("我的课程", "courses"),
        ]:
            btn = OneLineListItem(text=label)
            btn.bind(on_release=lambda x, t=target: self._nav(t))
            content.add_widget(btn)
        content.add_widget(MDLabel(text="系统", theme_text_color="Secondary",
                                   size_hint_y=None, height=28, padding=(12, 0)))
        for label, target in [("账号管理", "accounts"), ("退出登录", "login")]:
            btn = OneLineListItem(text=label)
            btn.bind(on_release=lambda x, t=target: self._nav(t))
            content.add_widget(btn)
        self.status_label = MDLabel(text="● 未登录", theme_text_color="Error",
                                    size_hint_y=None, height=36, padding=(12, 0))
        content.add_widget(self.status_label)
        self.add_widget(content)

    def _nav(self, target):
        self.app.nav_drawer.set_state("close")
        self.app.goto(target)

    def refresh(self):
        if self.app.client and self.app.client.user_info:
            self.status_label.text = f"● 已登录 {self.app.client.user_info.get('nickName','')}"
            self.status_label.theme_text_color = "Primary"
        else:
            self.status_label.text = "● 未登录"
            self.status_label.theme_text_color = "Error"


class LoginScreen(MDScreen):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.name = "login"
        self.app = app
        root = BoxLayout(orientation="vertical")
        root.add_widget(topbar("智慧职教 · 登录"))
        scroll = ScrollView()
        outer = BoxLayout(orientation="vertical", padding=SPACE, spacing=SPACE, size_hint_y=None)
        outer.bind(minimum_height=outer.setter("height"))

        card = make_card()
        card._inner.add_widget(MDLabel(text="① 用浏览器打开链接登录", theme_text_color="Primary",
                                size_hint_y=None, height=28))
        self.link_label = MDLabel(text=LOGIN_URL, size_hint_y=None, height=70,
                                  theme_text_color="Secondary")
        card._inner.add_widget(self.link_label)
        copy_btn = MDRaisedButton(text="复制链接", size_hint=(1, None), height=42)
        copy_btn.bind(on_release=lambda *_: self.copy_link())
        card._inner.add_widget(copy_btn)
        card._inner.add_widget(BoxLayout(size_hint_y=None, height=1, md_bg_color=[0.85,0.85,0.85,1]))
        card._inner.add_widget(MDLabel(text="② 复制地址栏网址粘贴到这里", theme_text_color="Primary",
                                size_hint_y=None, height=28))
        self.input = MDTextField(hint_text="粘贴 token 网址", size_hint_y=None, height=50)
        card._inner.add_widget(self.input)
        paste_btn = MDRaisedButton(text="粘贴", size_hint=(1, None), height=42)
        paste_btn.bind(on_release=lambda *_: self.do_paste())
        card._inner.add_widget(paste_btn)
        self.status = MDLabel(text="尚未登录", theme_text_color="Error",
                              size_hint_y=None, height=28)
        card._inner.add_widget(self.status)
        login_btn = MDRaisedButton(text="登 录", size_hint=(1, None), height=48)
        login_btn.bind(on_release=lambda *_: self.do_login())
        card._inner.add_widget(login_btn)
        outer.add_widget(card)

        outer.add_widget(section_header("已保存账号"))
        self.acc_list = MDList()
        outer.add_widget(self.acc_list)
        scroll.add_widget(outer)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self):
        self.acc_list.clear_widgets()
        for name, info in list_accounts():
            item = TwoLineListItem(text=name, secondary_text=f"学号 {info.get('userName','?')}")
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
        root.add_widget(topbar("控制台"))
        root.add_widget(menu_button(app))
        scroll = ScrollView()
        outer = BoxLayout(orientation="vertical", padding=SPACE, spacing=SPACE, size_hint_y=None)
        outer.bind(minimum_height=outer.setter("height"))

        card = make_card()
        self.welcome = MDLabel(text="", theme_text_color="Primary", size_hint_y=None, height=60)
        card._inner.add_widget(self.welcome)
        outer.add_widget(card)

        outer.add_widget(section_header("功能"))
        func_card = make_card(padding=4)
        for label, desc, target in [
            ("我的课程", "查看并选择课程", "courses"),
            ("一键刷课", "自动刷完课程视频", "speed"),
            ("自动答题", "拉取作业并自动作答", "answer"),
            ("签到改签", "补签或修改签到状态", "sign"),
            ("账号管理", "管理已保存的账号", "accounts"),
        ]:
            item = TwoLineListItem(text=label, secondary_text=desc)
            item.bind(on_release=lambda x, t=target: self.app.goto(t))
            func_card._inner.add_widget(item)
        outer.add_widget(func_card)
        scroll.add_widget(outer)
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
        root.add_widget(topbar("账号管理"))
        root.add_widget(menu_button(app))
        scroll = ScrollView()
        outer = BoxLayout(orientation="vertical", padding=SPACE, spacing=SPACE, size_hint_y=None)
        outer.bind(minimum_height=outer.setter("height"))
        outer.add_widget(section_header("已保存账号"))
        self.list = MDList()
        outer.add_widget(self.list)
        scroll.add_widget(outer)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self):
        self.list.clear_widgets()
        for name, info in list_accounts():
            current = "（当前）" if (self.app.client and self.app.client.user_info.get("nickName") == name) else ""
            item = TwoLineListItem(text=f"{name} {current}",
                                   secondary_text=f"学号 {info.get('userName','?')}  点删除")
            item.bind(on_release=lambda x, n=name: self.del_acc(n))
            self.list.add_widget(item)
        back = MDRaisedButton(text="返回控制台", size_hint=(1, None), height=46)
        back.bind(on_release=lambda *_: self.app.goto("dashboard"))
        self.list.add_widget(back)

    def del_acc(self, name):
        delete_account(name)
        self.on_pre_enter()


class CourseSelectScreen(MDScreen):
    def __init__(self, app, name, title, subtitle, action_label, action_key, **kw):
        super().__init__(**kw)
        self.name = name
        self.app = app
        self.action_key = action_key
        self.courses = []
        self.selected_course = None
        self._monitoring = False
        root = BoxLayout(orientation="vertical")
        root.add_widget(topbar(title))
        root.add_widget(menu_button(app))
        scroll = ScrollView()
        outer = BoxLayout(orientation="vertical", padding=SPACE, spacing=SPACE, size_hint_y=None)
        outer.bind(minimum_height=outer.setter("height"))

        outer.add_widget(MDLabel(text=subtitle, theme_text_color="Secondary",
                                 size_hint_y=None, height=28))

        outer.add_widget(section_header("选择课程"))
        self.list = MDList()
        outer.add_widget(self.list)

        outer.add_widget(section_header("操作"))
        action_card = make_card()
        self.action_btn = MDRaisedButton(text=action_label, size_hint=(1, None), height=46)
        self.action_btn.bind(on_release=lambda *_: self.do_action())
        action_card._inner.add_widget(self.action_btn)
        if action_key == "sign":
            self.custom_btn = MDRaisedButton(text="自定义改签", size_hint=(1, None), height=42)
            self.custom_btn.md_bg_color = [0.85, 0.85, 0.85, 1]
            self.custom_btn.text_color = [0.15, 0.15, 0.15, 1]
            self.custom_btn.bind(on_release=lambda *_: self.custom_sign())
            action_card._inner.add_widget(self.custom_btn)
            self.monitor_btn = MDRaisedButton(text="启动自动监听", size_hint=(1, None), height=42)
            self.monitor_btn.md_bg_color = [0.2, 0.7, 0.3, 1]
            self.monitor_btn.bind(on_release=lambda *_: self.toggle_monitor())
            action_card._inner.add_widget(self.monitor_btn)
        outer.add_widget(action_card)

        outer.add_widget(section_header("运行日志"))
        log_card = make_card()
        self.log = MDLabel(text="选择课程后点按钮开始", size_hint_y=None,
                           halign="left", valign="top", theme_text_color="Primary", height=120)
        log_card._inner.add_widget(self.log)
        outer.add_widget(log_card)

        scroll.add_widget(outer)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self):
        self.list.clear_widgets()
        self.list.add_widget(OneLineListItem(text="加载课程中..."))
        def work():
            try:
                self.courses = self.app.client.get_my_courses()
            except Exception:
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
        self.log.text = f"已选: {course.get('courseName','')}"

    def append(self, text):
        self.log.text += "\n" + text
        self.log.height = max(120, self.log.texture_size[1])

    def do_action(self):
        if not self.selected_course:
            self.append("!! 请先选择课程")
            return
        c = self.selected_course
        ctype = c.get("_courseType", "SPOC")
        cid = c.get("classId",""); ciid = c.get("courseInfoId",""); coid = c.get("courseId","")
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
                        mark = "已签" if st == "1" else ("未签" if st == "0" else "注意")
                        Clock.schedule_once(lambda dt, s=s, st=st, mark=mark: self.append(
                            f"[{mark}] {s.get('teachDate','')} {s.get('teachTitle','?')} {STATUS_MAP.get(st,st)}"), 0)
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

    def toggle_monitor(self):
        if self._monitoring:
            self._monitoring = False
            self.monitor_btn.text = "启动自动监听"
            self.monitor_btn.md_bg_color = [0.2, 0.7, 0.3, 1]
            self.append(">> 已停止监听")
        else:
            self._monitoring = True
            self.monitor_btn.text = "停止监听"
            self.monitor_btn.md_bg_color = [0.9, 0.3, 0.2, 1]
            self.append(">> 启动自动监听（每30秒扫描）")
            threading.Thread(target=self._monitor_loop, daemon=True).start()

    def _monitor_loop(self):
        import time
        seen = set()
        first = True
        while self._monitoring:
            try:
                courses = self.app.client.get_my_courses()
                for c in courses:
                    cid = c.get("classId",""); ciid = c.get("courseInfoId",""); coid = c.get("courseId","")
                    signs = get_signs(self.app.client, cid, ciid, coid)
                    for s in signs:
                        key = (cid, s.get("signId"))
                        if str(s.get("myStatus","0")) == "0" and key not in seen:
                            seen.add(key)
                            if not first:
                                type_map = {"1":"普通","2":"二维码","3":"手势","4":"位置","5":"人脸"}
                                t = type_map.get(s.get("signType","?"), "?")
                                Clock.schedule_once(lambda dt, c=c, s=s, t=t: self.append(
                                    f"[新签到] {c.get('courseName','?')} {t} {s.get('teachTitle','?')}"), 0)
                                result = batch_sign(self.app.client, [s], cid, ciid, coid)
                                for d in result.get("details", []):
                                    Clock.schedule_once(lambda dt, d=d, c=c: self.append(
                                        f"  {c.get('courseName','?')}: {d['result']} {d['msg']}"), 0)
                first = False
            except Exception as e:
                Clock.schedule_once(lambda dt, e=e: self.append(f"[监听] {e}"), 0)
            for _ in range(30):
                if not self._monitoring: break
                time.sleep(1)

    def custom_sign(self):
        if not self.selected_course:
            self.append("!! 请先选择课程")
            return
        c = self.selected_course
        cid = c.get("classId",""); ciid = c.get("courseInfoId",""); coid = c.get("courseId","")
        self.append(">> 拉取签到记录...")
        def work():
            signs = get_signs(self.app.client, cid, ciid, coid)
            if not signs:
                Clock.schedule_once(lambda dt: self.append("没有签到记录"), 0)
                return
            Clock.schedule_once(lambda dt: self._show_sign_dialog(signs, cid, ciid, coid), 0)
        threading.Thread(target=work, daemon=True).start()

    def _show_sign_dialog(self, items, cid, ciid, coid):
        layout = BoxLayout(orientation="vertical", spacing=2, size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))
        layout.add_widget(MDLabel(text="选择签到记录：", size_hint_y=None, height=32))
        self._sign_ctx = (cid, ciid, coid)
        for s in items:
            st = str(s.get("myStatus", "0"))
            item = TwoLineListItem(text=f"{s.get('teachDate','')} {s.get('teachTitle','?')}",
                                   secondary_text=f"当前：{STATUS_MAP.get(st,st)}")
            item.bind(on_release=lambda x, sig=s: self._pick_sign_status(sig))
            layout.add_widget(item)
        self._dialog = MDDialog(title="自定义改签", type="custom", content_cls=layout)
        self._dialog.open()

    def _pick_sign_status(self, sign):
        if self._dialog: self._dialog.dismiss()
        layout = BoxLayout(orientation="vertical", spacing=SMALL, size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))
        layout.add_widget(MDLabel(text=f"改为：{sign.get('teachTitle','')}",
                                  size_hint_y=None, height=32))
        from kivy.uix.gridlayout import GridLayout
        grid = GridLayout(cols=2, spacing=SMALL, size_hint_y=None)
        grid.bind(minimum_height=grid.setter("height"))
        for st, label in [("0","未签到"),("1","已签到"),("2","迟到"),
                          ("3","请假"),("4","病假"),("5","事假")]:
            btn = MDRaisedButton(text=label, size_hint=(1, None), height=46)
            btn.bind(on_release=lambda x, s=sign, st=st: self._do_custom_sign(s, st))
            grid.add_widget(btn)
        layout.add_widget(grid)
        cancel = MDFlatButton(text="取消", size_hint=(1, None), height=36)
        cancel.bind(on_release=lambda *_: self._dialog.dismiss())
        layout.add_widget(cancel)
        self._dialog = MDDialog(title="选择状态", type="custom", content_cls=layout)
        self._dialog.open()

    def _do_custom_sign(self, sign, status_type):
        if self._dialog: self._dialog.dismiss()
        cid, ciid, coid = self._sign_ctx
        client = self.app.client
        payload = {
            "classId": cid, "courseId": coid, "courseInfoId": ciid,
            "signId": sign["signId"], "signResultType": status_type,
            "teachId": sign.get("teachId",""),
            "studentId": client.stu_id or "",
            "studentName": client.user_info.get("nickName",""),
            "studentNo": client.user_info.get("userName",""),
        }
        self.append(f">> 改签为{STATUS_MAP.get(status_type,status_type)}...")
        def work():
            r = do_sign_action(client, payload)
            Clock.schedule_once(lambda dt: self.append(
                f"  {'成功' if r['code']==200 else '失败'}: {r['msg']}"), 0)
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
        self.courses = CourseSelectScreen(self, "courses", "我的课程", "选择课程查看详情", "开始刷课", "speed")
        self.speed = CourseSelectScreen(self, "speed", "一键刷课", "选择课程后自动刷完视频", "开始刷课", "speed")
        self.answer = CourseSelectScreen(self, "answer", "自动答题", "选择课程后拉取作业并作答", "拉取并作答", "answer")
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
        sm.current = "login"
        return self.nav_layout

    def on_start(self):
        Clock.schedule_once(lambda dt: self._set_status_bar(), 1.0)

    def on_resume(self):
        Clock.schedule_once(lambda dt: self._set_status_bar(), 0.3)

    def _set_status_bar(self):
        try:
            from android import mActivity
            from jnius import autoclass
            Color = autoclass("android.graphics.Color")
            mActivity.getWindow().setStatusBarColor(Color.parseColor("#2196F3"))
        except Exception:
            pass

    def goto(self, name):
        self.sidebar.refresh()
        self.sm.current = name
        screens = {"login": self.login, "dashboard": self.dashboard, "accounts": self.accounts,
                   "courses": self.courses, "speed": self.speed, "answer": self.answer, "sign": self.sign}
        screens[name].on_pre_enter()


if __name__ == "__main__":
    ICVEApp().run()
