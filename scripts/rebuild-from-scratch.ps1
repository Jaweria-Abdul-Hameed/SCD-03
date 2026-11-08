<#
.SYNOPSIS
  Rebuild the whole RAHBAR stack from a clean clone (no cluster yet).
.DESCRIPTION
  Expected duration: about 1 hour on the reference laptop
    minikube start + addons ........ 3-5 min
    docker build x3 + image load ... 5-10 min
    apply + pods ready ............. 2-3 min
    Ollama model pulls (2 GB) ...... 5-15 min (network)
    corpus fetch + copy to PVC ..... 3-5 min  (skipped when corpus/raw is full)
    indexer Job (480 chunks) ....... about 4 min with OLLAMA_NUM_THREAD pinned
    demo-check ..................... 3-5 min (CPU generation)
  Idempotent: every step re-checks its own result. Prints PASS/FAIL lines.
  NEVER deletes a cluster, PVC or image - use only on a machine with no rahbar
  cluster, or to repair one (it re-applies manifests and re-runs the Job).
  Usage (from the repository root, PowerShell):  .\scripts\rebuild-from-scratch.ps1
#>
$ErrorActionPreference = 'Stop'
$ns = 'rahbar'
$root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Set-Location $root
if (-not (Get-Command minikube -ErrorAction SilentlyContinue)) { $env:Path += ';C:\Program Files\Kubernetes\Minikube' }
function Pass($m) { Write-Host "[PASS] $m" -ForegroundColor Green }
function Fail($m) { Write-Host "[FAIL] $m" -ForegroundColor Red; exit 1 }
function Info($m) { Write-Host "[....] $m" -ForegroundColor Cyan }
function Run($cmd) { Info $cmd; Invoke-Expression $cmd; if ($LASTEXITCODE -ne 0) { Fail "command failed ($LASTEXITCODE): $cmd" } }

Write-Host 'Expected total duration: about 1 hour (see the header of this script).' -ForegroundColor Yellow

# 0. prerequisites
foreach ($tool in 'docker', 'kubectl', 'minikube', 'git', 'python') {
  if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) { Fail "$tool not found on PATH" }
}
docker info *> $null
if ($LASTEXITCODE -ne 0) { Fail 'Docker Desktop is not running' }
Pass 'prerequisites present, Docker Desktop running'

# 1. cluster (Calico is mandatory: the default CNI silently ignores NetworkPolicy)
$st = (minikube status --format '{{.Host}}' 2>$null)
if ($st -ne 'Running') {
  Run 'minikube start --driver=docker --cni=calico --memory=8192 --cpus=6'
}
Run 'minikube addons enable metrics-server'
Run 'minikube addons enable ingress'
Pass 'minikube running with Calico, metrics-server and ingress'

# 2. images: TAG = short git SHA (never :latest)
$tag = (git rev-parse --short HEAD).Trim()
if (-not $tag) { $tag = 'local' }
foreach ($n in 'api', 'ui', 'indexer') {
  Run "docker build -t ghcr.io/rahbar/${n}:$tag ./$n"
  Run "minikube image load ghcr.io/rahbar/${n}:$tag"
}
Pass "images built and loaded with tag $tag"

# 3. manifests (incluster-ollama overlay). No kustomize binary needed:
#    `kubectl kustomize` renders; the :SHA placeholder is replaced by the tag.
#    The placeholder Secret is NOT applied (and is not part of the kustomization).
kubectl apply -f k8s/base/namespace.yaml | Out-Host
$rendered = (kubectl kustomize k8s/overlays/incluster-ollama) -join "`n"
if ($LASTEXITCODE -ne 0) { Fail 'kubectl kustomize failed' }
$rendered = $rendered -replace ':SHA', ":$tag"
$rendered | kubectl apply -f - | Out-Host
if ($LASTEXITCODE -ne 0) { Fail 'kubectl apply failed' }
Pass 'manifests applied (overlay k8s/overlays/incluster-ollama)'

# 4. secret ONLY for the hosted provider
$provider = (kubectl get configmap rahbar-config -n $ns -o jsonpath='{.data.LLM_PROVIDER}')
if ($provider -eq 'hosted') {
  if (-not $env:LLM_API_KEY) { Fail 'LLM_PROVIDER=hosted needs $env:LLM_API_KEY' }
  kubectl create secret generic rahbar-secret -n $ns --from-literal=LLM_API_KEY="$env:LLM_API_KEY" --dry-run=client -o yaml | kubectl apply -f - | Out-Host
  Pass 'hosted LLM secret created from the environment (never committed)'
} else { Pass "LLM_PROVIDER=$provider - no secret needed" }

# 5. Ollama up, models pulled
Run "kubectl rollout status deploy/ollama -n $ns --timeout=600s"
foreach ($m in 'nomic-embed-text', 'llama3.2:3b') {
  $have = kubectl exec deploy/ollama -n $ns -- ollama list | Out-String
  if ($have -notmatch [regex]::Escape($m)) { Run "kubectl exec deploy/ollama -n $ns -- ollama pull $m" }
  Pass "Ollama model $m present"
}

# 6. corpus: fetch if empty, copy to the corpus-data PVC
if (-not (Test-Path 'corpus/raw') -or @(Get-ChildItem 'corpus/raw' -File -ErrorAction SilentlyContinue).Count -lt 15) {
  Run 'python scripts/fetch_corpus.py'
}
if (@(Get-ChildItem 'corpus/raw' -File).Count -lt 15) { Fail 'corpus/raw has fewer than 15 files after fetch' }
Pass 'corpus/raw populated (15 files)'
$loader = @"
apiVersion: v1
kind: Pod
metadata: {name: corpus-loader, namespace: $ns}
spec:
  restartPolicy: Never
  containers:
    - name: loader
      image: busybox:1.36
      command: ["sleep", "3600"]
      volumeMounts: [{name: corpus, mountPath: /corpus}]
  volumes:
    - name: corpus
      persistentVolumeClaim: {claimName: corpus-data}
"@
$loader | kubectl apply -f - | Out-Host
Run "kubectl wait --for=condition=ready pod/corpus-loader -n $ns --timeout=180s"
Run "kubectl exec -n $ns pod/corpus-loader -- mkdir -p /corpus/raw"
Run "kubectl cp corpus/raw/. ${ns}/corpus-loader:/corpus/raw/"
Run "kubectl exec -n $ns pod/corpus-loader -- chmod -R a+rX /corpus"
kubectl delete pod corpus-loader -n $ns --wait=true | Out-Host
Pass 'corpus copied to the corpus-data PVC'

# 7. index (the overlay already created the Job; wait for it)
Run "kubectl wait --for=condition=complete --timeout=1800s job/indexer -n $ns"
kubectl logs job/indexer -n $ns | Select-String 'index_done' | Out-Host
Pass 'indexer Job complete'

# 8. wait for api and smoke test
Run "kubectl rollout status deploy/api -n $ns --timeout=600s"
Pass 'api rolled out (3 replicas Ready only when the collection is non-empty)'
& (Join-Path $PSScriptRoot 'demo-up.ps1')
& (Join-Path $PSScriptRoot 'demo-check.ps1')
if ($LASTEXITCODE -ne 0) { Fail 'demo-check failed' }
Write-Host 'RESULT: PASS - stack rebuilt from scratch' -ForegroundColor Green
