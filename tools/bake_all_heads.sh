#!/bin/bash
# 把多个 PMX 各烘成一个可切换头模：Resources/heads/<id>/head.fch + 同目录纹理。
# 用法：bash tools/bake_all_heads.sh
set -u
BL=/Applications/Blender.app/Contents/MacOS/Blender
SRC="/Users/bytedance/Downloads/Reika 18"
ROOT="/Users/bytedance/work/mytest/facecap_ios"
LOG="$ROOT/tools/bake_all.log"
: > "$LOG"

# id:文件名（id 即头模显示名，也是 bundle 子目录名）
MODELS=(
  "Children:Reika18_Children.pmx"
  "Office:Reika18_Office.pmx"
  "AC:Reika18_AC.pmx"
  "inase:Reika_inase.pmx"
  "Remake:Reika18_Remake.pmx"
)

for entry in "${MODELS[@]}"; do
  id="${entry%%:*}"; pmx="${entry#*:}"
  out="$ROOT/Resources/heads/$id"
  mkdir -p "$out"
  echo "========== BAKING $id ($pmx) ==========" | tee -a "$LOG"
  if [ ! -f "$SRC/$pmx" ]; then
    echo "MISSING PMX: $SRC/$pmx" | tee -a "$LOG"
    continue
  fi
  "$BL" --background --python "$ROOT/tools/bake_head_from_pmx.py" -- "$SRC/$pmx" "$out" >> "$LOG" 2>&1
  if [ -f "$out/head.fch" ]; then
    sz=$(stat -f%z "$out/head.fch")
    ntex=$(ls "$out" | grep -ivE '\.fch$' | wc -l | tr -d ' ')
    echo "OK $id -> head.fch ${sz}B, ${ntex} textures" | tee -a "$LOG"
  else
    echo "FAIL $id -> no head.fch (see log)" | tee -a "$LOG"
  fi
done
echo "ALL DONE" | tee -a "$LOG"
