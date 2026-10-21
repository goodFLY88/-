"""智慧职教工具 — CLI 主入口(桌面/服务器命令行版)。

交互式菜单:登录、查看课程、一键刷课、签到改签、账号管理。
优化版:删死代码(未实现的取消信号)、统一 isEnded 判定、Ctrl+C 友好退出。
"""

from zjy_client import ZjyClient
from auth import login
from accounts import list_accounts, delete_account
from speed_course import run_speed_course
from sign import get_signs, one_click_sign, batch_sign, sign_is_ended, SIGN_TYPE_MAP, SIGN_STATUS_MAP
from utils import log, print_banner, print_menu, input_choice, input_int, truncate

# 当前活跃的 ZjyClient 实例
current_client: ZjyClient = None


def main():
    """CLI 主循环。"""
    print_banner()
    log("欢迎使用智慧职教工具,请先登录", "INFO")

    while True:
        # 已登录时先显示当前账号(非菜单项),再打印功能菜单
        if current_client:
            nick = current_client.user_info.get("nickName", "?") if current_client.user_info else "?"
            print(f"\n  当前账号: {nick}", flush=True)
            print_menu([
                "登录 / 切换账号",
                "查看我的课程",
                "一键刷课",
                "签到 / 改签",
                "账号管理",
                "退出",
            ])
        else:
            print_menu([
                "登录",
                "查看我的课程",
                "一键刷课",
                "签到 / 改签",
                "账号管理",
                "退出",
            ])

        choice = input_choice("请选择", ["1", "2", "3", "4", "5", "6"])

        if choice == "1":
            menu_login()
        elif choice == "2":
            menu_courses()
        elif choice == "3":
            menu_speed()
        elif choice == "4":
            menu_sign()
        elif choice == "5":
            menu_accounts()
        elif choice == "6":
            log("再见!", "INFO")
            break
        else:
            log("无效选择,请重试", "WARNING")


def menu_login():
    """登录 / 切换账号。"""
    global current_client
    log("正在启动登录流程...", "INFO")
    client = login()
    if client:
        current_client = client
    else:
        log("登录失败,请重试", "WARNING")


def menu_courses():
    """查看课程列表。"""
    if not _check_login():
        return
    log("正在拉取课程列表...", "INFO")
    try:
        courses = current_client.get_my_courses()
    except Exception as e:
        log(f"拉取课程异常: {e}", "ERROR")
        return

    if not courses:
        log("未找到课程", "INFO")
        return

    log(f"共 {len(courses)} 门课程:", "INFO")
    type_colors = {"SPOC": "📘", "MOOC": "📗", "RESOURCE": "📙"}
    for i, c in enumerate(courses, 1):
        ctype = c.get("_courseType", "?")
        icon = type_colors.get(ctype, "📚")
        name = truncate(c.get("courseName", "未知"), 35)
        print(f"  [{i}] {icon} [{ctype}] {name}", flush=True)


def menu_speed():
    """一键刷课菜单。"""
    if not _check_login():
        return

    log("正在拉取课程列表...", "INFO")
    try:
        courses = current_client.get_my_courses()
    except Exception as e:
        log(f"拉取课程异常: {e}", "ERROR")
        return

    if not courses:
        log("未找到课程", "INFO")
        return

    log("选择要刷的课程:", "INFO")
    for i, c in enumerate(courses, 1):
        ctype = c.get("_courseType", "?")
        name = truncate(c.get("courseName", "未知"), 35)
        print(f"  [{i}] [{ctype}] {name}", flush=True)

    idx = input_int("课程编号", 1, len(courses))
    if idx is None:
        return
    course = courses[idx - 1]

    print("\n  范围选择:", flush=True)
    print("  [1] 全部(进度+答题+讨论)", flush=True)
    print("  [2] 仅进度", flush=True)
    print("  [3] 仅讨论", flush=True)
    print("  [4] 仅答题", flush=True)
    print("  [0] 返回", flush=True)
    scope = input_choice("选择", ["0", "1", "2", "3", "4"])
    if scope == "0":
        return
    speed_type = {"1": "all", "2": "progress", "3": "discussion", "4": "exam"}[scope]

    log(f"开始刷课: {course.get('courseName', '?')} (Ctrl+C 可中断)", "INFO")
    try:
        run_speed_course(current_client, course, speed_type)
    except KeyboardInterrupt:
        log("已中断刷课(当前课程的后续操作不会继续)", "WARNING")
    except Exception as e:
        log(f"刷课异常: {e}", "ERROR")


