param([switch]$ListOnly)
$ErrorActionPreference='Stop'
$root=[IO.Path]::GetFullPath($PSScriptRoot)
$entry=Join-Path $root 'portable_entry.py'
$entryPattern=[regex]::Escape($entry)
$targets=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {
    $_.CommandLine -match $entryPattern -and $_.CommandLine -match '(launch_local\.py|server[/\\]backend\.py|client[/\\](ui|native_app)\.py)'
})
if($ListOnly){$targets|Select-Object ProcessId,ExecutablePath,CommandLine|Format-List;exit 0}
foreach($target in $targets){
    $current=Get-CimInstance Win32_Process -Filter "ProcessId=$($target.ProcessId)" -ErrorAction SilentlyContinue
    if($current -and $current.CommandLine -eq $target.CommandLine -and $current.CommandLine -match $entryPattern){
        Stop-Process -Id $target.ProcessId -ErrorAction SilentlyContinue
    }
}
Start-Sleep -Milliseconds 800
$remaining=@(Get-CimInstance Win32_Process -Filter "Name='python.exe' OR Name='pythonw.exe'" | Where-Object {$_.CommandLine -match $entryPattern -and $_.CommandLine -match '(launch_local\.py|server[/\\]backend\.py|client[/\\](ui|native_app)\.py)'})
if($remaining.Count){Write-Host 'Some bundle processes are still running.';exit 1}
Write-Host 'Motion capture UI and backend stopped. Warudo was not touched.'