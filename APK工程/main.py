# -*- coding: utf-8 -*-
"""ICVE 安卓版（KivyMD）—— 桌面版布局：侧边抽屉导航 + 独立功能页"""
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

def topbar(title):
    bar = MDTopAppBar(title=title)
    bar.md_bg_color = [1, 1, 1, 1]
    bar.specific_text_color = [0.2, 0.2, 0.2, 1]
    return bar

def menu_button(app):
    b = MDFlatButton(text="菜单", size_hint=(None, None), size=(80, 35), pos_hint={"left": 1})
    b.bind(on_release=lambda *_: app.nav_drawer.set_state("open"))
    return b

LOGIN_URL = f"{SSO_BASE}/h5/?mode=simple&source=15&redirect=http://127.0.0.1:9527#/login"
STATUS_MAP = {"0": "未签到", "1": "已签到", "2": "迟到", "3": "请假", "4": "病假", "5": "事假"}


class SidebarMenu(BoxLayout):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.orientation = "vertical"
        self.padding = (10, 20, 10, 10)
        self.spacing = 2
        self.app = app
        self.add_widget(MDLabel(text="ICVE 学习助手", theme_text_color="Primary",
                                size_hint_y=None, height=50, font_style="H6"))
        self.add_widget(MDLabel(text="主功能", theme_text_color="Secondary",
                                size_hint_y=None, height=30))
        for label, target in [
            ("控制台", "dashboard"),
            ("一键刷课", "speed"),
            ("自动答题", "answer"),
            ("签到改签", "sign"),
            ("我的课程", "courses"),
        ]:
            btn = OneLineListItem(text=label)
            btn.bind(on_release=lambda x, t=target: self._nav(t))
            self.add_widget(btn)
        self.add_widget(MDLabel(text="系统", theme_text_color="Secondary",
                                size_hint_y=None, height=30))
        for label, target in [
            ("账号管理", "accounts"),
            ("退出登录", "login"),
        ]:
            btn = OneLineListItem(text=label)
            btn.bind(on_release=lambda x, t=target: self._nav(t))
            self.add_widget(btn)
        self.status_label = MDLabel(text="● 未登录", theme_text_color="Error",
                                    size_hint_y=None, height=40)
        self.add_widget(self.status_label)

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
        box = BoxLayout(orientation="vertical", padding=20, spacing=15, size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        box.add_widget(MDLabel(text="① 用浏览器打开链接登录：", theme_text_color="Primary", size_hint_y=None, height=40))
        self.link_label = MDLabel(text=LOGIN_URL, size_hint_y=None, height=80, theme_text_color="Secondary")
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
            item = TwoLineListItem(text=f"{name}", secondary_text=f"学号 {info.get('userName','?')}")
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
        box = BoxLayout(orientation="vertical", padding=20, spacing=15, size_hint_y=None)
        box.bind(minimum_height=box.setter("height"))
        self.welcome = MDLabel(text="", theme_text_color="Primary", size_hint_y=None, height=80)
        box.add_widget(self.welcome)
        for label, desc, target in [
            ("我的课程", "查看并选择课程", "courses"),
            ("一键刷课", "自动刷完课程视频", "speed"),
            ("自动答题", "拉取作业并自动作答", "answer"),
            ("签到改签", "补签或修改签到状态", "sign"),
            ("账号管理", "管理已保存的账号", "accounts"),
        ]:
            item = TwoLineListItem(text=label, secondary_text=desc)
            item.bind(on_release=lambda x, t=target: self.app.goto(t))
            box.add_widget(item)
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
        root.add_widget(topbar("账号管理"))
        root.add_widget(menu_button(app))
        scroll = ScrollView()
        self.list = MDList()
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        self.add_widget(root)

    def on_pre_enter(self):
        self.list.clear_widgets()
        for name, info in list_accounts():
            current = "（当前）" if (self.app.client and self.app.client.user_info.get("nickName") == name) else ""
            item = TwoLineListItem(text=f"{name} {current}", secondary_text=f"学号 {info.get('userName','?')}  点删除")
            item.bind(on_release=lambda x, n=name: self.del_acc(n))
            self.list.add_widget(item)
        back = MDRaisedButton(text="返回控制台", size_hint=(1, None), height=50)
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
        root = BoxLayout(orientation="vertical")
        root.add_widget(topbar(title))
        root.add_widget(menu_button(app))
        # 副标题
        root.add_widget(MDLabel(text=subtitle, theme_text_color="Secondary",
                                size_hint_y=None, height=40, padding=(15, 5)))
        # 课程列表
        self.list = MDList()
        scroll = ScrollView(size_hint_y=0.35)
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        # 操作按钮
        self.action_btn = MDRaisedButton(text=action_label, size_hint=(1, None), height=50)
        self.action_btn.bind(on_release=lambda *_: self.do_action())
        root.add_widget(self.action_btn)
        if action_key == "sign":
            self.custom_btn = MDFlatButton(text="自定义改签", size_hint=(1, None), height=40)
            self.custom_btn.bind(on_release=lambda *_: self.custom_sign())
            root.add_widget(self.custom_btn)
        # 日志
        self.log = MDLabel(text="选择课程后点按钮开始", size_hint_y=None, markup=True,
                           halign="left", valign="top", theme_text_color="Primary", padding=(10, 10))
        self.log.bind(texture_size=lambda w, s: setattr(w, "height", max(s[1], 120)))
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
        self.log.text = f"[b]已选: {course.get('courseName','')}[/b]\n"

    def append(self, text):
        self.log.text += text + "\n"

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
                        mark = "[已签]" if st == "1" else ("[未签]" if st == "0" else "[注意]")
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
        layout = BoxLayout(orientation="vertical", spacing=5, size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))
        layout.add_widget(MDLabel(text="选择签到记录（标注当前状态）：", size_hint_y=None, height=40))
        self._sign_ctx = (cid, ciid, coid)
        for s in items:
            st = str(s.get("myStatus", "0"))
            st_label = STATUS_MAP.get(st, st)
            btn = MDFlatButton(text=f"[{s.get('teachDate','')}] {s.get('teachTitle','?')}  [{st_label}]",
                               size_hint=(1, None), height=42)
            btn.bind(on_release=lambda x, sig=s: self._pick_sign_status(sig))
            layout.add_widget(btn)
        self._dialog = MDDialog(title="自定义改签", type="custom", content_cls=layout)
        self._dialog.open()

    def _pick_sign_status(self, sign):
        if self._dialog: self._dialog.dismiss()
        layout = BoxLayout(orientation="vertical", spacing=8, size_hint_y=None)
        layout.bind(minimum_height=layout.setter("height"))
        layout.add_widget(MDLabel(text=f"改签为：{sign.get('teachTitle','')}", size_hint_y=None, height=40))
        for st, label in [("0","未签到"),("1","已签到"),("2","迟到"),("3","请假"),("4","病假"),("5","事假")]:
            btn = MDRaisedButton(text=label, size_hint=(1, None), height=45)
            btn.bind(on_release=lambda x, s=sign, st=st: self._do_custom_sign(s, st))
            layout.add_widget(btn)
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
        sm.current = "login"
        return self.nav_layout

    def goto(self, name):
        self.sidebar.refresh()
        self.sm.current = name
        screens = {"login": self.login, "dashboard": self.dashboard, "accounts": self.accounts,
                   "courses": self.courses, "speed": self.speed, "answer": self.answer, "sign": self.sign}
        screens[name].on_pre_enter()


if __name__ == "__main__":
    ICVEApp().run()
