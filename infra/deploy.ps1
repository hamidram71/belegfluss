<#
.SYNOPSIS
  Deploys Belegfluss to Azure (Container Apps + PostgreSQL with pgvector). See infra/README.md.

.EXAMPLE
  ./infra/deploy.ps1 -GitHubUser hamidram71 -Email you@example.com
#>
param(
    [Parameter(Mandatory = $true)] [string] $GitHubUser,
    [string] $ResourceGroup = "belegfluss-rg",
    [string] $Location = "northeurope",
    [string] $ImageTag = "latest",
    [string] $Email = ""
)
# Native commands (az) report failure through $LASTEXITCODE, not through PowerShell errors.
# "Stop" would turn harmless stderr output into a fatal error in Windows PowerShell 5.1,
# so failures are checked explicitly after every az call instead.
$ErrorActionPreference = "Continue"

function Assert-AzSucceeded([string] $What) {
    if ($LASTEXITCODE -ne 0) {
        Write-Host "FAILED: $What (exit code $LASTEXITCODE). See the az output above." -ForegroundColor Red
        exit 1
    }
}

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    Write-Host "Azure CLI not found. Install it with: winget install --id Microsoft.AzureCLI -e" -ForegroundColor Red
    exit 1
}

az account show --output none 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Not logged in to Azure; opening the login ..."
    az login --output none
    Assert-AzSucceeded "az login"
}
$subscription = az account show --query name -o tsv
Write-Host "Using subscription: $subscription"

# Fail fast: free-trial subscriptions often may not create PostgreSQL in some regions
# (germanywestcentral answered "The value of the 'Version' should be in: []" after minutes).
Write-Host "Checking PostgreSQL Flexible Server (B1ms, version 16) in $Location ..."
$skus = az postgres flexible-server list-skus --location $Location -o json 2>$null | Out-String
if ($LASTEXITCODE -ne 0 -or $skus -notmatch "Standard_B1ms" -or $skus -notmatch '"16"') {
    Write-Host "PostgreSQL B1ms / version 16 is not available to this subscription in $Location." -ForegroundColor Red
    Write-Host "Try another region, for example: -Location northeurope, westeurope or swedencentral"
    exit 1
}

$openAiKey = Read-Host "OpenAI API key" -AsSecureString
# Letters and digits only: the password is embedded in a connection string.
$chars = [char[]]"abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
$pgPassword = -join (1..24 | ForEach-Object { $chars | Get-Random })

Write-Host "Creating resource group $ResourceGroup in $Location ..."
az group create --name $ResourceGroup --location $Location --tags project=belegfluss --output none
Assert-AzSucceeded "creating the resource group"

$image = "ghcr.io/$($GitHubUser.ToLower())/belegfluss-demo:$ImageTag"
Write-Host "Deploying $image (this takes 5-10 minutes, mostly PostgreSQL) ..."
$plainKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($openAiKey))
$outputs = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$PSScriptRoot/main.bicep" `
    --parameters image=$image openAiApiKey=$plainKey postgresAdminPassword=$pgPassword `
                 budgetContactEmail=$Email `
    --query properties.outputs -o json
$exitCode = $LASTEXITCODE
$plainKey = $null
if ($exitCode -ne 0) {
    Write-Host "FAILED: the deployment (exit code $exitCode). See the az output above." -ForegroundColor Red
    exit 1
}

$result = $outputs | ConvertFrom-Json
Write-Host ""
Write-Host "Done. API: $($result.apiUrl.value)/docs" -ForegroundColor Green
Write-Host "The first request after idle takes a few seconds (scale from zero)."
Write-Host "Delete everything with: az group delete --name $ResourceGroup --yes"
