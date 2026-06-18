# A-Roll V21 Fixture Requirements

Production-parity fixtures must be minimal and sanitized.

Allowed:

- Canonical source graph snippets
- Word timeline snippets
- Display subtitle/caption snippets
- Final timeline/EDL snippets
- Material template snippets
- Validator reports and blocker reports

Forbidden:

- `draft_content.json`
- `template-2.tmp`
- Jianying draft folders
- Images, audio, video, generated media
- Large runtime JSON
- Raw logs

Current fixture roots:

- `fixtures/real_materials/`
- `fixtures/real_timelines/`
- `fixtures/uat_capsules/`

Use `tools/export_aroll_v21_uat_capsule.py` to export only V21 artifacts from a V21 run directory.

If a fixture was not exported from a live UAT run, mark it as `synthetic_realistic` and `real_uat=false`.
