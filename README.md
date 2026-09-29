# WeChat Ops

用「**截图 → 视觉识别 → 动作 → 截图验证**」的闭环操作电脑（macOS 本机路线 + Linux 云服务器常驻 Agent 路线），代替人手点按钮、输文字、切窗口、走界面流程。

适用于 Claude Code、Codex 等支持 skill 的 AI 编程助手。

## 为什么不是「录制回放」

| | 录制回放（写死坐标） | 本技能（视觉驱动） |
|---|---|---|
| 定位时机 | 录制时定一次 | **每次执行时实时定位** |
| 界面变了 | 静默点错 | 看图发现异常，改道 |
| 出错后 | 不知道，继续错 | **截图验证，立即发现** |
| 存什么 | 像素坐标 | 语义特征 + 判断方法 |

坐标是易耗品：分辨率、窗口位置、应用版本、系统语言，任何一样变了写死的坐标就失效。所以本技能存的是**「怎么找到它」**，不是「它在哪」。

## 核心原则

1. **坐标绝不落盘** —— 坐标只存在于本次任务的上下文里，任务结束即作废。该记的是语义特征和判断方法。
2. **每步都要验证** —— 视觉方案真正的价值不是"能看图"，而是"点完能确认"。判断标准：如果这一步失败了你不会察觉，那这一步就该加验证。
3. **先想清楚交互方式** —— 同一个控件，单击和长按可能完全是两回事。拿不准就先试。

## 安装

```bash
git clone https://github.com/kenyanghui/wechat-ops.git

cp -r wechat-ops ~/.claude/skills/    # Claude Code
cp -r wechat-ops ~/.codex/skills/     # Codex
```

## 依赖

```bash
pip3 install pyautogui pyperclip pillow
```

并在「系统设置 → 隐私与安全性」中授权：

- **辅助功能** —— 才能模拟点击和按键
- **屏幕录制** —— 才能截图。缺这项时 `screencapture` 会**静默返回成功但只拍到壁纸**，只能靠看图发现

## 用法

```bash
python3 scripts/vision.py shot [名字]           # 截图，自动缩放到逻辑分辨率
python3 scripts/vision.py grid [名字] [间距]     # 叠加带刻度的坐标网格
python3 scripts/vision.py crop x1 y1 x2 y2      # 裁剪放大，看小图标/小字
python3 scripts/vision.py click X Y             # 单击
python3 scripts/vision.py dclick X Y            # 双击
python3 scripts/vision.py longpress X Y [秒]    # 长按
python3 scripts/vision.py activate 微信          # 按窗口/进程名激活并置前
python3 scripts/vision.py type "文本"            # 输入，走剪贴板，支持中文长文本
python3 scripts/vision.py key cmd+v             # 按键，支持组合键
python3 scripts/vision.py scroll N [X Y]        # 滚动，可指定鼠标落点
python3 scripts/vision.py pos                   # 打印屏幕尺寸与鼠标位置
```

截图统一存在 `/tmp/wechat_ops/`。

## 坐标系（先读这段，否则必错）

macOS Retina 屏上，**截图分辨率和点击分辨率不是一回事**：`screencapture` 输出物理像素（通常 2 倍），`pyautogui` 用逻辑像素。

`vision.py` 已自动把截图缩放到逻辑分辨率，所以：

> **图上量到的坐标 = 直接可用的点击坐标**

这也是为什么所有操作都要走 `vision.py`，而不是直接 `screencapture`——手工换算 2 倍关系是最高频的错误来源。

## 已知陷阱

实测踩过的坑，完整版见 [SKILL.md](SKILL.md)：

- **中文输入法会吃掉组合键** —— `pyautogui.hotkey('command','v')` 会退化成裸字母 `v`。须用 AppleScript 发键（`vision.py` 已处理）
- **读图命令会读到旧截图** —— 图本身没错，错的是它描述的那个瞬间已经过去了（`crop`/`grid` 已默认重新截图）
- **滚动前先把鼠标移进目标区域** —— 滚轮事件发给指针所在的那个视图
- **弹窗会挡住目标** —— 动作后一定截图

## 安全边界

以下动作**先跟用户确认再执行**：对外发布（发消息、发邮件、提交表单）、破坏性操作（删除、覆盖）、花钱（下单、支付）、任何不可逆的操作。

一个实用做法：**把流程走到最后一步停住**，让用户看到完整状态，再决定要不要按下那个不可逆的按钮。

## License

[MIT](LICENSE)

## 维护纪律(skill-ops 工作流)

本仓库按 [references/ops-workflow.md](references/ops-workflow.md) 维护:失败基线优先、
安全闸门固化进代码、证据分级表述(已验证:证据 / 未验证:待确认)、
守卫检查(`bash scripts/check-skill.sh .`)、CHANGELOG 版本化。
改动 scripts/agent.py 时,服务器部署实例必须回填仓库后再发布。
