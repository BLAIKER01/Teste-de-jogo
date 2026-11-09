@echo off
REM Gera MansaoFugaSombria.exe (precisa de Python e internet na primeira vez).
pip install pygame pyinstaller
pyinstaller --onefile --noconsole --name MansaoFugaSombria Teste_6_3d.py
echo.
echo Pronto! O executavel esta em dist\MansaoFugaSombria.exe
echo Config, placar e conquistas ficam em %%APPDATA%%\MansaoFugaSombria
pause
