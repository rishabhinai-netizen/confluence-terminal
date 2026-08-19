# Confluence Terminal — one-shot GitHub Pages deployment for Windows PowerShell
# Usage:
#   1. Open PowerShell in the automation/ folder (right-click folder, "Open in Terminal")
#   2. Run:  .\deploy.ps1
#   3. Paste your GitHub PAT when prompted (ghp_...)
#   4. Wait ~2 min; the live URL is printed at the end

$ErrorActionPreference = 'Stop'

Write-Host "`n=== Confluence Terminal · GitHub Pages deploy ===" -ForegroundColor Cyan

# Prompt for PAT (never stored on disk)
$secure = Read-Host "Paste your GitHub PAT (starts with ghp_)" -AsSecureString
$TOKEN = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure))
if (-not $TOKEN.StartsWith("ghp_")) { Write-Error "Not a valid PAT"; exit 1 }

# Discover username
$headers = @{ Authorization = "Bearer $TOKEN"; Accept = "application/vnd.github+json" }
$user = Invoke-RestMethod -Uri "https://api.github.com/user" -Headers $headers
$OWNER = $user.login
$REPO = "confluence-terminal"
Write-Host "Authenticated as: $OWNER" -ForegroundColor Green

# Read cookies from the sensitive file next to this repo
$cookiePath = Join-Path (Get-Location).Path "..\Session Cookies (SENSITIVE - do not share).txt"
if (-not (Test-Path $cookiePath)) {
    $cookiePath = Read-Host "Path to your 'Session Cookies' file (or press Enter to skip)"
}
$STOCKSCANS_COOKIE = ""
$EQUISENSE_COOKIE = ""
if ($cookiePath -and (Test-Path $cookiePath)) {
    $raw = Get-Content $cookiePath -Raw
    $ssMatch = [regex]::Match($raw, '(?ms)STOCKSCANS\.IN.*?\n\n(_ga=.+?)\r?\n')
    if ($ssMatch.Success) { $STOCKSCANS_COOKIE = $ssMatch.Groups[1].Value.Trim() }
    $esMatch = [regex]::Match($raw, '(?ms)EQUISENSE\.AI.*?\n\n(es_anon_id=.+?)\r?\n')
    if ($esMatch.Success) { $EQUISENSE_COOKIE = $esMatch.Groups[1].Value.Trim() }
    Write-Host "Cookies loaded from $cookiePath" -ForegroundColor Green
} else {
    Write-Host "No cookie file — you can add secrets later via repo Settings." -ForegroundColor Yellow
}

