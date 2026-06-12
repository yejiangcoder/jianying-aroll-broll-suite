# Workflow

The project follows a local-first workflow.

```text
B-roll design markdown
  + final subtitles
  + local AI image directory
      |
      v
broll_semantic_plan.csv
      |
      v
broll_exec_plan.csv
      |
      v
optional AI_BROLL draft JSON track
```

## Inputs

- B-roll design markdown with `index`, `type`, `target_quote`, and `visual_direction`.
- A subtitle source, currently SRT or a readable Jianying-style attachment JSON.
- A local image directory containing files with stable IDs such as `*_AI_01_*.png`.

## Plans

The semantic plan confirms which image maps to which target quote. The execution plan adds final subtitle timing:

- image ID
- image path
- subtitle index
- matched subtitle text
- start time
- fixed duration
- confidence

## Draft Write

The draft writer expects a readable draft JSON object. It appends a video track named `AI_BROLL`, adds photo materials, and creates one segment per execution plan row.

The package does not bundle proprietary draft decoders. Users can plug in their own local decoder through external tooling if their editor version stores encoded draft content.

