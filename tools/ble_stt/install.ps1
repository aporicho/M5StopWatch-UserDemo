param(
    [switch]$Upgrade,
    [switch]$Uninstall,
    [switch]$PurgeModels,
    [int]$WaitForPid = 0
)

$ErrorActionPreference = "Stop"
$Repository = "aporicho/M5StopWatch-UserDemo"
$Model = if ($env:BLE_STT_MODEL) { $env:BLE_STT_MODEL } else { "medium" }
$Engine = if ($env:BLE_STT_ENGINE) { $env:BLE_STT_ENGINE } else { "auto" }
$Root = Join-Path $env:LOCALAPPDATA "M5StopWatch\ble-stt"
$BinDir = Join-Path $env:LOCALAPPDATA "M5StopWatch\bin"
$Shim = Join-Path $BinDir "ble-stt.cmd"
$CurrentFile = Join-Path $Root "current.txt"
$ModelCache = Join-Path $env:LOCALAPPDATA "M5StopWatch\Cache\ble-stt"
$Work = $null
$Target = $null
$InstallComplete = $false
$ServiceSwitchStarted = $false
$OldService = $null
$Service = $null

function Show-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Cyan
}

function Invoke-Checked([string]$File, [string[]]$Arguments) {
    & $File @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$File exited with code $LASTEXITCODE"
    }
}

if ($Uninstall) {
    if ($WaitForPid -gt 0) {
        try { Wait-Process -Id $WaitForPid -Timeout 30 -ErrorAction SilentlyContinue } catch {}
    }
    Show-Step "Removing M5StopWatch BLE STT"
    if (Test-Path $CurrentFile) {
        $Current = (Get-Content $CurrentFile -Raw).Trim()
        $Service = Join-Path $Current "source\.venv\Scripts\ble-stt-service.exe"
        if (Test-Path $Service) {
            & $Service uninstall
        }
    }
    Remove-Item $Shim -Force -ErrorAction SilentlyContinue
    if ((Test-Path $BinDir) -and -not (Get-ChildItem $BinDir -Force | Select-Object -First 1)) {
        Remove-Item $BinDir -Force -ErrorAction SilentlyContinue
    }
    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $RemainingPath = @($UserPath -split ";" | Where-Object { $_ -and $_ -ne $BinDir })
    [Environment]::SetEnvironmentVariable("Path", ($RemainingPath -join ";"), "User")
    Remove-Item $Root -Recurse -Force -ErrorAction SilentlyContinue
    if ($PurgeModels) {
        Remove-Item $ModelCache -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "[ok] Program, login service, and downloaded speech models removed."
    } else {
        Write-Host "[ok] Program and login service removed. Downloaded model caches were preserved."
    }
    exit 0
}

if ($PurgeModels) {
    throw "-PurgeModels can only be used with -Uninstall"
}

