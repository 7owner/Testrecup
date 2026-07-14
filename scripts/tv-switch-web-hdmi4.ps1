param(
  [string]$AdbPath = "C:\Users\takot\Documents\projet_AIX\platform-tools-latest-windows (1)\platform-tools\adb.exe",
  [string]$TvSerial = "192.168.43.146:5555",
  [string]$DashboardUrl = "http://192.168.43.118:8080",
  [int]$IntervalSeconds = 40
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if (-not (Test-Path $AdbPath)) {
  throw "adb introuvable: $AdbPath"
}

function Invoke-Adb {
  param([string[]]$Args)
  & $AdbPath @Args
}

function Open-Web {
  Write-Host "[TV] Ouvre page web: $DashboardUrl"
  Invoke-Adb @('-s', $TvSerial, 'shell', 'am', 'start', '-a', 'android.intent.action.VIEW', '-d', $DashboardUrl) | Out-Null
}

function Open-Hdmi4 {
  Write-Host '[TV] Switch HDMI4: Sources -> gauche (reset) -> 3x droite -> OK'

  Invoke-Adb @('-s', $TvSerial, 'shell', 'input', 'keyevent', '178') | Out-Null
  Start-Sleep -Milliseconds 900

  1..8 | ForEach-Object {
    Invoke-Adb @('-s', $TvSerial, 'shell', 'input', 'keyevent', '21') | Out-Null
    Start-Sleep -Milliseconds 100
  }

  1..3 | ForEach-Object {
    Invoke-Adb @('-s', $TvSerial, 'shell', 'input', 'keyevent', '22') | Out-Null
    Start-Sleep -Milliseconds 120
  }

  Invoke-Adb @('-s', $TvSerial, 'shell', 'input', 'keyevent', '66') | Out-Null
}

Write-Host '=== TV Auto Switch Web <-> HDMI4 ==='
Write-Host "ADB: $AdbPath"
Write-Host "TV : $TvSerial"
Write-Host "URL: $DashboardUrl"
Write-Host "Intervalle: ${IntervalSeconds}s"

Invoke-Adb @('connect', $TvSerial) | Out-Null

# Forcer le premier affichage sur la page web.
Open-Web
Start-Sleep -Seconds $IntervalSeconds

$showWeb = $false

while ($true) {
  if ($showWeb) {
    Open-Web
  } else {
    Open-Hdmi4
  }

  $showWeb = -not $showWeb
  Start-Sleep -Seconds $IntervalSeconds
}
