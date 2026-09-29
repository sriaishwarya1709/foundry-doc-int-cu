<#
.SYNOPSIS
  Deploy everything from your machine (no GitHub needed): Bicep -> .env -> bootstrap -> web app.
.EXAMPLE
  ./scripts/deploy-local.ps1 -ResourceGroup rg-docdemo -Seed
#>
param(
  [Parameter(Mandatory)] [string] $ResourceGroup,
  [string] $Location = 'swedencentral',
  [string] $EnvironmentName = 'docdemo',
  [switch] $Seed,
  [switch] $SkipAppDeploy
)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$env:ENVIRONMENT_NAME = $EnvironmentName
$env:AZURE_LOCATION = $Location
$env:DEPLOYER_PRINCIPAL_ID = az ad signed-in-user show --query id -o tsv
$env:DEPLOYER_PRINCIPAL_TYPE = 'User'

Write-Host "==> Provisioning infrastructure in $ResourceGroup ($Location)" -ForegroundColor Cyan
az group create -n $ResourceGroup -l $Location -o none
$outputs = az deployment group create -g $ResourceGroup -n "docdemo-local" --parameters infra/main.bicepparam `
  --query properties.outputs -o json | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Bicep deployment failed' }

$lines = $outputs.PSObject.Properties | ForEach-Object { "$($_.Name)=$($_.Value.value)" }
[IO.File]::WriteAllLines((Join-Path $root '.env'), [string[]]$lines)
Write-Host "==> Wrote .env" -ForegroundColor Cyan

Write-Host "==> Installing Python dependencies" -ForegroundColor Cyan
if (-not (Test-Path .venv)) { python -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -q -r src/requirements.txt

Write-Host "==> Bootstrapping CU defaults, Search index and Foundry agent" -ForegroundColor Cyan
Push-Location src
for ($i = 1; $i -le 5; $i++) {
  & ..\.venv\Scripts\python.exe -m app.bootstrap
  if ($LASTEXITCODE -eq 0) { break }
  if ($i -eq 5) { Pop-Location; throw 'Bootstrap failed' }
  Write-Host "Retrying in 60s (role assignments can take a few minutes to propagate)..." -ForegroundColor Yellow
  Start-Sleep 60
}
Pop-Location

if (-not $SkipAppDeploy) {
  Write-Host "==> Deploying web app" -ForegroundColor Cyan
  $zip = Join-Path $env:TEMP 'docdemo-app'
  & .\.venv\Scripts\python.exe -c "import shutil; shutil.make_archive(r'$zip', 'zip', 'src')"
  az webapp deploy -g $ResourceGroup -n $outputs.WEB_APP_NAME.value --src-path "$zip.zip" --type zip -o none

  if ($Seed) {
    Write-Host "==> Seeding sample documents through the web app (both engines)" -ForegroundColor Cyan
    $seeds = @(
      @('invoice-contoso.pdf', 'prebuilt-invoice', 'prebuilt-invoice'),
      @('receipt-contoso.png', 'prebuilt-receipt', 'prebuilt-receipt'),
      @('contract-property-management.pdf', 'prebuilt-contract', 'prebuilt-documentSearch')
    )
    foreach ($s in $seeds) {
      curl.exe -fsS --max-time 600 -F "file=@samples/$($s[0])" -F engine=both -F di_model=$($s[1]) -F cu_analyzer=$($s[2]) "$($outputs.WEB_APP_URL.value)/api/ingest" | Out-Null
      Write-Host "    ingested $($s[0])"
    }
  }
}

Write-Host "`nDone." -ForegroundColor Green
Write-Host "Web app : $($outputs.WEB_APP_URL.value)"
