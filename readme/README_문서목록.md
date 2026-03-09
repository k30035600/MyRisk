# readme — 문서 모음

이 폴더의 **문서는 삭제하지 마세요.** 프로젝트 참고용으로만 사용합니다.

---

## 가이드/ (10개)

운영·설정·분류에 관한 가이드 문서입니다.

| 파일 | 설명 |
|------|------|
| Railway_가입_배포_도메인.md | Git 초기화 ~ GitHub 푸시 ~ Railway 배포·도메인·한글 깨짐 (통합) |
| 한글_깨짐_Add-Content_오류.md | 한글 경로/깨짐/Add-Content 오류 종합 대응법 |
| 금융정보_위험도_지표_매칭_가이드.md | 위험도 1~10호 지표·호별 매칭·금액 설정·저장 흐름 (통합) |
| 업종분류_참조코드.md | category_table 기반 업종분류 구조 + 코드 위치 참조 |
| category_table_업종분류_xlsx_백업.md | category_table JSON↔XLSX 백업/복구 스크립트 (통합) |
| 파일_정리_가이드.md | 파일+폴더 구조·JSON 분류·정리 방안 (통합) |
| cash_bank_card_컬럼_매칭.md | bank_after/card_after → cash_after 컬럼 매핑 스키마 |
| 은행_전처리후_키워드_카테고리_기타거래_안내.md | 은행 before→after 흐름, 빈 값 처리 |
| 코드_주석_및_유지보수_가이드.md | 코드 주석 구조·유지보수 규칙 |
| 금융정보_고급분석.md | 금융정보 종합의견·고위험 카테고리 보정 설계 |

---

## 스크립트/ (13개)

서버 기동·카테고리 동기화·백업 등 유틸 스크립트입니다.

| 파일 | 설명 |
|------|------|
| start-server.ps1 | MyRisk 서버 기동 (UTF-8 설정 포함) |
| start-server.bat | 서버 기동 배치 스크립트 |
| start-cursor-no-hangul.ps1 | TEMP 한글 제거 후 Cursor 실행 |
| create-workspace-junction.ps1 | C:\CursorWorkspace 정션 생성 |
| setup-git-utf8.ps1 | Git UTF-8 인코딩 설정 |
| run_full_flow.py | 전체 처리 흐름 일괄 실행 |
| backup_업종분류_to_xlsx.py | 업종분류_table xlsx 내보내기 |
| category_table_xlsx_to_json.py | category_table xlsx → json 변환 |
| sync_category_from_server.py | 서버 → 로컬 category_table 동기화 |
| sync_category_from_server.ps1 | 서버 → 로컬 동기화 (PowerShell) |
| add_virtual_asset_category.py | 가상자산 category_table 항목 추가 |
| 로딩시간_줄이는_방법.md | 로딩 시간 감축 방법 정리 |
| 로딩시간_단축_제안_승인후적용.md | 로딩 단축 제안 (승인 후 적용) |

---

## 특허자료/ (4개)

시스템 구성도·특허 명세서 관련 자료입니다.

| 파일 | 설명 |
|------|------|
| system_flow.md | 시스템 구성도·순서도 Mermaid (특허 명세서용) |
| system_flow_print.html | 시스템 구성도 인쇄용 HTML |
| 인공지능 기반의 개인회생_파산_면책 소명자료 자동생성 시스템 및 방법.pdf | 특허 출원 관련 PDF |
| 인공지능 기반의 개인회생파산면책 프롬프트 작성용.docx | 특허 프롬프트 작성용 Word |

---

## 참고자료/ (6개)

코드 개선 제안·API 참고·분석 보고서입니다.

| 파일 | 설명 |
|------|------|
| 코드_개선_종합.md | 코드 개선 적용 이력 + 미적용 잔여 제안 (4개 파일 통합) |
| 금융정보 고급분석.pdf | 금융정보 고급분석 PDF 보고서 |
| 금융정보 고급분석.docx | 금융정보 고급분석 Word 원본 |
| cash_after 컬럼 매칭.docx | cash_after 컬럼 매칭 설계 문서 |
| 금융_업종_API_참고.txt | 업종·FIU·가상자산 API 참고 체크리스트 |
| # 모든 행의 위험도는 0.1이 기본.txt | 위험도 기본값·매칭 절차 정의 메모 |

---

## 분석메모/ (10개)

과거 작업 중 분석·검토·점검 기록입니다.

| 파일 | 설명 |
|------|------|
| 로딩시간_리팩토링_검토.md | 로딩 병목 분석·캐시 동작·미적용 최적화 제안 (3개 파일 통합) |
| 업종분류_미사용_전수조사_문제점.md | category_table 기반 업종분류 의존성 조사 |
| 금융정보_카테고리조회_처리내용.md | 금융정보 통합 조회 UI/API/테이블 구조 |
| 네비게이션_구조_검증.md | 네비게이션 계층·경로 구조 점검 |
| 말풍선_카테고리조회_vs_업종분류조회.md | 카테고리·업종분류 말풍선 CSS/동작 비교 |
| 반응형_수정_시_문제점_정리.md | 반응형 수정 시 주의사항 체크리스트 |
| 테이블_헤더_비침_해결_확인_전체.md | 테이블 헤더 비침 문제 해결 현황 |
| 폴더_사용여부_검사.md | 폴더 사용 여부 점검 결과 |
| bank_card_source_before_after_비교.md | 3개 앱 데이터 플로우 비교 |
| category_통합_가이드.md | category.html 통합 방안 (미착수 계획) |

---

- **루트 README**: 프로젝트 루트의 `README.md`는 GitHub에서 기본으로 보이는 요약입니다.
- **정리 보고서**: `readme_파일목록_정리.html` — A4 출력용 파일 목록 정리 (2026-03-09)
