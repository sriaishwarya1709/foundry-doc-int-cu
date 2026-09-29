// Document Intelligence + Content Understanding + Foundry Agent demo
targetScope = 'resourceGroup'

@description('Short environment name used to derive resource names.')
@minLength(2)
@maxLength(12)
param environmentName string

@description('Region. Must support Content Understanding and the selected models.')
param location string = resourceGroup().location

@description('Object ID of the user or service principal running deployments / local dev. Gets data-plane roles.')
param deployerPrincipalId string = ''

@allowed(['User', 'ServicePrincipal'])
param deployerPrincipalType string = 'User'

@description('Chat model used by the Foundry agent and by Content Understanding field extraction.')
param chatModelName string = 'gpt-4.1'
param chatModelVersion string = '2025-04-14'
param chatModelCapacity int = 50

@description('Mini model required by Content Understanding prebuilt-*Search analyzers.')
param miniModelName string = 'gpt-4.1-mini'
param miniModelVersion string = '2025-04-14'
param miniModelCapacity int = 50

param embeddingModelName string = 'text-embedding-3-large'
param embeddingModelVersion string = '1'
param embeddingModelCapacity int = 50

param appServiceSku string = 'B2'

var token = toLower(uniqueString(subscription().id, resourceGroup().id, environmentName))
var foundryName = 'aif-${environmentName}-${token}'
var projectName = 'docintel-demo'
var searchName = 'srch-${environmentName}-${token}'
var storageName = take('st${replace(environmentName, '-', '')}${token}', 24)
var planName = 'plan-${environmentName}-${token}'
var webAppName = 'app-${environmentName}-${token}'
var logName = 'log-${environmentName}-${token}'
var appInsightsName = 'appi-${environmentName}-${token}'
var searchConnectionName = 'doc-search'
var searchIndexName = 'processed-documents'
var agentName = 'document-analyst'
var tags = { 'azd-env-name': environmentName, demo: 'docintel-cu-foundry' }

// Built-in role definition IDs
var roles = {
  cognitiveServicesUser: 'a97b65f3-24c7-4388-baec-2e87135dc908'
  cognitiveServicesOpenAIUser: '5e0bd9bd-7b93-4f28-af87-19fc36ad61bd'
  azureAIUser: '53ca6127-db72-4b80-b1b0-d745d6d5456d'
  storageBlobDataContributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
  searchIndexDataContributor: '8ebe5a00-799e-43f5-93ac-243d3dce84a7'
  searchServiceContributor: '7ca78c08-252a-4471-8644-bb5ff32d4ba0'
}

// ---------------- Observability ----------------
resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: logName
  location: location
  tags: tags
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  tags: tags
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: logAnalytics.id
  }
}

// ---------------- Microsoft Foundry (AI Services: DI + CU + OpenAI models + Agents) ----------------
resource foundry 'Microsoft.CognitiveServices/accounts@2025-06-01' = {
  name: foundryName
  location: location
  tags: tags
  kind: 'AIServices'
  sku: { name: 'S0' }
  identity: { type: 'SystemAssigned' }
  properties: {
    allowProjectManagement: true
    customSubDomainName: foundryName
    disableLocalAuth: true
    publicNetworkAccess: 'Enabled'
  }
}

resource project 'Microsoft.CognitiveServices/accounts/projects@2025-06-01' = {
  parent: foundry
  name: projectName
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    displayName: 'Document Intelligence Demo'
    description: 'Document ingestion with Document Intelligence and Content Understanding, queried by a Foundry agent.'
  }
}

// Deployments must be created sequentially on the same account.
resource chatDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: chatModelName
  sku: { name: 'GlobalStandard', capacity: chatModelCapacity }
  properties: {
    model: { format: 'OpenAI', name: chatModelName, version: chatModelVersion }
  }
  dependsOn: [project]
}

resource miniDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: miniModelName
  sku: { name: 'GlobalStandard', capacity: miniModelCapacity }
  properties: {
    model: { format: 'OpenAI', name: miniModelName, version: miniModelVersion }
  }
  dependsOn: [chatDeployment]
}

resource embeddingDeployment 'Microsoft.CognitiveServices/accounts/deployments@2025-06-01' = {
  parent: foundry
  name: embeddingModelName
  sku: { name: 'GlobalStandard', capacity: embeddingModelCapacity }
  properties: {
    model: { format: 'OpenAI', name: embeddingModelName, version: embeddingModelVersion }
  }
  dependsOn: [miniDeployment]
}

// ---------------- Azure AI Search ----------------
resource search 'Microsoft.Search/searchServices@2024-06-01-preview' = {
  name: searchName
  location: location
  tags: tags
  sku: { name: 'basic' }
  identity: { type: 'SystemAssigned' }
  properties: {
    replicaCount: 1
    partitionCount: 1
    hostingMode: 'default'
    semanticSearch: 'free'
    publicNetworkAccess: 'enabled'
    disableLocalAuth: false
    authOptions: {
      aadOrApiKey: { aadAuthFailureMode: 'http401WithBearerChallenge' }
    }
  }
}

