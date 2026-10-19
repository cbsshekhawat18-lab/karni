# Karni brand assets

The Karni mark is a hand-drawn crown — three orange rings over interlocking
white strokes — on a black, slightly irregular ground. The strokes are
deliberately not geometric; every file here is traced from the original
drawing, not redrawn.

## Files

| File | Use |
|---|---|
| `karni-mark.svg` | The mark. Square canvas, transparent outside the black ground. Use at 48px and above. |
| `karni-mark-simple.svg` | The small-size variant: solid dots, heavier strokes, two crossings. Use at 32px and below (favicons, tab bars, avatars). |
| `karni-mark-mono.svg` | One colour (`currentColor`), rings and strokes knocked out of the ground. One-colour print, stamps, anywhere the orange cannot be used. |
| `karni-mark-light.svg` | The light-ground inversion (white ground, black strokes, orange rings). Only for surfaces so dark that the black ground would vanish. |
| `karni-horizontal.svg` | Mark plus the `karni` wordmark, for light surfaces. README and docs header. |
| `karni-horizontal-dark.svg` | The same lockup for dark surfaces. |
| `favicon.svg`, `favicon-16.png`, `favicon-32.png`, `favicon-48.png`, `apple-touch-icon-180.png` | The icon set; `favicon.svg` is the simple variant. |
| `avatar-400.png`, `avatar-460.png`, `avatar-512.png`, `avatar-1024.png` | Profile avatars: the mark at 86% on a solid black square, so a circular crop (GitHub, npm, X) is a black disc and a rounded-square crop (Docker Hub, Gravatar) keeps its corners. 400 for Gravatar and social accounts, 460 for the npm org, 512 for GitHub and Docker Hub, 1024 for anything that asks for more. |
| `avatar-400-transparent.png` … `avatar-1024-transparent.png` | The same sizes with the mark's own ground on a transparent canvas, for surfaces that show the avatar uncropped on their own background. |
| `social-1280x640.png` | 1280×640 social preview (GitHub repository, Open Graph and Twitter cards on the docs site). |

The SVGs are generated — see [`scripts/brand/`](../../scripts/brand/) —
from the source drawing; edit the drawing or the scripts, not the SVGs.
The PNGs are rendered from the SVGs by `scripts/brand/render.mjs`, which
also writes two contact sheets to `scripts/brand/out/`: `contact-sheet.png`
(every variant at 16–512px on white, black and grey) and
`avatar-contact-sheet.png` (`avatar-400.png` square and circle-cropped at
40, 80, 200 and 400px on white, GitHub dark `#0d1117` and GitHub light
`#f6f8fa`). The avatars are rendered from the full mark: on that sheet the
three rings are still visible at 40px as thin hollow dots, so the small-size
variant was not needed; its 40px rendering sits beside the full mark on the
sheet's last row (`avatar-400-simple-candidate.png`) and `AVATAR_SOURCE` in
the script switches the whole set to it if a platform's smallest size proves
too small.

## Colours

| | Hex | Use |
|---|---|---|
| Ground | `#000000` | the mark's ground, dark surfaces |
| Accent | `#FB5D08` | the three rings — and nothing else in the mark |
| Line | `#FFFFFF` | the strokes, the wordmark on dark surfaces |

The wordmark is set in [Jost](https://github.com/google/fonts/tree/main/ofl/jost)
(SIL Open Font License) at weight 600, converted to outlines; no font is
needed to display it. For text next to the mark, any geometric sans works
(Jost, Outfit, Poppins) — never a serif or a script face.

## Rules

- **Clear space:** keep at least 10% of the mark's width clear on every
  side. The square SVG canvas already includes that space: butt the canvas
  against other elements, never the artwork.
- **Minimum size:** `karni-mark.svg` at 48px; below that use
  `karni-mark-simple.svg`, which stays legible at 16px. The wordmark reads
  down to 80px wide.
- **Which file:** on white and light surfaces, `karni-mark.svg`; on near-black
  surfaces, either the standard mark (the ground merges with the surface
  and the strokes carry it) or `karni-mark-light.svg`; in a single ink,
  `karni-mark-mono.svg`.
- **Do not** recolour (the orange is the only accent; the strokes are
  white), rotate, stretch or skew, add shadows, gradients, outlines or
  glows, put the mark inside another shape, crop the ground, or set the
  wordmark in another face or weight.
