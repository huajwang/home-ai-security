# Copy the Home Assistant stack to the ROCK 5T. Does not restart the old hub.
param(
    [string]$TargetHost = "10.0.0.83",
    [string]$User = "radxa",
    [string]$RemoteDir = "/home/radxa/home-ai-security"
)

$ErrorActionPreference = "Stop"

Write-Host "==> Running tests..." -ForegroundColor Cyan
python -m pytest
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tests failed. Nothing was copied." -ForegroundColor Red
    exit 1
}

Write-Host "==> Copying deploy/rock5t, link, and docs to ${User}@${TargetHost}..." -ForegroundColor Cyan
ssh "${User}@${TargetHost}" "mkdir -p ${RemoteDir}/deploy ${RemoteDir}/docs ${RemoteDir}/link"
scp -r deploy\rock5t deploy\elegoo_alert.py "${User}@${TargetHost}:${RemoteDir}/deploy/"
scp -r link "${User}@${TargetHost}:${RemoteDir}/"
scp -r docs\ha-cutover.md docs\lovelace.md docs\alexa.md "${User}@${TargetHost}:${RemoteDir}/docs/"

Write-Host "Files are on the board. Follow docs/ha-cutover.md. This script does not stop home-ai-hub." -ForegroundColor Green
