# E:\DS公作区\tools\lab\lab.ps1
# Lab shell helpers: py / pyq / js
#   - auto-selects the nearest .venv\Scripts\python.exe walking up from the script
#   - falls back to the DSH runtime python
#   - always sets PYTHONIOENCODING=utf-8
#   - pyq prints only the last 25 lines (the "[exit N]" tail is kept)
#
# Usage:
#   . E:\DS公作区\tools\lab\lab.ps1
#   py  tools/gh-login/_verify_trap.py
#   pyq 自进化/audit_ssot.py
#   js  tools/gh-login/_asar_read.cjs "dsh/node_modules/x/README.md"
#
# All comments are ASCII on purpose: .ps1 files must stay BOM-safe for PS 5.1.

$script:LabRoot  = 'E:\DS公作区'
$script:LabSysPy = 'C:\Users\Administrator\.dsh\dsh-runtimes\dsh-plugin-desktop-primary-runtime\dependencies\python\python.exe'

function Resolve-LabPath {
  param([string]$Path)
  if ([System.IO.Path]::IsPathRooted($Path)) { return $Path }
  return (Join-Path $script:LabRoot $Path)
}

function Find-LabVenv {
  param([string]$StartDir)
  if (-not $StartDir) { return $null }
  $d = Get-Item -LiteralPath $StartDir -ErrorAction SilentlyContinue
  while ($null -ne $d) {
    $cand = Join-Path (Join-Path $d.FullName '.venv') 'Scripts\python.exe'
    if (Test-Path -LiteralPath $cand) { return $cand }
    if ($d.FullName -eq $script:LabRoot) { return $null }
    if ($null -eq $d.Parent) { return $null }
    $d = $d.Parent
  }
  return $null
}

function Invoke-LabRun {
  param(
    [string]$Exe,
    [string]$Target,
    [string[]]$Rest,
    [int]$Tail,
    [string]$Label
  )
  $env:PYTHONIOENCODING = 'utf-8'
  if (-not (Test-Path -LiteralPath $Target)) {
    Write-Host ("[FAIL:capability-missing] target not found -> " + $Target) -ForegroundColor Red
    return 1
  }
  $argv = @($Target)
  if ($null -ne $Rest -and $Rest.Count -gt 0) { $argv += $Rest }
  if ($Tail -gt 0) {
    & $Exe @argv 2>&1 | Select-Object -Last $Tail
  } else {
    & $Exe @argv
  }
  $code = $LASTEXITCODE
  if ($code -ne 0 -and $null -ne $code) {
    Write-Host ("[exit " + $code + "] " + $Label) -ForegroundColor Yellow
  }
  return $code
}

function py {
  param(
    [Parameter(Mandatory, Position = 0)][string]$Script,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest
  )
  $p = Resolve-LabPath $Script
  $exe = Find-LabVenv (Split-Path -Parent $p)
  if (-not $exe) { $exe = $script:LabSysPy }
  return Invoke-LabRun -Exe $exe -Target $p -Rest $Rest -Tail 0 -Label 'py'
}

function pyq {
  param(
    [Parameter(Mandatory, Position = 0)][string]$Script,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest
  )
  $p = Resolve-LabPath $Script
  $exe = Find-LabVenv (Split-Path -Parent $p)
  if (-not $exe) { $exe = $script:LabSysPy }
  return Invoke-LabRun -Exe $exe -Target $p -Rest $Rest -Tail 25 -Label 'pyq'
}

function js {
  param(
    [Parameter(Mandatory, Position = 0)][string]$Script,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest
  )
  $p = Resolve-LabPath $Script
  return Invoke-LabRun -Exe 'node' -Target $p -Rest $Rest -Tail 0 -Label 'js'
}

function jsq {
  param(
    [Parameter(Mandatory, Position = 0)][string]$Script,
    [Parameter(Position = 1, ValueFromRemainingArguments = $true)][string[]]$Rest
  )
  $p = Resolve-LabPath $Script
  return Invoke-LabRun -Exe 'node' -Target $p -Rest $Rest -Tail 25 -Label 'jsq'
}

Write-Host ("[lab] ready  root=" + $script:LabRoot)
