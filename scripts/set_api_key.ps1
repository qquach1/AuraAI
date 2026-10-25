# Prompts for your Anthropic API key (input hidden) and writes it to a .env file, replacing only
# the ANTHROPIC_API_KEY line. .env is gitignored: never commit it.
#   powershell -ExecutionPolicy Bypass -File scripts\set_api_key.ps1 [-Path C:\path\to\.env]
param([string]$Path = (Join-Path (Resolve-Path "$PSScriptRoot\..").Path ".env"))

$secure = Read-Host "Paste your NEW Anthropic API key (input hidden), then press Enter" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $key = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($bstr).Trim() }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr) }
if (-not $key.StartsWith("sk-ant-")) {
    Write-Warning "That doesn't look like an Anthropic API key (it should start with sk-ant-). Nothing was written."
    exit 1
}
$lines = @()
if (Test-Path $Path) { $lines = @(Get-Content $Path | Where-Object { $_ -notmatch '^\s*ANTHROPIC_API_KEY\s*=' }) }
$lines += "ANTHROPIC_API_KEY=$key"
[IO.File]::WriteAllText($Path, (($lines -join "`n") + "`n"))
Write-Host "Saved to $Path"
