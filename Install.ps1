param([switch]$Uninstall)
$ErrorActionPreference = 'Stop'
$id = '{A3F248D9-4C38-42DA-B020-097445264E71}'
$destination = Join-Path $env:ProgramData 'Alibre AddOns\SlidingDovetailJointManager'
$legacyDestination = @('C:\ProgramData\Alibre AddOns\SlidingDovetailPrototype', 'C:\Program Files\Alibre Design\Addons\SlidingDovetailPrototype', 'C:\Program Files\Alibre Design\Addons\SlidingDovetailJointManager')
$keys = @('HKLM:\SOFTWARE\Alibre Design Add-Ons', 'HKLM:\SOFTWARE\WOW6432Node\Alibre Design Add-Ons')
$legacyKey = 'HKLM:\SOFTWARE\Alibre, LLC\Alibre Design\Addons\SlidingDovetailJointManager'
$uninstallKeys = @(
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{B23B3ACB-1BFC-4AF4-A9AA-5D6590B7BAAA}_is1',
  'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\{A3F248D9-4C38-42DA-B020-097445264E71}_is1_is1'
)
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (!$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) { throw 'Run Install.cmd and approve the administrator prompt.' }
if (Get-Process -Name 'Alibre Design' -ErrorAction SilentlyContinue) { throw 'Close Alibre Design before installing or uninstalling.' }

function Remove-DovetailArtifacts {
  foreach ($key in $keys) {
    if (Test-Path -LiteralPath $key) { Remove-ItemProperty -LiteralPath $key -Name $id -ErrorAction SilentlyContinue }
  }
  if (Test-Path -LiteralPath $legacyKey) { Remove-Item -LiteralPath $legacyKey -Recurse -Force }
  foreach ($key in $uninstallKeys) { if (Test-Path -LiteralPath $key) { Remove-Item -LiteralPath $key -Recurse -Force } }
  foreach ($path in @($destination) + $legacyDestinations) {
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
  }
}

if ($Uninstall) {
  Remove-DovetailArtifacts
  Write-Output 'Removed every known Sliding Dovetail installation. Spline Tools was not touched.'
  exit
}

$files = @('SlidingDovetailAddon05.dll','SlidingDovetailJointManager.adc','SlidingDovetailJointManager.ico','scripts\bootstrap.py','scripts\manager.py','scripts\dt_defaults.py','scripts\dt_form.py')
foreach ($file in $files) { if (!(Test-Path -LiteralPath (Join-Path $PSScriptRoot $file))) { throw "Missing package file: $file" } }
# This clears only historical Sliding Dovetail registrations and folders.
# Spline Tools uses a different folder and is never enumerated or changed.
Remove-DovetailArtifacts
New-Item -ItemType Directory -Path (Join-Path $destination 'scripts') -Force | Out-Null
foreach ($file in $files) { Copy-Item -LiteralPath (Join-Path $PSScriptRoot $file) -Destination (Join-Path $destination $file) -Force }
New-Item -Path $keys[0] -Force | Out-Null
New-ItemProperty -LiteralPath $keys[0] -Name $id -Value $destination -PropertyType String -Force | Out-Null
Write-Output 'Installed the clean v0.8.0 test build. Restart Alibre Design.'