---
name: noto-emoji
description: Fetch and embed Google Noto Color Emoji animated GIFs from the official CDN. Use when user wants animated emojis, Noto emojis, lottie emojis, or replacing static emoji with animated ones in web pages or React/Docusaurus sites.
---

# Noto Animated Emoji

## CDN URL pattern

```
https://fonts.gstatic.com/s/e/notoemoji/latest/<codepoint>/512.gif
```

Where `<codepoint>` is the lowercase hex Unicode codepoint (without `U+`). For example:
- 🐟 `U+1F41F` → `https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.gif`
- 🍺 `U+1F37A` → `https://fonts.gstatic.com/s/e/notoemoji/latest/1f37a/512.gif`

**Multi-codepoint emojis** use underscore separators (rare for most emojis):
- 👨‍💻 (man technologist) → codepoints are `1f468_200d_1f4bb` but most emojis are single-codepoint

**Available sizes**: `128`, `256`, `512`

**Fallback**: Use static WebP for browsers that don't support GIF: same URL with `.webp` instead of `.gif`.

## Using the script

```bash
# Get the GIF URL for a single emoji
node ~/.pi/agent/skills/james/noto-emoji/scripts/emoji-url.mjs "🐟"
# → https://fonts.gstatic.com/s/e/notoemoji/latest/1f41f/512.gif

# Get URLs for multiple emojis as JSON
node ~/.pi/agent/skills/james/noto-emoji/scripts/emoji-url.mjs "🐟" "🧰" "📦"
# → {"🐟":"https://...1f41f/512.gif","🧰":"https://...1f9f0/512.gif","📦":"https://...1f4e6/512.gif"}
```

## Using in Docusaurus/React

Import the `AnimatedEmoji` component:

```tsx
import AnimatedEmoji from '@site/src/components/AnimatedEmoji';

<AnimatedEmoji emoji="🐟" size={64} />
```

The component resolves the animated GIF URL at build time. Install it via:

```bash
cp ~/.pi/agent/skills/james/noto-emoji/components/AnimatedEmoji.tsx \
  src/components/AnimatedEmoji/index.tsx
cp ~/.pi/agent/skills/james/noto-emoji/components/AnimatedEmoji.module.css \
  src/components/AnimatedEmoji/styles.module.css
```

## Common tunaOS emoji mappings

| Emoji | Name | Codepoint | CDN URL |
|-------|------|-----------|---------|
| 🐟 | fish | 1f41f | `/1f41f/512.gif` |
| 🐠 | tropical-fish | 1f420 | `/1f420/512.gif` |
| 🍣 | sushi | 1f363 | `/1f363/512.gif` |
| 🎣 | fishing-pole | 1f3a3 | `/1f3a3/512.gif` |
| 🧰 | toolbox | 1f9f0 | `/1f9f0/512.gif` |
| 📦 | package | 1f4e6 | `/1f4e6/512.gif` |
| 💻 | laptop | 1f4bb | `/1f4bb/512.gif` |
| 🟠 | orange-circle | 1f7e0 | `/1f7e0/512.gif` |
| 🏔 | mountain-snow | 1f3d4 | `/1f3d4/512.gif` |
| 💪 | flexed-biceps | 1f4aa | `/1f4aa/512.gif` |
| 🔧 | wrench | 1f527 | `/1f527/512.gif` |
| 🍺 | beer-mug | 1f37a | `/1f37a/512.gif` |
| ⌨  | keyboard | 2328 | `/2328/512.gif` |
| 🖥 | desktop | 1f5a5 | `/1f5a5/512.gif` |
| 📖 | open-book | 1f4d6 | `/1f4d6/512.gif` |
