# One-time setup: copies the secrets the probe needs into this repo's GitHub secrets and turns on Pages.
# Values go straight from your files/terminal into `gh secret set` via stdin; nothing is printed or saved.
# Run from D:\ops-dashboard after the GitHub repo exists:  .\setup.ps1
$ErrorActionPreference = "Stop"
$repo = "sayaksatpathi/ops-dashboard"
$trader = "D:\aitrader"

function Set-Secret($name, $value) {
    if ([string]::IsNullOrWhiteSpace($value)) { Write-Host "  skip $name (empty)"; return }
    $value | gh secret set $name -R $repo
    if ($LASTEXITCODE -ne 0) { throw "gh secret set $name failed" }
    Write-Host "  set  $name"
}
function Read-EnvFile($path) {
    $h = @{}
    foreach ($line in Get-Content $path) {
        if ($line -match '^\s*([A-Z0-9_]+)\s*=\s*"?(.*?)"?\s*$') { $h[$Matches[1]] = $Matches[2] }
    }
    $h
}
function Read-Optional($prompt) {
    $s = Read-Host "$prompt (Enter to skip)" -AsSecureString
    [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}

Write-Host "ai-trader (from $trader\agent\.env)"
$agent = Read-EnvFile "$trader\agent\.env"
Set-Secret AITRADER_URL $agent["CLOUD_URL"]
Set-Secret TG_AITRADER_TOKEN $agent["TELEGRAM_BOT_TOKEN"]
Set-Secret TG_ALERT_TOKEN $agent["TELEGRAM_BOT_TOKEN"]   # alerts come from the ai-trader bot to your own chat
Set-Secret TG_ALERT_CHAT $agent["TELEGRAM_CHAT_ID"]

Write-Host "Values only you have"
# Not pulled from Vercel: `vercel env pull` writes "[SENSITIVE]" instead of the real value for these.
Set-Secret UPSTASH_URL (Read-Optional "Upstash REST URL (console -> database -> REST API)")
Set-Secret UPSTASH_READ_TOKEN (Read-Optional "Upstash READ-ONLY token (same page, 'Read-Only Token')")
Set-Secret TG_JOBS_TOKEN (Read-Optional "job-autopilot Telegram bot token")
Set-Secret HC_PING_URL (Read-Optional "healthchecks.io ping URL")
Set-Secret UPSTASH_DB_ID (Read-Optional "Upstash database id (console -> database -> details)")
Set-Secret UPSTASH_EMAIL (Read-Optional "Upstash account email")
Set-Secret UPSTASH_API_KEY (Read-Optional "Upstash management API key (console -> Account -> Management API)")

Write-Host "GitHub Pages (built by Actions)"
gh api -X POST "repos/$repo/pages" -f build_type=workflow 2>$null | Out-Null
gh api -X PUT "repos/$repo/pages" -f build_type=workflow | Out-Null
gh workflow run probe.yml -R $repo
Write-Host "Done. First run started: https://github.com/$repo/actions"
