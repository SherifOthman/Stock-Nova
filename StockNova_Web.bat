@echo off
title StockNova AI Web Analytics
cd /d "d:\Stock Automation"
set PYTHONPATH=d:\Stock Automation

echo Starting Web Analytics Dashboard...
start http://localhost:8585
python "d:\Stock Automation\stockpilot\web_dashboard.py"
