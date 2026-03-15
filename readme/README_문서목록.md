# readme — 문서 모음

이 폴더의 **문서는 삭제하지 마세요.** 프로젝트 참고용으로만 사용합니다.

---

## 가이드/ (10개)

배포·분류·UI·데이터 관련 가이드 문서입니다.

| 파일 | 설명 |
|------|------|
| Railway_가입_배포_도메인.md | Railway 배포·도메인 설정 |
| 금융정보_위험도_지표_매칭_가이드.md | 1~10호 위험도 지표 매칭 절차 |
| 업종분류_참조코드.md | category_table 기반 업종분류 참조 |
| category_table_업종분류_xlsx_백업.md | JSON↔XLSX 백업 방법 |
| cash_bank_card_컬럼_매칭.md | cash↔bank↔card 컬럼 매핑 |
| 은행_전처리후_키워드_카테고리_기타거래_안내.md | bank_after 키워드 비었을 때 해결 |
| 계정과목_표준.md | category_table.json 파싱·변환 규칙 |
| 파일_정리_가이드.md | 프로젝트 파일 구조·정리 방안 |
| 팔레트_가이드.md | MyRisk 모듈별 색상 팔레트 |
| MyRisk_Color_Palette.png | 색상 팔레트 시각 자료 |

---

## 스크립트/ (11개)

서버 기동·카테고리 동기화·백업 등 유틸 스크립트입니다.

| 파일 | 설명 |
|------|------|
| start-server.ps1 | UTF-8 설정 후 MyRisk 서버 기동 |
| start-server.bat | Cursor 밖에서 서버 실행용 배치 |
| start-cursor-no-hangul.ps1 | TEMP=C:\Temp로 Cursor 실행 |
| create-workspace-junction.ps1 | C:\CursorWorkspace 정션 생성 (한글 깨짐 방지) |
| setup-git-utf8.ps1 | Git UTF-8 인코딩 설정 |
| run_full_flow.py | 은행·카드 before 확보 후 서버 기동 |
| backup_업종분류_to_xlsx.py | category_table → 업종분류_table.xlsx 내보내기 |
| category_table_xlsx_to_json.py | .source/category_table.xlsx → JSON 변환 |
| sync_category_from_server.py | 서버 → 로컬 category_table 복사 |
| sync_category_from_server.ps1 | 서버 → 로컬 동기화 래퍼 (PowerShell) |
| add_virtual_asset_category.py | 가상자산 업체를 category_table에 추가 |

---

## 특허자료/ (14개)

특허 출원·시스템 구성도·법률 참고 자료입니다.

| 파일 | 설명 |
|------|------|
| system_flow.md | MyRisk 시스템 구성·순서도 기술문서 |
| system_flow_print.html | 시스템 구성도 Mermaid 인쇄용 HTML |
| 인공지능 기반의 개인회생_파산_면책 소명자료 자동생성 시스템 및 방법.pdf | AI 파산면책 소명자료 자동생성 특허 |
| 인공지능 기반의 개인회생파산면책 프롬프트 작성용.docx | AI 파산면책 프롬프트 작성 가이드 |
| 특허출원.docx | 특허출원서 원본 |
| 특허출원가이드.docx | 특허출원 절차·양식 가이드 |
| p-14_s(특허출원서).hwp | 특허출원서 원문 (한글) |
| p-14_s(특허출원서).pdf | 특허출원서 PDF |
| 제564조 제1항 각 호에 따른 데이터 판별 로직.txt | 564조 법적 사유별 위험도 판별 로직 |
| 카드사별 매출전표 집계 시스템.docx | 카드사별 매출전표 집계 시스템 문서 |
| [별표 1] 협업기업 선정에서 제외되는 업종(...).pdf | 협업 제외 업종 법률 자료 |
| 가상자산사업자 신고에 관한 정보공개현황(2026.1.14. 기준).xlsx | FIU 가상자산사업자 신고 현황 |
| 파산면책회생조정(김찬식).xlsx | 파산면책 회생조정 관련 자료 |
| 파산신청준비서류.pdf | 파산신청 필요 서류 목록 |

---

## 참고자료/ (1개)

코드 개선 제안 문서입니다.

| 파일 | 설명 |
|------|------|
| 코드_개선_종합.md | 코드 개선 적용 이력 + 미적용 잔여 제안 |

---

## 분석메모/ (9개)

UI 레이아웃·데이터 플로우·리팩토링 검토 기록입니다.

| 파일 | 설명 |
|------|------|
| 로딩시간_리팩토링_검토.md | 카테고리 데이터 로딩 시간 단축 검토 |
| 금융정보_카테고리조회_처리내용.md | 금융정보 통합조회(은행+카드) 처리 내용 |
| 네비게이션_구조_검증.md | 네비게이션 계층 구조 및 홈 통일 검증 |
| 말풍선_카테고리조회_vs_업종분류조회.md | 행 툴팁(말풍선) 속성·차이 비교 |
| 반응형_수정_시_문제점_정리.md | 반응형 수정 시 CSS·스크롤 이슈 정리 |
| 은행거래전처리_구성요소_높이속성.md | 전처리전/후 영역 구성요소·높이 속성 |
| 은행거래카테고리_카테고리적용후_속성_높이.md | 카테고리적용후 영역 CSS·높이 속성 |
| bank_card_source_before_after_비교.md | 은행·카드 source→before→after 구현 비교 |
| category_통합_가이드.md | category.html·모듈 통합 가능 여부 가이드 |

---

- **루트 README**: 프로젝트 루트의 `README.md`는 GitHub에서 기본으로 보이는 요약입니다.
