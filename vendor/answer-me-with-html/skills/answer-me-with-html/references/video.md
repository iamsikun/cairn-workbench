# Explicit explainer-video requests

Use only for an explicit video request. The basic output is an HTML player; export a video file when requested and supported.

Save a Markdown draft. Each `##` is a scene; `>` lines are narration beats. Use a focused picture and enough narration to explain it. A bracketed `[name]` in narration focuses the matching diagram node/actor. Preserve names across scenes for continuity; choose scene count from the explanation.

````markdown
---
title: A request and its reply
lang: en
---
## A Exchange
```sequence
Client -> Service: request
Service -> Client: reply
```
> The client sends a request.
> The service sends a reply.
````

```text
node "/path/to/skill/scripts/am.mjs" video "/path/to/video-draft.md" -o "/path/to/video.html" --voice auto --no-open
```

`auto` chooses available local system speech, otherwise captions. A cloud credential alone never selects a cloud provider. `--voice off` always uses captions; `--voice system` requires local speech. `--voice elevenlabs` explicitly selects cloud narration and needs configured provider credentials. `--voice local` explicitly selects the configured OpenAI-compatible endpoint (`AM_TTS_URL`). A saved page cannot grant provider permission. Existing explicit voice settings are respected; inspect them if narration destination matters. Never expose credentials in drafts or logs.

Raw-markup and network-asset flags apply to player resources. Speech-provider requests are separate from browser asset loading and follow the user's provider choice. Final audio is embedded.

`--mp4` needs Chromium, Node.js 22+, and ffmpeg. `--webm` needs Chromium and Node.js 22+. Do not install them automatically. Export can be slow; retain the verified player if export fails and report the missing output. Validate timing, captions, controls, reduced motion, and audio when tooling permits. A synthetic provider test validates plumbing, not voice quality.
