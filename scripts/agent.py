#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微信值守 Agent：盯屏 → 识别新消息 → GLM-5.3-Flash 决策回复 → GUI 发送。
模式: observe=只记录 | draft=拟回复不发送 | auto=自动发送(仅白名单)
无 API key 时自动降级为 observe。触摸 /opt/wechat-agent/PAUSE 可暂停。
"""
import json, os, sys, time, base64, logging, subprocess, re
from datetime import datetime, timedelta
from PIL import Image

BASE = os.path.dirname(os.path.abspath(__file__))
CFG = json.load(open(os.path.join(BASE, "config.json"), encoding="utf-8"))
ENV = dict(os.environ, DISPLAY=CFG["display"], HOME=os.environ.get("HOME", "/root"))
# HOME 必须有:systemd 服务环境默认不带 HOME,拉起的微信会因写不了 ~/.xwechat 秒退
PAUSE = os.path.join(BASE, "PAUSE")
INBOX = os.path.join(BASE, "inbox.log")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.FileHandler(os.path.join(BASE, "agent.log"), encoding="utf-8"),
              logging.StreamHandler()])
log = logging.getLogger("agent")

def sh(cmd, timeout=20):
    return subprocess.run(cmd, shell=True, capture_output=True, timeout=timeout, env=ENV)

def scrot(path="/tmp/agent_shot.png"):
    sh(f"scrot -o {path}")
    return Image.open(path).convert("RGB")

LAST_RESTART = 0.0

def _weixin_width():
    out = sh("wmctrl -lG").stdout.decode(errors="ignore")
    for line in out.splitlines():
        if "Weixin" in line:
            try:
                return int(line.split()[4])      # lG 格式: id desk x y W H name
            except (IndexError, ValueError):
                return 0
    return 0

def _center_bright(img):
    """窗口中心区亮度占比。亮=有内容渲染(主窗口或登录窗),暗=透明壳/无窗口"""
    region = img.crop((550, 300, 900, 620))
    n = tot = 0
    for px in region.getdata():
        r, g, b = px[:3]
        tot += 1
        if (r + g + b) / 3 > 110:
            n += 1
    return n / max(tot, 1)

def _login_button(img):
    """登录窗的实心 Log In 按钮(~170x33px)。判据:单行连续绿像素>50。
    'Scan to log in'绿字每行只有零散笔画(≤30),实心按钮中心行约75+,可靠区分。"""
    px = img.load()
    max_cnt = 0
    for yy in range(470, 580, 2):
        cnt = 0
        for xx in range(620, 820, 2):
            r, g, b = px[xx, yy][:3]
            if r < 80 and g > 160 and 60 < b < 140:
                cnt += 1
        max_cnt = max(max_cnt, cnt)
    return max_cnt > 50

def _launch_app():
    """硬重启:只用于进程死亡或窗口透明壳。进程活着但窗口未映射是登录/启动
    过渡态,绝不能走到这里——杀进程会毁掉刚登录的会话(实战踩坑)。"""
    global LAST_RESTART
    if time.time() - LAST_RESTART < 90:          # 冷却,防止连环重启
        return False
    LAST_RESTART = time.time()
    log.warning("重启微信进程(渲染失效或进程消失)")
    sh("pkill -x wechat")
    time.sleep(3)
    subprocess.Popen("nohup /usr/bin/wechat >/dev/null 2>&1 &",
                     shell=True, env=ENV,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    time.sleep(12)
    _activate_all()
    return True

def _activate_all():
    ids = sh("xdotool search --class wechat").stdout.decode().split()
    for line in ids:
        sh(f"wmctrl -i -a {hex(int(line))}")     # 激活=自动取消最小化/托盘隐藏
        time.sleep(0.3)
        if "Weixin" in sh("wmctrl -l").stdout.decode(errors="ignore"):
            break

def ensure_window():
    """确保微信主窗口可用。返回 True=主窗口就绪(已最大化)。
    自愈链:show-desktop清除 → 无条件激活 → 透明壳检测重启进程 → 登录窗自动点
    Log In → 手机确认期记日志等待。注意:微信隐藏到托盘后 wmctrl -l 仍列出它,
    不能用'列表里没有'当恢复条件。"""
    sh("wmctrl -k off")
    if not sh("xdotool search --class wechat").stdout.decode().split():
        _launch_app()
    _activate_all()
    for attempt in range(3):
        w = _weixin_width()
        img = scrot()
        bright = _center_bright(img)
        if w >= 700:                             # 主窗口(最大化或默认尺寸)
            if bright > 0.4:
                sh("wmctrl -r Weixin -b add,maximized_vert,maximized_horz")
                return True
            if not _launch_app():                # 透明壳:渲染死了,重启进程
                return False
        elif w > 0:
            # 小窗=登录/二维码/手机确认。只要还亮着就绝不重启进程——
            # 重启会刷新二维码,用户永远扫不上(实测踩坑)。
            if _login_button(img):
                log.info("检测到登录窗,自动点击 Log In")
                click(720, 540, 8.0)
                _activate_all()
            elif bright > 0.3:
                log_inbox("微信等待扫码或手机确认登录")
                log.warning("等待扫码/手机确认登录")
                return False
            elif not _launch_app():
                return False
        else:
            # 无窗口:进程活着=启动/登录过渡态,只等不杀(杀=毁掉登录会话)
            if sh("pgrep -x wechat").stdout.decode().split():
                log.info("微信窗口未映射,等待过渡完成")
                time.sleep(8)
                _activate_all()
            elif not _launch_app():
                return False
    return False

def click(x, y, wait=0.6):
    sh(f"xdotool mousemove {x} {y} click 1")
    time.sleep(wait)

def press(key, wait=0.5):
    sh(f"xdotool key {key}")
    time.sleep(wait)

def paste(text):
    with open("/tmp/agent_clip.txt", "w", encoding="utf-8") as f:
        f.write(text)
    subprocess.Popen("xclip -selection clipboard < /tmp/agent_clip.txt",
                     shell=True, env=ENV,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    time.sleep(0.5)
    press("ctrl+v", 0.6)

def red_score(img, slot_i):
    """某个聊天位号的红点像素数(新消息指示)"""
    c = CFG["coords"]
    y = c["slot_y0"] + slot_i * c["slot_dy"]
    box = (c["badge_x0"], y - 25, c["badge_x1"], y + 25)
    region = img.crop(box)
    n = 0
    for px in region.getdata():
        r, g, b = px[:3]
        if r > 195 and g < 95 and b < 95:
            n += 1
    return n

def list_region(img):
    c = CFG["coords"]
    return img.crop((c["list_x0"], c["list_y0"], c["list_x1"], c["list_y1"]))

def img_hash(img):
    small = img.resize((24, 64))
    return hash(tuple(v // 24 for p in small.getdata() for v in p[:3]))

def to_b64(img):
    img.save("/tmp/agent_b64.png")
    return base64.b64encode(open("/tmp/agent_b64.png", "rb").read()).decode()

# ---------------- GLM 大脑 ----------------
def glm_chat(payload, timeout=90):
    import requests
    api = CFG["api"]
    r = requests.post(f"{api['base']}/chat/completions",
        headers={"Authorization": f"Bearer {api['key']}"},
        json={"model": payload.get("model", api["text_model"]),
              "messages": payload["messages"], "temperature": payload.get("temperature", 0.6)},
        timeout=timeout)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]

def brain_ready():
    return bool(CFG["api"].get("key"))

def vision(prompt, img, model=None):
    return glm_chat({"model": model or CFG["api"]["vision_model"], "temperature": 0.2,
        "messages": [{"role": "user", "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{to_b64(img)}"}},
            {"type": "text", "text": prompt}]}]})

def think(prompt):
    return glm_chat({"messages": [{"role": "user", "content": prompt}]})

# ---------------- 业务动作 ----------------
def chat_header_name():
    """读取聊天窗口顶部标题,用于发送前核验,防止发错人"""
    shot = scrot()
    try:
        ans = vision("这是微信聊天窗口顶部标题栏截图。如果里面显示了聊天对象的名字,只输出名字本身;"
                     "看不到名字就只输出NONE。不要输出任何解释。",
                     shot.crop((300, 60, 900, 105)))
        ans = ans.strip().strip('"')
        return "" if ("NONE" in ans.upper() or "微信" == ans or len(ans) > 20) else ans
    except Exception as e:
        log.warning("读标题失败: %s" % e)
        return ""

def header_matches(header, name):
    """标题核验。header 为空一律不通过——空字符串是任何名字的子串,曾导致
    在登录界面也'核验通过'的漏洞。"""
    if not header:
        return False
    h, n = header.lower(), name.lower()
    return n in h or h in n

def open_chat_via_search(name):
    c = CFG["coords"]
    # 注意:此处绝不能按 Escape——实测按 Esc 会打断搜索交互并让渲染崩成透明壳,
    # 进而被自愈逻辑误判死亡而重启进程,毁掉登录会话(坑#18)。
    click(*c["search_box"])
    press("ctrl+a", 0.2)
    paste(name)
    time.sleep(1.6)
    shot = scrot()
    try:
        ans = vision("这是微信搜索下拉结果截图。找到「Contacts」区域下名字等于「%s」的联系人条目,"
                     "返回中心坐标,格式 JSON: {\"x\":整数,\"y\":整数,\"found\":true/false}。"
                     "坐标以截图左上角为原点,宽1440高900。没有本地联系人结果时 found=false。" % name, shot)
        m = re.search(r"\{[^{}]*\"x\"[^{}]*\}", ans, re.S)
        if m:
            pos = json.loads(m.group(0))
            if pos.get("found"):
                click(int(pos["x"]), int(pos["y"]), 1.5)
                header = chat_header_name()
                if header_matches(header, name):
                    return True
                log.warning("打开的会话标题(%s)与目标(%s)不符,中止" % (header, name))
                return False
    except Exception as e:
        log.warning("视觉定位失败(%s),退回默认坐标" % e)
    click(*c["search_first_result"], 1.5)      # 兜底:第一个结果位
    header = chat_header_name()
    ok = header_matches(header, name)
    if not ok:
        log.warning("兜底打开的会话标题(%s)与目标(%s)不符,中止" % (header, name))
    return ok

def read_conversation():
    shot = scrot()
    try:
        ans = vision("Read the WeChat chat window in this screenshot. Output JSON with the ACTUAL "
                     "window title and the ACTUAL text of the most recent messages, transcribed "
                     "character-for-character from the image. Never output placeholder text like "
                     "... or generic words - only real content you can see. If the screenshot shows "
                     "no chat window, output {\"chat_name\":\"\",\"messages\":[]}. "
                     "Format: {\"chat_name\":\"<real title>\",\"messages\":[{\"from\":\"them|me\","
                     "\"text\":\"<real message>\"}]} (newest last, max 6 messages).", shot)
        m = re.search(r"\{.*\}", ans, re.S)
        info = json.loads(m.group(0)) if m else None
        # 防幻觉:全是占位符/空文本视为读取失败
        if info and info.get("messages"):
            real = [x for x in info["messages"]
                    if len(x.get("text", "")) >= 2 and x["text"] not in ("...", "…")]
            if not real:
                log.warning("视觉读取返回疑似占位符,丢弃")
                return None
        return info
    except Exception as e:
        log.warning("读会话失败: %s" % e)
        return None

def send_text(text):
    c = CFG["coords"]
    click(*c["input_box"])
    paste(text)
    press("Return", 0.8)
    if ensure_window():                          # 发送动作可能触发窗口隐藏,救回来再审计
        time.sleep(0.5)
        scrot().save(os.path.join(BASE, "last_sent.png"))
    log.info("已发送: %s" % text[:40].replace("\n", " "))

SAFE_ACK = "这条我记下来了,回头我详细答复你"
DANGER = re.compile(r"转账|红包|密码|验证码|汇款|付款")
URL_RE = re.compile(r"https?://[^\s\"'<>]+")

def fetch_url_text(url):
    """链接阅读(学自 WXAUTO_SE):抓网页正文,失败返回 None 走兜底"""
    try:
        import requests
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        if not r.encoding or r.encoding.lower() in ("iso-8859-1", "latin-1"):
            r.encoding = r.apparent_encoding         # 同上,防中文乱码
        r.raise_for_status()
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", r.text)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text)[:3000]
    except Exception as e:
        log.warning("链接抓取失败 %s: %s" % (url, e))
        return None

def memory_file(chat):
    safe = re.sub(r"[^\w\u4e00-\u9fff-]", "_", chat) or "unknown"
    return os.path.join(BASE, "memory", safe + ".md")

def memory_context(chat):
    mf = memory_file(chat)
    if not os.path.exists(mf):
        return ""
    lines = open(mf, encoding="utf-8").readlines()
    return "".join(lines[-40:])

def remember_exchange(chat, last_them, reply):
    """对话落记忆文件;每 10 次交互让 GLM 压缩一份摘要(学自 WXAUTO_SE 记忆功能)"""
    mf = memory_file(chat)
    os.makedirs(os.path.dirname(mf), exist_ok=True)
    stamp = datetime.now().strftime("%m-%d %H:%M")
    with open(mf, "a", encoding="utf-8") as f:
        f.write("[%s] 对方: %s\n[%s] 我: %s\n" % (
            stamp, (last_them or "")[:80], stamp, reply[:80].replace("\n", " ")))
    try:
        n = sum(1 for _ in open(mf, encoding="utf-8"))
        if n >= 20 and n % 20 < 2:
            head = "".join(open(mf, encoding="utf-8").readlines()[-40:])
            summary = think("把以下微信对话记录压缩成不超过300字的记忆要点(事实/承诺/偏好/待办),直接输出要点:\n" + head)
            sf = os.path.join(os.path.dirname(mf), "summary-" + os.path.basename(mf))
            open(sf, "w", encoding="utf-8").write(summary.strip())
            log.info("记忆摘要已更新: %s" % os.path.basename(sf))
    except Exception:
        log.warning("记忆压缩失败", exc_info=True)

KB_DIR = os.path.join(BASE, "kb")

def _ima_headers():
    ima = CFG.get("ima", {})
    return {"ima-openapi-clientid": ima.get("client_id", ""),
            "ima-openapi-apikey": ima.get("api_key", ""),
            "Content-Type": "application/json"}

def ima_kb_id():
    """解析知识库名→ID(内存缓存)。凭证只存服务器 config,不落日志不进仓库。"""
    ima = CFG.get("ima", {})
    if ima.get("kb_id"):
        return ima["kb_id"]
    if not (ima.get("enabled") and ima.get("client_id") and ima.get("api_key") and ima.get("kb_name")):
        return ""
    try:
        import requests
        r = requests.post("https://ima.qq.com/openapi/wiki/v1/search_knowledge_base",
                          headers=_ima_headers(),
                          json={"query": ima["kb_name"], "cursor": "", "limit": 10}, timeout=15)
        r.raise_for_status()
        for kb in (r.json().get("data") or {}).get("info_list") or []:
            # 实测 API 返回 kb_id/kb_name(文档写 id/name,不一致——兼容两者)
            name = kb.get("kb_name") or kb.get("name")
            kid = kb.get("kb_id") or kb.get("id")
            if name == ima["kb_name"] and kid:
                ima["kb_id"] = kid
                log.info("ima 知识库已解析: %s -> %s" % (name, kid))
                return kid
        log.warning("ima 未找到知识库: %s" % ima["kb_name"])
    except Exception as e:
        log.warning("ima 知识库解析失败: %s" % e)
    return ""

def _keywords(query):
    """中文分词提关键词(jieba 优先),过滤虚词,按词长降序(信息量大的优先),最多6个"""
    words = []
    try:
        import jieba
        jieba.setLogLevel(logging.WARNING)       # 静音 jieba 的建词典 DEBUG 输出
        words = [w for w in jieba.lcut(query) if len(w) >= 2]
    except Exception:
        words = re.findall(r"[A-Za-z0-9]{2,}", query)
    stop = {"怎么办", "怎么", "什么", "为什么", "可以", "应该", "如何", "一下", "看看",
            "介绍", "需要", "还是", "能把", "告诉", "我们", "你们", "知道", "出来",
            "相关", "信息", "没有", "这个", "那个", "时候", "开始", "内容", "资料",
            "文章", "重点", "整理"}
    seen, out = set(), []
    for w in sorted(set(words) - stop, key=len, reverse=True):
        if w not in seen:
            seen.add(w)
            out.append(w)
    # 中文前缀候选:长词的前两字也作为关键词(「四会开」→「四会」,专名常见形态)
    for w in list(out):
        if len(w) >= 3 and re.match(r"^[\u4e00-\u9fff]{2}", w):
            pre = w[:2]
            if pre not in seen:
                seen.add(pre)
                out.append(pre)
    return out[:6]

def ima_search(query):
    """ima 开放平台 search_knowledge。长问题分词分别查,合并去重;
    返回 [{title, highlight, media_id}, ...] 最多6条。"""
    kb_id = ima_kb_id()
    if not kb_id:
        return []
    queries, seen_q = [], set()
    first = query.strip()[:20]
    if first:
        queries.append(first)
    for t in _keywords(query):
        if t not in seen_q:
            queries.append(t)
    out, seen = [], set()
    try:
        import requests
        for q in queries[:6]:                    # 控延迟:最多6次查询
            r = requests.post("https://ima.qq.com/openapi/wiki/v1/search_knowledge",
                              headers=_ima_headers(),
                              json={"query": q, "cursor": "", "knowledge_base_id": kb_id},
                              timeout=15)
            r.raise_for_status()
            for x in ((r.json() or {}).get("data") or {}).get("info_list") or []:
                key = x.get("media_id") or x.get("title")
                if not key or key in seen:
                    continue
                seen.add(key)
                out.append({"title": x.get("title", ""),
                            "highlight": x.get("highlight_content", ""),
                            "media_id": x.get("media_id", "")})
            if len(out) >= 6:
                break
    except Exception as e:
        log.warning("ima 搜索失败: %s" % e)
    return out[:6]

def ima_media_text(media_id):
    """网页型收藏取原文(get_media_info → url_info.url → 抓正文),失败返回 None"""
    try:
        import requests
        r = requests.post("https://ima.qq.com/openapi/wiki/v1/get_media_info",
                          headers=_ima_headers(), json={"media_id": media_id}, timeout=15)
        url = (((r.json() or {}).get("data") or {}).get("url_info") or {}).get("url")
        if not url:
            return None
        rr = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        if not rr.encoding or rr.encoding.lower() in ("iso-8859-1", "latin-1"):
            rr.encoding = rr.apparent_encoding       # 防 UTF-8 被按 Latin-1 解成乱码
        rr.raise_for_status()
        text = re.sub(r"(?is)<(script|style).*?</\1>", " ", rr.text)
        text = re.sub(r"<[^>]+>", " ", text)
        return re.sub(r"\s+", " ", text)[:1500]
    except Exception as e:
        log.warning("ima 原文获取失败 %s: %s" % (media_id, e))
        return None

def kb_context(question):
    """知识库检索(轻量RAG):扫 kb/ 下 md/txt 的段落,按问题关键词重合度取最优段。
    知识来源是 ima 知识库「AI教育杨老师」的导出文档;MCP 直连见 Loong 工单 #13。"""
    try:
        if not os.path.isdir(KB_DIR):
            return ""
        q = set(question)
        best, best_score = [], 0
        for fn in os.listdir(KB_DIR):
            if not fn.lower().endswith((".md", ".txt")):
                continue
            try:
                content = open(os.path.join(KB_DIR, fn), encoding="utf-8").read()
            except Exception:
                continue
            for para in re.split(r"\n\s*\n", content):
                para = para.strip()
                if len(para) < 30:
                    continue
                score = sum(1 for ch in q if ch in para and not ch.isspace())
                if score > best_score and score >= 3:
                    best, best_score = ["[%s] %s" % (fn, para[:600])], score
                elif score == best_score and score >= 3 and len(best) < 3:
                    best.append("[%s] %s" % (fn, para[:600]))
        return ("\n\n".join(best))[:2500] if best else ""
    except Exception:
        log.warning("知识库检索失败", exc_info=True)
        return ""

