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
import threading
import time

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
from sign import (get_signs, batch_sign, do_sign_action,
                  SIGN_TYPE_MAP, SIGN_STATUS_MAP)
from accounts import list_accounts, save_account, delete_account

from kivy.core.text import LabelBase
LabelBase.register(name="Roboto",
                   fn_regular="NotoSansSC.ttf",
                   fn_bold="NotoSansSC.ttf",
                   fn_italic="NotoSansSC.ttf",
                   fn_bold_italic="NotoSansSC.ttf")

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


class SidebarMenu(BoxLayout):
    def __init__(self, app, **kw):
        super().__init__(**kw)
        self.orientation = "vertical"
        self.padding = 0
        self.spacing = 0
        self.app = app
        # 顶部标题栏
        header = MDCard(size_hint_y=None, height=110,
                        md_bg_color=[0.13, 0.59, 0.95, 1], radius=[0,0,0,0],
                        elevation=0, padding=(20, 15, 20, 15))
        header_box = BoxLayout(orientation="vertical", spacing=8)
        header_box.add_widget(MDLabel(text="ICVE 学习助手", theme_text_color="Custom",
                                      text_color=[1, 1, 1, 1], size_hint_y=None, height=40))
        header_box.add_widget(MDLabel(text="智慧职教工具", theme_text_color="Custom",
                                      text_color=[0.9, 0.9, 0.9, 1], size_hint_y=None, height=25))
        header.add_widget(header_box)
        self.add_widget(header)
        # 菜单内容
        content = BoxLayout(orientation="vertical", padding=(5, 10, 5, 10), spacing=2)
        content.add_widget(MDLabel(text="主功能", theme_text_color="Secondary",
                                   size_hint_y=None, height=30, padding=(15, 0)))
        for label, target in [
            ("控制台", "dashboard"),
            ("一键刷课", "speed"),
            ("自动答题", "answer"),
            ("签到改签", "sign"),
            ("我的课程", "courses"),
        ]:
            btn = OneLineListItem(text=label)
            btn.bind(on_release=lambda x, t=target: self._nav(t))
            content.add_widget(btn)
        content.add_widget(MDLabel(text="系统", theme_text_color="Secondary",
                                   size_hint_y=None, height=30, padding=(15, 0)))
        for label, target in [
            ("账号管理", "accounts"),
            ("退出登录", "logout"),
        ]:
            btn = OneLineListItem(text=label)
            btn.bind(on_release=lambda x, t=target: self._nav(t))
            content.add_widget(btn)
        self.status_label = MDLabel(text="● 未登录", theme_text_color="Error",
                                    size_hint_y=None, height=40, padding=(15, 0))
        content.add_widget(self.status_label)
        self.add_widget(content)

    def _nav(self, target):
        self.app.nav_drawer.set_state("close")
        if target == "logout":
            self.app.logout()
        else:
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
        box.add_widget(MDLabel(text="已保存账号", theme_text_color="Secondary", size_hint_y=None, height=30))
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
            client = None
            try:
                client = _exchange_token(sso)
            except Exception as e:
                # 注意:先格式化成字符串再进 lambda —— except 块结束后 e 会被删除,
                # lambda 里直接引用会在回调时 NameError
                err = f"登录异常: {e}"
                Clock.schedule_once(lambda dt: setattr(self.status, "text", err), 0)
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
                err = f"失败: {e}"
                Clock.schedule_once(lambda dt: setattr(self.status, "text", err), 0)
        threading.Thread(target=work, daemon=True).start()

    def _on_login(self, client, sso=""):
        if client:
            self.app.client = client
            if sso: save_account(client, sso)
            self.input.text = ""
            self.status.text = "登录成功"
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
        box.add_widget(MDLabel(text="功能", theme_text_color="Secondary",
                               size_hint_y=None, height=30, padding=(0, 5)))
        for label, desc, target in [
            ("我的课程", "浏览已选课程", "courses"),
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
        else:
            self.welcome.text = "尚未登录，请先到登录页登录"


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
        current_name = ""
        if self.app.client and self.app.client.user_info:
            current_name = self.app.client.user_info.get("nickName", "")
        for name, info in list_accounts():
            current = "（当前）" if current_name == name else ""
            item = TwoLineListItem(text=f"{name} {current}", secondary_text=f"学号 {info.get('userName','?')}  点删除")
            item.bind(on_release=lambda x, n=name: self.del_acc(n))
            self.list.add_widget(item)
        back = MDRaisedButton(text="返回控制台", size_hint=(1, None), height=50)
        back.bind(on_release=lambda *_: self.app.goto("dashboard"))
        self.list.add_widget(back)

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
        root = BoxLayout(orientation="vertical")
        root.add_widget(topbar(title))
        root.add_widget(menu_button(app))
        # 副标题
        root.add_widget(MDLabel(text=subtitle, theme_text_color="Secondary",
                                size_hint_y=None, height=50, padding=(15, 10)))
        # 区块：选择课程
        root.add_widget(MDLabel(text="选择课程", theme_text_color="Secondary",
                                size_hint_y=None, height=30, padding=(15, 5)))
        # 课程列表
        self.list = MDList()
        scroll = ScrollView(size_hint_y=0.3)
        scroll.add_widget(self.list)
        root.add_widget(scroll)
        # 区块：操作
        root.add_widget(MDLabel(text="操作", theme_text_color="Secondary",
                                size_hint_y=None, height=30, padding=(15, 5)))
        # 操作按钮
        self.action_btn = MDRaisedButton(text=action_label, size_hint=(1, None), height=50)
        self.action_btn.bind(on_release=lambda *_: self.do_action())
        root.add_widget(self.action_btn)
        if action_key == "sign":
            self.custom_btn = MDRaisedButton(text="自定义改签", size_hint=(1, None), height=45)
            self.custom_btn.md_bg_color = [0.9, 0.9, 0.9, 1]
            self.custom_btn.text_color = [0.15, 0.15, 0.15, 1]
            self.custom_btn.bind(on_release=lambda *_: self.custom_sign())
            root.add_widget(self.custom_btn)
            self.monitor_btn = MDRaisedButton(text="启动自动监听签到", size_hint=(1, None), height=45)
            self.monitor_btn.md_bg_color = [0.2, 0.7, 0.3, 1]
            self.monitor_btn.bind(on_release=lambda *_: self.toggle_monitor())
            root.add_widget(self.monitor_btn)
            self._monitoring = False
            self._monitor_thread = None
        # 区块：日志
        root.add_widget(MDLabel(text="运行日志", theme_text_color="Secondary",
                                size_hint_y=None, height=30, padding=(15, 5)))
        # 日志
        self.log = MDLabel(text="选择课程后点按钮开始", size_hint_y=None, markup=True,
                           halign="left", valign="top", theme_text_color="Primary", padding=(10, 10))
        self.log.bind(texture_size=lambda w, s: setattr(w, "height", max(s[1], 150)))
        sv = ScrollView()
        sv.add_widget(self.log)
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
            self.list.add_widget(OneLineListItem(text="(未找到课程)"))
            return
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
        for k in list(self.theme_cls.font_styles.keys()):
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


if __name__ == "__main__":
    ICVEApp().run()
