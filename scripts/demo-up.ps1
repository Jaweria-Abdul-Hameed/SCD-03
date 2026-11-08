<#
.SYNOPSIS
  Bring the RAHBAR demo stack up after a reboot with ONE command.
.DESCRIPTION
  Idempotent. Starts minikube if needed, waits for every pod in namespace
  `rahbar`, checks the Chroma index and the Ollama models, starts the UI/API
  port-forwards, pre-warms Ollama with one real question and prints a status
  table. Uses `minikube start` only; it never deletes anything.
  Usage:  .\scripts\demo-up.ps1
#>
$ErrorActionPreference = 'Continue'
$ns = 'rahbar'
$mk = 'C:\Program Files\Kubernetes\Minikube'
if (-not (Get-Command minikube -ErrorAction SilentlyContinue)) { $env:Path += ";$mk" }
$fail = 0
function Pass($m) { Write-Host "[PASS] $m" -ForegroundColor Green }
function Fail($m) { Write-Host "[FAIL] $m" -ForegroundColor Red; $script:fail++ }
function Info($m) { Write-Host "[....] $m" -ForegroundColor Cyan }

# 1. Docker Desktop
docker info *> $null
if ($LASTEXITCODE -ne 0) {
  Fail 'Docker Desktop is not running. Start Docker Desktop, wait for the whale icon to settle, then re-run this script.'
  exit 1
}
Pass 'Docker Desktop is running'

# 2. minikube
$st = (minikube status --format '{{.Host}}/{{.Kubelet}}/{{.APIServer}}' 2>$null)
if ($st -ne 'Running/Running/Running') {
  Info "minikube is '$st' - running 'minikube start' (1-3 minutes)"
  minikube start | Out-Host
}
$st = (minikube status --format '{{.Host}}/{{.Kubelet}}/{{.APIServer}}' 2>$null)
if ($st -eq 'Running/Running/Running') { Pass 'minikube is Running' } else { Fail "minikube status: $st"; exit 1 }

# 3. wait for pods (timeout 10 min). Completed Job pods are ignored.
Info 'waiting for all rahbar pods to be Running and api to be 3/3 Ready (timeout 10 min)'
$deadline = (Get-Date).AddMinutes(10)
$ok = $false
while ((Get-Date) -lt $deadline) {
  $pods = kubectl get pods -n $ns -o json 2>$null | ConvertFrom-Json
  if ($pods -and $pods.items) {
    $live = $pods.items | Where-Object { $_.status.phase -ne 'Succeeded' }
    $notReady = $live | Where-Object {
      -not ($_.status.phase -eq 'Running' -and (($_.status.containerStatuses | Where-Object { -not $_.ready }).Count -eq 0))
    }
    $apiReady = ($live | Where-Object { $_.metadata.labels.app -eq 'api' -and $_.status.phase -eq 'Running' -and (($_.status.containerStatuses | Where-Object { -not $_.ready }).Count -eq 0) }).Count
    if (@($notReady).Count -eq 0 -and $apiReady -ge 3) { $ok = $true; break }
  }
  Start-Sleep -Seconds 10
}
kubectl get pods -n $ns | Out-Host
if ($ok) { Pass 'all pods Running; api >= 3 Ready' } else { Fail 'pods not all Ready within 10 min (wait 2 more minutes and re-run; see docs/DEMO.md troubleshooting)' }

# 4. index present + Ollama models present
$cnt = kubectl exec deploy/api -n $ns -- python -c "import chromadb;print(chromadb.HttpClient(host='chroma',port=8000).get_collection('rahbar_corpus').count())" 2>$null
if ($cnt -and [int]$cnt -gt 0) { Pass "Chroma collection rahbar_corpus has $cnt chunks" } else { Fail 'Chroma collection is empty/missing - run the indexer Job (docs/DEMO.md, rebuild section)' }
$provider = kubectl get cm rahbar-config -n $ns -o jsonpath='{.data.LLM_PROVIDER}'
if ($provider -eq 'ollama-host') {
  # GPU mode: the api talks to the Ollama running on this laptop (RTX GPU), reached from the cluster as
  # host.minikube.internal:11434. That Ollama stays bound to 127.0.0.1 - nothing is exposed on 0.0.0.0.
  $tags = $null
  try { $tags = (Invoke-RestMethod http://127.0.0.1:11434/api/tags -TimeoutSec 10).models.name -join ' ' } catch { }
  if (-not $tags) { Fail 'host Ollama is not answering on 127.0.0.1:11434 - start the Ollama app and re-run' }
  foreach ($m in 'nomic-embed-text', 'llama3.2:3b') {
    if ($tags -match [regex]::Escape($m)) { Pass "host Ollama has model $m" }
    else { Info "host Ollama model $m missing - pulling"; ollama pull $m | Out-Host; Fail "model $m was missing: re-run demo-up after the pull" }
  }
  $reach = kubectl exec deploy/api -n $ns -- python -c "import urllib.request;print(urllib.request.urlopen('http://host.minikube.internal:11434/api/tags',timeout=8).status)" 2>$null
  if ($reach -eq '200') { Pass 'api pod reaches the host Ollama (GPU) through host.minikube.internal:11434' } else { Fail 'api pod cannot reach host.minikube.internal:11434 - see docs/DEMO.md (GPU mode)' }
} else {
  $models = kubectl exec deploy/ollama -n $ns -- ollama list 2>$null | Out-String
  foreach ($m in 'nomic-embed-text', 'llama3.2:3b') {
    if ($models -match [regex]::Escape($m)) { Pass "Ollama has model $m" }
    else {
      Info "Ollama model $m missing - pulling (several minutes)"
      kubectl exec deploy/ollama -n $ns -- ollama pull $m | Out-Host
      $models = kubectl exec deploy/ollama -n $ns -- ollama list 2>$null | Out-String
      if ($models -match [regex]::Escape($m)) { Pass "Ollama has model $m" } else { Fail "Ollama model $m could not be pulled" }
    }
  }
}

# 4b. index health: after an unclean node crash Chroma's HNSW index can silently miss
#     recent vectors (measured: recall@5 0.833 -> 0.654, no error anywhere). Compare the
#     approximate search with an exact brute-force search for a fixed question.
$probePy = @'
import chromadb, math
from app.providers import get_provider
from app.services.chat import query_text
q = "What is the tuition fee per credit hour?"
e = get_provider().embed([query_text(q)])[0]
c = chromadb.HttpClient(host="chroma", port=8000).get_collection("rahbar_corpus")
d = c.get(where={"superseded": False}, include=["embeddings"])
def cos(a, b):
    return sum(x * y for x, y in zip(a, b)) / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))
