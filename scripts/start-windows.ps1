$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')

function Get-Sha256($File) {
    $stream = [IO.File]::OpenRead((Resolve-Path -LiteralPath $File).Path)
    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '')
    } finally {
        $algorithm.Dispose()
        $stream.Dispose()
    }
}

function Install-PortableTool($Name, $Url, $Sha256, $Executable) {
    $folder = Join-Path '.runtime/windows-tools' $Name
    $binary = Join-Path $folder $Executable
    if (-not (Test-Path -LiteralPath $binary -PathType Leaf)) {
        Write-Host "Downloading $Name..."
        New-Item -ItemType Directory -Force -Path $folder | Out-Null
        $archive = Join-Path $folder 'download.zip'
        & curl.exe --fail --silent --show-error --location --connect-timeout 15 --max-time 180 --retry 2 --output $archive $Url
        if ($LASTEXITCODE -ne 0) { throw "Could not download $Name." }
        if ((Get-Sha256 $archive) -ne $Sha256) {
            throw "SHA-256 verification failed for $Name."
        }
        & tar.exe -xf $archive -C $folder
        if ($LASTEXITCODE -ne 0) { throw "Could not extract $Name." }
        Remove-Item -LiteralPath $archive
    }
    (Resolve-Path -LiteralPath $binary).Path
}

try {
    if ([System.Runtime.InteropServices.RuntimeInformation]::OSArchitecture -ne 'X64') {
        throw 'This launcher requires 64-bit Windows on x64.'
    }
    $uv = Install-PortableTool 'uv-0.13.10' 'https://files.pythonhosted.org/packages/cf/e4/d0704c116ada58e8450890e2defaaf2f07e8d264cf94669210e0823fbcb2/uv-0.13.10-py3-none-win_amd64.whl' 'd87b9cf8165f2b3cc596e856b5bf794da9cfad6d1b110ca9d87eed42a15b3684' 'uv-0.13.10.data/scripts/uv.exe'
    $env:UV_PROJECT_ENVIRONMENT = '.runtime/venv-windows'
    & $uv sync --locked --group web
    if ($LASTEXITCODE -ne 0) { throw 'Python dependencies could not be installed.' }

    $npm = (Get-Command npm.cmd -ErrorAction SilentlyContinue).Source
    $node = Get-Command node.exe -ErrorAction SilentlyContinue
    $version = if ($npm -and $node) { [version]((& $node.Source --version).TrimStart('v')) }
    if (-not $version -or $version -lt [version]'22.12.0') {
        $npm = Install-PortableTool 'node-22.23.3' 'https://nodejs.org/dist/v22.23.3/node-v22.23.3-win-x64.zip' '2b0ff57b049cda1bbcea2240eec20467018713c1efe1f7360c2681859b90ed71' 'node-v22.23.3-win-x64/npm.cmd'
        $env:Path = "$(Split-Path -Parent $npm);$env:Path"
    }

    $lockHash = Get-Sha256 'frontend/package-lock.json'
    $stamp = 'frontend/node_modules/.shanhe-lock-hash'
    if (-not (Test-Path -LiteralPath $stamp) -or (Get-Content -LiteralPath $stamp -Raw).Trim() -ne $lockHash) {
        & $npm --prefix frontend ci --no-audit --no-fund
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependencies could not be installed.' }
        Set-Content -LiteralPath $stamp -Value $lockHash
    }
    & $npm --prefix frontend run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }

    $modeArgs = @()
    if (-not (Test-Path -LiteralPath '.env')) {
        Write-Host 'Starting in demo mode with sample data.'
        $modeArgs += '--demo'
    } else {
        Write-Host 'Starting with the database and batch configured in .env.'
    }
    $env:FLASK_HOST = '127.0.0.1'
    & '.runtime/venv-windows/Scripts/python.exe' -m scripts.web --open-browser @modeArgs
    exit $LASTEXITCODE
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
