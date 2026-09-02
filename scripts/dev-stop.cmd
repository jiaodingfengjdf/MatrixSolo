@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev-stop.ps1" %*