def menu_sign():
    """签到 / 改签菜单。"""
    if not _check_login():
        return

    log("正在拉取课程列表...", "INFO")
    try:
        courses = current_client.get_my_courses()
    except Exception as e:
        log(f"拉取课程异常: {e}", "ERROR")
        return

    if not courses:
        log("未找到课程", "INFO")
        return

    log("选择课程:", "INFO")
    for i, c in enumerate(courses, 1):
        name = truncate(c.get("courseName", "未知"), 35)
        print(f"  [{i}] {name}", flush=True)

    idx = input_int("课程编号", 1, len(courses))
    if idx is None:
        return
    course = courses[idx - 1]

    class_id = course.get("classId", "")
    course_info_id = course.get("courseInfoId", "")
    course_id = course.get("courseId", "")

    log("正在获取签到列表...", "INFO")
    try:
        signs = get_signs(current_client, class_id, course_info_id, course_id)
    except Exception as e:
        log(f"获取签到列表异常: {e}", "ERROR")
        return

    if not signs:
        log("该课程无签到记录", "INFO")
        return

    log(f"共 {len(signs)} 个签到活动:", "INFO")
    status_map = {"0": "❌未签", "1": "✅已签", "2": "迟到", "3": "请假"}
    for i, s in enumerate(signs, 1):
        sign_type = SIGN_TYPE_MAP.get(s.get("signType", ""), "?")
        status = status_map.get(s.get("myStatus", "0"), "?")
        date = s.get("teachDate", "")
        title = truncate(s.get("teachTitle", ""), 25)
        print(f"  [{i}] {date} | {sign_type} | {status} | {title}", flush=True)

    print("\n  [1] 选择单个签到(补签)", flush=True)
    print("  [2] 一键补签所有未签", flush=True)
    print("  [3] 代改考勤(修改签到状态)", flush=True)
    print("  [0] 返回", flush=True)
    action = input_choice("选择", ["0", "1", "2", "3"])

    if action == "0":
        return

    if action == "2":
        # 一键补签所有未签
        result = batch_sign(current_client, signs, class_id, course_info_id, course_id)
        log(f"补签完成: 成功 {result['success']}, 失败 {result['fail']}", "INFO")

    elif action == "1":
        # 选择单个签到
        sign_idx = input_int("签到编号", 1, len(signs))
        if sign_idx is None:
            return
        sign = signs[sign_idx - 1]

        # 补充课程上下文
        sign["classId"] = class_id
        sign["courseId"] = course_id
        sign["courseInfoId"] = course_info_id
        sign["isEnded"] = sign_is_ended(sign)

        # 手势签到提示
        if sign.get("signType") == "2" and sign.get("gesture"):
            log(f"提示: 该签到为手势签到,手势密码: {sign['gesture']}", "INFO")

        result = one_click_sign(current_client, sign)
        log(result["msg"], "INFO")

    elif action == "3":
        # 代改考勤:修改签到状态
        _menu_sign_action(current_client, signs, class_id, course_id, course_info_id)


