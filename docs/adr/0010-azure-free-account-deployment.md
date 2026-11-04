# ADR 0010: Deployment on an Azure free account

- Status: accepted
- Date: 2026-11-04

## Context

The project needs a public, working deployment on Azure, the cloud most German enterprises
use. It runs on an Azure free account: $200 credit for 30 days and selected services free for
12 months. Two constraints shaped the design:

- Free-trial subscriptions get zero or very restricted quota for Azure OpenAI models; deploying
  a model requires upgrading to pay-as-you-go, which removes the spending cap.
- Anything that runs permanently (a VM, a container registry, an always-on replica) eats the
  credit, and after the trial unused resources would start to cost money.

## Decision

| Need | Choice | Why |
| --- | --- | --- |
| API | Azure Container Apps, consumption plan, 0 to 1 replicas | Free monthly grant; scales to zero, so idle costs nothing |
| Contract index | PostgreSQL Flexible Server B1ms, 32 GB, pgvector | Free for 12 months on a free account; same database as locally and in CI |
| Documents, review queue | Azure Files share mounted at /app/var | Survives restarts and scale to zero; a few cents per month |
| Image registry | GitHub Container Registry, public package | Free; Azure Container Registry costs a daily fee |
| LLM | OpenAI API, key as a Container Apps secret | Works on the trial; Azure OpenAI is a configuration switch later |
| Adjudicator | `hybrid` | Rules first, model only where rules cannot decide (ADR 0008 update) |
| Demo data | Synthetic dataset baked into a separate demo image | The hosted app works without uploading any real data |
| Infrastructure | One Bicep file, validated in CI | Reproducible; `az group delete` removes everything |
| Cost control | Log Analytics daily cap; optional budget alert | A runaway log stream or mistake cannot burn the credit |

## Consequences

- One command deploys and one command removes the whole stack.
- PostgreSQL accepts connections from Azure services (firewall rule 0.0.0.0) over TLS with a
  generated password, because consumption-plan Container Apps have no fixed outbound address.
  Production would use VNet integration and private access; this is a deliberate demo
  trade-off, documented here.
- The first request after idle takes a few seconds (scale from zero).
- The free credit lasts 30 days. Unless the subscription is upgraded, the deployment stops
  then; the demo video and the Bicep file are the lasting artefacts.
