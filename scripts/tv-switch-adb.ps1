param(
  [string]$TvSerial = "",
  [string]$TvHost = "",
  [string]$DashboardUrl = "http://192.168.43.118:8080",
  [int]$IntervalSeconds = 40,
  [string]$HdmiInputId = "",
  [int]$HdmiMenuIndex = 4,
  [int]$HdmiKeyCode = 0,
  [int]$HdmiNavKeyCode = 22,
  [int]$HdmiNavDelayMs = 180,
  [switch]$CalibrateHdmiIndex,
  [int]$CalibMinIndex = 3,
  [int]$CalibMaxIndex = 8,
  [string]$AdbPath = "",
  [switch]$OpenWebOnly,
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
$script:FlagFile = Join-Path $PSScriptRoot ".hdmi-menu-index.flag"
$script:DetectedHdmiMenuIndex = $null

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
  $serial = ""
  if (-not [string]::IsNullOrWhiteSpace($script:TargetSerial)) {
    $serial = $script:TargetSerial
  } elseif (-not [string]::IsNullOrWhiteSpace($TvSerial)) {
    $serial = $TvSerial
  }

  # Meme forme que la commande manuelle qui fonctionne.
  $argList = @()
  if (-not [string]::IsNullOrWhiteSpace($serial)) {
    $argList += @("-s", $serial)
  }
  $argList += @("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", $Url)
  Start-Process -FilePath $script:AdbExe -ArgumentList $argList -NoNewWindow -Wait
}

function Open-Hdmi4 {
  $targetIndex = $HdmiMenuIndex
  if ($script:DetectedHdmiMenuIndex) {
    $targetIndex = [int]$script:DetectedHdmiMenuIndex
  }

  if (-not [string]::IsNullOrWhiteSpace($HdmiInputId)) {
    $passthroughUri = "content://android.media.tv/passthrough/$HdmiInputId"
    Write-Host "[TV] Switch HDMI via inputId: $HdmiInputId"
    $serial = ""
    if (-not [string]::IsNullOrWhiteSpace($script:TargetSerial)) {
      $serial = $script:TargetSerial
    } elseif (-not [string]::IsNullOrWhiteSpace($TvSerial)) {
      $serial = $TvSerial
    }
    $argList = @()
    if (-not [string]::IsNullOrWhiteSpace($serial)) {
      $argList += @("-s", $serial)
    }
    $argList += @("shell", "am", "start", "-a", "android.intent.action.VIEW", "-d", $passthroughUri)
    Start-Process -FilePath $script:AdbExe -ArgumentList $argList -NoNewWindow -Wait
    return
  }

  if ($HdmiKeyCode -ge 243 -and $HdmiKeyCode -le 246) {
    Write-Host "[TV] Switch HDMI via keycode: $HdmiKeyCode"
    $serial = ""
    if (-not [string]::IsNullOrWhiteSpace($script:TargetSerial)) {
      $serial = $script:TargetSerial
    } elseif (-not [string]::IsNullOrWhiteSpace($TvSerial)) {
      $serial = $TvSerial
    }
    $argList = @()
    if (-not [string]::IsNullOrWhiteSpace($serial)) {
      $argList += @("-s", $serial)
    }
    $argList += @("shell", "input", "keyevent", "$HdmiKeyCode")
    Start-Process -FilePath $script:AdbExe -ArgumentList $argList -NoNewWindow -Wait
    return
  }

  Write-Host "[TV] Switch HDMI via menu INPUT (fallback)"
  $serial = ""
  if (-not [string]::IsNullOrWhiteSpace($script:TargetSerial)) {
    $serial = $script:TargetSerial
  } elseif (-not [string]::IsNullOrWhiteSpace($TvSerial)) {
    $serial = $TvSerial
  }
  # KEYCODE_TV_INPUT = 178
  $argInput = if ([string]::IsNullOrWhiteSpace($serial)) {
    @("shell", "input", "keyevent", "178")
  } else {
    @("-s", $serial, "shell", "input", "keyevent", "178")
  }
  Start-Process -FilePath $script:AdbExe -ArgumentList $argInput -NoNewWindow -Wait
  Start-Sleep -Milliseconds 900

  # Navigation menu source (ex: RIGHT=22, DOWN=20) puis valider
  for ($i = 1; $i -lt $targetIndex; $i++) {
    $argNav = if ([string]::IsNullOrWhiteSpace($serial)) {
      @("shell", "input", "keyevent", "$HdmiNavKeyCode")
    } else {
      @("-s", $serial, "shell", "input", "keyevent", "$HdmiNavKeyCode")
    }
    Start-Process -FilePath $script:AdbExe -ArgumentList $argNav -NoNewWindow -Wait
    Start-Sleep -Milliseconds $HdmiNavDelayMs
  }
  # KEYCODE_ENTER = 66
  $argEnter = if ([string]::IsNullOrWhiteSpace($serial)) {
    @("shell", "input", "keyevent", "66")
  } else {
    @("-s", $serial, "shell", "input", "keyevent", "66")
  }
  Start-Process -FilePath $script:AdbExe -ArgumentList $argEnter -NoNewWindow -Wait
}

