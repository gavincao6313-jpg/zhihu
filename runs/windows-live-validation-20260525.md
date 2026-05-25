# Windows Live Validation - 2026-05-25

## Git
- branch: `main`
- validated commit: `78c568e`

## Command
- run command: `run_zhihu_live.bat "<live URL>"`
- with Gemini: yes
- capture mode: continuous HLS recorder + async consumer
- stream-stage Gemini: no
- final synthesis: one-shot

## Outputs
- BASE: `live_20260525_电商行业AI转型应用_选品_智能决策_营销辅助`
- base marker: `runs/stream-base-live-20260525-195230.txt`
- final QC: `runs/stream-live_20260525_电商行业AI转型应用_选品_智能决策_营销辅助-20260525-225815.final-qc.json`

## Key Metrics
- chunks: 183
- timeline duration: 11003s
- transcript chars: 55447
- frames: 499
- gaps: 0
- failed chunks: 0
- silent chunks: 0
- source_status: `full`
- body_coverage_status: `ok`
- body_tail_gap_s: 3
- deterministic appendices: `full_transcript`, `visual_evidence_index`

## Review Notes
- This run validates the production live capture shape: continuous HLS completed with no recorded gaps and no failed chunks.
- The committed QC file records `synthesis_model: gemini-2.5-flash`, so this run does not prove the later `gemini-3.5-flash` code path. Validate the 3.5 path separately with `scripts/build_stream_markdown.py --dry-run` plus one controlled final synthesis run.
- The base marker preserved Chinese characters correctly: `live_20260525_电商行业AI转型应用_选品_智能决策_营销辅助`.
