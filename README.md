# 智慧职教工具（ICVE Toolkit）

> 职教喵喵喵～ —— SPOC / MOOC / 资源库三类课程的自动化学习助手：
> 自动登录、一键刷课、自动答题、讨论自动回复、签到补签改签、签到自动监听。

- 协议：[PolyForm Noncommercial 1.0.0](LICENSE)（禁止商用，收费代刷/引流变现均属商用）
- 适配：桌面 CLI（Windows / macOS / Linux）、安卓 APK（KivyMD）、Termux 极简版

---

## 一、仓库结构（优化版：单一代码源）

```
.
├── main.py             # 安卓/桌面 GUI 入口（KivyMD，APK 打包也用这个文件）
├── cli.py              # 桌面命令行版入口（原 main.py，已更名避免与 GUI 入口冲突）
├── mobile.py           # Termux 手机极简版入口
├── login_mobile.py     # Termux 专用极简登录脚本
├── zjy_client.py       # 核心 API 客户端（三域鉴权/课程/心跳/签到）
├── auth.py             # 登录（全自动滑块 + 浏览器回调兜底）
├── slider_auto.py      # 【优化版新增】全自动滑块登录（补齐原仓库缺失模块）
├── speed_course.py     # 刷课（SPOC/MOOC/资源库，并发车道心跳）
├── answer.py           # 自动答题（作业/考试/测验）
├── sign.py             # 签到列表/补签/代改考勤 + 统一的类型状态映射
├── accounts.py         # 多账号管理（原子写 + 权限控制 + 损坏备份）
├── utils.py            # 日志/菜单/输入校验
├── NotoSansSC.ttf      # 中文字体（GUI 必须，buildozer 已配置打进 APK）
├── buildozer.spec      # 安卓打包配置（根目录直接打包）
├── 一键打包apk.py       # WSL 内一键打包脚本
├── requirements.txt    # 桌面端依赖
├── .github/workflows/  # CI：push 自动出 APK
└── LICENSE             # PolyForm Noncommercial 1.0.0
```

> 与原版的区别：原仓库在根目录、`APK工程/`、`.github/workflows/` 三处各存一份
> 相同代码，修改容易漏同步。优化版合并为根目录单一代码源，buildozer 直接以
> 根目录为 `source.dir` 打包，`APK工程/` 与 workflows 里的 .py 副本已移除。

## 二、快速开始

### 桌面命令行版

```bash
pip install -r requirements.txt
python cli.py
```

- 首次登录：自动滑块（需装 playwright 等依赖）失败会自动回退浏览器人工登录
- 之后运行会列出已保存账号，选编号即可复用登录态

### 安卓 APP

- 直接用 CI 产物：GitHub Actions → Artifacts → `ICVE刷课APK`
- 或本地打包（必须在 Linux/WSL，不能 Windows 原生）：

```bash
# WSL/Ubuntu 内，仓库根目录执行
python3 一键打包apk.py
```

成功后 APK 在 `bin/`。安装后：登录页复制链接到浏览器登录 → 把地址栏网址粘回 App。

### Termux 极简版

```bash
pkg install python
pip install requests pycryptodome
python mobile.py          # 或 python login_mobile.py 只登录
```

## 三、功能说明

| 功能 | 入口 | 说明 |
| --- | --- | --- |
| 登录 | cli / GUI | 账密自动过滑块；失败回退浏览器回调；token 过期自动用 ssoToken 刷新 |
| 我的课程 | 菜单 2 / GUI | 聚合 SPOC / MOOC / 资源库课程 |
| 一键刷课 | 菜单 3 / GUI | 进度（视频/音频/图片心跳）+ 答题 + 讨论，可选范围 |
| 自动答题 | GUI / mobile | 拉取作业/考试/测验，自动作答并提交 |
| 签到改签 | 菜单 4 / GUI | 补签、代改考勤、自定义改签 |
| 签到监听 | GUI | 每 30 秒扫描所有课程，发现新签到自动签 |
| 账号管理 | 菜单 5 / GUI | 多账号保存/切换/删除（删除有二次确认） |

