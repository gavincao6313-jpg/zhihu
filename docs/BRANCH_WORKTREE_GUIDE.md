# Zhihu Branch and Worktree Guide

Last updated: 2026-05-18

This repository is maintained with two active working directories. Keep the
directory, branch, and workload aligned before committing or pushing.

## Windows worktrees

| Local directory | Branch | Purpose |
| --- | --- | --- |
| `D:\zhihu\zhihu_file` | `feature/local-transcript-appendix` | Parse local MP4 files, transcribe audio, generate word-level transcripts, and write Markdown output. |
| `D:\zhihu\zhihu_url` | `feature/stream-transcript-validation` | Parse video streams or URLs, transcribe audio, generate word-level transcripts, and write Markdown output. |

The `zhihu_url` directory is a Git worktree whose `.git` pointer should resolve
to:

```text
D:/zhihu/zhihu_file/.git/worktrees/zhihu_url
```

## Mac user workflow

Before pushing, verify the current branch:

```bash
git status --short --branch
```

Use these branch meanings:

- Push local MP4 file parsing/transcript changes to
  `feature/local-transcript-appendix`.
- Push video stream or URL parsing/transcript changes to
  `feature/stream-transcript-validation`.

If both workflows changed, commit and push them separately from the matching
branch. Do not mix local-file changes and URL/stream changes in one branch
unless the same change is intentionally shared by both workflows.

## Recommended checks before push

```bash
git status --short --branch
git diff --stat
python -m py_compile zhihuTTS.py zhihuTTS_video.py
```

For the URL/stream branch, also compile stream-specific modules when present:

```bash
python -m py_compile zhihuTTS_stream.py stream_extractors.py sensevoice_probe.py
```

## Windows notes

If Git reports a dubious ownership error after moving or renaming directories,
add both directories as safe repositories:

```bash
git config --global --add safe.directory D:/zhihu/zhihu_file
git config --global --add safe.directory D:/zhihu/zhihu_url
```

If `D:\zhihu\zhihu_url` stops being recognized as a Git repository after a
rename, check `D:\zhihu\zhihu_url\.git`. It should contain:

```text
gitdir: D:/zhihu/zhihu_file/.git/worktrees/zhihu_url
```
