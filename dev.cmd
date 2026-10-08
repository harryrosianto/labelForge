@echo off
rem Pembungkus dev.ps1 untuk Command Prompt. Contoh: dev, dev -NoWorker, dev -Stop
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0dev.ps1" %*