function Load-HdmiMenuIndexFlag {
  if (Test-Path $script:FlagFile) {
    try {
      $v = Get-Content $script:FlagFile -Raw
      $n = [int]($v.Trim())
      if ($n -ge 1) {
        $script:DetectedHdmiMenuIndex = $n
      }
    } catch {
      # ignore
    }
  }
}

function Save-HdmiMenuIndexFlag {
  param([int]$Index)
  try {
    Set-Content -Path $script:FlagFile -Value "$Index" -Encoding utf8
    $script:DetectedHdmiMenuIndex = $Index
  } catch {
    # ignore
  }
}

function Calibrate-HdmiMenuIndex {
  $min = [Math]::Max(1, $CalibMinIndex)
  $max = [Math]::Max($min, $CalibMaxIndex)
  Write-Host "Calibration HDMI menu index: test de $min a $max"
  Write-Host "Regarde la TV et repond: y = bon index, n = suivant, q = quitter"

  for ($idx = $min; $idx -le $max; $idx++) {
    Write-Host "[CALIB] Test index $idx"
    $script:DetectedHdmiMenuIndex = $idx
    Open-Hdmi4
    Start-Sleep -Milliseconds 1200
    Write-Host "[CALIB] HDMI cible affiche sur TV? (y/n/q)"
    $ans = ''
    try {
      $ans = [System.Console]::ReadKey($true).KeyChar
      Write-Host ("[CALIB] touche: " + $ans)
    } catch {
      $ans = Read-Host
    }

    if ([string]$ans -match '^[Yy]') {
      Save-HdmiMenuIndexFlag -Index $idx
      Write-Host "[CALIB] Index memorise: $idx"
      return $true
    }
    if ([string]$ans -match '^[Qq]') {
      Write-Host "[CALIB] Annulee"
      return $false
    }
  }
  Write-Host "[CALIB] Aucun index valide trouve dans la plage testee."
  return $false
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

Load-HdmiMenuIndexFlag
if ($script:DetectedHdmiMenuIndex) {
  Write-Host "Index HDMI memorise: $script:DetectedHdmiMenuIndex"
}

if ($HdmiInputId) {
  Write-Host "Mode HDMI: inputId direct ($HdmiInputId)"
} else {
  $displayIndex = if ($script:DetectedHdmiMenuIndex) { $script:DetectedHdmiMenuIndex } else { $HdmiMenuIndex }
  Write-Host "Mode HDMI: menu INPUT fallback (index HDMI=$displayIndex, navKey=$HdmiNavKeyCode)"
  Write-Host "Astuce: pour un switch direct, recupere l'ID avec: adb shell cmd tv_input list"
}

if ($CalibrateHdmiIndex -and [string]::IsNullOrWhiteSpace($HdmiInputId) -and -not ($HdmiKeyCode -ge 243 -and $HdmiKeyCode -le 246)) {
  Calibrate-HdmiMenuIndex | Out-Null
}

if ($OpenWebOnly) {
  Open-Web -Url $DashboardUrl
  Write-Host "[TV] Mode OpenWebOnly: fin (pas de boucle, pas de switch)."
  exit 0
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
