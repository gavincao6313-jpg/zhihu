# Windows Transcript Backfill - 2026-05-17

## Scope

- Pulled the latest Mac-side code on `feature/stream-transcript-validation`.
- Set `core.hooksPath` to `githooks`.
- Ran transcript backfill for already-completed videos.
- Checked whether missing transcript appendices could be generated from local inputs.

## Git / Branch

- Branch: `feature/stream-transcript-validation`
- Repo was already up to date after `git pull --ff-only`.

## Commands Run

```powershell
git pull --rebase
git config core.hooksPath githooks
python zhihuTTS.py --status
python zhihuTTS.py --backfill-transcripts
python zhihuTTS.py --backfill-transcripts --transcribe-missing
```

## Results

- `python zhihuTTS.py --backfill-transcripts` completed successfully.
- Backfill summary:
  - `updated=13`
  - `skipped_existing=0`
  - `missing_markdown=15`
  - `missing_transcript=35`
  - `transcribed=0`
- The run appended transcript sections to 13 completed Markdown files from cache.
- The subsequent `--transcribe-missing` run was allowed to finish; the working tree shows 16 Markdown files modified in total, covering:
  - the 13 cache-backed backfills
  - 3 older completed items under `Markdowns/TTS_0515_*`

## Shared Outputs

- Updated Markdown files under `Markdowns/TTS_*.md`
- Run notes under `runs/*.md`

## Local-Only Artifacts

- `zhihuTTS.log`
- `.claude/settings.local.json`
- `.codex/hooks.json`
- Raw replay artifacts under `runs/stream-replay-full_chunk*.{txt,json}`

## Notes

- The PowerShell execution-policy warning still appears because the profile is loaded by default.
- Git also emits a permission warning for `C:\Users\Admin\.config\git\ignore`.
- The run produced stream-validation Markdown artifacts under `runs/stream-replay-full_chunk*.md`; these are shared outputs and should be committed separately from the raw `.txt` / `.json` replay files.
