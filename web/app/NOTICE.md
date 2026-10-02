# DSH reuse and attribution

Upstream: https://github.com/deepseek-ai/deepseek-harness

Reference commit: `639ed015397290b3745d163aafe02ffee4aa3f84`.
Copyright (c) 2026 DeepSeek. The complete MIT license is retained in
[third-party/DEEPSEEK-LICENSE.txt](third-party/DEEPSEEK-LICENSE.txt).

| Upstream source at the reference commit                                | Use in this app                                                                                                                        |
| ---------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------- |
| `packages/client/ui-primitives/src/Button.tsx` and `Button.module.css` | Selected forwardRef/native-prop implementation in `primitives/Atoms.tsx`; adapted sizes, variants and CSS tokens in `Atoms.module.css` |
| `packages/client/ui-primitives/src/Input.tsx` and `Input.module.css`   | Selected input implementation, optional leading icon and wrapper focus styles; project tokens and native validation retained           |
| `packages/client/ui-primitives/src/Pill.tsx` and `Pill.module.css`     | Selected button/static-span implementation; project state tones and accessibility attributes added                                     |
| `packages/client/ui-theme/src/styles/design-platform.css`              | Neutral light/dark surface and control conventions; only the needed semantic token roles are retained in `client/styles.css`           |
| `ui-layout`, `ui-sidebar`, `ui-model-selection`                        | Studied as visual/interaction references; implementations are rewritten with plain React props and this project's client               |

Unlike the HTML design reference, this app includes selected upstream React
primitive code. Attribution is also present at the top of each adapted source
file. No DSH runtime, Cordis, Typert gateway, Slots/store/plugin framework,
FishLogo, BrandWordmark, official account UI or brand font is included.

All navigation, task/evidence projections and control forms belong to the
chat-codex front end. React, clsx and lucide-react are package dependencies,
with their own licenses distributed by npm. This notice covers the attributed
DSH portions; it does not choose a new license for the rest of this repository.

# TISU model reuse

Upstream: https://github.com/xiangshui001/tisu

Reference commit: `7297fcbcc7663f4b51bd41b19ef43e63e1b8aea8`.
The complete `components/astral-library/` directory from that commit is copied
byte for byte to `public/tisu/astral-library/`, following upstream's directory
layout requirement. File hashes are recorded in
[screenshots/login-verification.json](screenshots/login-verification.json).

The React wrapper imports only `library.js` and uses `mountLibrary`, `pause`,
`resume`, and `dispose`. The scene remains in its default outside view.
`element.js` and `index.js` are retained for source completeness but are never
executed; no custom element, full-page example, toolbar, tour, reading/gallery
path or TISU demo branding UI is mounted. No architecture or vendor code is
rewritten. The wrapper disables pointer/focus interaction with the canvas.

Upstream vendors Three.js r186. Both ES modules and the complete MIT license
are retained in
[public/tisu/astral-library/vendor/THREE-LICENSE.txt](public/tisu/astral-library/vendor/THREE-LICENSE.txt).
There are no CDN, external texture, external model or runtime API requests for
the display. The upstream repository does not declare a separate project
license; this records reuse for the owner's requested integration without
adding a license for that code or the rest of this repository.
