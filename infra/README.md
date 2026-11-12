# Deploying Belegfluss to Azure

Architecture and trade-offs: [ADR 0010](../docs/adr/0010-azure-free-account-deployment.md).
Everything fits an Azure free account; the OpenAI API is used for the LLM.

## Once: publish the demo image

1. Push to `main`. After CI passes, the workflow **Publish demo image** pushes
   `ghcr.io/<github-user>/belegfluss-demo:latest` (or run it by hand under *Actions*).
2. On GitHub: your profile, *Packages*, `belegfluss-demo`, *Package settings*, change
   visibility to **Public**. Azure pulls the image without credentials; it contains only code
   and synthetic data.

## Deploy (Windows PowerShell)

```powershell
winget install --id Microsoft.AzureCLI -e     # once; then open a new terminal
./infra/deploy.ps1 -GitHubUser <github-user> -Email you@example.com
```

The script asks for the OpenAI API key, generates a database password, creates the resource
group `belegfluss-rg` and deploys `main.bicep` (5-10 minutes). It prints the API address;
open `<address>/docs`. On the first match request the app builds the contract index in
PostgreSQL (a few cents of embeddings).

The script first checks that PostgreSQL B1ms (version 16) is available to the subscription in
the region; free-trial subscriptions are restricted in some regions. The default is
`northeurope`; choose another with `-Location westeurope` (or `swedencentral`).

## Update after a code change

Push to `main`; after the new image is published, deploy it by its commit SHA. (Re-using the
`latest` tag would not create a new revision, so the old image would keep running.)

```powershell
$sha = git rev-parse HEAD
az containerapp update -g belegfluss-rg -n belegfluss-api --image ghcr.io/<github-user>/belegfluss-demo:$sha
```

## Watch matches in the logs

Every match writes one JSON line (decision, findings, duration per step, tokens, estimated
cost). In the Azure portal: Log Analytics workspace `belegfluss-logs`, *Logs*:

```kusto
ContainerAppConsoleLogs_CL
| where Log_s has '"event": "match"'
| extend m = parse_json(substring(Log_s, indexof(Log_s, "{")))
| project TimeGenerated, decision = tostring(m.decision), findings = m.findings,
          duration_ms = toint(m.duration_ms), tokens_in = toint(m.input_tokens)
| order by TimeGenerated desc
```

To show an estimated cost per match, pass current prices (USD per million tokens) from the
provider's pricing page when deploying:
`az deployment group create ... --parameters llmInputUsdPerMtok=<in> llmOutputUsdPerMtok=<out>`.

## Remove everything

```powershell
az group delete --name belegfluss-rg --yes
```