def _menu_sign_action(client, signs: list, class_id: str, course_id: str, course_info_id: str):
    """代改考勤子菜单:选择签到项 → 选择新状态 → 提交修改。"""
    from sign import do_sign_action, one_click_sign

    sign_idx = input_int("选择签到项编号", 1, len(signs))
    if sign_idx is None:
        return
    sign = signs[sign_idx - 1]

    sign_id = sign.get("signId", "")
    teach_id = sign.get("teachId", "")
    if not sign_id:
        log("无效的签到项", "WARNING")
        return

    # 显示当前状态(统一用 sign.SIGN_STATUS_MAP)
    cur_status = sign.get("myStatus", "0")
    log(f"当前状态: {SIGN_STATUS_MAP.get(cur_status, cur_status)}", "INFO")

    # 选择新状态
    print("\n  选择新的签到状态:", flush=True)
    print("  [1] 已签到(signResultType=1)", flush=True)
    print("  [2] 迟到(signResultType=2)", flush=True)
    print("  [3] 请假(signResultType=3)", flush=True)
    print("  [4] 病假(signResultType=4)", flush=True)
    print("  [5] 事假(signResultType=5)", flush=True)
    print("  [6] 改为未签到(signResultType=0)", flush=True)
    print("  [0] 返回", flush=True)
    status_choice = input_choice("选择", ["0", "1", "2", "3", "4", "5", "6"])
    if status_choice == "0":
        return
    sign_result_type = {"1": "1", "2": "2", "3": "3", "4": "4", "5": "5", "6": "0"}[status_choice]

    # 获取学生信息(从签到记录中匹配本人)
    my_name = client.user_info.get("nickName", "") if client.user_info else ""
    my_no = client.user_info.get("userName", "") if client.user_info else ""
    stu_id = client.stu_id or ""

    # 查询签到记录获取 record_id 和学生信息
    records = client._fetch_sign_records(sign_id, class_id)
    my_record = client._match_my_record(records) if records else None

    record_id = (my_record or {}).get("id", "")
    real_student_no = (my_record or {}).get("studentNo") or my_no
    real_student_name = (my_record or {}).get("studentName") or my_name
    real_student_id = (my_record or {}).get("studentId") or stu_id

    # 未签状态(无记录)改签到"已签到"时,走补签逻辑(三级兜底更可靠)
    if not record_id and sign_result_type == "1":
        log("未签到状态,走补签逻辑...", "INFO")
        sign["classId"] = class_id
        sign["courseId"] = course_id
        sign["courseInfoId"] = course_info_id
        sign["isEnded"] = sign_is_ended(sign)
        result = one_click_sign(client, sign)
        log(result["msg"], "INFO")
        return

    # 其他情况走代改考勤(有记录或改签到非签到状态)
    payload = {
        "id": record_id,
        "signId": sign_id,
        "classId": class_id,
        "courseId": course_id,
        "courseInfoId": course_info_id,
        "teachId": teach_id,
        "signResultType": sign_result_type,
        "studentId": real_student_id,
        "studentName": real_student_name,
        "studentNo": real_student_no,
    }

    result = do_sign_action(client, payload)
    log(result["msg"], "INFO")


def menu_accounts():
    """账号管理菜单。"""
    global current_client
    accounts = list_accounts()
    if not accounts:
        log("无保存的账号", "INFO")
        return

    log("已保存的账号:", "INFO")
    for i, (name, info) in enumerate(accounts, 1):
        print(f"  [{i}] {name} ({info.get('userName', '?')})", flush=True)

    print("\n  输入编号删除账号,0 返回", flush=True)
    idx = input_int("选择", 0, len(accounts))
    if idx is None or idx == 0:
        return

    name = accounts[idx - 1][0]
    if delete_account(name):
        log(f"已删除账号: {name}", "SUCCESS")
        # 如果删的是当前账号,清除当前会话
        if current_client and current_client.user_info and current_client.user_info.get("nickName") == name:
            current_client = None
            log("当前账号已被删除,请重新登录", "WARNING")
    else:
        log(f"删除失败: 账号 {name} 不存在", "ERROR")


def _check_login() -> bool:
    """检查是否已登录,未登录时提示。"""
    if not current_client:
        log("请先登录(菜单 [1])", "WARNING")
        return False
    return True


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n已取消( Ctrl+C ),再见!", "WARNING")
    except EOFError:
        log("\n输入结束,再见!", "INFO")
