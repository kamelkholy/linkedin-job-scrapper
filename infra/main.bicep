// LinkedIn Scrapper — Azure Container Apps + Cosmos DB.
// Provisions:
//   - Log Analytics workspace
//   - Azure Container Registry (Basic)
//   - User-assigned Managed Identity (used by both compute resources)
//   - Cosmos DB (NoSQL Core API, serverless) + database + 3 containers
//   - Container Apps Environment
//   - Container App for the Flask web UI (public ingress)
//   - Container Apps Job for the daily scrape (cron schedule)

@description('Short prefix used to derive resource names. Must be 3-12 lowercase alphanumeric chars.')
@minLength(3)
@maxLength(12)
param prefix string = 'lkdscraper'

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Container image tag (e.g. v1, or a git SHA). Bicep uses ACR\'s login server prefix.')
param imageTag string = 'latest'

@description('Name of an existing Azure Container Registry (created by deploy.ps1 before this Bicep runs).')
param acrName string

@description('UTC cron expression for the daily scrape (default: 06:00 UTC daily).')
param cronExpression string = '0 6 * * *'

@description('Max concurrent executions of the daily job. Keep at 1.')
param jobReplicaCount int = 1

@description('Job timeout in seconds — the scrape can take a while across multiple locations.')
param jobTimeoutSeconds int = 3600

@description('Username for HTTP Basic Auth on the web UI. Leave empty along with authPassword to disable auth.')
param authUsername string = 'admin'

@description('Password for HTTP Basic Auth on the web UI. Stored as a Container Apps secret. Leave empty to disable auth.')
@secure()
param authPassword string = ''

@description('Optional: tag for the resources.')
param tags object = {
  app: 'linkedin-scraper'
}

// ── Naming ───────────────────────────────────────────────────────────────
var uniq            = uniqueString(resourceGroup().id)
var lawName         = '${prefix}-law'
var identityName    = '${prefix}-id'
var cosmosName      = toLower('${prefix}-cosmos-${take(uniq, 6)}')
var cosmosDbName    = 'linkedinscraper'
var envName         = '${prefix}-env'
var webAppName      = '${prefix}-web'
var jobName         = '${prefix}-job'
var imageName       = 'linkedin-scraper'
var fullImage       = '${acr.properties.loginServer}/${imageName}:${imageTag}'

// ── Log Analytics ────────────────────────────────────────────────────────
resource law 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: lawName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

// ── ACR (created beforehand by deploy.ps1) ───────────────────────────────
resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' existing = {
  name: acrName
}

// ── User-assigned Managed Identity ───────────────────────────────────────
resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: identityName
  location: location
  tags: tags
}

// AcrPull role for the identity on the registry (lets Container Apps pull images).
var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'
resource acrPullAssignment 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, identity.id, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: identity.properties.principalId
    principalType: 'ServicePrincipal'
  }
}

// ── Cosmos DB (serverless NoSQL Core) ────────────────────────────────────
resource cosmos 'Microsoft.DocumentDB/databaseAccounts@2024-05-15' = {
  name: cosmosName
  location: location
  tags: tags
  kind: 'GlobalDocumentDB'
  properties: {
    databaseAccountOfferType: 'Standard'
    locations: [
      {
        locationName: location
        failoverPriority: 0
      }
    ]
    capabilities: [
      { name: 'EnableServerless' }
    ]
    consistencyPolicy: {
      defaultConsistencyLevel: 'Session'
    }
    publicNetworkAccess: 'Enabled'
    disableLocalAuth: false
  }
}

resource cosmosDb 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases@2024-05-15' = {
  parent: cosmos
  name: cosmosDbName
  properties: {
    resource: { id: cosmosDbName }
  }
}

resource jobsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDb
  name: 'jobs'
  properties: {
    resource: {
      id: 'jobs'
      partitionKey: {
        paths: [ '/source' ]
        kind: 'Hash'
      }
    }
  }
}

resource settingsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDb
  name: 'settings'
  properties: {
    resource: {
      id: 'settings'
      partitionKey: {
        paths: [ '/id' ]
        kind: 'Hash'
      }
    }
  }
}

resource runsContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDb
  name: 'runs'
  properties: {
    resource: {
      id: 'runs'
      partitionKey: {
        paths: [ '/yearMonth' ]
        kind: 'Hash'
      }
    }
  }
}

