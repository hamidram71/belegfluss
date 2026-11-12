// Belegfluss on Azure, sized for an Azure free account (ADR 0010).
//
//   Container Apps (consumption, scales to zero)  ->  API, demo dataset baked into the image
//   PostgreSQL Flexible Server B1ms + pgvector     ->  contract index (free for 12 months)
//   Azure Files                                     ->  uploaded documents and review queue
//   Log Analytics (daily cap)                       ->  container logs
//
// The LLM is called through the OpenAI API (key stored as a Container Apps secret). Switching
// to Azure OpenAI later is configuration only: BELEGFLUSS_LLM_PROVIDER=azure plus endpoint.

targetScope = 'resourceGroup'

@description('Azure region. Free-trial subscriptions restrict PostgreSQL in some regions; deploy.ps1 checks availability first.')
param location string = resourceGroup().location

@description('Short lowercase prefix for resource names.')
@minLength(3)
@maxLength(12)
param namePrefix string = 'belegfluss'

@description('Public container image, e.g. ghcr.io/<github-user>/belegfluss-demo:latest')
param image string

@description('OpenAI API key, stored as a Container Apps secret.')
@secure()
param openAiApiKey string

@description('LLM used for PDFs, scans and hard cases.')
param llmModel string = 'gpt-6-luna'

@description('Embedding model for the contract index.')
param embeddingModel string = 'text-embedding-3-small'

@description('Optional: USD per million input tokens, to show an estimated cost per match. Empty = no estimate.')
param llmInputUsdPerMtok string = ''

@description('Optional: USD per million output tokens.')
param llmOutputUsdPerMtok string = ''

@description('PostgreSQL administrator login (not admin, root, postgres ...).')
param postgresAdminLogin string = 'belegflussadmin'

@description('PostgreSQL administrator password: 16+ characters, letters and digits only.')
@secure()
@minLength(16)
param postgresAdminPassword string

@description('E-mail address for the budget alert. Empty = no budget.')
param budgetContactEmail string = ''

@description('Monthly budget in the subscription currency for the alert.')
param budgetAmount int = 10

@description('First day of the current month, for the budget start date.')
param budgetStartDate string = utcNow('yyyy-MM-01')

var suffix = uniqueString(resourceGroup().id)
var postgresName = '${namePrefix}-pg-${suffix}'
var storageName = take(toLower('${namePrefix}st${suffix}'), 24)
var shareName = 'belegfluss-var'
var tags = { project: 'belegfluss' }

// --- Logs ---------------------------------------------------------------------------------
resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${namePrefix}-logs'
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
    workspaceCapping: { dailyQuotaGb: json('0.1') } // a demo never needs more; caps the cost
  }
}

// --- PostgreSQL with pgvector -------------------------------------------------------------
resource postgres 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: postgresName
  location: location
  tags: tags
  sku: { name: 'Standard_B1ms', tier: 'Burstable' } // free-account eligible
  properties: {
    version: '16'
    administratorLogin: postgresAdminLogin
    administratorLoginPassword: postgresAdminPassword
    storage: { storageSizeGB: 32 } // the free-account limit
    backup: { backupRetentionDays: 7, geoRedundantBackup: 'Disabled' }
    highAvailability: { mode: 'Disabled' }
    network: { publicNetworkAccess: 'Enabled' }
  }
}

// pgvector must be allow-listed before CREATE EXTENSION works.
resource pgExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: postgres
  name: 'azure.extensions'
  properties: { value: 'VECTOR', source: 'user-override' }
}

resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = {
  parent: postgres
  name: 'belegfluss'
  properties: { charset: 'UTF8', collation: 'en_US.utf8' }
  dependsOn: [pgExtensions]
}

// Container Apps outbound addresses are not fixed on the consumption plan; this rule allows
// connections from Azure services only (0.0.0.0). Traffic is TLS and password protected.
// Production would use VNet integration and private access instead (see ADR 0010).
resource allowAzure 'Microsoft.DBforPostgreSQL/flexibleServers/firewallRules@2024-08-01' = {
  parent: postgres
  name: 'AllowAzureServices'
  properties: { startIpAddress: '0.0.0.0', endIpAddress: '0.0.0.0' }
}