# Step 1: Create private repo
Write-Host "`n[1/6] Creating private repo '$REPO'..." -ForegroundColor Cyan
try {
    $body = @{ name = $REPO; private = $true; auto_init = $false;
               description = "Cross-source equity intelligence terminal";
               has_issues = $false; has_wiki = $false } | ConvertTo-Json
    $repo = Invoke-RestMethod -Uri "https://api.github.com/user/repos" `
        -Method Post -Headers $headers -Body $body -ContentType "application/json"
    Write-Host "    Created: $($repo.clone_url)" -ForegroundColor Green
} catch {
    if ($_.Exception.Response.StatusCode.Value__ -eq 422) {
        Write-Host "    Repo already exists — reusing" -ForegroundColor Yellow
    } else { throw }
}

# Step 2: Init git in current folder and push
Write-Host "`n[2/6] Initializing git and pushing code..." -ForegroundColor Cyan
if (-not (Test-Path ".git")) { git init -b main | Out-Null }
git config user.email "confluence@local"
git config user.name "confluence"
git add -A
git commit -m "Initial deploy" --allow-empty | Out-Null
git remote remove origin 2>$null
git remote add origin "https://x-access-token:$TOKEN@github.com/$OWNER/$REPO.git"
git push -u origin main --force
Write-Host "    Pushed to main" -ForegroundColor Green

# Step 3: Set repo secrets (cookies)
if ($STOCKSCANS_COOKIE -or $EQUISENSE_COOKIE) {
    Write-Host "`n[3/6] Setting repo secrets (cookies)..." -ForegroundColor Cyan
    # Get public key for encryption
    $keyResp = Invoke-RestMethod -Uri "https://api.github.com/repos/$OWNER/$REPO/actions/secrets/public-key" -Headers $headers
    # Load sodium.js equivalent — using .NET
    $keyBytes = [System.Convert]::FromBase64String($keyResp.key)

    # Encrypt with libsodium (uses PSSodium if available; else prompt manual)
    if (-not (Get-Module -ListAvailable PSSodium)) {
        Write-Host "    Installing PSSodium (needed to encrypt secrets)..." -ForegroundColor Yellow
        try { Install-Module PSSodium -Scope CurrentUser -Force -AllowClobber -ErrorAction Stop }
        catch { Write-Host "    Couldn't install PSSodium. Add secrets manually via repo Settings; see fallback below." -ForegroundColor Yellow }
    }

    if (Get-Module -ListAvailable PSSodium) {
        Import-Module PSSodium
        function Set-RepoSecret($name, $value) {
            if (-not $value) { return }
            $enc = ConvertTo-SodiumEncryptedString -Text $value -PublicKey $keyResp.key
            $secretBody = @{ encrypted_value = $enc; key_id = $keyResp.key_id } | ConvertTo-Json
            Invoke-RestMethod -Uri "https://api.github.com/repos/$OWNER/$REPO/actions/secrets/$name" `
                -Method Put -Headers $headers -Body $secretBody -ContentType "application/json" | Out-Null
            Write-Host "    Secret '$name' set." -ForegroundColor Green
        }
        Set-RepoSecret "STOCKSCANS_COOKIE" $STOCKSCANS_COOKIE
        Set-RepoSecret "EQUISENSE_COOKIE" $EQUISENSE_COOKIE
    } else {
        Write-Host "    Add secrets manually: https://github.com/$OWNER/$REPO/settings/secrets/actions" -ForegroundColor Yellow
    }
}

# Step 4: Enable GitHub Pages (source = GitHub Actions)
Write-Host "`n[4/6] Enabling GitHub Pages (source = Actions)..." -ForegroundColor Cyan
try {
    Invoke-RestMethod -Uri "https://api.github.com/repos/$OWNER/$REPO/pages" `
        -Method Post -Headers $headers `
        -Body (@{ build_type = "workflow" } | ConvertTo-Json) `
        -ContentType "application/json" | Out-Null
    Write-Host "    Pages enabled" -ForegroundColor Green
} catch {
    if ($_.Exception.Response.StatusCode.Value__ -eq 409) {
        Write-Host "    Pages already enabled" -ForegroundColor Yellow
    } else { throw }
}

# Step 5: Trigger workflow
Write-Host "`n[5/6] Triggering first workflow run..." -ForegroundColor Cyan
try {
    Invoke-RestMethod -Uri "https://api.github.com/repos/$OWNER/$REPO/actions/workflows/daily.yml/dispatches" `
        -Method Post -Headers $headers `
        -Body (@{ ref = "main" } | ConvertTo-Json) `
        -ContentType "application/json" | Out-Null
    Write-Host "    Workflow triggered" -ForegroundColor Green
} catch {
    Write-Host "    Workflow will auto-trigger on the next cron (07:00 IST daily)" -ForegroundColor Yellow
}

# Step 6: Return URLs
Write-Host "`n[6/6] Done!" -ForegroundColor Cyan
Write-Host ""
Write-Host "Repo:        https://github.com/$OWNER/$REPO" -ForegroundColor White
Write-Host "Actions:     https://github.com/$OWNER/$REPO/actions" -ForegroundColor White
Write-Host "Live URL:    https://$OWNER.github.io/$REPO/  (available ~2-3 min after workflow finishes)" -ForegroundColor Yellow
Write-Host ""
Write-Host "Bookmark the Live URL. From tomorrow, the workflow auto-fires at 07:00 IST." -ForegroundColor Cyan