def compose_reply(info):
    chat = info.get("chat_name", "未知")
    last_them = next((m["text"] for m in reversed(info.get("messages", []))
                      if m["from"] == "them"), "")
    history = "\n".join(("对方: " if m["from"] == "them" else "我: ") + m["text"]
                        for m in info["messages"])
    persona = CFG.get("personas", {}).get(chat, CFG["persona"])   # 每会话独立人设(学自 WXAUTO_SE)
    memory = memory_context(chat)
    link_note = ""
    urls = URL_RE.findall(last_them)
    if urls:
        content = fetch_url_text(urls[0])
        link_note = ("\n对方消息含链接 %s,网页正文如下:\n%s\n请结合网页内容回复。" % (urls[0], content)
                     if content else
                     "\n对方消息含链接 %s(抓取失败,可建议对方粘贴正文)。" % urls[0])
    prompt = (persona +
              "\n\n当前时间: " + datetime.now().strftime("%Y-%m-%d %H:%M %A") +   # AI时间感知(学自 WXAUTO_SE)
              "\n当前聊天对象: " + chat +
              (("\n相关历史记忆:\n" + memory) if memory else "") +
              link_note +
              "\n最近对话:\n" + history +
              "\n\n请以「我」的身份回复对方最后一条消息。只输出回复正文,不要任何解释、引号或表情符号堆砌。")
    if chat in CFG.get("kb_chats", []):
        q = (last_them or history[-200:])
        kb_parts = []
        for h in ima_search(q)[:3]:                      # ima OpenAPI 优先
            line = "《%s》%s" % (h["title"], h["highlight"])
            if len(kb_parts) < 2 and h.get("media_id"):  # 最多取2篇原文,控延迟
                text = ima_media_text(h["media_id"])
                if text:
                    line += " 正文:" + text
            kb_parts.append(line)
        if not kb_parts:
            kb_parts.append(kb_context(q))               # 文件检索兜底
        kb = "\n".join(p for p in kb_parts if p)
        if kb:
            prompt += "\n\n知识库参考(「AI教育杨老师」知识库,回答以下列内容为准,没有的如实说需要查证):\n" + kb
    reply = think(prompt).strip().strip('"')
    if DANGER.search(reply):
        return SAFE_ACK
    remember_exchange(chat, last_them, reply)
    return reply