// Foundry project connections: Search (for the agent tool) and App Insights (for tracing)
resource searchConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: searchConnectionName
  properties: {
    category: 'CognitiveSearch'
    target: 'https://${search.name}.search.windows.net'
    authType: 'AAD'
    isSharedToAll: true
    metadata: {
      ApiType: 'Azure'
      ResourceId: search.id
      location: search.location
    }
  }
}

resource appInsightsConnection 'Microsoft.CognitiveServices/accounts/projects/connections@2025-06-01' = {
  parent: project
  name: 'appinsights'
  properties: {
    category: 'AppInsights'
    target: appInsights.id
    authType: 'ApiKey'
    isSharedToAll: true
    credentials: { key: appInsights.properties.ConnectionString }
    metadata: {
      ApiType: 'Azure'
      ResourceId: appInsights.id
    }
  }
}

// ---------------- Storage (raw + processed documents) ----------------
resource storage 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: storageName
  location: location
  tags: tags
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    publicNetworkAccess: 'Disabled'
    minimumTlsVersion: 'TLS1_2'
    supportsHttpsTrafficOnly: true
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: storage
  name: 'default'
}

resource rawContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'documents'
}

resource processedContainer 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = {
  parent: blobService
  name: 'processed'
}

// ---------------- Network: storage is private-only (policy-friendly); web app reaches it via VNet ----------------
resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: 'vnet-${environmentName}-${token}'
  location: location
  tags: tags
  properties: {
    addressSpace: { addressPrefixes: ['10.60.0.0/16'] }
    subnets: [
      {
        name: 'app'
        properties: {
          addressPrefix: '10.60.1.0/24'
          delegations: [{ name: 'web', properties: { serviceName: 'Microsoft.Web/serverFarms' } }]
        }
      }
      {
        name: 'private-endpoints'
        properties: { addressPrefix: '10.60.2.0/24' }
      }
    ]
  }
}

resource blobDnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.blob.${environment().suffixes.storage}'
  location: 'global'
  tags: tags
}

resource blobDnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: blobDnsZone
  name: 'vnet-link'
  location: 'global'
  properties: {
    registrationEnabled: false
    virtualNetwork: { id: vnet.id }
  }
}

resource blobPrivateEndpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-blob-${token}'
  location: location
  tags: tags
  properties: {
    subnet: { id: '${vnet.id}/subnets/private-endpoints' }
    privateLinkServiceConnections: [
      {
        name: 'blob'
        properties: { privateLinkServiceId: storage.id, groupIds: ['blob'] }
      }
    ]
  }
}

resource blobPeDns 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: blobPrivateEndpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [{ name: 'blob', properties: { privateDnsZoneId: blobDnsZone.id } }]
  }
}

// ---------------- Web App ----------------
resource plan 'Microsoft.Web/serverfarms@2024-04-01' = {
  name: planName
  location: location
  tags: tags
  kind: 'linux'
  sku: { name: appServiceSku }
  properties: { reserved: true }
}

var projectEndpoint = 'https://${foundry.name}.services.ai.azure.com/api/projects/${project.name}'

resource webApp 'Microsoft.Web/sites@2024-04-01' = {
  name: webAppName
  location: location
  tags: union(tags, { 'azd-service-name': 'web' })
  kind: 'app,linux'
  identity: { type: 'SystemAssigned' }
  properties: {
    serverFarmId: plan.id
    httpsOnly: true
    virtualNetworkSubnetId: '${vnet.id}/subnets/app'
    vnetRouteAllEnabled: true
    siteConfig: {
      linuxFxVersion: 'PYTHON|3.11'
      alwaysOn: true
      ftpsState: 'Disabled'
      minTlsVersion: '1.2'
      appCommandLine: 'gunicorn -w 2 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 --timeout 600 app.main:app'
      appSettings: [
        { name: 'SCM_DO_BUILD_DURING_DEPLOYMENT', value: 'true' }
        { name: 'WEBSITES_PORT', value: '8000' }
        { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', value: appInsights.properties.ConnectionString }
        { name: 'AI_SERVICES_ENDPOINT', value: 'https://${foundry.name}.services.ai.azure.com/' }
        { name: 'DOCUMENT_INTELLIGENCE_ENDPOINT', value: foundry.properties.endpoint }
        { name: 'AZURE_OPENAI_ENDPOINT', value: 'https://${foundry.name}.openai.azure.com/' }
        { name: 'FOUNDRY_PROJECT_ENDPOINT', value: projectEndpoint }
        { name: 'CHAT_DEPLOYMENT', value: chatDeployment.name }
        { name: 'MINI_DEPLOYMENT', value: miniDeployment.name }
        { name: 'EMBEDDING_DEPLOYMENT', value: embeddingDeployment.name }
        { name: 'SEARCH_ENDPOINT', value: 'https://${search.name}.search.windows.net' }
        { name: 'SEARCH_INDEX_NAME', value: searchIndexName }
        { name: 'SEARCH_CONNECTION_NAME', value: searchConnection.name }
        { name: 'STORAGE_ACCOUNT_URL', value: storage.properties.primaryEndpoints.blob }
        { name: 'AGENT_NAME', value: agentName }
      ]
    }
  }
}

// ---------------- RBAC (keyless everywhere) ----------------
// Web app identity -> Foundry (DI, CU, embeddings, agents), Storage, Search
resource webFoundryRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for r in [roles.cognitiveServicesUser, roles.cognitiveServicesOpenAIUser, roles.azureAIUser]: {
    scope: foundry
    name: guid(foundry.id, webApp.id, r)
    properties: {
      principalId: webApp.identity.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    }
  }
]

