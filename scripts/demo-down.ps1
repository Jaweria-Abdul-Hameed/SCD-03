<#
.SYNOPSIS
  Stop the demo: close the port-forwards and `minikube stop` (NOT delete).
  PVCs, loaded images and Ollama models survive. Usage: .\scripts\demo-down.ps1
#>
$ErrorActionPreference = 'Continue'
if (-not (Get-Command minikube -ErrorAction SilentlyContinue)) { $env:Path += ';C:\Program Files\Kubernetes\Minikube' }
foreach ($port in 3000, 8000, 8001, 8080) {
  $c = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
  if ($c) {
    $c | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
    Write-Host "[PASS] closed port-forward on :$port" -ForegroundColor Green
  }
}
minikube stop | Out-Host
$st = (minikube status --format '{{.Host}}' 2>$null)
if ($st -eq 'Stopped') { Write-Host 'RESULT: PASS - minikube stopped (data kept; run demo-up.ps1 to resume)' -ForegroundColor Green; exit 0 }
else { Write-Host "RESULT: FAIL - minikube host is '$st'" -ForegroundColor Red; exit 1 }
