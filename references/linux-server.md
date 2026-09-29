# Linux 云服务器路线:7x24 挂机的微信 Agent

> macOS 路线(vision.py)操作你眼前的电脑;本路线把微信搬上云服务器虚拟屏,
> 配一个 GLM 视觉 Agent 常驻值守——人关机,微信不下线。已在 2核2G Ubuntu 24.04 实战。

## 与 macOS 路线的哲学分工

| | macOS(vision.py) | Linux 服务器(agent.py) |
|---|---|---|
| 坐标性质 | **易耗品**:每次实时定位,绝不落盘 | **固定资产**:虚拟屏分辨率固定+窗口最大化固定,坐标一次校准长期有效 |
| 会话生命周期 | 跟随你的电脑 | 持久虚拟屏,断开连接微信照常在线 |
| 决策 | 人(你)实时判断 | GLM 视觉模型+规则闸门 |
| 适用 | 当下的一次性界面操作 | 长期自动值守 |

为什么 Linux 侧可以写死坐标:虚拟屏 `:1` 分辨率永远是 1440x900,微信窗口被 wmctrl
强制最大化——布局漂移的根源(真实桌面)不存在。**一旦换了分辨率,全部坐标重新校准**,
校准方法见下文。

## 架构

```
xfce4 桌面 + TigerVNC 虚拟屏 :1 (仅监听 localhost)
  └─ 微信官方 Linux 版(常驻)
       └─ agent.py (systemd 常驻)
            ├─ 每 8 秒 scrot 截屏 → PIL 红点像素检测(本地,零成本)
            ├─ 白名单过滤 → GLM 视觉读会话 → GLM 生成回复
            ├─ 发送前视觉核验窗口标题(防发错人的最后闸门)
            └─ xdotool 点击 / xclip 剪贴板粘贴中文
noVNC(websockify) ← SSH 隧道 ← 你的浏览器(看它干活)
```

不 hook 协议、不逆向,纯 GUI 自动化,封号风险最低。

## 快速部署

```bash
# 1. 环境搭建(幂等,装 xfce+TigerVNC+noVNC+中文字体+swap+微信,约10分钟)
scp scripts/setup-server.sh root@<服务器IP>:/root/
ssh root@<服务器IP> "bash setup-server.sh"   # 末尾按提示 vncpasswd 设密码

# 2. 本机建隧道,浏览器开 http://localhost:6080/vnc.html 扫码登录
ssh -L 6080:localhost:6080 root@<服务器IP>

# 3. 部署 Agent
ssh root@<服务器IP> "mkdir -p /opt/wechat-agent"
scp scripts/agent.py scripts/config-template.json root@<服务器IP>:/opt/wechat-agent/
scp scripts/wechat-agent.service root@<服务器IP>:/etc/systemd/system/
# 编辑 /opt/wechat-agent/config.json:填 bigmodel API key、改白名单
ssh root@<服务器IP> "systemctl daemon-reload && systemctl enable --now wechat-agent"
```

模型:bigmodel 免费档够用(`text: glm-4.5-flash` + `vision: glm-4v-flash`);
付费档(glm-5.3-flash 等)需资源包,拿到 key 先逐模型探测再写配置。

## 三档模式(先 draft 后 auto)

- `observe`:只记录新消息到 inbox.log,零操作
- `draft`:GLM 拟回复写 inbox.log,**不发送**——人工审一天看质量
- `auto`:全自动发送

安全闸门(全部固化在代码里,不是散文):发送前视觉核验窗口标题(空标题一律拒绝)、
白名单外零操作(不点击不标已读)、≤10条/时、23:00-7:00 静默、转账/密码类只回
"记下来了"、`touch /opt/wechat-agent/PAUSE` 一秒急停。

## 坐标校准(换分辨率时)

1. `wmctrl -r Weixin -b add,maximized_vert,maximized_horz` 最大化
2. `scrot` 截图,人工读图量出:搜索框、列表槽位(y0/间距)、图标列、输入框、标题栏
3. 改 config.json 的 coords → `python3 agent.py once` 验证红点检测
4. **永远先拿 File Transfer 当发送链路的小白鼠**,不拿真人会话试

## 运维速查

```bash
tail -f /opt/wechat-agent/inbox.log    # 消息流和草稿
python3 /opt/wechat-agent/agent.py once                     # 单次检测
python3 /opt/wechat-agent/agent.py send "联系人" "内容"      # 定向发送(带核验)
touch /opt/wechat-agent/PAUSE && rm /opt/wechat-agent/PAUSE # 暂停/恢复
systemctl stop wechat-agent            # 彻底停机
```

## 已知坑

17 条实战踩坑实录见 [pitfalls-linux.md](pitfalls-linux.md),高频三则:
xclip 会挂起 ssh 会话、pkill 模式会匹配脚本自身、微信窗口隐藏后 wmctrl 仍能看到它
(恢复逻辑必须无条件激活,不能以"列表里没有"为条件)。

## 风险与边界

个人微信自动化违反微信用户协议,有封号风险:控制频率、建议小号先行、
本仓库所有安全闸门不建议放宽。扫码前确认手机当前登录的是**目标账号**
——桌面版可切换多账号,登错号是真实发生过的事故(见 pitfalls 第17条)。
