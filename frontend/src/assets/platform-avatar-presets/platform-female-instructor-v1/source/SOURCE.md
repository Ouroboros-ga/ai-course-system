# platform-female-instructor-v1 source frames

- Character: `platform-female-instructor-v1`
- Source: user-authorized, wholly fictional images generated in Codex on 2026-08-10.
- Real-person reference: none. The prompts explicitly prohibited real-person and celebrity likenesses.
- Source assets: no third-party image, logo, trademark, or teacher portrait was supplied to the generator.
- Implemented processing (2026-08-10): `01-mouth-sil.png` was resized to the immutable 960px `body.png`; each mouth frame was reduced to a feathered local mouth patch; an additional internal closed-eye processing frame was cropped to `eyes-closed.png`. The resulting 11 runtime PNGs live in `backend/app/assets/platform_avatar_presets/platform-female-instructor-v1/1.0.0/` and are seeded into object storage under content-addressed keys by `platform_media_preset_service.py`. They are browser playback assets only through a course/release/preset-scoped signed URL.
- Generated dimensions: `1254 × 1254` PNG for every frame. The built-in generator did not return the requested 2048-pixel output; do not describe these files as 2K originals. This resolution remains sufficient for the current 480p PixiJS target, but a higher-resolution source should be commissioned if a larger display target is added.
- Commercial use, modification, and redistribution: confirm the applicable image-generation service terms and project legal policy before external distribution. This record is provenance evidence, not a legal opinion or a substitute for a public-release license review.

## Frames

| File | Viseme / role | SHA-256 |
|---|---|---|
| `00-master-reference.png` | fixed identity and composition reference | `f1f62ff8d1e2f47123de94114ba832825239f7abbd6274189a530087bcaa919a` |
| `01-mouth-sil.png` | relaxed closed mouth | `0bd30d4c0418560db22149c896d7a7f4f6cdc3603ef624076205e8f33774a131` |
| `02-mouth-mbp.png` | m / b / p lip closure | `7f231d9a7d59c381c55e975a71bca8cab6b7b9f853c2fa0adb3a21e18c46af93` |
| `03-mouth-a.png` | a | `b1bacf50112e9364a60e7b14d436a06c43988c393063f060be6091b9934b46ce` |
| `04-mouth-e.png` | e | `ea95e1e873e2cab9d1a891489670a18e2e7f2114461ab385cbfe0832a39b7469` |
| `05-mouth-i.png` | i | `45853b3e839bf2e2971394e6f6963db88c333769afac8a234803d271f6dbc2e1` |
| `06-mouth-o.png` | o | `870fbfb6c4676f9b7e48821fa5336d147e599d9adce654d52cca6b418af7ea96` |
| `07-mouth-u.png` | u | `0eeb549556860e83ed399910e2c10817cb8c0d4bfaf83da7c0e7cdf92f4d08c9` |
| `08-mouth-fv.png` | f / v | `1818d10c28923e72e5fde364ec3e9ea880dc89c73c2f849c8eaf03da0bfc46f1` |
