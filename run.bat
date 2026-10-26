@echo off
title StockNova AI Studio
cd /d "d:\Stock Automation"
set PYTHONPATH=d:\Stock Automation

:: Launch the Modern Native Edge WebView2 Studio Desktop Window silently
start "" pythonw "d:\Stock Automation\stockpilot\desktop_app.py"
exit
