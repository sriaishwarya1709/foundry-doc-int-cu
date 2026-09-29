using './main.bicep'

param environmentName = readEnvironmentVariable('ENVIRONMENT_NAME', 'docdemo')
param location = readEnvironmentVariable('AZURE_LOCATION', 'swedencentral')
param deployerPrincipalId = readEnvironmentVariable('DEPLOYER_PRINCIPAL_ID', '')
param deployerPrincipalType = readEnvironmentVariable('DEPLOYER_PRINCIPAL_TYPE', 'User')