// --- Persistent files ---------------------------------------------------------------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  sku: { name: 'Standard_LRS' }
  kind: 'StorageV2'
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    supportsHttpsTrafficOnly: true
  }
}

resource fileService 'Microsoft.Storage/storageAccounts/fileServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource share 'Microsoft.Storage/storageAccounts/fileServices/shares@2023-05-01' = {
  parent: fileService
  name: shareName
  properties: { shareQuota: 1 } // GiB
}

// --- Container Apps -----------------------------------------------------------------------
resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${namePrefix}-env'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: logs.properties.customerId
        sharedKey: logs.listKeys().primarySharedKey
      }
    }
  }
}

resource environmentStorage 'Microsoft.App/managedEnvironments/storages@2024-03-01' = {
  parent: environment
  name: 'belegfluss-var'
  properties: {
    azureFile: {
      accountName: storage.name
      accountKey: storage.listKeys().keys[0].value
      shareName: share.name
      accessMode: 'ReadWrite'
    }
  }
}

var databaseUrl = 'host=${postgres.properties.fullyQualifiedDomainName} port=5432 dbname=${database.name} user=${postgresAdminLogin} password=${postgresAdminPassword} sslmode=require'

resource api 'Microsoft.App/containerApps@2024-03-01' = {
  name: '${namePrefix}-api'
  location: location
  tags: tags
  properties: {
    managedEnvironmentId: environment.id
    configuration: {
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      secrets: [
        { name: 'openai-api-key', value: openAiApiKey }
        { name: 'database-url', value: databaseUrl }
      ]
    }
    template: {
      containers: [
        {
          name: 'api'
          image: image
          resources: { cpu: json('0.5'), memory: '1Gi' }
          env: concat([
            { name: 'BELEGFLUSS_ENVIRONMENT', value: 'azure' }
            { name: 'BELEGFLUSS_STORAGE_DIR', value: '/app/var/documents' }
            { name: 'BELEGFLUSS_MATCHES_DIR', value: '/app/var/matches' }
            { name: 'BELEGFLUSS_LLM_PROVIDER', value: 'openai' }
            { name: 'BELEGFLUSS_LLM_MODEL', value: llmModel }
            { name: 'BELEGFLUSS_EMBEDDING_MODEL', value: embeddingModel }
            { name: 'BELEGFLUSS_ADJUDICATOR', value: 'hybrid' }
            { name: 'OPENAI_API_KEY', secretRef: 'openai-api-key' }
            { name: 'BELEGFLUSS_DATABASE_URL', secretRef: 'database-url' }
          ], empty(llmInputUsdPerMtok) || empty(llmOutputUsdPerMtok) ? [] : [
            { name: 'BELEGFLUSS_LLM_INPUT_USD_PER_MTOK', value: llmInputUsdPerMtok }
            { name: 'BELEGFLUSS_LLM_OUTPUT_USD_PER_MTOK', value: llmOutputUsdPerMtok }
          ])
          volumeMounts: [{ volumeName: 'var', mountPath: '/app/var' }]
          probes: [
            {
              type: 'Liveness'
              httpGet: { path: '/health', port: 8000 }
              initialDelaySeconds: 10
              periodSeconds: 30
            }
          ]
        }
      ]
      volumes: [
        { name: 'var', storageType: 'AzureFile', storageName: environmentStorage.name }
      ]
      scale: { minReplicas: 0, maxReplicas: 1 } // scale to zero: no cost while idle
    }
  }
  dependsOn: [allowAzure]
}

// --- Optional budget alert ----------------------------------------------------------------
resource budget 'Microsoft.Consumption/budgets@2023-11-01' = if (!empty(budgetContactEmail)) {
  name: '${namePrefix}-budget'
  properties: {
    category: 'Cost'
    amount: budgetAmount
    timeGrain: 'Monthly'
    timePeriod: { startDate: budgetStartDate }
    notifications: {
      actual80: {
        enabled: true
        operator: 'GreaterThanOrEqualTo'
        threshold: 80
        contactEmails: [budgetContactEmail]
        thresholdType: 'Actual'
      }
    }
  }
}

output apiUrl string = 'https://${api.properties.configuration.ingress.fqdn}'
output postgresServer string = postgres.properties.fullyQualifiedDomainName
