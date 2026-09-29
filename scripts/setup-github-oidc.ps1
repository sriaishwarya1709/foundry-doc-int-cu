<#
.SYNOPSIS
  One-time setup of GitHub Actions -> Azure OIDC (no secrets) for this repo.
  Creates an Entra app + service principal with a federated credential for the main branch,
  grants Contributor + Role Based Access Control Administrator on the resource group,
  and sets the repository variables used by .github/workflows/deploy.yml.
.EXAMPLE
  ./scripts/setup-github-oidc.ps1 -Repo myorg/foundry-doc-int-cu -ResourceGroup rg-docdemo
#>
param(
  [Parameter(Mandatory)] [string] $Repo,
  [Parameter(Mandatory)] [string] $ResourceGroup,
  [string] $Location = 'swedencentral',
  [string] $EnvironmentName = 'docdemo',
  [string] $Branch = 'main'
)
$ErrorActionPreference = 'Stop'

$subscriptionId = az account show --query id -o tsv
$tenantId = az account show --query tenantId -o tsv
az group create -n $ResourceGroup -l $Location -o none
$rgId = az group show -n $ResourceGroup --query id -o tsv

$appName = "gh-$($Repo.Replace('/', '-'))"
$appId = az ad app list --display-name $appName --query '[0].appId' -o tsv
if (-not $appId) { $appId = az ad app create --display-name $appName --query appId -o tsv }
$spId = az ad sp list --filter "appId eq '$appId'" --query '[0].id' -o tsv
if (-not $spId) { $spId = az ad sp create --id $appId --query id -o tsv }

$ownerName, $repoName = $Repo.Split('/')
$ownerId = gh api "users/$ownerName" -q .id
$repoId = gh api "repos/$Repo" -q .id
$subjects = @{
  "github-$Branch"     = "repo:${Repo}:ref:refs/heads/$Branch"
  # Newer repos issue ID-qualified subjects.
  "github-$Branch-ids" = "repo:$ownerName@$ownerId/$repoName@${repoId}:ref:refs/heads/$Branch"
}
foreach ($credName in $subjects.Keys) {
  if (az ad app federated-credential list --id $appId --query "[?name=='$credName'].name" -o tsv) { continue }
  $fic = @{ name = $credName; issuer = 'https://token.actions.githubusercontent.com'; subject = $subjects[$credName]; audiences = @('api://AzureADTokenExchange') } | ConvertTo-Json -Compress
  $tmp = New-TemporaryFile; Set-Content $tmp $fic
  az ad app federated-credential create --id $appId --parameters "@$tmp" -o none
  Remove-Item $tmp
}

# Contributor to create resources; RBAC Administrator so Bicep can create the role assignments.
foreach ($role in 'Contributor', 'Role Based Access Control Administrator') {
  az role assignment create --assignee-object-id $spId --assignee-principal-type ServicePrincipal --role $role --scope $rgId -o none
}

$vars = @{
  AZURE_CLIENT_ID       = $appId
  AZURE_TENANT_ID       = $tenantId
  AZURE_SUBSCRIPTION_ID = $subscriptionId
  AZURE_SP_OBJECT_ID    = $spId
  AZURE_RESOURCE_GROUP  = $ResourceGroup
  AZURE_LOCATION        = $Location
  ENVIRONMENT_NAME      = $EnvironmentName
}
foreach ($k in $vars.Keys) { gh variable set $k --repo $Repo --body $vars[$k] }
Write-Host "GitHub OIDC configured for $Repo. Run the 'deploy' workflow." -ForegroundColor Green
