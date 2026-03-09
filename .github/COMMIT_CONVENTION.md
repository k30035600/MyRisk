# 커밋 메시지 규칙

한글·영문 모두 사용 가능합니다. UTF-8로 저장된 메시지 파일 사용 시 한글 깨짐을 방지할 수 있습니다.

## 형식 (선택)

- `feat: 설명` — 기능 추가
- `fix: 설명` — 버그 수정
- `refactor: 설명` — 리팩터/정리
- `docs: 설명` — 문서만 변경

## 예시

- 한글: `feat: 은행 잔액 그래프 절대값 표시`
- 영문: `fix(bank): handle empty category table`

## 한글 커밋 시: commit_msg_utf8.txt

**commit_msg_utf8.txt**는 한글 커밋 메시지를 UTF-8로 넣기 위한 **임시 파일**입니다.

1. 메시지를 UTF-8로 저장한 파일을 만듭니다. (예: `commit_msg_utf8.txt`)
2. `git commit -F commit_msg_utf8.txt` 로 커밋합니다.
3. 이 파일은 `.gitignore`의 `commit_msg_*.txt`에 의해 **커밋되지 않습니다** (로컬에서만 사용).

예시는 `.github/commit_msg_utf8.example.txt` 를 복사해 쓰면 됩니다.

```bash
git add .
copy .github\commit_msg_utf8.example.txt commit_msg_utf8.txt
# commit_msg_utf8.txt 내용 수정 후
git commit -F commit_msg_utf8.txt
```

상세: 프로젝트 `.cursor/rules/git-commit-encoding.mdc` 및 `readme/` 내 Git 관련 문서 참고.
