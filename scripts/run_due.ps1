$ErrorActionPreference = 'Stop'
$SkillRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$ReportDir = Join-Path $SkillRoot 'reports'
New-Item -ItemType Directory -Force -Path $ReportDir | Out-Null
$Output = & py -3 (Join-Path $SkillRoot 'scripts\maintainer.py') run --due 2>&1
$Output | Out-File -FilePath (Join-Path $ReportDir 'scheduler.log') -Append -Encoding utf8
exit $LASTEXITCODE
