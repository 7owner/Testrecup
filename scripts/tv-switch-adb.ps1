param(
  [string]$TvSerial = "",
  [string]$DashboardUrl = "http://192.168.43.118:8080",
  [int]$IntervalSeconds = 40,
  [string]$HdmiInputId = "",
  [int]$HdmiMenuIndex = 4,
  [switch]$StartOnWeb
)

function Invoke-Adb {
  param([string[]]$Args)
  if ([string]::IsNullOrWhiteSpace($TvSerial)) {
    & adb @Args
  } else {
    & adb -s $TvSerial @Args
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

if (-not (Get-Command adb -ErrorAction SilentlyContinue)) {
  Write-Error "adb introuvable. Installe Android Platform Tools et ajoute adb au PATH."
  exit 1
}

Write-Host "=== TV Auto Switch (Android TV via ADB) ==="
Write-Host "Intervalle: $IntervalSeconds s"
Write-Host "URL: $DashboardUrl"
if ($TvSerial) { Write-Host "TV serial: $TvSerial" }
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

