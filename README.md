# 토스쇼핑 쉐어링크 특가 수집기

토스쇼핑 쉐어링크의 큐레이션 API에서 특가 상품을 수집하고, 할인율·30일 최저가 기준으로 걸러낸다.

## 준비

```bash
copy .env.example .env
```

`.env` 의 `TBIZAUTH` 에 쉐어링크 로그인 쿠키를 넣는다.
브라우저 **F12 → Application → Cookies → https://sharelink.toss.im** 에서 복사.

> ⚠️ `TBIZAUTH` 는 로그인 세션 그 자체다. 유출되면 계정이 그대로 넘어간다.
> `.gitignore` 에 `.env` 가 들어있으니 커밋될 일은 없지만, 어디에도 붙여넣지 말 것.
> 만료되면 `collect.py` 가 401로 알려준다. 브라우저에서 재로그인 후 다시 복사.

## 사용

```bash
python collect.py              # API 호출 → snapshots/ 저장 + deals.db 적재
python report.py               # 할인율 50%+ 또는 30일 최저가
python report.py --min-discount 70
python report.py --lowest-only
python report.py --drops        # 직전 수집 대비 가격 하락분
python report.py --json         # 발행 파이프라인용

python report.py --new          # 이번 수집에서 새로 등장한 딜

python issue.py                 # 특가 상품 쉐어링크 자동 발급
python issue.py --limit 20 --min-discount 70
python issue.py --dry-run       # 대상만 확인

python links.py list            # 발급된 링크 목록
python settoken.py              # 토큰 갱신 (401 났을 때)
```

## 사이트

`build.py` 가 `docs/index.html` 을 만든다.
**쉐어링크가 발급된 상품만** 싣는다(링크 없으면 수익이 안 나므로).

```bash
python build.py
python build.py --min-discount 40 --limit 300
```

## 클라우드 자동 실행 (PC 꺼져 있어도 동작)

- **GitHub Actions** 가 하루 4번(한국시간 07/12/18/22시) 수집 → 발급 → 사이트 생성 → 커밋
- **Vercel** 이 그 푸시를 감지해 자동 배포

둘 다 무료다.

**설정 순서**

1. 저장소를 만들고 이 폴더를 push (`.env` 는 `.gitignore` 로 빠진다)
2. **Settings → Secrets and variables → Actions → New repository secret**
   - `TBIZAUTH` : `.env` 의 값
   - `TGSID` : `.env` 의 값 (선택)
3. Vercel 에서 **Add New → Project → 이 저장소 Import**
   - `vercel.json` 이 `outputDirectory: docs` 를 지정하므로 빌드 설정은 건드리지 않는다
4. **Actions** 탭에서 `딜 수집` → `Run workflow` 로 첫 실행

`deals.db` 는 일부러 커밋한다. 실행 사이에 **링크 캐시와 가격 이력이 이어져야** 하기 때문이다.
토큰은 `.env` 와 GitHub Secrets 에만 있고 DB 에는 들어가지 않는다.

## 토큰 관리

`TBIZAUTH` 는 base64 로 감싼 세션 UUID다. 만료 시각이 값에 들어있지 않고 서버가 관리한다.

**API 를 호출해도 서버가 세션을 연장해주지 않는다** (응답에 `Set-Cookie` 가 없음).
따라서 자동 수집으로 세션을 살려둘 수는 없고, **주기적으로 갱신해야 한다.**
주기는 서버 정책이라 관측해봐야 안다.

만료되면:

1. Actions 가 401 로 실패하고 **GitHub 이 알림 메일을 보낸다**
2. 배포 단계까지 가지 않으므로 **사이트는 마지막 정상 버전이 유지된다**
3. 브라우저에서 `TBIZAUTH` 쿠키를 복사해 저장소 시크릿만 수정하면 끝 (30초)

로컬은 `python settoken.py` 로 갱신한다.

## 로컬 주기 실행

`run.bat` 이 수집 → 발급 → 사이트 생성 → 신규/하락 리포트를 순서대로 돌리고
`new_deals.txt`, `price_drops.txt`, `run.log` 를 남긴다.

윈도우 작업 스케줄러에 등록 (관리자 명령 프롬프트):

```cmd
schtasks /create /tn "토스딜수집" /sc hourly /tr "\"c:\dev\claude code\refferal\run.bat\""
```

한 번 도는 데 약 40초, 요청 40여 건이다. 매시간이면 충분하고,
더 자주 돌리려면 `REQUEST_DELAY` 를 줄이지 말고 주기만 조절할 것.

## 데이터

