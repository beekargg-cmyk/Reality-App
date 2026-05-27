$ErrorActionPreference = "Stop"

$GoDir = Split-Path -Path $PSScriptRoot -Parent
$AndroidProjectDir = "$GoDir\android"
$LibsDir = "$AndroidProjectDir\app\libs"

Write-Host "1. Compiling vpncore into AAR..." -ForegroundColor Cyan
Set-Location -Path $GoDir
# Build AAR library with -a flag to force rebuilding all packages
gomobile bind -a -target=android -androidapi 21 -ldflags="-checklinkname=0" -o vpncore.aar ./vpncore

Write-Host "2. Copying vpncore.aar to Android project as vpncore_V8.aar..." -ForegroundColor Cyan
if (!(Test-Path -Path $LibsDir)) {
    New-Item -ItemType Directory -Force -Path $LibsDir
}
Copy-Item -Path ".\vpncore.aar" -Destination "$LibsDir\vpncore_V8.aar" -Force
Remove-Item -Path "$LibsDir\vpncore.aar" -ErrorAction SilentlyContinue

Write-Host "3. Building and installing Android app (installDebug)..." -ForegroundColor Cyan
Set-Location -Path $AndroidProjectDir
# Force clean to prevent AAR caching issues
.\gradlew.bat clean
# Build and install APK
.\gradlew.bat installDebug --no-build-cache

if ($LASTEXITCODE -eq 0) {
    Write-Host "SUCCESS! App installed on the phone." -ForegroundColor Green
} else {
    Write-Host "ERROR building Android project." -ForegroundColor Red
}
