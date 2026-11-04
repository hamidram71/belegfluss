<#
.SYNOPSIS
  Deploys Belegfluss to Azure (Container Apps + PostgreSQL with pgvector). See infra/README.md.

.EXAMPLE
  ./infra/deploy.ps1 -GitHubUser hamidram71 -Email you@example.com
#>
param(
    [Parameter(Mandatory = $true)] [string] $GitHubUser,
    [string] $ResourceGroup = "belegfluss-rg",
    [string] $Location = "germanywestcentral",
    [string] $ImageTag = "latest",
    [string] $Email = ""
)
$ErrorActionPreference = "Stop"

if (-not (Get-Command az -ErrorAction SilentlyContinue)) {
    throw "Azure CLI not found. Install it with: winget install --id Microsoft.AzureCLI -e"
}
az account show 1>$null 2>$null
if ($LASTEXITCODE -ne 0) { az login | Out-Null }

$openAiKey = Read-Host "OpenAI API key" -AsSecureString
# Letters and digits only: the password is embedded in a connection string.
$chars = [char[]]"abcdefghijkmnopqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
$pgPassword = -join (1..24 | ForEach-Object { $chars | Get-Random })

Write-Host "Creating resource group $ResourceGroup in $Location ..."
az group create --name $ResourceGroup --location $Location --tags project=belegfluss | Out-Null

$image = "ghcr.io/$($GitHubUser.ToLower())/belegfluss-demo:$ImageTag"
Write-Host "Deploying $image (this takes 5-10 minutes, mostly PostgreSQL) ..."
$plainKey = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
    [Runtime.InteropServices.Marshal]::SecureStringToBSTR($openAiKey))
$result = az deployment group create `
    --resource-group $ResourceGroup `
    --template-file "$PSScriptRoot/main.bicep" `
    --parameters image=$image openAiApiKey=$plainKey postgresAdminPassword=$pgPassword `
                 budgetContactEmail=$Email `
    --query properties.outputs -o json | ConvertFrom-Json
$plainKey = $null

Write-Host ""
Write-Host "Done. API: $($result.apiUrl.value)/docs"
Write-Host "The first request after idle takes a few seconds (scale from zero)."
Write-Host "Delete everything with: az group delete --name $ResourceGroup --yes"
