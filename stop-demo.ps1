<#
.SYNOPSIS
  Stop exactly the processes run-demo started (listed in data\demo.pids), with their children.
#>
[CmdletBinding()]
param()

. (Join-Path $PSScriptRoot 'infra\demo\demo-lib.ps1')
Write-Step "Stopping the demo"
Stop-DemoProcesses
exit 0
