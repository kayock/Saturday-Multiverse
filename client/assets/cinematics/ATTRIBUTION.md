# Cinematic assets — attribution

Pack: **Saturday Multiverse Cinematic Asset Pack v1**  
Integrated into the game under `client/assets/cinematics/`.

| Media | Origin |
|---|---|
| Photoreal tavern / shore / portal / campfire / Salt-Grave stills | Juggernaut XL v9 (RunDiffusion Photo) via Kayock Image Hub / SwarmUI; prompts & seeds in upstream pack `generation-params.json` |
| Animated MP4s | OpenFilm 0.4.1 Ken Burns + canvas overlays; h264_nvenc 1080p30 |
| Audio inside MP4s | Locally synthesized beds (ffmpeg); see `meta/AUDIO_LICENSING.md` |

Runtime gameplay does not invoke OpenFilm, Juggernaut, or any image/video model.