## 四、优化版修订记录（相对原版）

**结构 / 打包**
1. 三份重复代码合并为单一代码源；`APK工程/`、`.github/workflows/*.py` 副本移除
2. buildozer `include_exts` 补 `ttf` —— 原配置漏了字体扩展名，`NotoSansSC.ttf`
   不会进 APK，安卓端中文全是豆腐块
3. buildozer 增加 `armeabi-v7a` 架构（原来只有 arm64-v8a，32 位旧机型装不上）
4. 新增 `.gitignore`（accounts.json 含 Token，原仓库无忽略规则，有泄露风险）
5. 新增 `LICENSE`（banner 声称 PolyForm Noncommercial，但原仓库没有许可证文件）
6. CI 改为根目录打包，清理产物路径

**功能缺陷**
7. 补齐 `slider_auto.py`：auth.py 一直引用但原仓库没有此文件，导致"全自动滑块
   登录"实际永远走不通（ImportError 直接转人工）
8. GUI 退出登录不清会话（状态灯仍显示已登录，其他页仍可用）—— 已修
9. GUI `goto()` 重复触发 `on_pre_enter`，课程列表每次加载两遍 —— 已修
10. GUI 未登录可进功能页，静默显示空列表 —— 已增加未登录保护并跳转登录页
11. GUI 账号删除无确认，点一下即删 —— 已加二次确认对话框
12. 签到类型映射三处不一致（GUI 里 2/3 类型与后端 `signType==3` 为二维码的
    实际分支矛盾）—— 统一为 `sign.SIGN_TYPE_MAP` 单一来源
13. "我的课程"页按钮是"开始刷课"（与刷课页重复且文不对意）—— 改为只读浏览
14. `custom_sign` 工作线程无异常保护，出错时静默死亡 —— 已补
15. CLI 死代码 `_cancel_event`（注释"未来支持中断"从未实现）—— 已移除，
    刷课改为 Ctrl+C 可中断并有友好提示
16. `isEnded`（签到是否结束）逻辑在 cli/sign 重复三份 —— 抽为 `sign_is_ended()`
17. accounts.json 直接覆盖写，崩溃可能写坏 —— 改原子写；文件自动 600 权限；
    损坏时自动备份 `.bak-<时间戳>` 而不是丢掉全部账号
18. 已保存账号选择输入非法数字时直接掉进浏览器登录流程 —— 改为重问/可取消
19. GUI 登录线程、改签线程未捕获异常 —— 已补 try/except
20. GUI 刷课接入 `progress_cb`，日志实时显示阶段进度；监听线程退出时停止

**CI 假绿（推送后实测发现并修复）**
21. 新版 `kivy/buildozer` 镜像在 root 下会交互询问 "Are you sure you want to
    continue [y/n]?"，CI 无 stdin → 6 次重试全部 `EOFError` 崩溃；而旧工作流
    结构下"构建全失败也返回 success"，导致长期假绿、实际没有 APK 产物。
    已改为 `yes | buildozer` 自动应答 + 结尾强制校验 `bin/*.apk` 存在 +
    `if-no-files-found: error`，没有产物就让 Job 失败。

**启动闪退（2026-10-22 实测复现并修复）**
22. 闪退根因一：`requirements = kivy, kivymd` 不锁版本，pip/buildozer 会拉到
    KivyMD 2.0.0（2026-08 发布的大版本重构），它删除了 1.x 的
    `OneLineListItem` / `TwoLineListItem` 等 API，`main.py` 第 28 行
    ImportError 直接闪退。已锁定 `kivy==2.3.1` + `kivymd==1.0.2`
    （kivy 锁 2.3.1 是因为 2.2.x 没有 py3.13 wheel；kivymd 锁 1.0.2 是因为
    1.1.1/1.2.0 官方只发源码包没有 wheel，安卓 p4a 的 `--only-binary` +
    android 平台过滤装不上，实测报错后才定位到；1.0.2 是最后一个有 wheel
    的 1.x 版本，API 兼容，本地冒烟测试通过）
