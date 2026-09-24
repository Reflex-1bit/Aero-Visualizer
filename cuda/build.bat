@echo off
rem Build the LBM solver. Needs the CUDA toolkit and Visual Studio (C++ workload).
rem sm_120 = RTX 50-series (Blackwell); override with: build.bat sm_89
setlocal
set ARCH=%1
if "%ARCH%"=="" set ARCH=sm_120
for /f "usebackq delims=" %%i in (`"%ProgramFiles(x86)%\Microsoft Visual Studio\Installer\vswhere.exe" -latest -property installationPath`) do set VS=%%i
call "%VS%\VC\Auxiliary\Build\vcvars64.bat" >nul || exit /b 1
cd /d "%~dp0"
nvcc -O3 -arch=%ARCH% -use_fast_math -o lbm.exe lbm.cu || exit /b 1
echo built %~dp0lbm.exe