try {
    Show-Step "Checking this computer"
    $PythonExe = $null
    $PythonPrefix = @()
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
        if ($LASTEXITCODE -eq 0) {
            $PythonExe = (Get-Command py).Source
            $PythonPrefix = @("-3")
        }
    }
    if (-not $PythonExe -and (Get-Command python -ErrorAction SilentlyContinue)) {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
        if ($LASTEXITCODE -eq 0) {
            $PythonExe = (Get-Command python).Source
        }
    }
    if (-not $PythonExe) {
        if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
            throw "Python 3.10+ is required and winget is unavailable"
        }
        Show-Step "Installing Python 3.12 with winget"
        Invoke-Checked "winget" @(
            "install", "--id", "Python.Python.3.12", "--exact",
            "--accept-source-agreements", "--accept-package-agreements"
        )
        $PythonExe = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
        if (-not (Test-Path $PythonExe)) {
            throw "Python was installed but could not be located; open a new PowerShell window and retry"
        }
    }

    $Work = Join-Path ([IO.Path]::GetTempPath()) ("ble-stt-" + [guid]::NewGuid().ToString("N"))
    New-Item $Work -ItemType Directory -Force | Out-Null
    $SourceDir = $null
    if ($PSScriptRoot -and (Test-Path (Join-Path $PSScriptRoot "pyproject.toml"))) {
        $SourceDir = $PSScriptRoot
    }
    if ($env:BLE_STT_SOURCE_DIR) {
        $SourceDir = $env:BLE_STT_SOURCE_DIR
    }

    $Release = if ($env:BLE_STT_VERSION) { $env:BLE_STT_VERSION } else { "latest" }
    if (-not $SourceDir) {
        $AssetBase = if ($env:BLE_STT_ASSET_BASE) {
            $env:BLE_STT_ASSET_BASE.TrimEnd("/")
        } elseif ($Release -eq "latest") {
            "https://github.com/$Repository/releases/latest/download"
        } else {
            "https://github.com/$Repository/releases/download/$Release"
        }
        Show-Step "Downloading the stable release"
        $Archive = Join-Path $Work "source.zip"
        $Checksum = Join-Path $Work "source.zip.sha256"
        Invoke-WebRequest "$AssetBase/ble-stt-source.zip" -OutFile $Archive
        Invoke-WebRequest "$AssetBase/ble-stt-source.zip.sha256" -OutFile $Checksum
        $Expected = ((Get-Content $Checksum -Raw).Trim() -split "\s+")[0].ToLowerInvariant()
        $Actual = (Get-FileHash $Archive -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($Actual -ne $Expected) {
            throw "download checksum does not match"
        }
        Expand-Archive $Archive (Join-Path $Work "unpacked") -Force
        $SourceDir = Join-Path $Work "unpacked\ble_stt"
        if (-not (Test-Path (Join-Path $SourceDir "pyproject.toml"))) {
            throw "release archive has an unexpected layout"
        }
    }

    $Project = Get-Content (Join-Path $SourceDir "pyproject.toml") -Raw
    if ($Project -notmatch '(?m)^version = "([^"]+)"') {
        throw "could not determine the package version"
    }
    $Version = $Matches[1]
    if (Test-Path $CurrentFile) {
        $OldTarget = (Get-Content $CurrentFile -Raw).Trim()
        $OldServiceCandidate = Join-Path $OldTarget "source\.venv\Scripts\ble-stt-service.exe"
        if (Test-Path $OldServiceCandidate) {
            $OldService = $OldServiceCandidate
        }
    }
    $Target = Join-Path $Root "versions\$Version"
    if (Test-Path $Target) {
        $Target = Join-Path $Root ("versions\$Version-" + (Get-Date -Format "yyyyMMddHHmmss"))
    }
    New-Item $Target -ItemType Directory -Force | Out-Null
    $InstalledSource = Join-Path $Target "source"
    New-Item $InstalledSource -ItemType Directory -Force | Out-Null
    Get-ChildItem $SourceDir -Force |
        Where-Object { $_.Name -notin @(".venv", "__pycache__") } |
        Copy-Item -Destination $InstalledSource -Recurse -Force

    Show-Step "Installing platform components"
    & $PythonExe @PythonPrefix -m venv (Join-Path $InstalledSource ".venv")
    if ($LASTEXITCODE -ne 0) { throw "could not create the Python environment" }
    $VenvPython = Join-Path $InstalledSource ".venv\Scripts\python.exe"
    $BleStt = Join-Path $InstalledSource ".venv\Scripts\ble-stt.exe"
    $Doctor = Join-Path $InstalledSource ".venv\Scripts\ble-stt-doctor.exe"
    $Check = Join-Path $InstalledSource ".venv\Scripts\ble-stt-check.exe"
    $Service = Join-Path $InstalledSource ".venv\Scripts\ble-stt-service.exe"
    Invoke-Checked $VenvPython @("-m", "pip", "install", "--upgrade", "pip")
    Invoke-Checked $VenvPython @("-m", "pip", "install", $InstalledSource)

    Show-Step "Downloading and verifying the $Model speech model"
    Invoke-Checked $BleStt @("prepare", "--engine", $Engine, "--model", $Model)

    Show-Step "Checking input permissions"
    Invoke-Checked $Doctor @()

    $SkipTest = $env:BLE_STT_SKIP_TEST -eq "1"
    if (-not $Upgrade -and -not $SkipTest) {
        Show-Step "Connecting and testing the watch"
        while ($true) {
            & $Check
            if ($LASTEXITCODE -eq 0) { break }
            Read-Host "Open BLE Remote and complete Windows Bluetooth pairing, then press Enter to retry"
        }
        Invoke-Checked $BleStt @("test", "--engine", $Engine, "--model", $Model)
    }

    New-Item $Root -ItemType Directory -Force | Out-Null
    New-Item $BinDir -ItemType Directory -Force | Out-Null

    if ($PSScriptRoot -and (Test-Path $PSCommandPath)) {
        $SavedInstaller = Join-Path $Root "install.ps1"
        if ([IO.Path]::GetFullPath($PSCommandPath) -ne [IO.Path]::GetFullPath($SavedInstaller)) {
            Copy-Item $PSCommandPath $SavedInstaller -Force
        }
    } elseif ($AssetBase) {
        Invoke-WebRequest "$AssetBase/ble-stt-install.ps1" -OutFile (Join-Path $Root "install.ps1")
    }

    $UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $PathParts = @($UserPath -split ";" | Where-Object { $_ })
    if ($PathParts -notcontains $BinDir) {
        [Environment]::SetEnvironmentVariable("Path", (($PathParts + $BinDir) -join ";"), "User")
    }

    Show-Step "Registering the login service"
    $ServiceSwitchStarted = $true
    Invoke-Checked $Service @("install", "--", "--engine", $Engine, "--model", $Model)

    # Publish the new command only after all validation and service steps have
    # succeeded. A failed upgrade leaves the previous version selected.
    Set-Content $CurrentFile $Target -Encoding UTF8
    $Command = "@echo off`r`n`"$BleStt`" %*`r`n"
    Set-Content $Shim $Command -Encoding Default

    $InstallComplete = $true
    Write-Host "`n[ok] M5StopWatch BLE STT $Version is installed and running." -ForegroundColor Green
    Write-Host "     Open a new PowerShell window and run: ble-stt status"
} finally {
    if ($Work -and (Test-Path $Work)) {
        Remove-Item $Work -Recurse -Force -ErrorAction SilentlyContinue
    }
    if (-not $InstallComplete -and $Target -and (Test-Path $Target)) {
        if ($ServiceSwitchStarted) {
            if ($OldService -and (Test-Path $OldService)) {
                Write-Warning "Restoring the previous login service"
                & $OldService install -- --engine $Engine --model $Model
            } elseif ($Service -and (Test-Path $Service)) {
                Write-Warning "Removing the incomplete login service"
                & $Service uninstall
            }
        }
        Remove-Item $Target -Recurse -Force -ErrorAction SilentlyContinue
    }
}
