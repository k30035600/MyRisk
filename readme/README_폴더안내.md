# readme 폴더 안내

이 폴더는 **참고 문서·가이드·유틸 스크립트**를 모아 둔 곳입니다. 삭제하지 마세요.

## 서브폴더 구조

| 폴더 | 내용 | 개수 |
|------|------|:----:|
| **가이드/** | 배포·분류·UI·데이터 가이드 | 10개 |
| **스크립트/** | 서버 기동·카테고리 동기화·백업 유틸 | 11개 |
| **특허자료/** | 특허 출원·시스템 구성도·법률 참고 | 14개 |
| **참고자료/** | 코드 개선 제안 | 1개 |
| **분석메모/** | UI 레이아웃·데이터 플로우·리팩토링 검토 | 9개 |

## 주요 스크립트 (readme/스크립트/)

| 파일 | 용도 | 실행 예 |
|------|------|---------|
| start-server.ps1 | MyRisk 서버 기동 | `.\readme\스크립트\start-server.ps1` |
| setup-git-utf8.ps1 | Git UTF-8 설정 | `.\readme\스크립트\setup-git-utf8.ps1` |
| create-workspace-junction.ps1 | C:\CursorWorkspace 정션 | `.\readme\스크립트\create-workspace-junction.ps1` |
| start-cursor-no-hangul.ps1 | Cursor 한글 경로 오류 시 | `.\readme\스크립트\start-cursor-no-hangul.ps1` |
| run_full_flow.py | 은행·카드 before 확보 후 서버 기동 | `python readme/스크립트/run_full_flow.py` |
| category_table_xlsx_to_json.py | .source/xlsx → JSON 변환 | `python readme/스크립트/category_table_xlsx_to_json.py` |
| backup_업종분류_to_xlsx.py | category_table → xlsx 내보내기 | `python readme/스크립트/backup_업종분류_to_xlsx.py` |

자세한 내용은 **README_문서목록.md**를 보세요.
