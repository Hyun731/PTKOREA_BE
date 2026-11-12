# 개발 계획: 팩트북 품질 개선 (지향 덱 수준까지)

작성 2026-11-10. 기준 코드: PTKOREA_BE `53af865`, PTKOREA_FE `ccb2072` (김가은 님 피드백 #1~#5 작업 포함).

이 문서는 [HANDOFF.md](HANDOFF.md)의 다음 단계입니다. **"개발하면서 지켜야 할 점"은 HANDOFF.md 2장을 그대로 따릅니다.** 바뀐 원칙은 아래 0장에 적었습니다.

AI 코딩 도구로 작업할 때는 이렇게 시작하세요.

```text
PTK 팩트북 서비스에 작업해 줘. 먼저 backend/docs/HANDOFF.md의 "개발하면서 지켜야 할 점"과
backend/docs/IMPROVEMENT_PLAN.md의 0장을 읽고 지켜. 그다음 IMPROVEMENT_PLAN.md의 작업 [번호]를 구현해.
작업의 "완료 기준"을 모두 확인하고, 기능 단위로 작게 커밋해(rebase만, merge 커밋 금지).
```

---

## 0. 배경과 바뀐 점

### 왜 하는가
지향 덱(`1번_샘소나이트_팩트북.pptx`, 140장)과 지금 결과물(`샘소나이트_팩트북_v6.pdf`, deck v14, 37장)을 비교한 결과입니다.

| 지표 | 지향 덱 | 지금 |
|---|---|---|
| 차트 | 41 (본문 22) | 2 (점 3개짜리 선 차트) |
| 표 | 56 | 약 12 (그중 4장은 출처 표) |
| 헤드라인 | 주장 + 수치 근거 두 줄 | 장표를 설명하는 문장 |
| 결론부 | 진단 요약, CDJ 시사점, 제안, 결론 | 없음 |
| 구조 | 브랜드별 진단 흐름 | 자료 종류별 템플릿 나열 |

원인은 다섯 가지입니다.
1. 장표가 자료 종류별 템플릿이라 여러 자료를 엮은 진단 장이 없습니다.
2. 헤드라인 규칙(`insights.py` SYSTEM)이 판단·제언을 금지하고 숫자를 2개로 제한합니다.
3. 차트는 Fact에서만 만들어지는데, 수치 입력 경로가 좁습니다. 막대 차트는 검색 장에만 쓰입니다.
4. 레이아웃이 행 수와 브랜드 수에 맞춰 줄어들어 아래가 비고, 하단 인사이트 영역이 없습니다.
5. 수집한 경쟁사 SNS 데이터를 장표에 쓰지 않습니다(`run_owned_item` 주석).

### 사용하는 키 (2026-11-10 확인)

| 키 | 상태 | 용도 |
|---|---|---|
| 네이버 검색 API (Developers, `.env`의 `NAVER_CLIENT_ID/SECRET`) | ✅ blog·cafearticle·news·webkr·kin 동작. shop은 SE05 오류 | 원문, 언급량, 공식 블로그 게시 수 |
| 네이버 데이터랩 (같은 앱) | 팀장님께 추가 요청함. **켜졌다고 가정** | 검색 점유, 쇼핑인사이트 |
| ScrapeCreators | ✅ 21,910 크레딧 | 6채널 공식 계정, 댓글, 검색, 광고 라이브러리 |
| Perplexity · Anthropic · Apify | ✅ | 시장·정책 / 추출·문장 / 해시태그 |
| 없음 | YouTube Data API, 공공데이터포털·KOSIS, Meta·TikTok 공식 API | 보도자료 수치, 고객 제공 자료 업로드로 대체 |

네이버 클라우드(NCP, `X-NCP-APIGW-*`) 키도 따로 있지만 구독한 API가 없어 쓰지 않습니다.

### HANDOFF.md 원칙 변경
- **원칙 4(네이버 API 금지)를 대체합니다.** 네이버 검색 API와 데이터랩을 씁니다. 단, 쇼핑 검색처럼 막힌 API의 우회는 만들지 않습니다.
- 나머지 원칙(자동 채택 금지, 로그인 정보 금지, 비용 UI 금지, 고객용 덱에 '자료 없음' 금지, 자사 브랜드끼리 비교 금지, 쉬운 한국어)은 그대로입니다.
- 추가 원칙: **숫자는 반드시 Fact(fact_ref)로만 문장에 들어갑니다.** 헤드라인, 인사이트, 종합 모두 마찬가지입니다.
- 추가 원칙: **수집한 데이터는 화면(자료 확인)과 장표 중 적어도 한 곳에 보여야 합니다.** 모으기만 하고 쓰지 않는 수집기를 만들지 않습니다.

### 목표 지표 (샘소나이트 자사 3 + 경쟁사 9로 측정)

| 지표 | 지금 | 목표 |
|---|---|---|
| 본문 장수 (별첨 제외) | 약 30 | 45 이상 |
| 차트 | 2 | 20 이상 |
| 주장 + 근거 헤드라인 비율 | 0% | 90% 이상 |
| 하단 번호 인사이트가 있는 본문 장 | 일부 | 80% 이상 |
| 아래 35% 이상 빈 장 | 약 10 | 0 |
| 브랜드당 소비자 원문 | 9 | 100 이상 |
| 자사·경쟁사 비교 채널 | 0 | 6 |
| 결론부 | 없음 | 자동 생성 |

---

## 1. 전체 순서와 담당

```
P1 기반 ──┬── P2 수집 확대 (수집 담당) ──────────────┐
          └── P3 장표·화면 (장표 담당) ──────────────┤
                                                     ├── P4 5대 축·업종 프로필 (함께)
                                                     └── P5 진단형 덱 (장표 담당) → 최종 측정
```

- P2와 P3은 동시에 진행합니다. 겹치는 파일은 `core/metrics/derived.py`(P1-2)뿐이고, 여기에 지표를 더할 때는 서로 알려 주세요.
- 각 P가 끝나면 샘소나이트 프로젝트로 다시 생성하고, P1-3 측정 도구로 목표표를 갱신해 이 문서 맨 아래 "진척 기록"에 적습니다.
- 크기: S(하루 안), M(2~4일), L(1주 이상)

---

## P1. 공통 기반

### P1-1. 차트 블록 확장 (M, 장표 담당)
- **목표:** 지향 덱이 쓰는 막대·세로 막대·누적·여러 계열 차트를 만들 수 있게 합니다.
- **변경:**
  - `core/schemas/slidespec.py` `BarChartBlock`
    - `orientation: Literal["h", "v"] = "h"`, `stacked: bool = False`를 추가합니다.
    - `series: list[BarSeries] | None = None`을 추가합니다. `BarSeries`는 `entity`, `role`, `items: list[BarItem]`입니다.
    - 기존 `items`(단일 계열)는 그대로 둡니다. 둘 중 하나만 채웁니다.
  - `core/rendering/pptx_renderer.py` `_bar_chart`: (방향, 누적) 조합을 `BAR_CLUSTERED`, `BAR_STACKED`, `COLUMN_CLUSTERED`, `COLUMN_STACKED`로 매핑합니다. 범례는 계열이 2개 이상일 때만 표시합니다.
  - `frontend/components/editor/slide-view.tsx`: 같은 옵션을 렌더링하고, `types.ts` 타입을 맞춥니다.
  - `build.py` `_bindings`: 계열마다 값 → fact_id 바인딩을 만듭니다(QC가 출처 없는 숫자를 잡는 기준).
- **완료 기준:**
  - 4가지 조합 렌더링 단위 테스트
  - 기존 차트 테스트 통과
  - 임시 덱을 렌더 컨테이너(`ptk-render:0.3`)로 PDF로 바꿔 눈으로 확인

### P1-2. 파생 Fact 모듈 (M, 장표 담당 → 이후 양쪽이 지표 추가)
- **목표:** 원문, 댓글, 리뷰, 검색 결과처럼 "건 단위 자료"를 브랜드 단위 수치로 바꿔 차트와 헤드라인에 쓰게 합니다.
- **변경:**
  - 새 파일 `core/metrics/derived.py`
    - `derive(project, materials, owned_posts, reviews, mentions) -> list[Fact]`
    - `source="derived"`, `method`에 계산식, `dims["n"]`에 표본 수를 넣습니다.
    - 채택(accepted)된 자료만 씁니다.
  - `build.py` `build_deck`: `compute()` 전에 파생 Fact를 `inputs.facts`에 더합니다.
  - **n < 20이면 비율 Fact를 만들지 않습니다.** 기준값은 `rules_config.json`의 `derived_min_n`에 둡니다.
  - 각주는 "n=○○ · AI 분류"를 자동으로 붙입니다(`chrome.footnote`의 파생 표시).
- **처음 넣을 지표:**

  | metric | 원천 | dims |
  |---|---|---|
  | `voc_negative_rate` | 소비자 원문 `voc_sentiment` | site(커뮤니티), n |
  | `voc_topic_share` | 소비자 원문 `voc_topic` | topic, n |
  | `voc_path_share` | 소비자 원문 인식 경로 | path, n |
  | `comment_sentiment_rate` | `OwnedPost.comment_sentiment` 합산 | channel, polarity, n |
  | `review_count`, `review_rating` | `ReviewSnapshotRef` | platform, product |

- **완료 기준:**
  - 지표마다 단위 테스트(n 미달이면 생성 안 함 포함)
  - 같은 입력이면 같은 fact id(content_hash 안정)

### P1-3. 덱 측정 도구 (S, 장표 담당)
- 새 파일 `tools/deck_metrics.py <pptx>`가 다음을 JSON과 표로 출력합니다.
  - 장수, 차트 수(종류별), 표, 그림
  - 장당 숫자 수, 헤드라인 형식 충족률, 하단 인사이트 비율
  - 빈 영역 비율이 35%를 넘는 장 목록
- 빈 영역은 각주 위 본문 영역에서 도형이 차지하지 않은 세로 비율로 잽니다.
- **완료 기준:** 지향 덱과 v14 PDF의 원본 PPTX에서 위 목표표의 "지금/지향" 값이 재현됩니다.

### P1-4. 데이터랩 연결 확인과 쇼핑인사이트 클라이언트 (S, 수집 담당)
- `integrations/naver/client.py`
  - 기존 `search_trend`를 실제 키로 한 번 호출해 확인합니다. 데이터랩이 켜졌는지 보는 단계입니다.
  - `shopping_category_trend(category_id, keywords?, start, end, time_unit)`과 `shopping_category_demographics(...)`(연령·성별, `/v1/datalab/shopping/category/age`, `/gender`)를 추가합니다.
- 오류 처리: 024(권한 없음)는 `PROVIDER_AUTH`로 바꿔, 빠진 장표 원인이 "설정 필요"로 표시되게 합니다.
- **완료 기준:**
  - 가짜 transport 테스트
  - 임시 DB에서 실제 키로 검색어 2개, 카테고리 1개 호출 성공

---

## P2. 수집 확대 (수집 담당)

### P2-1. 검색 장표 다시 켜기 (S)
- `scope.py` 3-2의 `default_channels`에 `search_naver`를 기본으로 둡니다(지금도 목록에 있음).
  - 프로젝트 생성 때 데이터랩 권한이 없으면(P1-4 판정) 항목에 "설정 필요"를 표시합니다.
- `run_search_item`(research.py 1341행 근처)이 브랜드명, 조합어(`+카테고리`), 타겟(연령·성별) 세트를 모두 수집하는지 확인하고, 빠진 세트를 보완합니다.
- **완료 기준:** 샘소나이트에서 2-8a~d가 생성되고, 발견 규칙 R03~R06 중 1건 이상, Recap 생성

### P2-2. 쇼핑인사이트 수집 (M)
- 새 조사 항목 채널 `shopping_insight`(catalog.py)를 3-11(검색 추이)에 붙입니다.
  - 제품군(`Brand.categories`)마다 네이버 쇼핑 카테고리 코드를 매핑합니다.
  - 매핑은 업종 프로필(P4-2)에 두고, 없으면 AI가 후보를 내고 사람이 확인합니다(`industry_keywords.py`와 같은 패턴).
- **저장할 Fact:**
  - `shop_click_index` (카테고리 × 월)
  - `shop_click_age_share`, `shop_click_gender_share`
- **성수기 판정:** 월별 지수가 12개월 평균의 1.2배 이상인 달을 `peak_month` Fact로 만듭니다. 기준값은 `rules_config`에 둡니다.
- Google Trends(TR1)는 보조로 남깁니다(데이터랩 실패 시).
- **완료 기준:** 카테고리 3개 이상의 월별 추이 + 성수기 Fact, 테스트

### P2-3. 블로그·카페 원문을 네이버 검색 API로 교체 (M)
- **지금:** `run_voc_item`의 카페·블로그 경로가 Perplexity로 `CAFE_BLOG_SITES`를 검색합니다(research.py 871행 근처).
- **변경:**
  - `integrations/naver/client.py`에 `search(kind: "blog"|"cafearticle"|"news"|"kin", query, display=100, start, sort="date")`를 추가합니다.
  - 브랜드 × (자사, 각 경쟁사) × 이름(`Brand.names_for`)마다 날짜순으로 넘기며, 기간 밖이 나오면 멈춥니다.
  - 브랜드당 상한은 블로그 150, 카페 150(`rules_config`)입니다.
  - 본문은 기존 `fetch_page`로 가져옵니다. 로그인 벽(`LOGIN_WALL_MARKERS`)이면 저장하지 않고 '접근 불가'로 셉니다.
  - 티스토리·다음 카페는 기존 Perplexity 경로를 유지합니다.
- 분류(감성, 주제, 인식 경로, 협찬)는 기존 파이프라인을 그대로 씁니다. **자동 채택하지 않습니다.**
- **완료 기준:**
  - 가짜 transport 테스트(기간 경계, 중복, 로그인 벽)
  - 실제 키로 브랜드 하나의 원문 100건 이상(채택 전 후보 기준)

### P2-4. 언급량 수집 (S)
- 같은 검색 API의 `total`을 `mention_total` Fact로 저장합니다.
  - dims: channel(blog/cafe/news), keyword_group(브랜드 / 브랜드+제품군)
  - `measured_at` = 수집일
- 최근 3개월은 P2-3에서 넘겨 본 결과를 월별로 세서 `mention_monthly`로 저장합니다. 상한에 걸리면 `partial=1` dim을 붙입니다.
- **표기 규칙:** 장표에는 "검색 결과 문서 수(누적)"로 씁니다. "검색량"이라고 쓰지 않으며, QC `OVERCLAIMS`에도 추가합니다.
- **완료 기준:** 자사·경쟁사 × 3채널 Fact, 테스트

### P2-5. 블로그 문서 유형 분류 (S)
- 브랜드와 대표 조합어(예: '샘소나이트 캐리어')마다 블로그 상위 30건(정확도순)을 Anthropic이 분류합니다: 실사용, 협찬, 쇼핑·제휴, 홍보 템플릿, 기타
- `blog_type_share` Fact로 저장합니다(dims: keyword, type, n=30).
- 근거 문서 링크는 Fact의 `source_locator`에 남깁니다.
- 분류 결과는 원문 자료가 아니라 측정값이므로 채택 대상이 아닙니다. 대신 자료 확인 화면에 표본 목록을 볼 수 있게 합니다(P3-2).
- **완료 기준:** 지향 덱 10·112쪽과 같은 형태의 수치가 나옴, 테스트

### P2-6. 공식 계정 6채널 수집 (L)
- **구조 변경:** `run_owned_item`을 채널별 함수로 나눕니다.
  - `_owned_instagram`, `_owned_youtube`(쇼츠 포함), `_owned_tiktok`, `_owned_facebook`, `_owned_x`, `_owned_threads`, `_owned_naver_blog`
  - 같은 채널에 URL이 여러 개면 전부 수집합니다. 지금은 `{prof.channel: prof}` 딕셔너리라 마지막 하나만 수집됩니다.
- **ScrapeCreators 클라이언트 추가** (`integrations/scrapecreators/client.py`). **구현 전에 실제 응답을 한 번 받아 필드를 확인**하고, 그 응답을 테스트 픽스처로 저장합니다.

  | 채널 | 엔드포인트 | Fact |
  |---|---|---|
  | 틱톡 | `/v1/tiktok/profile`, `/v3/tiktok/profile/videos` | 팔로워, 월 게시 수, 조회·좋아요·댓글·공유 중앙값 |
  | 페이스북 | `/v1/facebook/profile`, `/v1/facebook/profile/posts` | 팔로워, 월 게시 수, 반응·댓글 중앙값 |
  | X | `/v1/twitter/profile`, `/v1/twitter/user-tweets` | 팔로워, 반응 중앙값 (인기 트윗 기준이라 게시 빈도는 만들지 않음) |
  | 스레드 | `/v1/threads/profile`, `/v1/threads/user/posts` | 팔로워, 월 게시 수, 반응 |
  | 유튜브 쇼츠 | `/v1/youtube/channel/shorts` | 쇼츠 수, 평균 조회 (지금 10편만 잡히는 문제 해결) |
  | 네이버 블로그 | 네이버 검색 API blog, 결과의 `bloggerlink`가 공식 블로그인 것만 | 기간 내 게시 수 (이웃·방문자는 "공개 안 됨") |

- **Fact 이름:** 기존 owned 지표(`owned_followers`, `owned_posts_monthly`, `owned_likes_median`, `owned_views_avg`)에 channel dim만 바꿔 씁니다. 새 이름: `owned_shares_median`, `owned_comments_median`
- 자사와 경쟁사 모두 수집합니다. 경쟁사를 장표에 쓰지 않는다는 주석은 P3-1에서 지웁니다.
- 실패 처리: 비공개·삭제 계정은 '접근 불가', 엔드포인트 오류는 항목 오류로 남깁니다.
- **완료 기준:**
  - 채널별 가짜 transport 테스트
  - 실제 키로 자사 1 + 경쟁사 1 × 6채널 확인
  - 크레딧 사용량을 원장에 기록(프로젝트당 약 2,000 예상)

### P2-7. 댓글 감성과 페인 포인트 확대 (M)
- **지금:** 인스타 상위 3개 게시물 × 1페이지 표본입니다(김가은 님 e99e2d9).
- **변경:**
  - 대상: 기간 내 게시물 중 반응 상위 20개 × 인스타·유튜브·틱톡·페이스북. 댓글 엔드포인트는 각 채널의 `/post/comments`, `/video/comments`입니다.
  - AI 분류 스키마에 `pain_points: list[str]`(원문 속 짧은 불만 표현, 최대 3개)를 추가합니다. 소비자 원문 분류에도 같은 필드를 추가합니다(`CaseMaterial.voc_pain_points`, 마이그레이션 필요).
  - 비슷한 표현 묶기: 브랜드별 페인 포인트를 AI가 대표 표현 5~8개로 묶고 건수를 셉니다. 결과는 `pain_point_count` Fact로 저장하고, 대표 원문 링크를 붙입니다.
  - P1-2의 `comment_sentiment_rate`가 채널별로 계산되게 합니다.
- **완료 기준:** 브랜드별 감성 비율(n 표시)과 페인 포인트 상위 5개 이상, 테스트

### P2-8. 소비자 원문 채널 추가 (S)
- `run_voc_item`에 다음을 추가합니다. X·Threads 검색과 같은 '검색 결과 = 본문' 경로를 씁니다.
  - 틱톡 키워드 검색(`/v1/tiktok/search/keyword`)
  - 유튜브 검색(`/v1/youtube/search`) + 상위 영상 댓글
  - 네이버 지식iN(`kin`)
- `scope.py` 5-1·5-2의 channels/default_channels와 `catalog.py`에 등록합니다.
- **완료 기준:** 수집 현황 화면의 채널별 건수에 표시됨, 테스트

### P2-9. 경쟁사 광고 소재 (M)
- 메타(`/v1/facebook/adLibrary/company/ads`), 틱톡(`/v1/tiktok/ad-library/search`), 구글(`/v1/google/company/ads`)을 수집합니다.
  - 기존 `app/services/ad_library.py`(98d08d8)를 확장합니다.
- 소재 유형(제품, 셀럽, 크리에이터, 할인, 브랜드 필름)을 AI로 분류해 `ad_creative_type_share` Fact로 저장합니다. 대표 소재 이미지는 자산 채택 흐름을 그대로 씁니다.
- **완료 기준:** 경쟁사별 소재 수와 유형 비중, 3-5 포지셔닝 근거로 연결

### P2-10. 크리에이터 필터 (S)
- `discover_instagram`(research.py 655행~)에 다음 조건을 추가합니다.
  - 팔로워 수를 받은 뒤 `creator_min_followers`(기본 1000) 미만 제외
  - 캡션과 바이오에 한글이 없으면 제외(`creator_require_korean`, 기본 true)
- 제외 건수는 `skipped`에 `small`, `foreign`으로 남깁니다.
- **완료 기준:** 테스트, 샘소나이트 재수집 결과 3-1 표에 해외·소규모 계정 0건

---

## P3. 장표와 화면 (장표 담당)

### P3-1. 자사 vs 경쟁사 SNS 비교 장 OW-CMP (M)
- **새 템플릿** `owned.py` `channel_compare_page(ctx, brand_id)`
  - 채널마다 패널 하나: 팔로워, 월 게시 수, 게시물당 반응을 자사 + 경쟁사 묶음 막대(P1-1 여러 계열)로
  - 감성 비율은 누적 막대로
  - 하단에 번호 인사이트 3개(P3-5)
  - 채널이 4개를 넘으면 다음 장으로 이어서 배치
- **build.py:**
  - `TEMPLATE_SECTION`, `TEMPLATE_CHAPTER`(company), `TEMPLATE_LABEL`, `PAGE_ORDER`(2-1 다음)에 추가하고, 자사 브랜드별로 `slot(..., part=...)`
  - `run_owned_item`의 "장표에 끌어오지 않는다" 주석을 지우고, 경쟁사 Fact를 쓰게 합니다.
- **원칙 8 확인:** 자사 브랜드끼리는 비교하지 않습니다. 한 자사 브랜드와 그 브랜드의 경쟁사만 한 장에 둡니다.
- **완료 기준:** 6채널 데이터로 렌더링, 경쟁사 데이터가 없는 채널은 패널 생략, 테스트

### P3-2. 자료 확인 화면: 자사 분석 / 경쟁사 비교 탭 (M, 프론트 포함)
- **백엔드:** `GET /projects/{id}/owned-summary?brand_id=` → 채널별 자사·경쟁사 지표, 월별 게시 추이, 감성 비율, 페인 포인트, 블로그 유형 분포, 언급량. 계산은 P1-2·P2와 같은 Fact를 읽기만 합니다.
- **프론트:** `materials/page.tsx`에 탭 두 개를 추가합니다.
  - 차트는 편집기 `slide-view.tsx`의 차트 컴포넌트를 재사용합니다. 새 차트 라이브러리는 넣지 않습니다.
  - 카드: 채널별 KPI 숫자, 경쟁사 대비 차이
  - 수집이 아직 없으면 "공식 계정을 등록하면 자동으로 채워집니다"와 설정 화면 링크를 보여줍니다.
- **완료 기준:** `npx tsc --noEmit` 통과, 임시 DB에서 수집 직후 탭에 표시됨

### P3-3. 검색·수요·소비자 차트 장 (M)

| ID | 장 | 차트 | 데이터 |
|---|---|---|---|
| MN1 | 채널별 언급량 비교 | 묶음 막대 (자사 + 경쟁사 × 블로그·카페·뉴스) | P2-4 |
| BL1 | 블로그 문서 유형 | 누적 막대 (검색어별) | P2-5 |
| VC1 | 커뮤니티별 부정률 + 원문 카드 | 막대 + 오른쪽 인용 카드 3~4개 | P1-2, P2-3 |
| PP1 | 페인 포인트 | 막대 (상위 5~8) + 대표 원문 | P2-7 |
| SH1 | 품목별 쇼핑 수요·성수기 | 선 (카테고리별) + 성수기 띠 + 연령 막대 | P2-2 |

- 기존 5-1(원문 표)과 5-2(인식 경로 표)는 VC1과 PP1이 생기면 별첨으로 내립니다(P5-3).
- 인용 카드는 `cases.py`의 원문 근거 렌더링(440행 근처)을 `chrome.quote_cards()`로 빼서 같이 씁니다.
- **완료 기준:** 각 장 렌더 테스트, 데이터가 모자라면 생성하지 않음(P3-6 규칙)

### P3-4. 헤드라인 v2: 주장 + 근거 두 줄 (L)
- **스키마** (`insights.py`): `LEAD_SCHEMA`를 `{"claim": segments, "evidence": [segments, segments]}`로 바꿉니다. 이전 스키마로 저장된 `lead_overrides`는 claim만 있는 것으로 읽습니다.
- **규칙** (SYSTEM 프롬프트):
  - claim: 30자 안팎, 진단 판단(강점·이탈·격차·쏠림)을 허용합니다. 핵심어 하나를 강조색으로 표시합니다.
  - evidence: 줄마다 fact_ref 1~2개 또는 원문 인용 근거 1개
  - 유지: `OVERCLAIMS`(판매·매출·광고비 인과 단정), `FORBIDDEN_WORDS`, 숫자는 fact_ref로만
  - 근거 줄이 없는 claim은 다시 쓰게 합니다. 최대 2번 재시도 후 규칙 기반 리드로 대체합니다(기존 흐름).
- **렌더:** `chrome.lead_block`을 2단(`lead_claim`, `lead_evidence`)으로 바꾸고, `templates/style_tokens.v1.json`에 두 스타일과 강조색 `accent`(주황, 지향 덱 색 추출)를 추가합니다.
- **QC** (`qc.py`): 본문 장 헤드라인에 근거 줄이 없으면 경고, 근거 줄의 숫자가 fact_ref가 아니면 차단
- **초안 피드백** (`outline.feedback`): 새 스키마로 다시 씁니다.
- **완료 기준:** 테스트(규칙 위반 재시도, 이전 overrides 호환), 샘소나이트 덱에서 형식 충족률 90% 이상(P1-3)

### P3-5. 장마다 번호 인사이트 3개 (M)
- `insights.page_insights(slide) -> [{title, body_segments}]`. 컨텍스트는 `_body_context`를 재사용하고, 같은 QC를 거치며, fingerprint로 캐시합니다.
- 덱을 만들 때 본문 장(사례 상세 포함) 전체에 대해 실행합니다. 결과는 `chrome.insight_blocks()`로 그립니다.
- **레이아웃:** 모든 본문 템플릿의 본문 영역을 "리드 아래 ~ insights 영역 위"로 고정합니다.
  - 표는 행 수와 상관없이 영역 높이에 맞춰 행 간격을 늘립니다(`owned.py` `Region(h=32 + row_h * len(rows))` 계열을 모두 교체).
  - 패널 폭은 브랜드 수가 아니라 영역 기준으로 계산합니다.
- 사람은 초안 화면에서 고치거나 뺄 수 있습니다. 저장은 `lead_overrides`처럼 `insight_overrides` 컬럼에 합니다(마이그레이션).
- **완료 기준:** 빈 장 0(P1-3), 테스트

### P3-6. 최소 밀도 규칙 (S)
- `SlotPlan.readiness`에 `"thin"`을 추가하고, 템플릿별 최소 기준은 `rules_config.json`의 `min_density`에 둡니다.

  | 장 | 기준 | 미달이면 |
  |---|---|---|
  | 2-1 | 채널 2개 이상 | OW-CMP에 합침 |
  | 2-2, 2-5 | 4개월 이상 | KPI 숫자로 OW-CMP에 합침 |
  | 5-1, 5-2, VC1 | 원문 20건 이상 | 단독 장 없음 |
  | M1 | 근거 3건 이상이면서 자사 카테고리와 일치 | 별첨 |
  | 선 차트 전체 | 점 4개 이상 | 차트 대신 숫자 |

- `missing.py`의 사유: "자료가 적어 ○○ 장에 합쳤습니다"(내부 화면에만 표시)
- **완료 기준:** 테스트, 샘소나이트 덱에 1행 표·점 3개 차트 단독 장 0

### P3-7. 종합 장표 자동 생성 (M)
- `synthesis.py`
  - 덱을 만들 때 `insight` 유형을 자동으로 실행합니다(fingerprint 캐시).
  - SWOT과 문제·솔루션은 지금처럼 선택 사항입니다.
  - 본문 장의 bindings를 함께 넘겨, 수치는 fact_ref로 인용할 수 있게 합니다. 줄마다 근거 장 ref는 유지합니다.
- `synthesis.py`(composition)
  - SWOT 사분면 카드: 2×2 패널, 줄마다 근거 장 번호와 출처 링크
  - "3줄 핵심 인사이트" ES 상단 박스
- `draft/page.tsx`: "종합 장표 만들기" 버튼 대신 "다시 쓰기"로 바꿉니다. 기본 결과가 이미 있는 상태입니다.
- **완료 기준:** 버튼을 누르지 않아도 ES·인사이트가 덱에 포함됨, 테스트

### P3-8. 사례 상세 정리 (S)
- '성과 요약'이 '진행 방식'과 같으면 숨기고, 수치가 없으면 핵심 수치 칸을 빼서 이미지를 넓힙니다.
- 하단의 `ai_implication` 한 줄을 P3-5 번호 인사이트 3개로 바꿉니다(cases.py 459행 분기).
- 영어 원문 근거에는 한국어 요약 한 줄을 붙이고, 원문은 링크로 둡니다.
- **완료 기준:** 테스트, 샘소나이트 사례 상세 장 확인

---

## P4. 리서치 5대 축과 업종 variation (함께)

### P4-1. 시장·정책·관광 수치를 Fact로 (M, 수집 담당)
- 추출(`extract`) 스키마에 `figures: [{metric, value, unit, period, segment, quote}]`를 추가합니다. 시장, 정책, 업종 KPI 자료에서만 씁니다.
- 원문 문장(quote)과 대조되는 숫자만 Fact로 만듭니다(`verification_status=candidate`). 자료를 채택할 때 함께 채택됩니다.
- 정부 통계는 Perplexity로 한국관광공사·통계청·관세청 **보도자료**를 찾아 같은 방식으로 추출합니다. 출처는 보도자료 제목과 날짜로 표시합니다.
- **완료 기준:** 샘소나이트 시장 자료에서 시장 규모·CAGR·출입국자 수 Fact 생성, 테스트

### P4-2. 업종 프로필 12개 (M, 수집 담당 + 사람 검토)
- `core/industry_profiles.py` `IndustryProfile`을 다음처럼 넓힙니다.
  ```python
  class IndustryProfile(NamedTuple):
      keyword_hints: tuple[str, ...] = ()          # 기존
      gov_stats: tuple[str, ...] = ()              # 기존 (보도자료 검색어로 사용)
      axis_queries: dict[str, tuple[str, ...]] = {}  # 5대 축별 질의 템플릿 {market, demand, consumer, policy}
      key_metrics: tuple[str, ...] = ()            # 업종 핵심 지표 (예: 여행=출입국자 수, 뷰티=재구매율)
      season_calendar: tuple[str, ...] = ()        # 성수기 (예: "07-08 휴가", "추석", "설")
      policy_keywords: tuple[str, ...] = ()        # 예: 면세 한도, 소액 수입 기준
      shopping_categories: dict[str, str] = {}     # 제품군 → 네이버 쇼핑 카테고리 코드
      default_scope_on: tuple[str, ...] = ()       # 기본으로 켜는 조사 항목
  ```
- 12개 업종 초안은 AI로 만듭니다. 새 스크립트 `tools/draft_industry_profiles.py`가 Perplexity로 업종별 근거를 찾고, Anthropic이 위 형식으로 씁니다.
- 결과는 **사람이 검토해서** 코드에 넣습니다. 검토가 끝나기 전에는 기존 `industry_keywords.py` 후보 흐름을 씁니다.
- `research.build_queries`와 `scope.py`가 프로필의 `axis_queries`, `default_scope_on`을 읽게 합니다.
- **완료 기준:**
  - 12개 업종 프로필
  - 업종이 다른 두 프로젝트(여행 vs 뷰티)의 조사 항목·질의가 다르게 생성됨(테스트)

### P4-3. 수동 항목 자동화 (M, 수집 담당)
- `scope.py`에서 `collector: None`인 항목 중 공개 웹으로 찾을 수 있는 것을 `collector: "market"`(또는 새 `"issue"`)로 바꿉니다.

  | 항목 | 내용 | 수집 경로 |
  |---|---|---|
  | 4-1 | 신규 소식 | Perplexity + 네이버 뉴스 |
  | 4-2 | 부정 이슈 | Perplexity + 네이버 뉴스 |
  | 3-3 | 신규 플레이어 | Perplexity |
  | 3-6 | 경쟁사 메시지 | 공식 계정 게시물 + Perplexity |
  | 6-1 | 콘텐츠 형식 | Perplexity |
  | 2-5 / 라이프스타일 | 라이프스타일 | Perplexity (트렌드 리포트) |

- 내부 자료가 필요한 항목(2-4 인지·NPS, 2-3 매출 구성)은 P4-5 업로드로 연결합니다.
- **완료 기준:** 수동 항목 4개 이하, 각 항목 결과가 자료 확인 화면에 나옴

### P4-4. 5대 축 장표 (L, 장표 담당)

| ID | 장 | 구성 | 데이터 |
|---|---|---|---|
| MK1 | 시장 규모·성장 | 큰 숫자(시장 규모, CAGR) + 거시 지표 선 차트 + "연 N% 성장" 리드 | P4-1 |
| DM1 | 품목별 수요·시즌 | SH1과 같음 (P3-3에서 만든 것을 5대 축 구간에 배치) | P2-2 |
| PL1 | 정책·규제 | 이슈 / 기관 / 시행일 / 영향 표 (M1에서 분리, `market_aspect="policy"`) | 3-4 |
| CS1 | 소비자 인사이트 | 세대별 구매 결정 요인 + 페인 포인트 막대 + 원문 카드 | P2-7, P4-3 |
| 5-3 | 구매 여정 | 단계 × (접점, 상태, 끊기는 곳) 표 | 생성형 (P5-1과 공유) |
| 5-4 | 구매 상황 지도 | 상황 × 함께 고민하는 브랜드 × 고르는 이유·안 고르는 이유 (원문) | 소비자 원문, 지식iN |

- **완료 기준:** 각 장 렌더 테스트, 샘소나이트 덱에 MK1·PL1·CS1 생성

### P4-5. 고객 제공 자료 업로드 (M, 프론트 포함)
- 양식(엑셀/CSV): `entity, metric_label, value, unit, period_start, period_end, segment, sample_n, source_name, source_date`
  - 양식 파일은 화면에서 내려받습니다.
- 원문 PDF는 출처 파일로 함께 저장합니다(`storage`). Fact `source="client_provided"`, 각주는 "고객 제공 · {source_name}"
- 기존 CSV 가져오기(`core/ingestion/csv_import.py`)에 세 번째 종류로 추가합니다. 배치 단위로 채택해야 계산에 쓰입니다.
- `materials/page.tsx` 업로드 종류에 "보유 자료(설문·내부 리포트·SNS 인사이트)"를 추가합니다.
- 빠진 장표 원인 `upload`가 이 화면을 가리키게 합니다.
- **완료 기준:** 업로드 → 채택 → 차트에 표시(테스트 + 화면 확인)

---

## P5. 진단형 덱 (장표 담당)

### P5-1. 진단 플래너 (L)
- 새 서비스 `app/services/diagnosis.py`, AI 호출은 `STRUCTURED`를 거칩니다.
- **입력:** 브랜드별로 채택된 Fact(파생 포함) 목록(id, 지표, 값, 대상), 원문 요약, 사례 해석 문장, 페인 포인트
- **출력 스키마:**
  ```json
  {"profile": "브랜드 한 줄 진단",
   "funnel": [{"stage": "인지|고려|탐색|구매|검증", "fact_id": "...", "label": "...", "status": "강점|이탈|보통"}],
   "claims": [{"kind": "strength|weakness", "claim": [segments], "evidence": [[segments], [segments]],
               "chart": {"type": "bar|column|stacked|line", "fact_ids": ["..."]},
               "quote_material_ids": ["..."]}],
   "cdj": [{"stage": "...", "touchpoint": "...", "state": "...", "activity": "..."}],
   "proposals": [{"pillar": "소셜|인플루언서|콘텐츠", "title": "...", "cdj_stage": "...", "basis_fact_ids": ["..."]}]}
  ```
- **서버 검증:**
  - 모든 id가 실제 채택 자료에 있어야 합니다.
  - 근거 없는 claim과 proposal은 버립니다.
  - 차트 유형이 Fact 개수·단위와 맞지 않으면 서버가 바꿉니다(예: 시계열이 아니면 line 금지).
- **저장:** `projects.diagnosis`(JSON, 브랜드별·버전별, 마이그레이션). 덱을 만들 때 자동 실행하고 fingerprint로 캐시합니다.
- **화면:** 초안 화면에 "진단" 탭을 둡니다. 주장 목록이 기본으로 포함된 상태이고, 빼기·문장 고치기·다시 쓰기를 할 수 있습니다.
- **완료 기준:** 테스트(검증 규칙), 샘소나이트에서 브랜드마다 강점 1 + 약점 2~3

### P5-2. 진단 템플릿 6종 (L)
- 새 파일 `core/composition/diagnosis.py`

| ID | 장 | 지향 덱 쪽 | 구성 |
|---|---|---|---|
| D1 | 진단 요약 | 6 | 5단 화살표 머리 + 단계별 큰 숫자 + 강점·이탈 구간 괄호 |
| D2 | 강점·약점 증명 | 7~10 | 리드 v2 + 왼쪽 차트 + 오른쪽 원문 카드(태그 칩) + 하단 인사이트 |
| D3 | 경쟁 구도 | 11, 24 | 가격 계층(공식몰 가격, 리뷰 수) 또는 리뷰 격차 막대 + 대표 이미지 |
| D4 | CDJ 시사점 | 17 | 단계 × (고객 접점, 인지 상태 칩, 인지 증대 활동) 표 |
| D5 | 활동 제안 | 18 | 소셜·인플루언서·콘텐츠 3열 카드, 카드마다 CDJ 칩과 근거 한 줄 |
| D6 | 결론 | 57 | 자사 브랜드 × 끊긴 구간 × 3개 축 표 |

- D6은 자사 브랜드를 나란히 놓지만 순위나 점수는 매기지 않습니다(원칙 8).
- **완료 기준:** 각 템플릿 렌더 테스트, 지향 덱 해당 쪽과 나란히 놓고 확인

### P5-3. 덱 순서 전환 (M)
- `core/schemas/project.py`: `report_profile`에 `"diagnosis"`를 추가하고 새 프로젝트의 기본값으로 합니다. 기존 프로젝트는 지금 값을 유지합니다.
- `build.py`: `report_profile == "diagnosis"`이면 다음 순서로 짭니다.
  ```
  표지 → 목차 → ES → 조사 개요(1-1)
  자사 브랜드마다: 간지(profile) → D1 → D2(강점) → D2(약점 ×N) → D3 → OW-CMP → 3-1 크리에이터
                  → 사례 상세 → MK1·DM1·PL1·CS1 중 해당 → D4 → D5
  결론: D6 → 종합(SWOT 등 선택)
  별첨: 2-1·2-2·2-4·2-5·2-8a~d·5-1·5-2·M1·M2·사례 카드(C1)·출처
  ```
  - `CHAPTERS`에 `diagnosis:<brand>`, `conclusion`을 추가합니다. 별첨 장에는 "관련 본문 쪽" 표시(지향 덱 우상단 표기)를 붙입니다.
- 목차(index)는 브랜드 PART 단위로 요약합니다.
- **완료 기준:** 테스트(두 profile 모두), 샘소나이트 덱 구조가 지향 덱과 일치

### P5-4. 최종 측정과 리포트 (S)
- 샘소나이트(자사 3 + 경쟁사 9, 자사 기간 2026.01–09, 경쟁사 사례 2024.10–2026.10)로 다시 만듭니다.
- P1-3 결과를 목표표와 비교해 `var/output/samsonite/GAP_REPORT_v7.md`로 남깁니다.
- 못 미친 지표는 원인(자료 부족, 템플릿, 규칙)별로 다음 작업을 정리합니다.

---

## 하지 않는 것
- 로그인이 필요한 정보 수집. '접근 불가'로 표시만 합니다.
- 공개되지 않는 지표의 추정(인스타 노출·공유 수, 블로그 방문자). 고객 제공 자료로만 받습니다.
- 막힌 API의 우회(네이버 쇼핑 검색 SE05, 아카라이브 403, 페이스북 게시물 검색).
- 출처와 연결되지 않는 숫자가 들어간 문장.
- 고객용 덱의 '자료 없음' 장이나 문구.

## 진척 기록

| 날짜 | 완료 작업 | 장수 | 차트 | 헤드라인 형식 | 하단 인사이트 | 빈 장 | 원문/브랜드 | 메모 |
|---|---|---|---|---|---|---|---|---|
| 2026-11-10 | (기준) v14 | 37 | 2 | 0% | 일부 | 약 10 | 9 | |
| 2026-11-12 | P5-4 진단형 v7 | 106 (본문 47) | 16 | 24.0% | 28.0% | 21 | 0 | QC 차단 0, D1~D6·렌더 106/106; 신규 조사 계획 미적용 데이터셋 |
