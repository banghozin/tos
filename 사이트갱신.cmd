@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  ==== 특가레이더 사이트 갱신 ====
echo  (한국 IP에서만 됩니다. 이 PC에서 실행하세요)
echo.
python update_site.py
echo.
pause
