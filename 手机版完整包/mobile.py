#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ICVE 手机极简版（Termux / 无图形界面专用）

用法：
    pip install requests pycryptodome
    python mobile.py

登录方式（免滑块、免本地端口）：
    1. 程序打印一条 SSO 登录链接
    2. 在手机浏览器打开并登录智慧职教
    3. 登录后浏览器会跳到一个 http://127.0.0.1:9527/?token=... 的页面
       （打不开没关系，重点是地址栏里已经有 token）
    4. 复制浏览器地址栏的完整网址，粘贴回本程序回车
    5. 自动换取并保存账号，下次可直接选编号登录
"""
import re
import sys
import time

try:
    from zjy_client import ZjyClient, SSO_BASE, BASE_URL
    from auth import _exchange_token
    from accounts import load_accounts, list_accounts, save_account, delete_account
    from speed_course import run_speed_course
    from answer import get_course_exams_list, run_auto_answer_all_task
    from sign import get_signs, one_click_sign
    from utils import log
except Exception as e:
    print(f"[启动失败] 依赖未安装或文件不完整: {e}", flush=True)
    print("请先在本目录执行: pip install requests pycryptodome", flush=True)
    sys.exit(1)

current_client = None
# 与 auth.py 一致的 SSO 链接（redirect 用假地址，仅用于让浏览器地址栏带上 token）
LOGIN_URL = f"{SSO_BASE}/h5/?mode=simple&source=15&redirect=http://127.0.0.1:9527#/login"


def login_by_paste():
    """打印登录链接，用户粘贴浏览器地址栏 URL，抠出 token 完成登录。"""
    global current_client
    print("\n" + "=" * 46, flush=True)
    print("  ① 在手机浏览器打开下面这条链接并登录：", flush=True)
    print(f"  {LOGIN_URL}", flush=True)
    print("=" * 46, flush=True)
    print("  ② 登录成功后浏览器会跳到 127.0.0.1 页面（打不开正常）", flush=True)
    print("  ③ 复制浏览器【地址栏】的完整网址，粘贴到这里：", flush=True)
    raw = input("粘贴网址> ").strip()
    m = re.search(r"token=([^&#\s]+)", raw)
    if not m:
        print("未在内容里找到 token=...，请复制登录后地址栏的完整网址重试。", flush=True)
        return None
    sso_token = m.group(1)
    print("正在换取登录态...", flush=True)
    client = _exchange_token(sso_token)
    if client:
        current_client = client
        print(f"登录成功：{client.user_info.get('nickName', '?')} / "
              f"学号 {client.user_info.get('userName', '?')}\n", flush=True)
    else:
        print("登录失败，token 可能已过期，请重新打开链接登录。\n", flush=True)
    return client


def login_by_saved():
    """用已保存账号的 token 直接登录。"""
    global current_client
    try:
        accounts = list_accounts()
    except Exception:
        accounts = []
    if not accounts:
        print("没有已保存账号，请先选择「登录新账号」。\n", flush=True)
        return None
    print("\n已保存账号：", flush=True)
    for i, (name, info) in enumerate(accounts, 1):
        print(f"  [{i}] {name}（{info.get('userName', '?')}）", flush=True)
    choice = input("选择编号（回车取消）> ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(accounts)):
        return None
    name, info = accounts[int(choice) - 1]
    saved_token = info.get("token", "")
    saved_sso = info.get("ssoToken", "")
    if not saved_token:
        print("该账号 Token 为空，请重新登录。\n", flush=True)
        return None
    print(f"正在验证 {name} 的 Token...", flush=True)
    client = ZjyClient(sso_token=saved_sso or None)
    if client.apply_token(saved_token):
        current_client = client
        print(f"已登录：{client.user_info.get('nickName', '?')}\n", flush=True)
        return client
    if saved_sso:
        print("Token 过期，尝试刷新...", flush=True)
        client2 = ZjyClient(sso_token=saved_sso)
        if client2.refresh_token_from_sso():
            save_account(client2, saved_sso)
            current_client = client2
            print(f"刷新成功：{client2.user_info.get('nickName', '?')}\n", flush=True)
            return client2
    delete_account(name)
    print("Token 已失效并清除，请重新登录。\n", flush=True)
    return None


def pick_course():
    """列出课程让用户选，返回 course dict 或 None。"""
    courses = current_client.get_my_courses()
    if not courses:
        print("未找到课程。\n", flush=True)
        return None
    type_icon = {"SPOC": "📘", "MOOC": "📗", "RESOURCE": "📙"}
    print("\n课程列表：", flush=True)
    for i, c in enumerate(courses, 1):
        icon = type_icon.get(c.get("_courseType"), "📚")
        print(f"  [{i}] {icon} [{c.get('_courseType','?')}] {c.get('courseName','?')}", flush=True)
    choice = input("选择课程编号> ").strip()
    if not choice.isdigit() or not (1 <= int(choice) <= len(courses)):
        print("无效选择。\n", flush=True)
        return None
    return courses[int(choice) - 1]


def do_courses():
    courses = current_client.get_my_courses()
    print(f"\n共 {len(courses)} 门课程：", flush=True)
    for i, c in enumerate(courses, 1):
        print(f"  [{i}] [{c.get('_courseType','?')}] {c.get('courseName','?')}", flush=True)
    print(flush=True)


def do_speed():
    course = pick_course()
    if not course:
        return
    print("范围：[1]全部  [2]仅进度  [3]仅讨论  [4]仅答题", flush=True)
    s = input("选择> ").strip() or "1"
    speed_type = {"1": "all", "2": "progress", "3": "discussion", "4": "exam"}.get(s, "all")
    print(f"开始刷课：{course.get('courseName','?')}（{speed_type}）...", flush=True)
    try:
        run_speed_course(current_client, course, speed_type)
    except Exception as e:
        log(f"刷课异常: {e}", "ERROR")
    print(flush=True)


def do_answer():
    course = pick_course()
    if not course:
        return
    ctype = course.get("_courseType", "SPOC")
    print("正在拉取作业/考试/测验列表...", flush=True)
    try:
        exams = get_course_exams_list(current_client, course.get("classId", ""),
                                      course.get("courseInfoId", ""),
                                      course.get("courseId", ""), ctype)
    except Exception as e:
        log(f"拉取列表异常: {e}", "ERROR")
        return
    print(f"共 {len(exams)} 个任务。开始自动作答...", flush=True)
    try:
        run_auto_answer_all_task(current_client,
                                 current_client.user_info.get("nickName", ""),
                                 course.get("classId", ""),
                                 course.get("courseInfoId", ""),
                                 course.get("courseId", ""), ctype)
    except Exception as e:
        log(f"自动答题异常: {e}", "ERROR")
    print(flush=True)


def do_sign():
    course = pick_course()
    if not course:
        return
    try:
        signs = get_signs(current_client, course.get("classId", ""),
                           course.get("courseInfoId", ""), course.get("courseId", ""))
    except Exception as e:
        log(f"拉取签到异常: {e}", "ERROR")
        return
    print(f"共 {len(signs)} 条签到记录。未签到的将尝试一键补签...", flush=True)
    done = 0
    for s in signs:
        # myStatus: "0"未签 / "1"已签 / "2"迟到 / "3"~"5"请假类
        status = str(s.get("myStatus", "0"))
        if status == "0":
            try:
                r = one_click_sign(current_client, s)
                if r.get("success"):
                    done += 1
                    log(f"补签成功: {s.get('teachTitle', s.get('title','?'))}", "SUCCESS")
                else:
                    log(f"补签失败: {s.get('teachTitle', s.get('title','?'))} - {r.get('msg','')}", "WARNING")
                time.sleep(0.5)
            except Exception as e:
                log(f"补签异常: {e}", "ERROR")
    print(f"补签完成，成功 {done} 条。\n", flush=True)


def ensure_login():
    if current_client and current_client.user_info:
        return True
    print("请先登录。", flush=True)
    return False


def main():
    print("=" * 46, flush=True)
    print("   ICVE 手机极简版（Termux）", flush=True)
    print("=" * 46, flush=True)
    while True:
        nick = (current_client.user_info.get("nickName") if current_client and current_client.user_info else "未登录")
        print(f"\n当前账号：{nick}", flush=True)
        print("  [1] 登录新账号（粘贴链接 token）", flush=True)
        print("  [2] 用已保存账号登录", flush=True)
        print("  [3] 我的课程", flush=True)
        print("  [4] 一键刷课", flush=True)
        print("  [5] 自动答题", flush=True)
        print("  [6] 签到一键补签", flush=True)
        print("  [0] 退出", flush=True)
        c = input("选择> ").strip()
        if c == "1":
            login_by_paste()
        elif c == "2":
            login_by_saved()
        elif c == "3":
            if ensure_login():
                do_courses()
        elif c == "4":
            if ensure_login():
                do_speed()
        elif c == "5":
            if ensure_login():
                do_answer()
        elif c == "6":
            if ensure_login():
                do_sign()
        elif c == "0":
            print("再见~", flush=True)
            break
        else:
            print("无效选项。", flush=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n已退出。", flush=True)
