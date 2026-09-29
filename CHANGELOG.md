# CHANGELOG — wechat-ops

## v0.2.0 (2026-09-29)

新增 Linux 云服务器常驻 Agent 路线(与 macOS 视觉路线并行,共享视觉闭环纪律):

- `scripts/agent.py`:GLM 视觉值守 Agent(8秒盯屏→红点检测→白名单→读会话→拟回复→发送),内嵌安全闸门:发送前视觉核验窗口标题(空标题拒绝)、白名单外零操作、限速、静默时段、敏感词回退、PAUSE 急停、自愈状态机(托盘恢复/透明壳重启/自动登录/过渡态保护)
- `scripts/setup-server.sh`:一键环境搭建(xfce+TigerVNC+noVNC+中文字体+swap+微信Linux版,幂等)
- `scripts/wechat-agent.service` + `scripts/config-template.json`(已脱敏)
- `scripts/check-skill.sh`:skill 守卫(结构/引用/凭证/隐私/断言/编码/语法/CHANGELOG/包一致性)
- `references/linux-server.md`:部署与运维指南
- `references/pitfalls-linux.md`:17 条实战踩坑(xclip 挂起、pkill 自杀、托盘隐藏、置顶折叠、多账号陷阱等)
- `references/ops-workflow.md`:skill 建设与维护工作流(基线优先/形式匹配失败类型/守卫/三方同步/证据分级/复盘)
- SKILL.md 扩展为双平台入口,description 覆盖 Linux 值守场景触发词

## v0.1.x (历史)

macOS 视觉自动化技能初版:vision.py + 单文件 SKILL.md(坐标绝不落盘、每步验证、朋友圈发布全流程案例)。