resource webStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: storage
  name: guid(storage.id, webApp.id, roles.storageBlobDataContributor)
  properties: {
    principalId: webApp.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

resource webSearchRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for r in [roles.searchIndexDataContributor, roles.searchServiceContributor]: {
    scope: search
    name: guid(search.id, webApp.id, r)
    properties: {
      principalId: webApp.identity.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    }
  }
]

// Search identity -> Foundry embeddings (integrated vectorizer used by the agent's hybrid queries)
resource searchOpenAIRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: foundry
  name: guid(foundry.id, search.id, roles.cognitiveServicesOpenAIUser)
  properties: {
    principalId: search.identity.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cognitiveServicesOpenAIUser)
  }
}

// Foundry account + project identities -> Search (Agent Service Azure AI Search tool)
resource foundryAccountSearchRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for r in [roles.searchIndexDataContributor, roles.searchServiceContributor]: {
    scope: search
    name: guid(search.id, foundry.id, r)
    properties: {
      principalId: foundry.identity.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    }
  }
]

resource foundryProjectSearchRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for r in [roles.searchIndexDataContributor, roles.searchServiceContributor]: {
    scope: search
    name: guid(search.id, project.id, r)
    properties: {
      principalId: project.identity.principalId
      principalType: 'ServicePrincipal'
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    }
  }
]

// Deployer (you locally, or the GitHub Actions service principal) -> data-plane roles for bootstrap + local dev
resource deployerFoundryRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for r in [roles.cognitiveServicesUser, roles.cognitiveServicesOpenAIUser, roles.azureAIUser]: if (!empty(deployerPrincipalId)) {
    scope: foundry
    name: guid(foundry.id, deployerPrincipalId, r)
    properties: {
      principalId: deployerPrincipalId
      principalType: deployerPrincipalType
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    }
  }
]

resource deployerSearchRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for r in [roles.searchIndexDataContributor, roles.searchServiceContributor]: if (!empty(deployerPrincipalId)) {
    scope: search
    name: guid(search.id, deployerPrincipalId, r)
    properties: {
      principalId: deployerPrincipalId
      principalType: deployerPrincipalType
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', r)
    }
  }
]

resource deployerStorageRole 'Microsoft.Authorization/roleAssignments@2022-04-01' = if (!empty(deployerPrincipalId)) {
  scope: storage
  name: guid(storage.id, deployerPrincipalId, roles.storageBlobDataContributor)
  properties: {
    principalId: deployerPrincipalId
    principalType: deployerPrincipalType
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.storageBlobDataContributor)
  }
}

// ---------------- Outputs (consumed by GitHub Actions and local .env) ----------------
output WEB_APP_NAME string = webApp.name
output WEB_APP_URL string = 'https://${webApp.properties.defaultHostName}'
output AI_SERVICES_ENDPOINT string = 'https://${foundry.name}.services.ai.azure.com/'
output DOCUMENT_INTELLIGENCE_ENDPOINT string = foundry.properties.endpoint
output AZURE_OPENAI_ENDPOINT string = 'https://${foundry.name}.openai.azure.com/'
output FOUNDRY_PROJECT_ENDPOINT string = projectEndpoint
output CHAT_DEPLOYMENT string = chatDeployment.name
output MINI_DEPLOYMENT string = miniDeployment.name
output EMBEDDING_DEPLOYMENT string = embeddingDeployment.name
output SEARCH_ENDPOINT string = 'https://${search.name}.search.windows.net'
output SEARCH_INDEX_NAME string = searchIndexName
output SEARCH_CONNECTION_NAME string = searchConnection.name
output STORAGE_ACCOUNT_URL string = storage.properties.primaryEndpoints.blob
output AGENT_NAME string = agentName
