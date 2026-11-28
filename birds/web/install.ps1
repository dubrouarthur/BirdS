# Bird en local sur Windows, en une commande (PowerShell) :
#   irm https://bird-s.vercel.app/install.ps1 | iex
#
# Deux chemins, choisis automatiquement :
#   1. WSL présent (recommandé, carte NVIDIA) : le script Linux de Bird tourne dans WSL. Il installe vLLM, sert le modèle
#      et démarre Bird. Windows ouvre ensuite http://127.0.0.1:8765, car WSL partage ses ports locaux avec Windows.
#   2. Pas de WSL, mais un serveur compatible OpenAI tourne déjà sous Windows (BIRD_VLLM_URL, ou LM Studio / Ollama /
#      vLLM détectés sur 127.0.0.1) : Bird s'installe sous Windows (Python 3.10+, git) et se branche dessus.
#   Sinon : le script explique en deux lignes comment activer WSL (wsl --install, un redémarrage).
# Rien n'est envoyé ailleurs : le modèle, vos messages et les outils restent sur votre machine.
#
# Réglages facultatifs (variables d'environnement) :
#   $env:HF_TOKEN       jeton Hugging Face (modèle privé)
#   $env:BIRD_VLLM_URL  un serveur compatible OpenAI déjà lancé, par exemple http://127.0.0.1:1234/v1
#   $env:BIRD_PORT      port de Bird (défaut 8765)
#   $env:BIRD_NO_WSL=1  ne pas utiliser WSL
# Arrêter : & "$HOME\.bird\stop.ps1"

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
$Site = 'https://bird-s.vercel.app'
$Port = if ($env:BIRD_PORT) { [int]$env:BIRD_PORT } else { 8765 }
$BirdHome = Join-Path $HOME '.bird'
$Repo = if ($env:BIRD_REPO) { $env:BIRD_REPO } else { 'https://github.com/dubrouarthur/BirdS.git' }
$Ref = if ($env:BIRD_REF) { $env:BIRD_REF } else { 'ccr-f7b26c02-9v78gg' }
$Url = "http://127.0.0.1:$Port/"

function Say($m) { Write-Host "› $m" -ForegroundColor Cyan }
function Ok($m) { Write-Host "✓ $m" -ForegroundColor Green }
# an error stops the install with one red line (caught at the end), never a PowerShell stack trace
function Fail($m) { throw $m }

function Test-Http($u) {
  try { Invoke-RestMethod -Uri $u -TimeoutSec 3 -UseBasicParsing | Out-Null; return $true } catch { return $false }
}

function Wait-Bird {
  for ($i = 0; $i -lt 900; $i++) {
    if (Test-Http "$($Url)api/health") { return $true }
    Start-Sleep -Seconds 2
  }
  return $false
}

