# 把 loki-pet 安装/同步为 Agent Skill (~/.claude/skills/loki-pet)
# 用法: powershell -ExecutionPolicy Bypass -File install_skill.ps1 [-WithEmotes]
param(
    [switch]$WithEmotes  # 同时同步 assets/emotes 下已转换的表情(体积较大)
)

$src = $PSScriptRoot
$dst = Join-Path $env:USERPROFILE ".claude\skills\loki-pet"

New-Item -ItemType Directory -Force $dst | Out-Null
New-Item -ItemType Directory -Force "$dst\assets" | Out-Null

# 程序与 skill 定义
Copy-Item "$src\pet.py", "$src\emote_studio.py", "$src\hook_bridge.py", "$src\mail_notify.py", "$src\requirements.txt" $dst -Force
Copy-Item "$src\skill\SKILL.md" $dst -Force
# config.json 仅在目标不存在时写入,避免覆盖用户已有配置
if (-not (Test-Path "$dst\config.json")) {
    Copy-Item "$src\skill\config.json" $dst
}

# 素材
Copy-Item "$src\assets\loki.png" "$dst\assets" -Force
if (Test-Path "$src\assets\sounds") {
    Copy-Item "$src\assets\sounds" "$dst\assets" -Recurse -Force
}
if ($WithEmotes -and (Test-Path "$src\assets\emotes")) {
    Copy-Item "$src\assets\emotes" "$dst\assets" -Recurse -Force
}

Write-Host "已安装到 $dst"
Write-Host "其他支持 Agent Skills 的工具,把该目录拷到其 skills 目录即可。"
