#!/usr/bin/env bash
# 微信 GUI Agent 一键环境搭建(Ubuntu 22.04/24.04 x86_64, 幂等可重复执行)
# 用法: 上传到服务器 root 家目录, bash setup-server.sh
# 人工步骤在脚本结尾打印(vncpasswd + 微信扫码)
set -euo pipefail

echo "== 1/8 系统依赖 =="
apt-get update -qq
apt-get install -y -qq xfce4 xfce4-goodies tigervnc-standalone-server tigervnc-common \
  novnc websockify xdotool xclip wmctrl scrot dbus-x11 \
  python3-pil python3-requests fonts-noto-cjk >/dev/null

echo "== 2/8 swap(存在则跳过) =="
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile
  mkswap /swapfile && swapon /swapfile
  grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

echo "== 3/8 屏蔽 lightdm(xfce4-goodies 连带装上的,防开机抢占内存) =="
systemctl disable --now lightdm >/dev/null 2>&1 || true

echo "== 4/8 屏蔽 Evolution 自启(省约100M内存) =="
mkdir -p ~/.config/autostart
for app in org.gnome.Evolution-alarm-notify print-applet; do
  printf '[Desktop Entry]\nType=Application\nHidden=true\n' > ~/.config/autostart/$app.desktop
done
pkill -f "[e]volution" 2>/dev/null || true

echo "== 5/8 VNC xstartup =="
mkdir -p ~/.vnc
cat > ~/.vnc/xstartup <<'EOF'
#!/bin/sh
unset SESSION_MANAGER
unset DBUS_SESSION_BUS_ADDRESS
exec startxfce4
EOF
chmod +x ~/.vnc/xstartup

echo "== 6/8 VNC systemd 服务(虚拟屏 :1, 只听 localhost) =="
cat > /etc/systemd/system/tigervncserver@:1.service <<EOF
[Unit]
Description=Remote desktop service (VNC :1)
After=syslog.target network.target

[Service]
Type=forking
User=root
ExecStartPre=/usr/bin/tigervncserver -kill :1 >/dev/null 2>&1 || true
ExecStart=/usr/bin/tigervncserver -localhost=1 -geometry 1440x900 -depth 24 :1
ExecStop=/usr/bin/tigervncserver -kill :1
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

echo "== 7/8 noVNC systemd 服务(浏览器访问, 只听 localhost:6080) =="
cat > /etc/systemd/system/novnc.service <<EOF
[Unit]
Description=noVNC browser VNC client (localhost only)
After=network.target tigervncserver@:1.service

[Service]
ExecStart=/usr/bin/websockify --web=/usr/share/novnc 127.0.0.1:6080 localhost:5901
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload

echo "== 8/8 下载安装微信官方 Linux 版 =="
if ! command -v wechat >/dev/null; then
  curl -sL --retry 3 -o /tmp/WeChatLinux.deb \
    "https://dldir1v6.qq.com/weixin/Universal/Linux/WeChatLinux_x86_64.deb"
  apt-get install -y -qq /tmp/WeChatLinux.deb >/dev/null
  rm -f /tmp/WeChatLinux.deb
fi

cat <<'NOTE'

========== 人工步骤 ==========
1) 设 VNC 密码(记牢,浏览器连接时用):  vncpasswd
2) 启动桌面和远程访问:
     systemctl enable --now tigervncserver@:1 novnc
3) 本机建隧道后浏览器打开 http://localhost:6080/vnc.html 扫码登录微信:
     ssh -L 6080:localhost:6080 root@<服务器IP>
4) 部署 Agent(见 SKILL.md 快速开始第3步)
NOTE
