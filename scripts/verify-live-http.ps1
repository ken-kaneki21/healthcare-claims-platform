param(
    [Parameter(Mandatory=$true)][string]$Python,
    [Parameter(Mandatory=$true)][string]$ModelFile,
    [Parameter(Mandatory=$true)][string]$OutputDirectory,
    [switch]$PreflightOnly
)
$ErrorActionPreference = 'Stop'
$Python = (Resolve-Path -LiteralPath $Python).Path
$env:CLAIMS_EVAL_GGUF = (Resolve-Path -LiteralPath $ModelFile).Path
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory | Out-Null
Push-Location (Join-Path $PSScriptRoot '..')
$project = 'claims-gate-' + [guid]::NewGuid().ToString('N').Substring(0,12)
$config = @('compose','-p',$project,'-f','compose.yaml','-f','compose.local-llm.yaml',
    '-f','scripts/compose.live-acceptance.yml')
$env:CLAIMS_DEMO_SECRET = [guid]::NewGuid().ToString('N')
$env:CLAIMS_EVAL_LLM_PORT = '18769'
$started = $false
$record = [ordered]@{ project=$project; status='blocked'; stage='compose_configuration' }
$code = 2
try {
    $record.commit = (git rev-parse HEAD)
    if (-not $PreflightOnly) {
        $record.stage = 'docker_engine'
        $engine = docker version --format '{{.Server.Version}}' 2>&1
        if ($LASTEXITCODE -ne 0) { throw ($engine -join [Environment]::NewLine) }
        $record.stage = 'allocate_loopback_port'
        $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback,0)
        try { $listener.Start(); $env:CLAIMS_EVAL_LLM_PORT = "$($listener.LocalEndpoint.Port)" }
        finally { $listener.Stop() }
    }
    $record.stage = 'compose_configuration'
    $compose = docker @config config --format json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw 'Compose config failed' }
    $llm = $compose.services.llm
    if ($llm.container_name -or $llm.ports.Count -ne 1 -or $llm.ports[0].host_ip -ne '127.0.0.1' -or
        $llm.volumes.Count -ne 1 -or -not $llm.volumes[0].read_only -or
        $llm.volumes[0].target -ne '/models/qwen.gguf' -or $llm.image -notmatch '@sha256:[a-f0-9]{64}$') {
        throw 'Local model isolation or image pin check failed'
    }
    $record.image = $llm.image
    $record.model_bytes = (Get-Item -LiteralPath $env:CLAIMS_EVAL_GGUF).Length
    if ($PreflightOnly) {
        $record.status = 'configuration_validated'
        $code = 0
    } else {
        $record.stage = 'cached_image'
        docker image inspect --format '{{.Id}}' $llm.image | Out-Null
        if ($LASTEXITCODE -ne 0) { throw 'Pinned image is absent from the local cache' }
        $record.stage = 'model_start'
        $started = $true
        docker @config up -d --pull never --no-build llm
        if ($LASTEXITCODE -ne 0) { throw 'Pinned model container could not start' }
        $env:CLAIMS_LLM_ENDPOINT = "http://127.0.0.1:${env:CLAIMS_EVAL_LLM_PORT}/v1/chat/completions"
        $env:CLAIMS_LLM_MODEL = 'qwen2.5-1.5b-instruct-q4_k_m'
        $record.stage = 'authenticated_http'
        & $Python -m healthcare.verify_live_http --out (Join-Path $OutputDirectory 'http.json') --model-file $env:CLAIMS_EVAL_GGUF --runtime-revision $llm.image --startup-timeout 45
        $code = $LASTEXITCODE
        if ($code -eq 0) { $record.status = 'accepted' }
        elseif ($code -ne 2) { $record.status = 'failed' }
    }
} catch {
    $record.error = $_.Exception.Message
    Write-Error -ErrorAction Continue $record.error
    if ($started) { $record.status = 'failed'; $code = 1 }
} finally {
    if ($started) { docker @config stop --timeout 10 llm }
    $record | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $OutputDirectory 'gate.json') -Encoding utf8
    Pop-Location
}
exit $code
