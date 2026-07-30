@echo off
REM 주기 실행용. 윈도우 작업 스케줄러에 이 파일을 등록하면 된다.
REM   schtasks /create /tn "토스딜수집" /tr "\"c:\dev\claude code\refferal\run.bat\"" /sc hourly
chcp 65001 > nul
cd /d "%~dp0"

echo ================================================== >> run.log
echo [%date% %time%] 수집 시작 >> run.log
python collect.py >> run.log 2>&1

REM 링크 없는 특가 상품의 쉐어링크를 자동 발급 (한 번에 30개까지)
python issue.py --limit 30 >> run.log 2>&1

REM 사이트 생성 (docs/index.html)
python build.py >> run.log 2>&1

REM 이번 수집에서 새로 등장한 딜 (할인 50%% 이상 또는 30일 최저가)
python report.py --new >  new_deals.txt 2>&1
REM 직전 수집 대비 가격이 내려간 딜
python report.py --drops > price_drops.txt 2>&1

type new_deals.txt >> run.log
echo [%date% %time%] 완료 >> run.log
