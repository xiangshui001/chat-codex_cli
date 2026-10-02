# DSH reference and attribution

Upstream: https://github.com/deepseek-ai/deepseek-harness

Pinned reference: `639ed015397290b3745d163aafe02ffee4aa3f84` (read 2026-10-02).

Copyright (c) 2026 DeepSeek. Upstream uses the MIT License; the complete notice
is retained in [third-party/DEEPSEEK-LICENSE.txt](third-party/DEEPSEEK-LICENSE.txt)
and inside the standalone `index.html` file.

The HTML design preview adapts selected declarations and visual conventions
from `packages/client/ui-primitives/src/Button.module.css`,
`Input.module.css`, and `Pill.module.css`. Class names, token names, spacing
and colors are adjusted for this project. No upstream TypeScript runtime is
included. Dark/light surface conventions and the sidebar/main/detail layout
are studied from `ui-theme`, `ui-layout`, and `ui-sidebar`; their runtime
components are not copied.

The adaptation design identifies Button/Input/Pill as candidates for selective
React reuse in the later implementation. That prospective reuse has not been
performed by this design PR. No FishLogo, BrandWordmark, official brand plugin,
brand font, account assets, Cordis runtime, or Typert gateway is included.

This notice applies to the attributed upstream portions and does not choose a
new license for the rest of `chat-codex_cli`, whose root README currently leaves
that decision unspecified.