| 필드 | 출처 | 비고 |
|---|---|---|
| `discount_rate` | `productView.discountRate` | 토스 표시값. **쿠폰 미반영** |
| `effective_price` | 직접 계산 | `displayPrice - couponDiscountAmount` |
| `effective_rate` | 직접 계산 | 쿠폰까지 반영한 실할인율. 필터·정렬 기준 |
| `is_lowest_30d` | `displayContext.isLowestPriceIn30Days` | **30일 최저가 판정** |
| `link_issuable` | `linkIssueAvailability.available` | 쉐어링크 발급 가능 여부 |
| `campaign_end_at` | `tagMeta.campaignEndAt` | 딜 마감 시각 |
| `page_view_count` | `displayContext.pageViewCount` | 인기도 |

### 응답 구조에서 주의할 점

- `TODAY_DEAL` 외의 섹션은 **`item.productId` 가 `null`** 이다.
  실제 값은 `item.taca.productView.productId` 에만 있다.
- `discountRate` 에 `couponDiscountAmount` 가 반영돼 있지 않다.
  쿠폰이 붙은 상품은 표시 할인율보다 실제로 더 싸다.
  (예: 정가 117,000 → 표시 89,640 / 23% 인데 쿠폰 9,960 적용 시 79,680 / 31%)
- 할인율은 **내림**이다. 반올림하면 토스 표시값과 1% 어긋난다.

### 섹션

| sectionCode | 이름 | totalCount |
|---|---|---|
| `TODAY_DEAL` | 오늘만 이 가격에 살 수 있는 하루특가 | 80 |
| `BEST_SELLING` | 지금 많이 팔리는 BEST | 200 |
| `TRENDING` | 인기 급상승 | 200 |
| `CATEGORY_BEST` | 카테고리 인기 상품 (탭 12개) | — |

### API 정리 (실측)

```
GET /api-public/v3/shopping/sharelink/curation-sections?surface=BEST_RANKING
    → 섹션 목록. 섹션당 5~15개 미리보기만 온다. size 파라미터는 무시된다.
    → surface 유효값은 BEST_RANKING, HOME 둘뿐. 나머지는 400.

GET /api-public/v3/shopping/sharelink/curation-sections/{sectionCode}/items
    ?size=30&nextCursor={커서}
    → 섹션 전량. size 상한 30. 마지막 페이지에서 nextCursor 가 null.
    → 커서에 '30|31' 처럼 파이프가 들어온다. URL 인코딩하지 않으면 400.
```

```
POST /api-public/v3/shopping/sharelink/link/issue
     {"tacaItemId": 2372337773}
    → {"shortUrl":"https://toss.im/_m/ZXQASVem",
       "originUrl":"https://toss.shopping/t/{tacaId}?k={UUID}&referrer=affiliate"}
```

**발급 키는 `productId` 가 아니라 `tacaItemId` 다.** `productId` 로 보내면
"상품 정보를 찾을 수 없습니다" 가 뜬다. originUrl 의 경로도 productId 가 아니라 tacaId.

같은 상품을 다시 발급하면 **같은 shortUrl 이 돌아온다**(검증 완료).
그래서 `sharelinks` 테이블이 영구 자산이 되고, 재발급 비용이 0이다.

인증은 쿠키 `TBIZAUTH` 하나로 충분하다. 없으면 401.

테이블:

- `products` — 상품 최신 상태
- `observations` — 수집할 때마다 한 줄. 가격 변동 추적용
- `sharelinks` — **상품ID → 쉐어링크. 상품당 영구 고정이라 한 번 발급하면 계속 재사용**
- `published` — 발행 이력 (중복 발행 방지용, 아직 미사용)

## 남은 작업

- [x] 커서 페이징 엔드포인트 확인 → 652개 전량 수집
- [x] `surface` 유효값 전수 확인 → `BEST_RANKING`, `HOME` 뿐
- [x] 신규 딜 감지 (`--new`) · 가격 하락 감지 (`--drops`) · 주기 실행 (`run.bat`)
- [ ] `CATEGORY_BEST` 의 탭 12개 순회 (`tabCode` 파라미터, 미검증)
- [ ] `/links/recommended-products` 가 쓰는 별도 API 확인
- [x] 쉐어링크 발급 자동화 (`issue.py`)
- [ ] 발행 모듈 (텔레그램 / 카톡 오픈채팅)

## 운영 시 지켜야 할 것

- 게시물마다 경제적 이해관계 표시 (공정위 지침, 쉐어링크 운영정책)
  `✱ 이 포스팅은 토스쇼핑 쉐어링크 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.`
- 본인·가족 구매는 수익 불인정 (자전거래)
- 수신자 동의 없는 개인 메신저·SMS 발송 금지 → 구독형 채널만
- `REQUEST_DELAY` 를 무리하게 줄이지 말 것
