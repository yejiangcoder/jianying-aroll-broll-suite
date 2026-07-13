# Safety and Privacy

This project is designed as a local-first creator tool.

## Repository Safety Rules

Do not commit:

- private draft files;
- real generated media;
- full production scripts;
- screenshots;
- cover reference images and subject identity assets;
- runtime logs;
- credentials;
- cookies;
- tokens;
- local config files;
- large media files.

The `.gitignore` blocks common runtime and media artifacts by default.

The public `cover-maker` includes only code, tests, and a structural template manifest. Bring your own local subject image and font; generated candidates stay in the caller-selected runtime directory.

## Runtime Safety

Run plan generation before draft writing. Inspect the execution plan if a new editor version or draft structure is being tested.

The draft writer only operates on readable JSON passed to it. When using encoded draft formats, decode and re-encode with a separate local tool and keep that tool outside this repository unless its license allows redistribution.

## Data Handling

The package does not upload files. It reads local inputs and writes local outputs.
