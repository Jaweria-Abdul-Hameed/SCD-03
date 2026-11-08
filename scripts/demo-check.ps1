<#
.SYNOPSIS
  Smoke test for the live RAHBAR stack. Exits non-zero on any failure.
  Expects the API port-forward from demo-up.ps1 (http://localhost:8000).
  Usage:  .\scripts\demo-check.ps1
#>
$ErrorActionPreference = 'Continue'
$ns = 'rahbar'
$api = 'http://localhost:8000'
if (-not (Get-Command minikube -ErrorAction SilentlyContinue)) { $env:Path += ';C:\Program Files\Kubernetes\Minikube' }
$fail = 0
function Pass($m) { Write-Host "[PASS] $m" -ForegroundColor Green }
function Fail($m) { Write-Host "[FAIL] $m" -ForegroundColor Red; $script:fail++ }
function Ask($q) {
  $b = @{ question = $q } | ConvertTo-Json
  Invoke-RestMethod -Uri "$api/chat" -Method Post -ContentType 'application/json' -Body $b -TimeoutSec 300
}

try { $h = Invoke-RestMethod "$api/healthz" -TimeoutSec 10; Pass "/healthz -> $($h | ConvertTo-Json -Compress)" } catch { Fail "/healthz: $($_.Exception.Message)" }
try { $r = Invoke-RestMethod "$api/readyz" -TimeoutSec 10; if ($r.status -eq 'ready') { Pass "/readyz -> ready, $($r.collection_count) chunks, $($r.embed_model)" } else { Fail "/readyz: $($r | ConvertTo-Json -Compress)" } } catch { Fail "/readyz: $($_.Exception.Message)" }

# flush the semantic cache so the first ask below is a genuine miss
kubectl exec deploy/redis -n $ns -- redis-cli flushall *> $null

# 1. grounded + cited
try {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $a = Ask 'What is the tuition fee per credit hour?'
  $sw.Stop()
  $t = ($a | ConvertTo-Json -Depth 6)
  if ($a.answer.answered_from_context -and $a.answer.citations.Count -ge 1 -and $t -match '12,000') { Pass ("grounded answer with {0} citation(s), mentions Rs. 12,000 ({1:N1} s)" -f $a.answer.citations.Count, $sw.Elapsed.TotalSeconds) }
  else { Fail "grounded question did not return a cited answer containing 12,000: $($a.answer.answer)" }
} catch { Fail "grounded question: $($_.Exception.Message)" }

# 1b. the browser path: the chat UI on :3000 must proxy /api/chat to the API (a 405 here broke the page once)
try { $b = @{ question = 'What is the tuition fee per credit hour?' } | ConvertTo-Json; $u = Invoke-RestMethod -Uri 'http://localhost:3000/api/chat' -Method Post -ContentType 'application/json' -Body $b -TimeoutSec 300; if ($u.answer.answer) { Pass 'chat UI :3000 /api/chat reaches the API' } else { Fail 'chat UI returned no answer' } } catch { Fail "chat UI :3000 /api/chat: $($_.Exception.Message)" }

# 2. cache hit on the repeated question
try {
  $sw = [Diagnostics.Stopwatch]::StartNew()
  $a2 = Ask 'What is the tuition fee per credit hour?'
  $sw.Stop()
  if ($a2.cache_hit -eq $true) { Pass ("repeated question is a cache hit ({0:N2} s)" -f $sw.Elapsed.TotalSeconds) } else { Fail 'repeated question was not a cache hit' }
} catch { Fail "cache question: $($_.Exception.Message)" }

# 3. abstention
try {
  $a = Ask 'What are the hostel allotment rules for first-year students?'
  if ($a.answer.answered_from_context -eq $false) { Pass 'hostel question abstains (answered_from_context=false)' } else { Fail "hostel question was answered from context: $($a.answer.answer)" }
} catch { Fail "hostel question: $($_.Exception.Message)" }

# 4. version-sensitive
# The checks look at the ANSWER TEXT and the CITATIONS only (never at the model's `reasoning` or the retrieved text, which
# used to make a bare "11" or "1.21" anywhere in the JSON count as a pass). What is version-sensitive is WHICH document the
# answer comes from: the current one, not the superseded one.
function Warn($m) { Write-Host "[NOTE] $m" -ForegroundColor Yellow }
try {
  $a = Ask 'How many program learning outcomes (PLOs) does the Electrical Engineering program have?'
  $src = @($a.answer.citations | ForEach-Object { $_.source })
  if ($a.answer.answered_from_context -and $src.Count -gt 0 -and -not ($src -match 'before_2024')) {
    if ($src -match 'EE_PLOs_2024') { Pass 'EE PLOs question is answered from the current (2024 onwards, 11 PLOs) document, not the 12-PLO one' } else { Fail "EE PLOs question cites an unexpected source: $($src -join ', ')" }
  } else { Fail "EE PLOs question was not answered from the current document: $($a.answer.answer)" }
  if ($a.answer.answer -notmatch '(?<!PLO-)\b(11|eleven)\b') { Warn 'the EE PLOs answer text does not state the number 11 (3B model: it quotes PLO-8..PLO-11); see docs/evidence/final-verification-2026-11-08.md' }
  $a = Ask 'Which clause states the attendance requirement, and what does the current version say?'
  $src = @($a.answer.citations | ForEach-Object { $_.source })
  if ($a.answer.answered_from_context -and $src.Count -gt 0 -and -not ($src -match 'Undergraduate_Academic_Rules') -and $a.answer.answer -match '100\s*%') { Pass 'attendance question is answered from a current document (not the superseded 2023 rules) and states 100%' } else { Fail "attendance question was not answered from a current document: $($a.answer.answer)" }
  if (($a.answer.answer + ' ' + (($a.answer.citations | ForEach-Object { $_.section }) -join ' ')) -notmatch '1\.21') { Warn 'the attendance answer does not name clause 1.21 (it cites the Prospectus, where the clause is numbered 1); see docs/evidence/final-verification-2026-11-08.md' }
} catch { Fail "version-sensitive question: $($_.Exception.Message)" }

# 5. HPA real percentage + endpoints
$hpa = kubectl get hpa api -n $ns --no-headers 2>$null
if ($hpa -and $hpa -notmatch '<unknown>') { Pass "HPA reads a real value: $($hpa -replace '\s+',' ')" } else { Fail "HPA shows <unknown> or is missing: $hpa" }
$ep = kubectl get endpoints api -n $ns -o jsonpath='{.subsets[0].addresses[*].ip}' 2>$null
$n = if ($ep) { @($ep -split ' ' | Where-Object { $_ }).Count } else { 0 }
if ($n -ge 3) { Pass "service api has $n endpoints" } else { Fail "service api has $n endpoints (expected >= 3)" }

if ($fail -eq 0) { Write-Host 'RESULT: PASS - all checks green' -ForegroundColor Green; exit 0 }
else { Write-Host "RESULT: FAIL ($fail check(s) failed)" -ForegroundColor Red; exit 1 }