def in_quiet_hours():
    q = CFG.get("quiet_hours")
    if not q:
        return False
    h = datetime.now().hour
    a, b = q
    return h >= a or h < b

RATE = {"hour": None, "count": 0}
SCHED_FILE = os.path.join(BASE, "scheduled.json")

def load_tasks():
    try:
        return json.load(open(SCHED_FILE, encoding="utf-8"))
    except Exception as e:
        if os.path.exists(SCHED_FILE):
            log.warning("load_tasks 解析失败: %s (内容前80字节: %r)" % (
                e, open(SCHED_FILE, "rb").read(80)))
        return []

def save_tasks(tasks):
    json.dump(tasks, open(SCHED_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

def remove_task(task):
    """手术式移除已发送的任务(按 run_at+message+chat 精确匹配),保留其他任务"""
    try:
        kept = [x for x in load_tasks()
                if not (x.get("run_at") == task.get("run_at")
                        and x.get("message") == task.get("message")
                        and x.get("chat") == task.get("chat"))]
        save_tasks(kept)
    except Exception:
        log.warning("任务移除失败", exc_info=True)

def run_due_tasks():
    """到期定时任务经核验路径发送(学自 WXAUTO_SE 定时任务);daily 自动顺延。
    发送成功后手术式移除该条;失败重排队(+2分钟,3次放弃)。
    ⚠️ 需 config scheduled_enabled=true;实测曾出现重复触发循环,修复前保持关闭。"""
    if not CFG.get("scheduled_enabled"):
        return
    now = datetime.now()
    tasks = load_tasks()
    if not tasks:
        return
    changed = False
    fired = 0
    for t in tasks:
        try:
            run_at = datetime.strptime(t["run_at"], "%Y-%m-%d %H:%M")
        except Exception:
            continue
        if now < run_at:
            continue
        chat, msg = t.get("chat", ""), t.get("message", "")
        log.info("定时任务触发: %s -> %s" % (chat, msg[:30]))
        sent = False
        try:
            ensure_window()
            if open_chat_from_list(chat) or open_chat_via_search(chat):
                send_text(msg)
                log_inbox("定时任务已发送 %s: %s" % (chat, msg[:40]))
                sent = True
                fired += 1
        except Exception:
            log.exception("定时任务发送失败")
        if sent:
            if t.get("repeat") == "daily":
                t["run_at"] = (run_at + timedelta(days=1)).strftime("%Y-%m-%d %H:%M")
                changed = True
            else:
                remove_task(t)
                changed = True
        else:
            t["attempts"] = t.get("attempts", 0) + 1
            if t["attempts"] >= 3:
                log_inbox("定时任务连续3次失败已放弃: %s -> %s" % (chat, msg[:30]))
                remove_task(t)
                changed = True
            else:
                t["run_at"] = (now + timedelta(minutes=2)).strftime("%Y-%m-%d %H:%M")
                changed = True
    if changed:
        ensure_window()
        save_tasks(load_tasks())                 # 重读后保存,合并并发改动

def maybe_schedule(text, chat):
    """白名单消息含定时意图时 GLM 抽取结构化任务(学自 WXAUTO_SE);返回确认语或 None"""
    if not re.search(r"\d+\s*分钟|\d+\s*小时|每天.*点|明天.*点|提醒我", text):
        return None
    prompt = ("从这条微信消息抽取定时任务。只输出JSON:"
              '{"has": true/false, "run_at": "YYYY-MM-DD HH:MM", "message": "提醒内容", "repeat": "none或daily"}。'
              "没有定时意图则 has=false。当前时间: %s。消息: %s"
              % (datetime.now().strftime("%Y-%m-%d %H:%M"), text[:200]))
    try:
        m = re.search(r"\{[^{}]*\}", think(prompt), re.S)
        if not m:
            return None
        d = json.loads(m.group(0))
        if not d.get("has") or not d.get("run_at"):
            return None
        tasks = load_tasks()
        tasks.append({"run_at": d["run_at"], "chat": chat,
                      "message": d.get("message", ""), "repeat": d.get("repeat", "none")})
        save_tasks(tasks)
        log.info("定时任务已登记: %s %s" % (d["run_at"], d.get("message", "")[:30]))
        return "好的，已定好：%s（%s）" % (d.get("message", "")[:30], d["run_at"])
    except Exception:
        log.warning("定时任务抽取失败", exc_info=True)
        return None

def group_needs_reply(chat_name, messages):
    """群聊仅在被 @ 本号昵称时响应(学自 WXAUTO_SE)。群标题带成员数括号;
    未配置 self_nick 或非群会话保持原行为。"""
    if "(" not in (chat_name or ""):
        return True
    nick = CFG.get("self_nick", "")
    if not nick:
        return True
    them = " ".join(m.get("text", "") for m in messages if m.get("from") == "them")
    return nick in them

def rate_ok():
    h = datetime.now().hour
    if RATE["hour"] != h:
        RATE["hour"], RATE["count"] = h, 0
    return RATE["count"] < CFG["max_replies_per_hour"]

def log_inbox(line):
    with open(INBOX, "a", encoding="utf-8") as f:
        f.write("[%s] %s\n" % (datetime.now().strftime("%m-%d %H:%M:%S"), line))

def handle_trigger(slots, img):
    c = CFG["coords"]
    ensure_window()
    # 借视觉把槽位映射成联系人名(有大脑时)
    slot_map = {}
    if brain_ready():
        try:
            names = vision("这是微信聊天列表竖条截图。从上到下列出每个会话名字,"
                           "只输出JSON数组:[{\"slot\":0,\"name\":\"...\"}]", list_region(img))
            m = re.search(r"\[.*\]", names, re.S)
            slot_map = {x["slot"]: x["name"] for x in json.loads(m.group(0))} if m else {}
        except Exception as e:
            log.warning("解析聊天列表失败: %s" % e)
    for s in slots:
        name = slot_map.get(s, "槽位%d" % s)
        log_inbox("新消息 来自 %s" % name)
        if not any(w and (w in name or name in w) for w in CFG["whitelist"]):
            log.info("跳过非白名单: %s" % name)
            continue
        if not brain_ready():
            log.info("观察模式,无大脑,不操作: %s" % name)
            continue
        # 消息合并去抖(学自 WXAUTO_SE):等突发的一串消息到齐再读,避免逐条回复
        time.sleep(CFG.get("merge_wait", 8))
        y = c["slot_y0"] + s * c["slot_dy"]
        click(c["slot_click_x"], y, 1.5)          # 点开该会话
        info = read_conversation()
        if not info or not info.get("messages"):
            continue
        real_name = info.get("chat_name", "")
        if real_name and CFG.get("verify_chat_name", True) and \
           real_name not in name and name not in real_name:
            log.warning("窗口标题(%s)与预期(%s)不符,放弃回复" % (real_name, name))
            continue
        if not group_needs_reply(info.get("chat_name"), info.get("messages", [])):
            log.info("群内未被@本号,跳过: %s" % info.get("chat_name"))
            continue
        last_them = next((m["text"] for m in reversed(info.get("messages", []))
                          if m["from"] == "them"), "")
        sched = maybe_schedule(last_them, info.get("chat_name") or "")
        if sched:
            send_text(sched)
            log_inbox("定时任务已设定: %s" % sched)
            continue
        if not rate_ok():
            log.warning("超时速率限制,跳过回复 %s" % name)
            continue
        reply = compose_reply(info)
        mode = CFG["mode"]
        if mode == "draft" or in_quiet_hours():
            log_inbox("草稿(%s%s): %s" % (name, " 静默时段" if in_quiet_hours() else "", reply))
            log.info("草稿模式,未发送")
            continue
        send_text(reply)
        RATE["count"] += 1
        log_inbox("已回复 %s: %s" % (name, reply))
        time.sleep(1)

def expand_pinned_if_collapsed(img):
    """列表被折叠(显示 N pinned chats)时点开展开,否则找不到 File Transfer"""
    try:
        ans = vision("这是微信聊天列表顶部一小块截图。如果里面有「pinned chats」字样,"
                     "只输出FOUND,否则只输出NO。", img.crop((60, 240, 300, 285)))
        if "FOUND" in ans.upper():
            click(160, 260, 1.0)
            time.sleep(0.8)
            log.info("已展开置顶聊天")
            return True
    except Exception as e:
        log.warning("检查折叠条失败: %s" % e)
    return False

def _ft_icon_ref():
    return os.path.join(BASE, "ft_icon_ref.png")

def save_ft_template(img, y_top):
    """标题核验成功后把该图标存为参考模板(自学习),供后续模板匹配择优"""
    try:
        img.crop((74, y_top, 110, y_top + 36)).save(_ft_icon_ref())
        log.info("FT 图标参考模板已更新")
    except Exception:
        log.warning("FT 模板保存失败", exc_info=True)

def find_green_icon_y(img):
    """聊天列表图标列找 File Transfer 图标。候选=绿圈+白箭头双特征(green>250,white>250);
    存在参考模板时按 9x9 缩略图最小距离择优(修颜色质量误配,坑#2),无模板取最底部候选。"""
    c = CFG["coords"]
    px = img.load()
    cands = []
    y_cap = min(c["list_y1"] - 44, 826)          # 避开底部 pinned chats 开关区
    for y in range(c["list_y0"], y_cap, 2):
        green = white = 0
        for yy in range(y, y + 36):
            for xx in range(74, 110):
                r, g, b = px[xx, yy][:3]
                if r < 80 and g > 160 and 60 < b < 140:
                    green += 1
                elif r > 220 and g > 220 and b > 220:
                    white += 1
        if green > 250 and white > 250:
            cands.append(y)
    if not cands:
        return None
    ref_path = _ft_icon_ref()
    if os.path.exists(ref_path):
        try:
            ref = Image.open(ref_path).convert("RGB").resize((9, 9))
            ref_data = list(ref.getdata())
            best, best_d = None, None
            for y in cands:
                for dy in (0, -2, 2):                # 容忍1-2px行偏移
                    yy = y + dy
                    if yy < c["list_y0"] or yy + 36 > 870:
                        continue
                    patch = img.crop((74, yy, 110, yy + 36)).convert("RGB").resize((9, 9))
                    d = sum((a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2
                            for a, b in zip(patch.getdata(), ref_data))
                    if best_d is None or d < best_d:
                        best, best_d = yy, d
            if best_d is None or best_d > 100000:    # 校准:真身<10万(含微移),误配270万+
                log.warning("FT 模板匹配距离过大(%s),疑似列表异常,跳过" % best_d)
                return None
            log.info("FT 图标模板匹配: 候选%s 取 y=%s (距离%s)" % (cands[:5], best, best_d))
            return best + 18
        except Exception:
            log.warning("模板匹配异常,回退颜色规则", exc_info=True)
    return cands[-1] + 18

def open_chat_from_list(name):
    """在聊天列表里用视觉找到目标会话并点开(适用于搜索索引搜不到的内置会话如 File Transfer)"""
    c = CFG["coords"]
    img = scrot()
    try:
        ans = vision("这是微信聊天列表截图。找到名字为「%s」的会话条目,返回它的头像中心坐标,"
                     "格式 JSON: {\"x\":整数,\"y\":整数,\"found\":true/false}。"
                     "坐标以图片左上角为原点,图片宽240高840。" % name, list_region(img))
        m = re.search(r"\{[^{}]*\"x\"[^{}]*\}", ans, re.S)
        if not m:
            return False
        pos = json.loads(m.group(0))
        if not pos.get("found"):
            log.warning("列表中未找到 %s" % name)
            return False
        click(int(pos["x"]) + c["list_x0"], int(pos["y"]) + c["list_y0"], 1.5)
    except Exception as e:
        log.warning("列表定位异常: %s" % e)
        return False
    header = chat_header_name()
    ok = header_matches(header, name)
    if not ok:
        log.warning("点开的会话标题(%s)与目标(%s)不符,中止" % (header, name))
    return ok

def heartbeat():
    hb = CFG.get("heartbeat_chat")
    if not hb or not brain_ready():
        return                                   # 没有大脑时无法核验目标,不发,防误发
    hb_file = os.path.join(BASE, "last_hb")
    try:
        since = time.time() - os.path.getmtime(hb_file)
    except OSError:
        since = CFG["heartbeat_interval_min"] * 60
    if since < CFG["heartbeat_interval_min"] * 60 - 120:
        return                                   # 未到期。上次心跳时间持久化到文件,
                                                 # 服务重启不再重发(实测重启曾连发3条骚扰)
    if not ensure_window():
        return
    img = scrot()
    expand_pinned_if_collapsed(img)
    img = scrot()
    if hb.lower() in ("file transfer", "文件传输助手"):
        gy = find_green_icon_y(img)
        if gy is None:
            log.warning("未找到 File Transfer 绿色图标,跳过心跳")
            return
        click(91, gy, 2.0)                       # 点图标中心,避开下方折叠开关
        click_y_top = gy - 18
    elif not (open_chat_from_list(hb) or open_chat_via_search(hb)):
        click_y_top = None
        return
    header = chat_header_name()
    if hb.lower() not in header.lower():
        log.warning("心跳目标核验失败(标题:%s),不发送" % header)
        return
    try:
        if click_y_top is not None:
            # 必须用点击前的那张 img:点击后列表会重排(FT 跳到顶部),旧坐标处已不是 FT
            save_ft_template(img, click_y_top)
    except Exception:
        pass
    free = sh("free -m | awk '/Mem:/{print $7}'").stdout.decode().strip()
    send_text("〔自动心跳〕Agent在线 ✓ 可用内存%sMB 时间%s" % (free, datetime.now().strftime("%m-%d %H:%M")))
    open(hb_file, "w").write(datetime.now().isoformat())
    log.info("心跳已发")

# ---------------- 主循环 ----------------
def main():
    ensure_window()
    prev = None
    red_state = {}
    log.info("Agent启动 mode=%s brain=%s" % (CFG["mode"], "GLM" if brain_ready() else "无(观察)"))
    while True:
        try:
            if os.path.exists(PAUSE):
                prev = None
                time.sleep(3)
                continue
            if CFG["mode"] == "observe" and not brain_ready():
                pass  # 观察模式仍然盯屏记录
            if not ensure_window():
                prev = None                      # 未登录/渲染坏:不监控,等自愈
                time.sleep(8)
                continue
            img = scrot()
            cur = img_hash(list_region(img))
            if prev is not None and cur != prev:
                slots = [i for i in range(CFG["slot_count"]) if red_score(img, i) > CFG["red_threshold"]]
                fresh = [s for s in slots if red_state.get(s, 0) == 0]
                if fresh:
                    log.info("检测到新消息槽位: %s" % fresh)
                    handle_trigger(fresh, img)
                for s in slots:
                    red_state[s] = 1
                for k in [s for s in red_state if s not in slots]:
                    red_state[k] = 0
                prev = cur
            elif prev is None:
                prev = cur
            heartbeat()                              # 内部按 last_hb 文件到期判定,重启不重发
            run_due_tasks()                          # 定时任务到期即发
        except Exception:
            log.exception("循环异常")
            time.sleep(5)
        time.sleep(CFG["poll_interval"])

def cli_send(name, text):
    if not ensure_window():
        log.error("微信窗口未就绪(登录/渲染),未发送")
        return
    if not (open_chat_from_list(name) or open_chat_via_search(name)):
        log.error("无法核验目标会话 %s,未发送" % name)
        return
    send_text(text)
    log_inbox("CLI发送 %s: %s" % (name, text))

if __name__ == "__main__":
    if len(sys.argv) >= 4 and sys.argv[1] == "send":
        cli_send(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 2 and sys.argv[1] == "once":
        img = scrot(); ensure_window()
        slots = [i for i in range(CFG["slot_count"]) if red_score(img, i) > CFG["red_threshold"]]
        print("红点槽位:", slots)
        handle_trigger(slots, img)
    else:
        main()
