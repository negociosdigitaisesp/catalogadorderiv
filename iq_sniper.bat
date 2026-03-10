@echo off
REM ============================================================
REM iq_sniper.bat — Inicia IQ Option Sniper na VPS local ou dev
REM ============================================================
title IQ Sniper — Oracle Quant

cd /d %~dp0

REM Carrega .env se existir
if exist .env (
    for /F "tokens=1,2 delims==" %%a in (.env) do (
        set %%a=%%b
    )
)

REM CLIENT_ID padrão
if not defined CLIENT_ID set CLIENT_ID=GLOBAL

echo [IQ_SNIPER] Iniciando... CLIENT_ID=%CLIENT_ID%
python run_iq_sniper.py

pause