23. 闪退根因二：`main.py` 里 `LabelBase.register(..., fn_bold_italic=...)`
    参数名错误，Kivy 的正确名称是 `fn_bolditalic`（无下划线），任何版本
    都会 TypeError 闪退 —— 这是原版遗留 bug，已修
24. `requirements.txt` 原先没有 kivy/kivymd（注释说"由 buildozer 打包"），
    桌面用户 `pip install -r requirements.txt` 后跑 `python main.py` 必
    ModuleNotFoundError 闪退 —— 已补上并锁版本
25. 新增 `smoke_test.py`：无头跑 build() + 顺序切换全部 7 个页面，
    回归验证启动与页面导航，本地全绿

**安卓 17 适配（2026-10-22）**
26. `android.api = 33 → 37`（Android 17）。targetSdk 33 的包在安卓 17 上
    虽能装，但 Play Protect / 严格 ROM 会警告拦截，且拿不到新系统行为对齐
27. `android.ndk = 25b → 28c`：**这是安卓 17 闪退的第二根因**——安卓 15+
    新机（含全部安卓 17 机型）默认 16KB 内存页，NDK 25b 编出的 .so 是
    4KB 对齐，在这些设备上 dlopen 直接失败启动闪退。NDK r28c 完整支持
    16KB 对齐（NDK 命名是 r28c 这种格式，`27b` 是无效版本号）
28. `p4a.branch = develop`：16KB 对齐修复与 api 37 支持先进 develop 分支
    （社区验证配置：api36 + ndk28c + arm64 + p4a develop 可解 16KB 问题）
29. `android.archs` 双架构 → 仅 `arm64-v8a`：安卓 17 机型均为 arm64，
    单架构 CI 构建时间减半、包体减半；16KB 对齐 .so 在 4KB 页旧机
    仍可运行（向后兼容）
30. `p4a.python_version = 3.13`：镜像默认 3.14 会踩 ensurepip 旧 pip
    不兼容的坑（CI patch 循环一直在兜这个），显式锁版本

> 原版代码已完整保留在分支 `backup-before-optimize-20261022`，随时可还原：
> `git checkout backup-before-optimize-20261022`

## 五、安全与合规提醒

- `accounts.json` 保存登录 Token，已设置 600 权限并加入 `.gitignore`，
  但请勿把它提交到任何公开仓库或发给他人
- 本工具仅供学习交流使用，请遵守学校与平台的相关规定
- 禁止商用（含收费代刷、引流变现），详见 LICENSE

## 六、常见问题

- **打开闪退（最重要）**：90% 是 KivyMD 版本问题。请勿 `pip install kivymd`
  裸装（会拉 2.0.0，与本项目 1.x API 不兼容，启动即 ImportError）。
  必须用锁好版本的依赖：`pip install -r requirements.txt`
- **安卓 15+/17 上启动闪退**：旧 NDK 编的 .so 是 4KB 内存页对齐，在 16KB 页
  新机上 dlopen 直接失败。请用当前 CI 产物（NDK 28c + api 37 已适配），
  不要拿旧 APK 测试；本地重打必须 `buildozer android clean` 后再构建
- **安卓中文变方块**：确认 `NotoSansSC.ttf` 与 `main.py` 同目录（优化版已修打包配置）
- **自动登录不可用**：`pip install -r requirements.txt` 后重试；
  缺依赖时会提示自动安装，也可选 `n` 走人工登录
- **端口 9527 被占用**：关闭占用程序，或改 `auth.py` 的 `CALLBACK_PORT`
- **Token 失效**：删掉账号重新登录（过期账号会在验证失败后自动清除）