resource companiesContainer 'Microsoft.DocumentDB/databaseAccounts/sqlDatabases/containers@2024-05-15' = {
  parent: cosmosDb
  name: 'companies'
  properties: {
    resource: {
      id: 'companies'
      partitionKey: {
        paths: [ '/id' ]
        kind: 'Hash'
      }
    }
  }
}

// Cosmos DB built-in data plane RBAC: Data Contributor.
// Grants the identity full data-plane access to this Cosmos account.
resource cosmosDataContributor 'Microsoft.DocumentDB/databaseAccounts/sqlRoleAssignments@2024-05-15' = {
  parent: cosmos
  name: guid(cosmos.id, identity.id, '00000000-0000-0000-0000-000000000002')
  properties: {
    // Built-in role: Cosmos DB Built-in Data Contributor
    roleDefinitionId: '${cosmos.id}/sqlRoleDefinitions/00000000-0000-0000-0000-000000000002'
    principalId: identity.properties.principalId
    scope: cosmos.id
  }
}

// ── Container Apps Environment ───────────────────────────────────────────
resource cae 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: envName
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: {
        customerId: law.properties.customerId
        sharedKey: law.listKeys().primarySharedKey
      }
    }
  }
}

// Common env block for both compute resources.
var sharedEnv = [
  {
    name: 'COSMOS_ENDPOINT'
    value: cosmos.properties.documentEndpoint
  }
  {
    name: 'COSMOS_DB'
    value: cosmosDbName
  }
  {
    name: 'AZURE_CLIENT_ID'
    value: identity.properties.clientId
  }
]

// HTTP Basic Auth — only added when a password was supplied.
var authEnabled = !empty(authPassword)
var authSecrets = authEnabled ? [
  {
    name: 'auth-password'
    value: authPassword
  }
] : []
var authEnv = authEnabled ? [
  {
    name: 'AUTH_USERNAME'
    value: authUsername
  }
  {
    name: 'AUTH_PASSWORD'
    secretRef: 'auth-password'
  }
] : []

// ── Web UI (Container App) ───────────────────────────────────────────────
resource webApp 'Microsoft.App/containerApps@2024-03-01' = {
  name: webAppName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    managedEnvironmentId: cae.id
    configuration: {
      activeRevisionsMode: 'Single'
      secrets: authSecrets
      ingress: {
        external: true
        targetPort: 8000
        transport: 'auto'
        allowInsecure: false
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'web'
          image: fullImage
          resources: {
            cpu: json('0.5')
            memory: '1Gi'
          }
          env: concat(sharedEnv, [
            {
              name: 'DISABLE_SCHEDULER'
              value: '1'
            }
            {
              name: 'PORT'
              value: '8000'
            }
          ], authEnv)
        }
      ]
      scale: {
        minReplicas: 1
        maxReplicas: 1
      }
    }
  }
  dependsOn: [
    acrPullAssignment
    cosmosDataContributor
  ]
}

// ── Daily scrape (Container Apps Job, cron-triggered) ────────────────────
resource scrapeJob 'Microsoft.App/jobs@2024-03-01' = {
  name: jobName
  location: location
  tags: tags
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: {
      '${identity.id}': {}
    }
  }
  properties: {
    environmentId: cae.id
    configuration: {
      triggerType: 'Schedule'
      replicaTimeout: jobTimeoutSeconds
      replicaRetryLimit: 1
      scheduleTriggerConfig: {
        cronExpression: cronExpression
        parallelism: jobReplicaCount
        replicaCompletionCount: jobReplicaCount
      }
      registries: [
        {
          server: acr.properties.loginServer
          identity: identity.id
        }
      ]
    }
    template: {
      containers: [
        {
          name: 'scraper'
          image: fullImage
          command: [ 'python', 'runner_job.py' ]
          resources: {
            cpu: json('1.0')
            memory: '2Gi'
          }
          env: sharedEnv
        }
      ]
    }
  }
  dependsOn: [
    acrPullAssignment
    cosmosDataContributor
  ]
}

// ── Outputs (used by deploy.ps1) ─────────────────────────────────────────
output webUrl string = 'https://${webApp.properties.configuration.ingress.fqdn}'
output cosmosEndpoint string = cosmos.properties.documentEndpoint
output identityClientId string = identity.properties.clientId
output identityPrincipalId string = identity.properties.principalId
output jobName string = scrapeJob.name
output webAppName string = webApp.name
