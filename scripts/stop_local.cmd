@echo off
rem 功能说明：调用 PowerShell 退出 MoonToolBox 的托盘和后端进程。
cd /d %~dp0\..
powershell -ExecutionPolicy Bypass -File scripts\stop_local.ps1
