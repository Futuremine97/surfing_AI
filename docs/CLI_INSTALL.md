# surfing-ai CLI — 설치 가이드 (cmux · tmux · command, 전 OS)

이 문서는 `surfing-ai` CLI를 세 가지 사용 방식 모두에 대해 macOS / Linux / Windows에서 설치·실행하는 방법을 다룹니다. 사용 방식은 `cli/reverse_questions.json`의 역질문 흐름과 1:1로 대응합니다.

| 트랙 | 명령 | 추가 요구사항 |
|------|------|---------------|
| **cmux** (내장 멀티탭 TUI) | `surfing-ai`, `exec`, `par` | Node ≥ 18, python3 |
| **tmux** (4-pane / 그리드) | `tmux-private`, `max-procs` | python3, **tmux** |
| **command** (비대화형) | `exec`, `par`, `desktop`, `approvals`, `backend-health` | python3 (Node는 npm CLI 사용 시) |

모든 트랙은 동일한 private-mode 하니스(allowlist · file guard · redaction · audit · `files_sent_external = 0`)를 거칩니다.

---

## 0. 공통 사전 요구사항

- **Python 3.10+** (필수, 전 트랙)
- **Node.js 18+** (npm `surfing-ai` 래퍼 / cmux TUI 사용 시)
- **tmux** (tmux 트랙에서만)

### 설치 (OS별)

**macOS** (Homebrew)
```bash
brew install python node tmux
```

**Linux** (Debian/Ubuntu)
```bash
sudo apt update && sudo apt install -y python3 nodejs npm tmux
```
**Linux** (Fedora/RHEL)
```bash
sudo dnf install -y python3 nodejs tmux
```

**Windows**
```powershell
winget install Python.Python.3.12
winget install OpenJS.NodeJS.LTS
```
> tmux는 Windows 네이티브에 없습니다. tmux 트랙은 **WSL**(`wsl --install` 후 위 Linux 절차)에서 사용하세요. cmux·command 트랙은 PowerShell에서 그대로 동작합니다.

---

## 1. npm 설치 (cmux / command 트랙 권장 진입점)

```bash
npm install -g github:Futuremine97/surfing_AI   # GitHub에서 바로
# 레지스트리 게시 후에는:
npm install -g surfing-ai
```

설치 확인:
```bash
surfing-ai --version
surfing-ai --help
```

> npm 없이 로컬 체크아웃에서 직접 쓰려면 `python3 scripts/surfing_ai <command>` 형태로 동일하게 실행할 수 있습니다.

---

## 2. 트랙별 실행

### cmux — 내장 멀티탭 TUI
```bash
surfing-ai                      # 기본: 멀티탭 TUI (TTY일 때)
surfing-ai --mode redacted-external   # 모드 지정 시작
```
탭 단축키: `Ctrl+T` 새 탭 · `Ctrl+W` 닫기 · `Alt+1..9` / `Alt+←→` 전환 · `Ctrl+C` 종료.
탭 안 병렬: `:par a ; b ; c` (CPU 코어 수만큼 분산).

단발/병렬도 같은 트랙:
```bash
surfing-ai exec "git status"
surfing-ai par "git status" "ls -la" "python3 -V"
```

### tmux — 화면 분할 워크스페이스
```bash
surfing-ai tmux-private                 # 4-pane tmux 세션
surfing-ai tmux-private --dry-run       # 생성 계획만 미리보기
surfing-ai max-procs                    # 코어당 1 REPL 그리드 (tmux)
surfing-ai max-procs --panes 4          # pane 수 지정
surfing-ai max-procs --run "cmd a" "cmd b"   # 헤드리스 병렬 (tmux 불필요)
```
> tmux 미설치 시 `tmux-private`는 `TMUX_NOT_FOUND`와 함께 `terminal-private` 폴백을 안내합니다.

### command — 비대화형 / 자동화
```bash
surfing-ai exec "git status"            # 단발
surfing-ai par "a" "b" "c"              # 병렬
surfing-ai desktop --open               # 로컬 브라우저 UI (127.0.0.1:4175)
surfing-ai approvals list               # 승인 큐
surfing-ai backend-health               # 상태 점검
```
TTY가 없어도 동작하므로 CI/스크립트에 적합합니다.

---

## 2.5 스레드 사용량 제어 (multi-thread budget)

`surfing-ai`는 실행 머신의 **논리 스레드 수**(SMT/Hyper-Threading 포함, `os.cpu_count()`)를 읽어 워커 수를 비율로 정할 수 있습니다. 선택지는 **20% / 50% / 60% / 70% / 80% / 90% / 100%**.

먼저 내 머신 기준 환산표를 확인:
```bash
surfing-ai threads
```
예시 출력 (논리 스레드 8개):
```
logical threads detected: 8

  level   workers
  -----   -------
   20%        2
   50%        4  <- default
   60%        5
   70%        6
   80%        6
   90%        7
  100%        8
```
(반올림으로 일부 인접 단계가 같은 워커 수가 될 수 있습니다.)

비율로 병렬 실행:
```bash
surfing-ai max-procs --threads 50            # 논리 스레드의 50% 만큼 워커
surfing-ai max-procs --threads 100 --run "a" "b"   # 모든 스레드로 헤드리스 병렬
surfing-ai par --threads 70 "cmd a" "cmd b"  # par 단축형
```
규칙: 항상 최소 1워커, 총 스레드 초과 불가. `--panes <정수>`를 함께 주면 정확한 개수가 우선합니다. `--threads`는 `20|50|70|100|max`를 받습니다.

역질문 흐름에서는 `max-procs` 진입 시 "워커 수를 스레드 %로 정할지 / 정확한 개수로 정할지" 묻고, %를 고르면 20/50/70/100 중 선택지를 제시합니다(`cli/reverse_questions.json`의 `shared_questions.thread_budget`).

## 3. 보안 모드 (전 트랙 공통)

REPL 안에서 `:mode <name>`으로도 전환 가능합니다.

- `local-only` (기본) — allowlist 셸 명령만, 외부 백엔드/MCP 즉시 거부
- `redacted-external` — 리댁션 + 미리보기 + 명시적 `y` 승인 후에만 외부 전송 (파일 내용 전송 안 됨, Enter는 No)
- `audit` — 아무것도 실행하지 않고 모든 동작을 dry-run 계획으로 기록

선택적 deny 규칙: `.surfing_ai_private.yaml` (커밋 금지, `config/example_private_mode.yaml` 참고). 모든 세션은 `reports/surfing_ai_terminal_<timestamp>/`에 감사 로그를 남깁니다.

---

## 4. 데스크톱 앱 (선택)

GitHub Release에 tmux/cmux 스타일 멀티세션 데스크톱 앱이 첨부됩니다 (macOS `.dmg`, Windows `.exe`, Linux `.AppImage`/`.deb`). 직접 빌드:
```bash
python3 scripts/build_desktop_app.py --output dist --dmg
```
macOS 첫 실행이 차단되면: 우클릭 → 열기, 또는 `xattr -cr "/Applications/Surfing AI Desktop.app"`.

---

## 5. 역질문 흐름과의 연결

`cli/reverse_questions.json`은 위 트랙을 자동화하는 실행형 스펙입니다. 드라이버는 `entry_question`(cmux/tmux/command)으로 트랙을 고르고, 해당 명령의 질문을 물은 뒤 각 옵션의 `maps_to`로 플래그를 조립해 `command_template`을 완성합니다.
