# Deploy local hub code to ROCK 5T board via SCP and SSH
param(
    [string]$TargetHost = "10.0.0.83",
    [string]$User = "radxa",
    [string]$RemoteDir = "/home/radxa/home-ai-security"
)

$ErrorActionPreference = "Stop"

Write-Host "==> Step 1: Running local verification tests..." -ForegroundColor Cyan
python -m pytest
if ($LASTEXITCODE -ne 0) {
    Write-Host "Tests failed! Aborting deployment." -ForegroundColor Red
    exit 1
}

Write-Host "==> Step 2: Packaging hub files..." -ForegroundColor Cyan
$tarFile = "hub_dist.tar.gz"
if (Test-Path $tarFile) { Remove-Item -Force $tarFile }

# Pack core python services and dependencies, excluding caches
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='_tmp*' -czvf $tarFile hub requirements.txt

Write-Host "==> Step 3: Copying archive to ROCK 5T ($User@$TargetHost)..." -ForegroundColor Cyan
scp $tarFile "${User}@${TargetHost}:/tmp/${tarFile}"

Write-Host "==> Step 4: Extracting and restarting service on ROCK 5T..." -ForegroundColor Cyan
ssh "${User}@${TargetHost}" "mkdir -p ${RemoteDir} && tar -xzvf /tmp/${tarFile} -C ${RemoteDir}/ && rm -f /tmp/${tarFile} && sudo systemctl restart home-ai-hub"

if (Test-Path $tarFile) { Remove-Item -Force $tarFile }

Write-Host "`n Deployment to ROCK 5T successful!" -ForegroundColor Green
Write-Host "home-ai-hub.service has been restarted with the latest mask detection code." -ForegroundColor Green
