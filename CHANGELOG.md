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

## v0.2.1 (2026-09-29)

- agent.py: 消息合并去抖(merge_wait)、AI时间感知(当前时间注入prompt)、心跳时间持久化(重启不重发)、修复 Python3 推导式变量泄漏导致的红点状态复位崩溃
- pitfalls-linux.md: 第19条(发文件需先聚焦输入区,否则 Send 点击被吞)
- config-template: 新增 merge_wait

## v0.3.0 (2026-09-29) — 迭代1

学自同类项目(设计借鉴,无代码复制)落地五项:

- **每会话独立 Prompt**:config.personas 按会话名覆盖默认人设(#4)
- **聊天记忆**:memory/<会话>.md 落盘,最近40行注入 prompt,每10次交互 GLM 压缩摘要(#5)
- **群 @ 检测**:群会话仅被 @ self_nick 时响应,否则仅记录(#6)
- **链接阅读**:检测对方消息 URL→抓正文(3000字)→结合内容回复,失败降级(#8)
- **FT 图标模板匹配**:颜色候选+9x9 模板最小距离择优,核验成功后自学习模板(#2,待实测关闭)

其他:config 新增 self_nick/personas/merge_wait;send 前消息合并去抖;AI 时间感知;心跳持久化防重启重发;Python3 推导式崩溃修复(红点状态复位)。

## v0.3.1 (2026-09-29)

- **知识库接入**: kb/ 目录 + 轻量检索(kb_context 按关键词重合度取段落),群聊按 kb_chats 配置注入「AI教育杨老师」知识库参考;群人设升级为 AI 知识助教
- ima 知识库 MCP 直连列入升级票(#13)

## v0.3.2 (2026-09-29)

- **ima 知识库 OpenAPI 直连**(替代手动导出):双头认证(ima-openapi-clientid/apikey)、search_knowledge_base 解析知识库 ID(兼容实际返回 kb_id/kb_name 字段)、jieba 分词拆词搜索、get_media_info 取原文(编码探测防乱码)、文件检索兜底
- 凭证仅存服务器 config(600),仓库模板留空
- 群助人设升级为「AI教育杨老师」AI知识助教,kb_chats 控制生效范围

## v0.4.1 (2026-09-29)

- N-03 完成:6080 安全直连上线(nginx TLS+BasicAuth 反代,自签证书,htpasswd 哈希),公网实测 401/200 正常,明文 400 拒绝
- websockify 迁移至 127.0.0.1:6081,6080 公网面由 nginx 接管
- linux-server.md 补充安全直连部署说明
