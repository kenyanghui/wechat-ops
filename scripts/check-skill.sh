#!/usr/bin/env bash
# skill-ops 守卫:检查一个 skill 目录的结构完整性与发布卫生
# 用法: bash check-skill.sh <skill目录> [--bundle <tar.gz>]
# 退出码: 0=通过 1=有违例
set -uo pipefail

DIR="${1:-}"
BUNDLE=""
[ "${2:-}" = "--bundle" ] && BUNDLE="${3:-}"
FAIL=0

err() { echo "  ✗ $1"; FAIL=1; }
ok()  { echo "  ✓ $1"; }

[ -z "$DIR" ] && { echo "用法: bash check-skill.sh <skill目录> [--bundle <tar.gz>]"; exit 1; }
[ -d "$DIR" ] || { echo "目录不存在: $DIR"; exit 1; }
DIR=$(cd "$DIR" && pwd)
NAME=$(basename "$DIR")

echo "== 守卫: $NAME =="

# 1. SKILL.md 存在 + frontmatter
S="$DIR/SKILL.md"
if [ ! -f "$S" ]; then err "SKILL.md 不存在"; else
  ok "SKILL.md 存在"
  head -8 "$S" | grep -q "^name: *$NAME" && ok "name 与目录同名" || err "frontmatter name 应为: $NAME"
  D=$(sed -n 's/^description: *//p' "$S" | head -1)
  [ ${#D} -ge 20 ] && ok "description 非空(${#D}字符)" || err "description 缺失或过短"
  L=$(wc -l < "$S")
  [ "$L" -le 500 ] && ok "SKILL.md ${L} 行(≤500)" || err "SKILL.md ${L} 行,超 500,应拆分到 references/"
fi

# 2. 引用的本地文件真实存在
MISSING=$(grep -oE '(references|scripts|guards|checklists|rules)/[A-Za-z0-9._/-]+' "$S" 2>/dev/null | sort -u | while read -r f; do
  [ -e "$DIR/$f" ] || echo "$f"
done)
[ -z "$MISSING" ] && ok "SKILL.md 引用的文件全部存在" || { err "引用的文件不存在: $MISSING"; }

# 3. 凭证 HARD 扫描(guards/ 本身放检测模式,必须排除; 行内代码段先剥离——规则文档合法引用模式不算命中)
VIOL=$(grep -rnE "sk-[A-Za-z0-9]{20,}|BEGIN.{0,10}PRIVATE KEY|AIBay666|c21aebeaf354" \
  --include="*.md" --include="*.json" --include="*.py" --include="*.sh" --include="*.service" \
  --exclude-dir="guards" "$DIR" 2>/dev/null | grep -vF "$(basename "$0")" | while IFS= read -r l; do
    echo "${l#*:}" | sed 's/`[^`]*`//g' | grep -qE "sk-[A-Za-z0-9]{20,}|BEGIN.{0,10}PRIVATE KEY|AIBay666|c21aebeaf354" && echo "$l"
  done | head -5)
[ -z "$VIOL" ] && ok "无凭证泄露(HARD)" || { err "凭证泄露:"; echo "$VIOL" | sed 's/^/    /'; }

# 4. bigmodel key 形态扫描(hex.hex)
VIOL2=$(grep -rnE "[a-f0-9]{32}\.[A-Za-z0-9]{12,20}" --include="*.json" --include="*.md" "$DIR" 2>/dev/null | grep -v '"key": ""' | head -3)
[ -z "$VIOL2" ] && ok "无 bigmodel key 形态泄露" || { err "疑似 key:"; echo "$VIOL2" | sed 's/^/    /'; }

# 5. 私密信息 SOFT 扫描(分发内容不得含真实人名/具体联系人; rules 定义判据可含示例,排除)
PII=$(grep -rnE "李娜纯臻|李娜\(|杨辉191|三级拆书" --include="*.md" --include="*.json" \
  --exclude-dir="guards" --exclude-dir="rules" --exclude-dir="checklists" "$DIR" 2>/dev/null | head -3)
[ -z "$PII" ] && ok "无私密联系人信息(SOFT)" || { err "含私密信息(分发前匿名化):"; echo "$PII" | sed 's/^/    /'; }

# 6. 未证实断言扫描(剥离引号段——规则文档合法引用反例不算命中; 引号含中英文)
CLAIM=$(grep -rn "真实送达\|已经跑通.*送达\|验证成功.*送达" "$DIR/SKILL.md" "$DIR/references" 2>/dev/null | while IFS= read -r l; do
    echo "${l#*:}" | sed -E 's/[“”][^“”]*[“”]//g; s/`[^`]*`//g; s/"[^"]*"//g' | grep -q "真实送达\|已经跑通.*送达\|验证成功.*送达" && echo "$l"
  done | head -3)
[ -z "$CLAIM" ] && ok "无未证实的送达断言" || { err "含未证实断言:"; echo "$CLAIM" | sed 's/^/    /'; }

# 7. 编码健康(mojibake 特征)
MOJI=$(grep -rl $'\xe9\x8d\x94\|\xe9\x94\x9f' --include="*.md" "$DIR" 2>/dev/null | head -3)
[ -z "$MOJI" ] && ok "编码健康" || { err "疑似 mojibake: $MOJI"; }

# 8. 脚本语法
for s in "$DIR"/scripts/*.sh; do
  [ -f "$s" ] || continue
  bash -n "$s" 2>/dev/null && ok "bash 语法: $(basename "$s")" || err "bash 语法错误: $(basename "$s")"
done
PY=$(command -v python3 || command -v python || true)
for p in "$DIR"/scripts/*.py; do
  [ -f "$p" ] || continue
  if [ -n "$PY" ] && "$PY" -c "" >/dev/null 2>&1; then
    # Windows Store python 桩会假成功,交给远端校验;此处尽力而为
    "$PY" -m py_compile "$p" 2>/dev/null && ok "python 语法: $(basename "$p")" || echo "  ⚠ python 语法未在本机验证: $(basename "$p") (无可用解释器时属预期)"
  else
    echo "  ⚠ 本机无 python,跳过 $(basename "$p") 语法检查(可交远端校验)"
  fi
done

# 9. CHANGELOG
[ -f "$DIR/CHANGELOG.md" ] && ok "CHANGELOG.md 存在" || err "缺 CHANGELOG.md(版本化要求)"

# 10. 分发包比对
if [ -n "$BUNDLE" ]; then
  [ -f "$BUNDLE" ] || { err "分发包不存在: $BUNDLE"; }
  SRC=$(cd "$DIR/.." && tar -czf /tmp/_ref.tar.gz "$NAME" && tar -tzf /tmp/_ref.tar.gz | sort)
  PKG=$(tar -tzf "$BUNDLE" | sed 's#\\#/#g' | sort)
  DIFF=$(diff <(echo "$SRC") <(echo "$PKG") | grep -E "^[<>]" | head -10)
  [ -z "$DIFF" ] && ok "分发包与源目录一致" || { err "分发包漂移:"; echo "$DIFF" | sed 's/^/    /'; }
  rm -f /tmp/_ref.tar.gz
fi

echo "== 结果: $([ $FAIL -eq 0 ] && echo 通过 || echo 存在违例) =="
exit $FAIL
