# Windows Code Upgrade Retro - 2026-05-16

## Context

Mac side shipped commit `ca840e9 perf: add whisper.cpp CLI backend`.
Windows side was asked to pull, validate, report, and continue running as Run Owner.
Windows Run Owner boundary was preserved: no `.py`, dependency, hook, or architecture edits were made locally.

## Change Summary From Mac

- Added whisper.cpp CLI backend selection through environment variables.
- Added `WHISPER_BACKEND=auto` fallback behavior.
- Added `backend_used`, `fallback_reason`, and `failed_stage` progress fields.
- Added preprocessing caches under `cache/keyframes`, `cache/transcripts`, and `cache/payloads`.
- Added run reports under `runs/*.md`.
- Added more accurate Gemini request accounting for retries/continuations.
- Added Windows runbook documentation.

## Reasoning / Assessment

The upgrade is effective based on Windows validation.

Evidence:

- `whisper-cli.exe --help` worked.
- `python zhihuTTS.py --status` worked.
- With `WHISPER_BACKEND=auto`, real Windows run used `whispercpp-vulkan`.
- `.progress.json` recorded `backend_used=whispercpp-vulkan` and `fallback_reason=null`.
- A timeout/interruption after preprocessing did not waste the preprocessing work. Retry hit cache and completed.
- Today's >300 MiB processed video did not reproduce yesterday's `MAX_TOKENS` issue.

Limits:

- The one whisper.cpp sample was a different video than the CPU samples, so runtime is not a clean apples-to-apples speed comparison.
- Direct rerun of the exact three yesterday `MAX_TOKENS` videos was not performed because they were already marked done.

## Validation Commands

```powershell
git pull --rebase
python zhihuTTS.py --status

$env:WHISPER_BACKEND='auto'
$env:WHISPER_CPP_EXE='D:\tools\whisper.cpp\whisper-cli.exe'
$env:WHISPER_CPP_MODEL='D:\tools\whisper.cpp\models\ggml-small-q5_1.bin'
$env:WHISPER_BEAM_SIZE='1'
$env:WHISPER_WORD_TIMESTAMPS='0'
$env:WHISPER_CPU_THREADS='0'
$env:WHISPER_CPU_WORKERS='4'
python zhihuTTS.py
```

## Validation Results

- Pulled `ca840e9`, then committed Windows validation output as `3f08c3c`.
- CPU smoke run before whisper.cpp setup completed 3 videos:
  - `产品设计运营_08`
  - `多模态_01`
  - `多模态_02`
- whisper.cpp validation completed:
  - `部署交付_01_【David】智能算力那点事儿`
  - Backend: `whispercpp-vulkan`
  - Keyframes: 360
  - Transcript segments: 2507
  - Transcript chars: 87130
  - Transcription time: 2217.28s
- Retry after timeout logged cache reuse:
  - `命中预处理缓存: 360 张关键帧`
- Progress after validation:
  - Done: 39/63
  - Failed: 0
  - Quota: 11/20

## MAX_TOKENS Follow-up

Yesterday `MAX_TOKENS` occurrences:

- `AI编程_02`: `FinishReason.MAX_TOKENS`, 261455 chars
- `LangChain_01`: `FinishReason.MAX_TOKENS`, 169694 chars
- `RAG_02`: `FinishReason.MAX_TOKENS`, 4479 chars

Today:

- No `FinishReason.MAX_TOKENS` appeared in 2026-05-16 processed task logs.
- Today processed one >300 MiB video:
  - `产品设计运营_06`
  - 332.61 MiB / 348.76 MB
  - Completed without `MAX_TOKENS`.
- `RAG_02` source size is 261.95 MiB / 274.68 MB.

Assessment: the code upgrade contains the intended auto-continuation fix and today's runs did not reproduce `MAX_TOKENS`. Strict same-video regression for all three yesterday cases remains unperformed because those tasks are already marked done.

## Errors Observed And Handling

### Gemini SSL EOF

Observed:

```text
[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1081)
httpcore.ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1081)
httpx.ConnectError: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1081)
```

Handling:

- Let built-in retry continue.
- Retry succeeded.
- `.progress.json` correctly counted the affected video as `api_calls=2`.

### Runner Timeout

Observed:

```text
command timed out after 2400207 milliseconds
command timed out after 300201 milliseconds
```

Handling:

- Verified no lingering Python/whisper processes.
- Reran the command.
- Confirmed cache reuse before Gemini.

### PowerShell Profile Noise

Observed:

```text
cannot load C:\Users\Admin\Documents\WindowsPowerShell\Microsoft.PowerShell_profile.ps1 because script execution is disabled
```

Handling:

- Treated as environment noise.
- Kept it out of run-result interpretation.

### Git Credential / Permission Noise

Observed:

```text
schannel: AcquireCredentialsHandle failed: SEC_E_NO_CREDENTIALS (0x8009030e)
Unable to create '.git/index.lock': Permission denied
```

Handling:

- Re-ran Git operations with approved elevated permissions.
- Commit and push succeeded.

## Git Records

- Mac code upgrade: `ca840e9 perf: add whisper.cpp CLI backend`
- Windows validation output: `3f08c3c run: validate windows whispercpp backend`

## Next Action

Continue today's remaining quota from 39/63, quota 11/20, with the same safe whisper.cpp environment.
