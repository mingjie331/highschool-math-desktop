param(
    [string]$Package,
    [string]$Target = 'D:\Apps\高中数学题库',
    [string]$BackupRoot,
    [switch]$Worker,
    [int]$CloseTimeoutSeconds = 30,
    [int]$TestFailAfter = 0
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
[AppContext]::SetSwitch('Switch.System.IO.UseLegacyPathHandling',$false)
[AppContext]::SetSwitch('Switch.System.IO.BlockLongPaths',$false)
Add-Type -AssemblyName System.IO.Compression.FileSystem

function Write-Json($Value, [string]$Path) {
    $parent = Split-Path -Parent $Path
    [void][IO.Directory]::CreateDirectory($parent)
    $temporary = "$Path.$([guid]::NewGuid().ToString('N')).tmp"
    [IO.File]::WriteAllText($temporary, ($Value | ConvertTo-Json -Depth 30), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temporary -Destination $Path -Force
}
function File-Hash([string]$Path) { $stream=[IO.File]::OpenRead($Path);$algorithm=[Security.Cryptography.SHA256]::Create();try { ([BitConverter]::ToString($algorithm.ComputeHash($stream))).Replace('-','').ToLowerInvariant() } finally { $stream.Dispose();$algorithm.Dispose() } }
$script:CheckedPaths=@{}
function Safe-Path([string]$Base, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name.Contains('\') -or $Name.Contains(':') -or $Name.Contains([char]0) -or $Name.StartsWith('/') -or ($Name.Split('/') | Where-Object { $_ -eq '..' -or $_ -eq '.' -or $_ -match '[. ]$' })) { throw "Unsafe package path: $Name" }
    $root = [IO.Path]::GetFullPath($Base).TrimEnd('\')
    $path = [IO.Path]::GetFullPath((Join-Path $root $Name))
    if (-not $path.StartsWith($root + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Path escaped its expected root' }
    $check = $path
    while ($check -and $check.StartsWith($root,[StringComparison]::OrdinalIgnoreCase)) {
        if($script:CheckedPaths.ContainsKey($check)){break}
        if (Test-Path -LiteralPath $check) {
            if ((Get-Item -LiteralPath $check -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "Linked update path refused: $check" }
        }
        $script:CheckedPaths[$check]=$true
        if ($check -eq $root) { break }
        $check = Split-Path -Parent $check
    }
    $path
}
function Property($Object, [string]$Name, $Default) {
    if ($null -ne $Object.PSObject.Properties[$Name]) { return $Object.$Name }
    $Default
}
function Installed-Version([string]$Directory) {
    $exe = Join-Path $Directory '高中数学题库.exe'
    if (-not (Test-Path -LiteralPath $exe)) { throw 'Target application is missing' }
    $v = (Get-Item -LiteralPath $exe).VersionInfo.ProductVersion
    if ($v -notmatch '^\d+\.\d+\.\d+(?:\.\d+)?$') { throw 'Executable version resource is invalid' }
    $v
}
function Stop-Normally([string]$Directory) {
    $exe = Join-Path $Directory '高中数学题库.exe'
    $running = @(Get-CimInstance Win32_Process -Filter "Name='高中数学题库.exe'" | Where-Object { $_.ExecutablePath -eq $exe })
    foreach ($item in $running) {
        $process = Get-Process -Id $item.ProcessId -ErrorAction SilentlyContinue
        if ($process -and $process.MainWindowHandle -ne 0) { [void]$process.CloseMainWindow() }
    }
    $deadline = (Get-Date).AddSeconds($CloseTimeoutSeconds)
    do {
        $remaining = @(Get-CimInstance Win32_Process -Filter "Name='高中数学题库.exe' OR Name='question-backend.exe'" | Where-Object { $_.ExecutablePath -eq $exe -or $_.ExecutablePath -eq (Join-Path $Directory 'resources\payload\backend-runtime\question-backend.exe') })
        if (-not $remaining.Count) { return }
        Start-Sleep -Milliseconds 250
    } while ((Get-Date) -lt $deadline)
    throw 'Application has not finished saving or shutting down. No files were replaced; return to the application and save.'
}

try {
    if (-not $Package) {
        Add-Type -AssemblyName System.Windows.Forms
        $chooser = [Windows.Forms.OpenFileDialog]::new()
        $chooser.Title = '选择本地 Windows 发行 ZIP（同目录需有 release.json 和校验清单）'
        $chooser.Filter = 'Windows ZIP (*.zip)|*.zip'
        if ($chooser.ShowDialog() -ne [Windows.Forms.DialogResult]::OK) { exit 0 }
        $Package = $chooser.FileName
    }
    $Package = (Resolve-Path -LiteralPath $Package).Path
    $Target = [IO.Path]::GetFullPath($Target).TrimEnd('\')
    if (-not $BackupRoot) {
        $location = Join-Path $Target '.cache\installation.json'
        if (Test-Path -LiteralPath $location) { $BackupRoot = (Get-Content -LiteralPath $location -Raw | ConvertFrom-Json).backup_root }
        else { $BackupRoot = Join-Path (Split-Path -Parent $Target) '.question-bank-backups' }
    }
    $BackupRoot = [IO.Path]::GetFullPath($BackupRoot)
    if ($BackupRoot -eq $Target -or $BackupRoot.StartsWith($Target+'\',[StringComparison]::OrdinalIgnoreCase)) { throw 'Backup root must be outside the application directory' }
    if (-not $Worker) {
        # Run a stable copy so the updater itself can be replaced safely.
        $helper = Join-Path $BackupRoot ('helpers\'+[guid]::NewGuid().ToString('N'))
        [void][IO.Directory]::CreateDirectory($helper)
        $workerScript = Join-Path $helper 'update_app.ps1'
        Copy-Item -LiteralPath $PSCommandPath -Destination $workerScript
        & (Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe') -NoProfile -ExecutionPolicy Bypass -File $workerScript -Worker -Package $Package -Target $Target -BackupRoot $BackupRoot -CloseTimeoutSeconds $CloseTimeoutSeconds -TestFailAfter $TestFailAfter
        exit $LASTEXITCODE
    }
    $releaseDirectory = Split-Path -Parent $Package
    $release = Get-Content -LiteralPath (Join-Path $releaseDirectory 'release.json') -Raw | ConvertFrom-Json
    $version = [string]$release.version
    if ($version -notmatch '^\d+\.\d+\.\d+$') { throw 'Invalid release version' }
    $artifact = $release.artifacts.windows
    $checksum = Get-Content -LiteralPath (Join-Path $releaseDirectory "checksums-$version.json") -Raw | ConvertFrom-Json
    if ($artifact.filename -ne (Split-Path -Leaf $Package) -or $artifact.sha256 -ne $checksum.filename_sha256 -or $checksum.filename -ne $artifact.filename) { throw 'Release and checksum manifests disagree' }
    if ((Get-Item -LiteralPath $Package).Length -ne $artifact.bytes -or (File-Hash $Package) -ne $artifact.sha256) { throw 'Release ZIP checksum verification failed' }
    $archive = [IO.Compression.ZipFile]::OpenRead($Package)
    try {
        $entry = $archive.GetEntry('高中数学题库/app-files.json')
        if (-not $entry) { throw 'Release has no program-file manifest' }
        $reader = [IO.StreamReader]::new($entry.Open(),[Text.Encoding]::UTF8)
        try { $manifestText=$reader.ReadToEnd();$manifest=$manifestText|ConvertFrom-Json } finally { $reader.Dispose() }
        if ($manifest.version -ne $version -or $manifest.schema -ne 8) { throw 'Package version or schema mismatch' }
        $wanted = @{}; $wanted['app-files.json']=$true
        foreach ($item in $manifest.files) {
            [void](Safe-Path $Target $item.path)
            $first=$item.path.Split('/')[0].ToLowerInvariant()
            if ($first -in @('data','.cache','output','logs','runtime','test-results','.local') -or $item.path.EndsWith('.credentials.enc')) { throw 'Release contains personal runtime data' }
            if ($wanted.ContainsKey($item.path.ToLowerInvariant())) { throw 'Duplicate program path' }
            $wanted[$item.path.ToLowerInvariant()]=$true
        }
        $observed=@{}
        foreach ($item in $archive.Entries) {
            if ($item.FullName.EndsWith('/')) { continue }
            if (-not $item.FullName.StartsWith('高中数学题库/',[StringComparison]::Ordinal)) { throw 'Unexpected ZIP root' }
            $relative=$item.FullName.Substring('高中数学题库/'.Length)
            [void](Safe-Path $Target $relative)
            if (-not $wanted.ContainsKey($relative.ToLowerInvariant()) -or $observed.ContainsKey($relative.ToLowerInvariant())) { throw 'Unexpected or duplicate ZIP file' }
            $observed[$relative.ToLowerInvariant()]=$true
        }
        if ($observed.Count -ne $wanted.Count) { throw 'ZIP is missing declared files' }
        $transaction = Join-Path $BackupRoot ('updates\'+[guid]::NewGuid().ToString('N').Substring(0,12))
        $stage = Join-Path $transaction 'stage';[void][IO.Directory]::CreateDirectory($stage)
        foreach ($item in $archive.Entries) {
            if ($item.FullName.EndsWith('/')) { continue }
            $relative=$item.FullName.Substring('高中数学题库/'.Length);$destination=Safe-Path $stage $relative
            [void][IO.Directory]::CreateDirectory((Split-Path -Parent $destination))
            $inputStream=$item.Open();$outputStream=[IO.File]::Create($destination)
            try { $inputStream.CopyTo($outputStream) } finally { $inputStream.Dispose();$outputStream.Dispose() }
        }
    } finally { $archive.Dispose() }
    foreach ($item in $manifest.files) {
        $file=Safe-Path $stage $item.path
        if ((Get-Item -LiteralPath $file).Length -ne $item.bytes -or (File-Hash $file) -ne $item.sha256) { throw "Program file verification failed: $($item.path)" }
    }
    if ([version](Installed-Version $stage) -ne [version]$version) { throw 'Executable version differs from release manifest' }
    $current=Installed-Version $Target
    if ([version]$current -gt [version]$version) { throw 'Downgrade refused; use an explicit full recovery backup instead' }
    if ([version]$current -eq [version]$version) {
        foreach ($item in $manifest.files) { $file=Safe-Path $Target $item.path;if (-not (Test-Path -LiteralPath $file) -or (File-Hash $file) -ne $item.sha256) { throw 'Same version has different program contents; update refused' } }
        Write-Output "ALREADY_CURRENT=$version";exit 0
    }
    Stop-Normally $Target
    $oldManifestFile=Join-Path $Target 'app-files.json'
    if (-not (Test-Path -LiteralPath $oldManifestFile)) { throw 'Target lacks an installed file manifest; perform the verified initial migration first' }
    $oldManifest=Get-Content -LiteralPath $oldManifestFile -Raw | ConvertFrom-Json
    if ([version]$oldManifest.version -ne [version]$current) { throw 'Installed manifest and executable disagree' }
    $oldOwned=@{};foreach($item in $oldManifest.files){$oldOwned[$item.path.ToLowerInvariant()]=$true}
    foreach($item in $manifest.files){$file=Safe-Path $Target $item.path;if((Test-Path -LiteralPath $file) -and -not $oldOwned.ContainsKey($item.path.ToLowerInvariant())){throw 'New program path collides with an unknown existing file; preserved without overwrite'}}
    $paths=@{};foreach($item in @($oldManifest.files)+@($manifest.files)) { [void](Safe-Path $Target $item.path);$first=$item.path.Split('/')[0].ToLowerInvariant();if($first -in @('data','.cache','output','logs')){throw 'Installed manifest includes protected files'};$paths[$item.path]=$true }
    $paths['app-files.json']=$true
    $existing=@();$absent=@();$backup=Join-Path $transaction 'previous-program'
    foreach($name in $paths.Keys){
        $file=Safe-Path $Target $name
        if(Test-Path -LiteralPath $file){$saved=Safe-Path $backup $name;[void][IO.Directory]::CreateDirectory((Split-Path -Parent $saved));Copy-Item -LiteralPath $file -Destination $saved;$existing+=@{path=$name;sha256=(File-Hash $saved)}}else{$absent+=$name}
    }
    Write-Json @{status='prepared';old_version=$current;new_version=$version;target=$Target;existing=$existing;absent=$absent} (Join-Path $transaction 'transaction.json')
    $mutated=$false
    try {
        $count=0
        foreach($item in $manifest.files){$destination=Safe-Path $Target $item.path;[void][IO.Directory]::CreateDirectory((Split-Path -Parent $destination));$temporary="$destination.update-tmp";Copy-Item -LiteralPath (Safe-Path $stage $item.path) -Destination $temporary -Force;$mutated=$true;Move-Item -LiteralPath $temporary -Destination $destination -Force;$count++;if($TestFailAfter -gt 0 -and $count -ge $TestFailAfter){throw 'Controlled update failure for regression testing'}}
        foreach($item in $oldManifest.files){if(-not $wanted.ContainsKey($item.path.ToLowerInvariant())){$destination=Safe-Path $Target $item.path;if(Test-Path -LiteralPath $destination){$mutated=$true;Remove-Item -LiteralPath $destination}}}
        Copy-Item -LiteralPath (Join-Path $stage 'app-files.json') -Destination $oldManifestFile -Force
        foreach($item in $manifest.files){if((File-Hash (Safe-Path $Target $item.path)) -ne $item.sha256){throw 'Post-update file check failed'}}
        Write-Json @{status='complete';old_version=$current;new_version=$version;target=$Target;backup=$backup} (Join-Path $transaction 'transaction.json')
        Write-Output "UPDATE_COMPLETE=$version"
    } catch {
        $originalError=$_.Exception.Message
        if($mutated){
            foreach($item in $existing){$destination=Safe-Path $Target $item.path;Copy-Item -LiteralPath (Safe-Path $backup $item.path) -Destination $destination -Force}
            foreach($name in $absent){$destination=Safe-Path $Target $name;if(Test-Path -LiteralPath $destination){Remove-Item -LiteralPath $destination}}
            foreach($name in $paths.Keys){$temporary=(Safe-Path $Target $name)+'.update-tmp';if(Test-Path -LiteralPath $temporary){Remove-Item -LiteralPath $temporary}}
            foreach($item in $existing){if((File-Hash (Safe-Path $Target $item.path)) -ne $item.sha256){throw 'Rollback verification failed; preserve the backup and target for recovery'}}
        }
        Write-Json @{status='rolled_back';old_version=$current;new_version=$version;target=$Target;error=$originalError;backup=$backup} (Join-Path $transaction 'transaction.json')
        throw "Update failed; previous program restored. $originalError"
    }
} catch { Write-Error $_.Exception.Message;exit 1 }
