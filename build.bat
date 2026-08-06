@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 开始打包 exe（需要已安装 PyInstaller，首次请先运行：pip install pyinstaller）...
set "ROOT=%CD%"
python -m PyInstaller --noconsole --onefile --name "AI划词助手" ^
    --icon "%ROOT%\icon.ico" --add-data "%ROOT%\icon.ico;." ^
    --distpath . --workpath "%TEMP%\ai_chat_build" --specpath "%TEMP%\ai_chat_build" ^
    main.py
echo.
if exist "AI划词助手.exe" (
    echo 打包完成：AI划词助手.exe 已生成在当前目录，双击即可运行，无控制台窗口。
) else (
    echo 打包失败，请检查上方错误信息。
)
pause
