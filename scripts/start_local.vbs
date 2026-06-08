' 功能说明：以隐藏窗口方式启动本地工作台，避免弹出命令行终端。
Option Explicit

Dim shell
Dim scriptDir
Dim command

Set shell = CreateObject("WScript.Shell")
scriptDir = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptDir & "\start_local.ps1"""

shell.Run command, 0, False
