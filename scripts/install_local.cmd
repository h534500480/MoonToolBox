@echo off
cd /d %~dp0\..
powershell -ExecutionPolicy Bypass -File scripts\install_local.ps1
