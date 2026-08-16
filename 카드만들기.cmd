@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  ==== 딜 카드 5장 만들기 (스레드용) ====
echo  (한국 IP인 이 PC에서 실행하세요)
echo.
python publish_cards.py
echo.
pause
