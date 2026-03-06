param(
  [string]$TvSerial = "",
  [string]$TvHost = "",
  [string]$DashboardUrl = "http://192.168.43.118:8080",
  [int]$IntervalSeconds = 40,
  [string]$HdmiInputId = "",
  [int]$HdmiMenuIndex = 4,
  [int]$HdmiKeyCode = 0,
  [string]$AdbPath = "",
  [switch]$StartOnWeb
)

function Resolve-AdbPath {
  if (-not [string]::IsNullOrWhiteSpace($AdbPath) -and (Test-Path $AdbPath)) {
    return (Resolve-Path $AdbPath).Path
  }

  $cmd = Get-Command adb -ErrorAction SilentlyContinue
  if ($cmd) {
    return $cmd.Path
  }

  $repoRoot = Split-Path -Parent $PSScriptRoot
  $candidates = @(
    (Join-Path $repoRoot "platform-tools\adb.exe"),
    (Join-Path $repoRoot "platform-tools-latest-windows\platform-tools\adb.exe"),
    (Join-Path $repoRoot "platform-tools-latest-windows (1)\platform-tools\adb.exe")
  )

  foreach ($c in $candidates) {
    if (Test-Path $c) {
      return (Resolve-Path $c).Path
    }
  }

  $auto = Get-ChildItem -Path $repoRoot -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -like "platform-tools*" } |
    ForEach-Object {
      Join-Path $_.FullName "platform-tools\adb.exe"
    } |
    Where-Object { Test-Path $_ } |
    Select-Object -First 1

  if ($auto) {
    return (Resolve-Path $auto).Path
  }

  return $null
}

$script:AdbExe = Resolve-AdbPath
$script:TargetSerial = ""

function Invoke-Adb {
  param([string[]]$Args)
  if (-not $script:AdbExe) {
    throw "adb introuvable"
  }
  $serial = ""
  if (-not [string]::IsNullOrWhiteSpace($script:TargetSerial)) {
    $serial = $script:TargetSerial
  } elseif (-not [string]::IsNullOrWhiteSpace($TvSerial)) {
    $serial = $TvSerial
  }

  if ([string]::IsNullOrWhiteSpace($serial)) {
    & $script:AdbExe @Args
  } else {
    & $script:AdbExe -s $serial @Args
  }
}

function Open-Web {
  param([string]$Url)
  Write-Host "[TV] Ouverture URL: $Url"
  Invoke-Adb @("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", $Url) | Out-Null
}

function Open-Hdmi4 {
  if (-not [string]::IsNullOrWhiteSpace($HdmiInputId)) {
    $passthroughUri = "content://android.media.tv/passthrough/$HdmiInputId"
    Write-Host "[TV] Switch HDMI via inputId: $HdmiInputId"
    Invoke-Adb @("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", $passthroughUri) | Out-Null
    return
  }

  if ($HdmiKeyCode -ge 243 -and $HdmiKeyCode -le 246) {
    Write-Host "[TV] Switch HDMI via keycode: $HdmiKeyCode"
    Invoke-Adb @("shell", "input", "keyevent", "$HdmiKeyCode") | Out-Null
    return
  }

  Write-Host "[TV] Switch HDMI via menu INPUT (fallback)"
  # KEYCODE_TV_INPUT = 178
  Invoke-Adb @("shell", "input", "keyevent", "178") | Out-Null
  Start-Sleep -Milliseconds 900

  # Navigation menu source: descendre jusqu'a HDMI4 puis valider
  for ($i = 1; $i -lt $HdmiMenuIndex; $i++) {
    # KEYCODE_DPAD_DOWN = 20
    Invoke-Adb @("shell", "input", "keyevent", "20") | Out-Null
    Start-Sleep -Milliseconds 150
  }
  # KEYCODE_ENTER = 66
  Invoke-Adb @("shell", "input", "keyevent", "66") | Out-Null
}

if (-not $script:AdbExe) {
  Write-Error "adb introuvable. Ajoute platform-tools (adb.exe) ou passe -AdbPath."
  exit 1
}

Write-Host "=== TV Auto Switch (Android TV via ADB) ==="
Write-Host "ADB: $script:AdbExe"
Write-Host "Intervalle: $IntervalSeconds s"
Write-Host "URL: $DashboardUrl"
if ($TvSerial) { Write-Host "TV serial: $TvSerial" }

if ($TvHost) {
  Write-Host "[TV] adb connect $TvHost"
  & $script:AdbExe connect $TvHost | Out-Null
  if ([string]::IsNullOrWhiteSpace($TvSerial)) {
    $script:TargetSerial = $TvHost
  }
}

if ($HdmiInputId) {
  Write-Host "Mode HDMI: inputId direct ($HdmiInputId)"
} else {
  Write-Host "Mode HDMI: menu INPUT fallback (index HDMI=$HdmiMenuIndex)"
  Write-Host "Astuce: pour un switch direct, recupere l'ID avec: adb shell cmd tv_input list"
}

$showWeb = $StartOnWeb.IsPresent

while ($true) {
  if ($showWeb) {
    Open-Web -Url $DashboardUrl
  } else {
    Open-Hdmi4
  }

  $showWeb = -not $showWeb
  Start-Sleep -Seconds $IntervalSeconds
}
