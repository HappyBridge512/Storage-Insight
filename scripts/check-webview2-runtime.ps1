$ErrorActionPreference = "Stop"

$clientId = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
$registryPaths = @(
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\$clientId",
    "HKLM:\SOFTWARE\Microsoft\EdgeUpdate\Clients\$clientId",
    "HKCU:\Software\Microsoft\EdgeUpdate\Clients\$clientId"
)

foreach ($path in $registryPaths) {
    if (-not (Test-Path -LiteralPath $path)) {
        continue
    }

    $version = (Get-ItemProperty -LiteralPath $path -Name "pv" -ErrorAction SilentlyContinue).pv
    if (-not [string]::IsNullOrWhiteSpace($version) -and $version -ne "0.0.0.0") {
        Write-Host "WebView2 Runtime detected: $version"
        Write-Host "Registry: $path"
        exit 0
    }
}

Write-Error "Microsoft Edge WebView2 Runtime was not detected."
exit 1
