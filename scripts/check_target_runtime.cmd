@echo off
setlocal EnableExtensions

where adb >nul 2>nul || (
  echo ERROR: adb.exe not found in PATH.
  exit /b 2
)

for /f "usebackq delims=" %%V in (`adb shell getprop ro.build.version.release 2^>nul`) do set "ANDROID=%%V"
for /f "usebackq delims=" %%V in (`adb shell getprop ro.build.display.id 2^>nul`) do set "DISPLAY=%%V"
for /f "usebackq delims=" %%V in (`adb shell cat /proc/version 2^>nul`) do set "KERNEL=%%V"

if not defined ANDROID (
  echo ERROR: no Android device through adb.
  exit /b 3
)

echo Android: %ANDROID%
echo Build:   %DISPLAY%
echo Kernel:  %KERNEL%

echo %ANDROID% | findstr /b /c:"8.1" >nul || (
  echo.
  echo REFUSED: run46 is an Android-8.1 target kernel.
  echo This device is not currently running the target Android-8.1 stack.
  exit /b 20
)

echo.
echo TARGET RUNTIME CHECK PASS
exit /b 0
