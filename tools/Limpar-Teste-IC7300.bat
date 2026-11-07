@echo off
rem Duplo clique para abrir a janela de limpeza do ambiente de teste do IC-7300 Station.
powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0Limpar-Teste-IC7300.ps1"