# l'oiseau (here-string entre apostrophes : aucun caractère interprété)
$BirdArt = @'
        __                       __
        \ `-.__            __.-' /
         `-.   `-.__  __.-'   .-'
            `-.     (o >    .-'
               `-.__/  \__.-'
                    \__/
'@
Write-Host ""
Write-Host $BirdArt -ForegroundColor Blue
Write-Host ""
Write-Host "          B I R D   " -NoNewline
Write-Host "·  conçu en France" -ForegroundColor DarkGray
Write-Host "     Votre IA, chez vous. Sans abonnement." -ForegroundColor DarkGray
Write-Host ""

function Install-Bird {
  New-Item -ItemType Directory -Force -Path $BirdHome | Out-Null

  # ---- 1. WSL : tout le côté Linux (vLLM ne tourne pas nativement sous Windows)
  $wsl = Get-Command wsl.exe -ErrorAction SilentlyContinue
  $hasDistro = $false
  if ($wsl -and -not $env:BIRD_NO_WSL) {
    # without a distribution, wsl -l -q prints nothing useful (and exits non-zero)
    $list = (& wsl.exe -l -q 2>$null) -join '' -replace "`0", ''
    $hasDistro = ($LASTEXITCODE -eq 0) -and ($list.Trim().Length -gt 0)
  }

  if ($hasDistro -and -not $env:BIRD_VLLM_URL) {
    # the Linux disk of WSL is a file on a Windows drive: vLLM (~10 Go) and the model (~8 Go) land there
    & wsl.exe -e sh -c 'test -x ~/.bird/vllm-venv/bin/vllm' 2>$null
    if ($LASTEXITCODE -ne 0) {
      $drive = (Get-Item $env:LOCALAPPDATA).PSDrive
      $freeGb = [math]::Floor($drive.Free / 1GB)
      if ($freeGb -lt 25) {
        Fail "Il faut environ 25 Go libres sur le disque $($drive.Name): pour vLLM et le modèle ; il en reste $freeGb. Libérez de la place (Paramètres → Système → Stockage), puis relancez la même commande."
      }
    }
    Say "WSL détecté : installation de Bird et du modèle dans WSL (quelques minutes la première fois)…"
    # settings reach WSL through WSLENV (never on a command line, never written to a file: HF_TOKEN stays private)
    $env:BIRD_NO_BROWSER = '1'
    $env:BIRD_PORT = "$Port"
    $share = @('BIRD_NO_BROWSER/u', 'BIRD_PORT/u', 'HF_TOKEN/u', 'BIRD_MODEL/u', 'BIRD_REPO/u', 'BIRD_REF/u')
    $env:WSLENV = (@($env:WSLENV) + $share | Where-Object { $_ }) -join ':'
    & wsl.exe -e sh -c "curl -fsSL $Site/install.sh | sh"
    if ($LASTEXITCODE -ne 0) { Fail "L'installation dans WSL a échoué : voir ~/.bird/logs dans WSL." }
    if (-not (Wait-Bird)) { Fail "Bird ne répond pas sur $Url (WSL doit partager localhost : réglage par défaut de WSL 2)." }
    Set-Content -Path (Join-Path $BirdHome 'stop.ps1') -Encoding UTF8 -Value 'wsl.exe -e sh -c "sh ~/.bird/stop.sh"'
    Ok "Bird tourne sur votre machine : $Url"
    Write-Host "   Arrêter : & `"$BirdHome\stop.ps1`""
    Start-Process $Url
    return
  }

  # ---- 2. Sous Windows : un serveur compatible OpenAI déjà lancé
  $candidates = @()
  if ($env:BIRD_VLLM_URL) { $candidates += $env:BIRD_VLLM_URL.TrimEnd('/') }
  $candidates += 'http://127.0.0.1:8000/v1', 'http://127.0.0.1:1234/v1', 'http://127.0.0.1:11434/v1'
  $base = $null
  foreach ($c in $candidates) { if (Test-Http "$c/models") { $base = $c; break } }
  if (-not $base) {
    Write-Host ""
    Write-Host "Aucun serveur de modèle trouvé sur cette machine." -ForegroundColor Yellow
    Write-Host "  • Recommandé (carte NVIDIA) : activez WSL, puis relancez cette commande :"
    Write-Host "      wsl --install      (PowerShell administrateur, puis redémarrage)"
    Write-Host "  • Ou lancez un serveur compatible OpenAI (LM Studio, Ollama, vLLM…) et indiquez son adresse :"
    Write-Host "      `$env:BIRD_VLLM_URL = 'http://127.0.0.1:1234/v1'; irm $Site/install.ps1 | iex"
    return
  }
  Ok "Serveur du modèle trouvé : $base"

  $py = $null
  foreach ($cand in @(@('py', '-3'), @('python'), @('python3'))) {
    $cmd = Get-Command $cand[0] -ErrorAction SilentlyContinue
    if (-not $cmd) { continue }
    $pyArgs = @($cand | Select-Object -Skip 1)
    & $cand[0] @pyArgs -c 'import sys; sys.exit(sys.version_info < (3, 10))' 2>$null
    if ($LASTEXITCODE -eq 0) { $py = $cand; break }
  }
  if (-not $py) { Fail "Python 3.10 ou plus est requis : https://www.python.org/downloads/windows/ (cochez « Add to PATH »)." }
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) { Fail "git est requis : https://git-scm.com/download/win" }

  $App = Join-Path $BirdHome 'app'
  $Venv = Join-Path $BirdHome 'venv'
  $Logs = Join-Path $BirdHome 'logs'
  New-Item -ItemType Directory -Force -Path $Logs | Out-Null
  if (Test-Path (Join-Path $App '.git')) {
    Say "Mise à jour de Bird…"
    git -C $App fetch -q --depth 1 origin $Ref; git -C $App checkout -q -B bird FETCH_HEAD
  } else {
    Say "Téléchargement de Bird…"
    git clone -q --depth 1 --branch $Ref $Repo $App
    if ($LASTEXITCODE -ne 0) { Fail "Impossible de récupérer Bird depuis $Repo (dépôt privé : vérifiez vos accès Git)." }
  }
  if (-not (Test-Path $Venv)) { $pyArgs = @($py | Select-Object -Skip 1); & $py[0] @pyArgs -m venv $Venv }
  $VPy = Join-Path $Venv 'Scripts\python.exe'
  & $VPy -m pip install -q --upgrade pip
  & $VPy -m pip install -q -r (Join-Path $App 'requirements.txt') 'uvicorn[standard]'
  Ok "Bird installé dans $App"

  $out = Join-Path $Logs 'bird.log'
  $err = Join-Path $Logs 'bird.err.log'
  $proc = Start-Process -FilePath $VPy -WorkingDirectory $App -WindowStyle Hidden -PassThru `
    -RedirectStandardOutput $out -RedirectStandardError $err `
    -ArgumentList @('scripts\bird_local.py', '--vllm-url', $base, '--port', "$Port", '--no-browser')
  Set-Content -Path (Join-Path $BirdHome 'bird.pid') -Value $proc.Id
  Set-Content -Path (Join-Path $BirdHome 'stop.ps1') -Encoding UTF8 -Value @"
`$p = Get-Content '$BirdHome\bird.pid' -ErrorAction SilentlyContinue
if (`$p) { Stop-Process -Id `$p -ErrorAction SilentlyContinue }
Remove-Item '$BirdHome\bird.pid' -ErrorAction SilentlyContinue
Write-Host 'Bird local arrêté.'
"@
  if (-not (Wait-Bird)) { Fail "Bird ne démarre pas. Journal : $err" }
  Ok "Bird tourne sur votre machine : $Url"
  $link = Select-String -Path $out -Pattern 'https:\S*#bird-local=\d+:[A-Z0-9-]+' -ErrorAction SilentlyContinue |
    Select-Object -First 1 | ForEach-Object { $_.Matches[0].Value }
  if ($link) { Write-Host "   Depuis bird-s.vercel.app, ouvrez : $link" }
  Write-Host "   Journaux : $Logs   ·   Arrêter : & `"$BirdHome\stop.ps1`""
  Start-Process $Url
}

try { Install-Bird } catch { Write-Host "✗ $($_.Exception.Message)" -ForegroundColor Red }
