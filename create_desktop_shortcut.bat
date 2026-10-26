@echo off
title Create StockNova Desktop Shortcut
set SCRIPT="%TEMP%\CreateShortcut.vbs"

echo Set oWS = WScript.CreateObject("WScript.Shell") >> %SCRIPT%
echo sLinkFile = oWS.SpecialFolders("Desktop") ^& "\StockNova AI Studio.lnk" >> %SCRIPT%
echo Set oLink = oWS.CreateShortcut(sLinkFile) >> %SCRIPT%
echo oLink.TargetPath = "d:\Stock Automation\run.bat" >> %SCRIPT%
echo oLink.WorkingDirectory = "d:\Stock Automation" >> %SCRIPT%
echo oLink.Description = "StockNova AI Autonomous Studio" >> %SCRIPT%
echo oLink.Save >> %SCRIPT%

cscript /nologo %SCRIPT%
del %SCRIPT%

echo Shortcut created on your Desktop: "StockNova AI Studio"
pause
