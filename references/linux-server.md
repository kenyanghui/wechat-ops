
## 安全直连(替代 SSH 隧道的浏览器直达)

部署 nginx TLS+BasicAuth 反代:websockify 绑 127.0.0.1:6081,nginx 监听公网 6080 ssl,
自签证书 + htpasswd(密码必须哈希,htpasswd -nb 生成)。访问 https://<IP>:6080/vnc.html
(自签证书需手动信任一次)。安全组仅放行 6080;明文 HTTP 会被 TLS 端口直接拒绝(400)。
配置样例见仓库 history v0.4.1。
