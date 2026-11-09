"""签到模块:签到列表查询、一键补签、代改考勤。

功能:
- get_signs:获取课程下的签到活动列表及当前学生签到状态
- one_click_sign:一键补签(进行中/已结束)
- do_sign_action:代改考勤(修改签到状态)
"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from zjy_client import ZjyClient
from utils import log


# 签到类型映射（手机界面引用；signType==3 走二维码）
SIGN_TYPE_MAP = {"1": "普通", "2": "手势", "3": "二维码", "4": "位置", "5": "人脸"}

# 签到状态映射（手机界面引用）
SIGN_STATUS_MAP = {"0": "未签", "1": "已签", "2": "迟到", "3": "请假",
                   "4": "病假", "5": "事假"}

# 签到列表短缓存：key=(classId, courseInfoId, courseId, max_sessions, recent_days)
_sign_cache = {}
SIGN_CACHE_TTL = 45.0


def convert_gesture(raw) -> str:
    """将 API 返回的 0-based 手势数组转为 1-based 字符串。

    如 [3,4,2,5] -> '4536'
    """
    if isinstance(raw, list):
        return ''.join(str(int(x) + 1) for x in raw if isinstance(x, (int, float)))
    if isinstance(raw, str) and raw.startswith('['):
        try:
            arr = json.loads(raw)
            if isinstance(arr, list):
                return ''.join(str(int(x) + 1) for x in arr if isinstance(x, (int, float)))
        except Exception:
            pass
    return str(raw) if raw else ""


# ==================== 签到列表查询 ====================

def get_signs(client: ZjyClient, class_id: str, course_info_id: str, course_id: str,
              max_sessions: int = 12, recent_days: int = 0) -> list:
    """获取课程下的签到活动列表及当前学生的签到状态。

    :param max_sessions: 最多查多少个课堂会话（每个会话要 1 次请求）。
        原来固定 40，监听线程每轮对所有课程跑一遍 → 请求量爆炸。
    :param recent_days: >0 时只查最近 N 天有课的会话（监听用 1，只看今天）。
    :return: list[dict],每个含:
        teachId/teachDate/teachTitle/signId/signType/gesture/
        startTime/endTime/myStatus/mySignTime
    """
    _t0 = time.time()
    # 短缓存：页面连续点"拉取并补签→自定义改签"会重复拉同一门课，
    # 每次都重打 1+N+M 个接口，真机表现为"签到记录很慢"。
    # TTL 只给 15s，改签/补签成功后主动清缓存（见 _invalidate_sign_cache），
    # 所以不会出现"改完还显示旧状态"。
    ck = (class_id, course_info_id, course_id, max_sessions, recent_days)
    hit = _sign_cache.get(ck)
    if hit and time.time() - hit[0] < SIGN_CACHE_TTL:
        log(f"[签到] 命中缓存，{len(hit[1])} 条", "DEBUG")
        return [dict(s) for s in hit[1]]

    # 步骤一:获取课堂会话列表
    face_data = client.api_get("spoc/courseFaceTeachInfo/list", {
        "classId": class_id, "courseInfoId": course_info_id,
        "pageNum": "1", "pageSize": "200", "orderSort": "1",
    })
    sessions = client.extract_rows(face_data)
    if not sessions:
        return []

    sessions.sort(key=lambda s: s.get("teachDate", s.get("date", "")), reverse=True)
    # 只保留最近 N 天有课的会话（监听场景只看今天，避免翻历史）
    if recent_days > 0:
        from datetime import date, timedelta
        cutoff = (date.today() - timedelta(days=recent_days - 1)).isoformat()
        sessions = [s for s in sessions
                    if str(s.get("teachDate", "")).replace("/", "-")[:10] >= cutoff]
    sessions = sessions[:max_sessions]   # 原来是固定 40，现在可控

    # 步骤二:并发获取每个课堂会话下的签到活动
    sign_activities = []

    def fetch_session_activities(sess):
        teach_id = sess.get("id", "")
        title = sess.get("title", "未命名课堂")
        date_str = sess.get("teachDate", "")
        section = sess.get("classSection", "")

        act_data = client.api_get("spoc/courseFaceTeachInfo/attendClass", {
            "id": teach_id, "classId": class_id, "courseId": course_id,
            "courseInfoId": course_info_id, "requireType": "2",
        })
        acts_found = []
        if act_data and act_data.get("code") == 200 and act_data.get("data"):
            acts = act_data["data"] if isinstance(act_data["data"], list) else [act_data["data"]]
            for a in acts:
                if str(a.get("activityTypeId")) == "2":
                    acts_found.append({
                        "teachId": teach_id,
                        "teachDate": date_str,
                        "teachTitle": f"{section} | {title}" if section else title,
                        "signId": a.get("activityId", ""),
                        "signType": a.get("signType", ""),
                        "gesture": convert_gesture(a.get("gesture", "")),
                        # 活动接口若已带起止时间，后续就不必再单独查签到详情
                        "startTime": (a.get("startTime") or a.get("signStartTime")
                                      or a.get("beginTime") or ""),
                        "endTime": (a.get("endTime") or a.get("signEndTime") or ""),
                    })
        return acts_found

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(fetch_session_activities, s): s for s in sessions}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    sign_activities.extend(res)
            except Exception as e:
                log(f"获取签到活动异常: {e}", "ERROR")

    sign_activities.sort(key=lambda x: x.get("teachDate", ""), reverse=True)

    if not sign_activities:
        return []

    # 步骤三:并发获取当前学生在每个签到活动中的签到状态
    def fetch_student_status(sign_act):
        sid = sign_act["signId"]

        # 获取签到详情(开始/结束时间、手势)：活动接口已带起止时间就跳过，
        # 每条签到省 1 次请求（12 个会话 × 2 条 = 省 24 次/门课）
        if not (sign_act.get("startTime") and sign_act.get("endTime")):
            detail = client.api_get(f"spoc/courseFaceTeachSign/{sid}")
            if detail and detail.get("data"):
                d = detail["data"]
                sign_act["startTime"] = (d.get("startTime") or d.get("signStartTime")
                                         or d.get("beginTime") or "")
                sign_act["endTime"] = d.get("endTime") or d.get("signEndTime") or ""
                if d.get("gesture") and not sign_act["gesture"]:
                    sign_act["gesture"] = convert_gesture(d.get("gesture"))

        # 获取出勤记录,提取当前账号状态
        # 走 client._fetch_sign_records（命中即停 + 15s 缓存），
        # 避免 UI 与监听线程对同一签到重复打 3 个接口
        records = client._fetch_sign_records(sid, class_id)
        my_record = client._match_my_record(records)

        if my_record:
            sign_act["myStatus"] = str(my_record.get("signResultType", "0"))
            sign_act["mySignTime"] = (my_record.get("signTime") or
                                       my_record.get("createTime") or
                                       my_record.get("attendTime") or "")
            # 保存出勤记录主键，改签"已签→未签"时删除/覆盖原记录要用
            sign_act["recordId"] = my_record.get("id", "")
        else:
            sign_act["myStatus"] = "0"
            sign_act["mySignTime"] = ""
            sign_act["recordId"] = ""

        return sign_act

    # 限制并发状态查询深度(前30个)
    sign_activities_to_query = sign_activities[:30]
    final_signs = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(fetch_student_status, sa): sa for sa in sign_activities_to_query}
        for fut in as_completed(futures):
            try:
                res = fut.result()
                if res:
                    final_signs.append(res)
            except Exception as e:
                log(f"获取签到状态异常: {e}", "ERROR")

    final_signs.sort(key=lambda x: x.get("teachDate", ""), reverse=True)
    log(f"[签到] {course_id[:12]} 会话{len(sessions)} 签到{len(final_signs)} "
        f"耗时{time.time()-_t0:.1f}s", "DEBUG")
    _sign_cache[ck] = (time.time(), [dict(s) for s in final_signs])
    return final_signs


def _invalidate_sign_cache():
    """签到状态变更后清缓存，保证下次拉取拿到最新状态。"""
    _sign_cache.clear()


# ==================== 一键补签 ====================

def one_click_sign(client: ZjyClient, sign: dict) -> dict:
    """一键补签入口(封装进行中/已结束两种情况)。

    :param sign: dict,需含 signId/signType/teachId,以及
                 classId/courseId/courseInfoId(可选,从课程上下文补充),
                 isEnded(bool,可选),gesture(可选)
    :return: {"code": 200/500, "msg": "..."}
    """
    nickname = (client.user_info or {}).get("nickName", "未知")
    sign_id = sign["signId"]
    class_id = sign.get("classId", "")
    course_id = sign.get("courseId", "")
    course_info_id = sign.get("courseInfoId", "")
    sign_type = sign.get("signType", "")
    teach_id = sign.get("teachId", "")
    is_ended = sign.get("isEnded", False)

    if is_ended:
        ok, msg = client.do_sign_ended(sign_id, class_id, course_id, course_info_id, sign_type, teach_id)
    else:
        # 手势签到要把 gesture 带上，否则服务端校验不过
        ok, msg = client.do_sign(sign_id, class_id, course_id, course_info_id, sign_type, teach_id,
                                 sign.get("gesture", ""))

    if ok:
        log(f"[{nickname}] 签到成功: {msg}", "SUCCESS")
        return {"code": 200, "msg": msg}
    else:
        log(f"[{nickname}] 签到失败: {msg}", "WARNING")
        return {"code": 500, "msg": f"签到失败: {msg}"}


def batch_sign(client: ZjyClient, signs: list, class_id: str,
               course_info_id: str, course_id: str) -> dict:
    """一键补签所有未签到项。

    :return: {"code": 200, "success": int, "fail": int, "details": [...]}
    """
    nickname = (client.user_info or {}).get("nickName", "未知")
    log(f"[{nickname}] 开始批量补签 {len(signs)} 个签到项...", "INFO")

    success = 0
    fail = 0
    details = []

    for sign in signs:
        # 补充课程上下文
        sign["classId"] = class_id
        sign["courseId"] = course_id
        sign["courseInfoId"] = course_info_id

        # myStatus=="1" 表示已签到,跳过
        if sign.get("myStatus") == "1":
            continue

        # 基于 endTime 判断签到是否已结束
        end_time = sign.get("endTime", "")
        if end_time:
            try:
                from datetime import datetime
                end_dt = datetime.strptime(end_time[:19], "%Y-%m-%d %H:%M:%S")
                sign["isEnded"] = end_dt < datetime.now()
            except Exception:
                sign["isEnded"] = False
        else:
            # 无 endTime,用 myStatus 兜底(有记录视为已结束)
            sign["isEnded"] = sign.get("myStatus", "0") != "0"

        result = one_click_sign(client, sign)
        if result["code"] == 200:
            success += 1
            details.append({"signId": sign["signId"], "result": "成功", "msg": result["msg"]})
        else:
            fail += 1
            details.append({"signId": sign["signId"], "result": "失败", "msg": result["msg"]})

    log(f"[{nickname}] 批量补签完成: 成功 {success}, 失败 {fail}", "INFO")
    if success:
        _invalidate_sign_cache()   # 状态已变，下次拉取要拿最新
    return {"code": 200, "success": success, "fail": fail, "details": details}


# ==================== 代改考勤 ====================

def do_sign_action(client: ZjyClient, payload: dict) -> dict:
    """代改考勤:修改某学生在某签到活动中的签到状态。

    :param payload: dict,需含:
        id(可选,已有记录id;为空则POST新建),
        classId, courseId, courseInfoId,
        signId, signResultType, teachId,
        studentId, studentName, studentNo
    :return: {"code": 200/500, "msg": "..."}
    """
    nickname = (client.user_info or {}).get("nickName", "未知")
    sign_id = payload["signId"]
    sign_result_type = payload["signResultType"]

    if not payload.get("id"):
        # 无ID=未签到记录,POST创建(必须包含学生信息字段)
        body = {
            "classId": payload["classId"],
            "courseId": payload["courseId"],
            "courseInfoId": payload["courseInfoId"],
            "signId": sign_id,
            "signResultType": sign_result_type,
            "teachId": payload["teachId"],
            "studentId": payload["studentId"],
            "studentName": payload["studentName"],
            "studentNo": payload["studentNo"],
        }
        res = client.api_post("spoc/courseFaceTeachSignStudent", body)
        log(f"[{nickname}] [改签] POST创建: code={res.get('code') if res else 'None'}, msg={res.get('msg','') if res else '无响应'}", "DEBUG")
    else:
        # 有ID=已存在记录
        record_id = payload["id"]

        # 第1次PUT:最少参数(进行中的签到)
        res = client.api_put("spoc/courseFaceTeachSignStudent", {
            "id": record_id,
            "signId": sign_id,
            "signResultType": sign_result_type,
        })
        log(f"[{nickname}] [改签] PUT(minimal): code={res.get('code') if res else 'None'}, msg={res.get('msg','') if res else '无响应'}", "DEBUG")

        if not res or res.get("code") != 200:
            put_msg = res.get("msg", "") if res else "接口请求失败"
            # 第2次PUT:完整参数(已结束的签到需要更多参数)
            if "签到时间已结束" in put_msg or "已结束" in put_msg:
                res = client.api_put("spoc/courseFaceTeachSignStudent", {
                    "id": record_id,
                    "signId": sign_id,
                    "signResultType": sign_result_type,
                    "classId": payload["classId"],
                    "courseId": payload["courseId"],
                    "courseInfoId": payload["courseInfoId"],
                    "teachId": payload["teachId"],
                    "studentId": payload["studentId"],
                    "studentName": payload["studentName"],
                    "studentNo": payload["studentNo"],
                })
                log(f"[{nickname}] [改签] PUT(full): code={res.get('code') if res else 'None'}, msg={res.get('msg','') if res else '无响应'}", "DEBUG")

            # PUT都失败,回退POST(必须包含学生信息字段)
            if not res or res.get("code") != 200:
                post_body = {
                    "classId": payload["classId"],
                    "courseId": payload["courseId"],
                    "courseInfoId": payload["courseInfoId"],
                    "signId": sign_id,
                    "signResultType": sign_result_type,
                    "teachId": payload["teachId"],
                    "studentId": payload["studentId"],
                    "studentName": payload["studentName"],
                    "studentNo": payload["studentNo"],
                }
                res = client.api_post("spoc/courseFaceTeachSignStudent", post_body)
                log(f"[{nickname}] [改签] POST(回退): code={res.get('code') if res else 'None'}, msg={res.get('msg','') if res else '无响应'}", "DEBUG")

    if res and res.get("code") == 200:
        _invalidate_sign_cache()   # 状态已变，下次拉取要拿最新
        # 回读校验：服务器常"返回 200 但没落库"（改未签到踩过），
        # 不校验就会提示"修改成功"而实际没效果。
        actual = client._verify_sign_status(sign_id, payload.get("classId", ""))
        want = str(sign_result_type)
        if actual == "?":
            ok_verified = True      # 查不到状态不算失败，按接口结果
        elif want == "0":
            ok_verified = actual in (None, "0")   # 无记录也等于未签
        else:
            ok_verified = actual == want
        if not ok_verified:
            msg = f"服务器未生效(当前状态:{actual if actual else '无记录'})"
            log(f"[{nickname}] 签到状态修改未生效: {msg}", "WARNING")
            return {"code": 500, "msg": msg}
        # 检查是否"重复签到"(视为成功)
        if "重复签到" in str(res.get("msg", "")):
            log(f"[{nickname}] 签到状态已修改(已存在)", "INFO")
            return {"code": 200, "msg": "修改成功(已存在)"}
        log(f"[{nickname}] 签到状态已修改并已确认", "INFO")
        return {"code": 200, "msg": "修改成功"}

    err_msg = res.get("msg", "操作失败") if res else "请求接口失败"
    log(f"[{nickname}] 签到状态修改失败: {err_msg}", "WARNING")
    return {"code": 500, "msg": err_msg}