exact = sorted(((cos(e, v), i) for i, v in zip(d["ids"], d["embeddings"])), reverse=True)[:3]
ann = c.query(query_embeddings=[e], n_results=5, where={"superseded": False})["ids"][0]
print("OK" if exact[0][1] in ann else "STALE")
'@
$health = ($probePy | kubectl exec -i deploy/api -n $ns -- python - 2>$null | Select-Object -Last 1)
if ($health -eq 'OK') { Pass 'vector index health: approximate search agrees with exact search' }
else {
  Fail "vector index looks stale or unreachable ($health) - dropping the collection and re-indexing from scratch (about 4 minutes; api is not Ready meanwhile)"
  kubectl exec deploy/api -n $ns -- python -c "import chromadb;chromadb.HttpClient(host='chroma',port=8000).delete_collection('rahbar_corpus')" | Out-Host
  $jobName = 'demo-reindex-' + (Get-Date -Format 'HHmmss')
  kubectl create job --from=cronjob/reindex $jobName -n $ns | Out-Host
  Write-Host "Wait for it:  kubectl wait --for=condition=complete job/$jobName -n $ns --timeout=900s   then re-run demo-up.ps1" -ForegroundColor Yellow
}

# 5. port-forwards (restart them so they are fresh)
function Start-Forward($svc, $local, $remote, $fwdNs = $ns) {
  $existing = Get-NetTCPConnection -LocalPort $local -State Listen -ErrorAction SilentlyContinue
  if ($existing) {
    $alive = $false
    try { Invoke-WebRequest -UseBasicParsing "http://localhost:$local/" -TimeoutSec 5 | Out-Null; $alive = $true } catch { if ($_.Exception.Response) { $alive = $true } }  # any HTTP answer (even 404) = forward works
    if ($alive) { Pass "port-forward on :$local already working"; return }
    $existing | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
  }
  Start-Process -WindowStyle Hidden -FilePath kubectl -ArgumentList "port-forward svc/$svc ${local}:${remote} -n $fwdNs" | Out-Null
  Start-Sleep -Seconds 3
  if (Get-NetTCPConnection -LocalPort $local -State Listen -ErrorAction SilentlyContinue) { Pass "port-forward svc/$svc -> http://localhost:$local" } else { Fail "port-forward svc/$svc failed" }
}
Start-Forward 'ui' 3000 80
Start-Forward 'api' 8000 8000
Start-Forward 'ingress-nginx-controller' 8080 80 'ingress-nginx'

# 6. pre-warm Ollama with one real question
Info 'pre-warming Ollama with one real question (first call loads the model into RAM: can take 30-90 s)'
$sw = [Diagnostics.Stopwatch]::StartNew()
try {
  $body = @{ question = 'What is the tuition fee per credit hour?'; follow_up = $true } | ConvertTo-Json   # follow_up skips the semantic cache, so the model really runs
  $r = Invoke-RestMethod -Uri 'http://localhost:8000/chat' -Method Post -ContentType 'application/json' -Body $body -TimeoutSec 300
  $sw.Stop()
  Pass ("pre-warm answered in {0:N1} s (answered_from_context={1})" -f $sw.Elapsed.TotalSeconds, $r.answer.answered_from_context)
} catch { Fail "pre-warm question failed: $($_.Exception.Message)" }

# 6b. metrics-server needs ~1-2 minutes after a start before the HPA shows a percentage
Info 'waiting for the HPA to show a real CPU percentage (max 3 min)'
$hpaOk = $false
for ($i = 0; $i -lt 18; $i++) {
  $h = kubectl get hpa api -n $ns --no-headers 2>$null
  if ($h -and $h -notmatch '<unknown>') { $hpaOk = $true; break }
  Start-Sleep -Seconds 10
}
if ($hpaOk) { Pass "HPA reads a real value: $($h -replace '\s+',' ')" } else { Write-Host '[WARN] HPA still shows <unknown>; metrics-server is slow - re-check with: kubectl get hpa -n rahbar' -ForegroundColor Yellow }

# 7. summary
Write-Host ''
kubectl get pods,hpa -n $ns | Out-Host
Write-Host ''
Write-Host 'Chat UI : http://localhost:3000' -ForegroundColor Yellow
Write-Host 'API     : http://localhost:8000  (POST /chat, GET /readyz, /metrics)' -ForegroundColor Yellow
Write-Host 'Ingress : http://localhost:8080  (send header Host: rahbar.local; /api/... -> api, / -> ui)' -ForegroundColor Yellow
if ($fail -eq 0) { Write-Host 'RESULT: PASS - demo stack is up' -ForegroundColor Green; exit 0 }
else { Write-Host "RESULT: FAIL ($fail problem(s))" -ForegroundColor Red; exit 1 }
