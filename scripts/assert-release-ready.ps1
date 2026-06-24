$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$configPath = Join-Path $root "src-tauri\tauri.conf.json"
$config = Get-Content -LiteralPath $configPath -Raw | ConvertFrom-Json

function Assert-Condition {
    param(
        [bool]$Condition,
        [string]$Message
    )

    if (-not $Condition) {
        throw $Message
    }
}

$targets = @($config.bundle.targets)
Assert-Condition ($targets -contains "nsis") "Windows release must build the NSIS installer."

$webviewMode = $config.bundle.windows.webviewInstallMode
Assert-Condition ($null -ne $webviewMode) "bundle.windows.webviewInstallMode is required."
Assert-Condition ($webviewMode.type -eq "offlineInstaller") "WebView2 must use offlineInstaller for clean/offline Windows systems."
Assert-Condition ([bool]$webviewMode.silent) "WebView2 offline installer must run silently."
Assert-Condition (-not [string]::IsNullOrWhiteSpace($config.bundle.windows.minimumWebview2Version)) "minimumWebview2Version must be set."

$resources = $config.bundle.resources
Assert-Condition ($null -ne $resources) "Bundled resources are required."
Assert-Condition ($null -ne $resources."../backend/bin/storage-insight-backend.exe") "Bundled backend executable is missing from resources."
Assert-Condition (Test-Path -LiteralPath (Join-Path $root "backend\bin\storage-insight-backend.exe")) "backend\bin\storage-insight-backend.exe does not exist."

Assert-Condition (Test-Path -LiteralPath (Join-Path $root "src-tauri\icons\icon.ico")) "Application icon is missing."
Assert-Condition (Test-Path -LiteralPath (Join-Path $root "src-tauri\windows\nsis-hooks.nsh")) "NSIS hook file is missing."

Write-Host "Release configuration OK: NSIS + silent WebView2 offline installer + bundled backend."
