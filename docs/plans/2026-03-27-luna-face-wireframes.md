# Luna Face System — Wireframes & State Reference

**Date**: 2026-03-27
**Scope**: ASCII renderer, SVG renderer, all states, all moods, all sizes

---

## Design Direction

Luna is NOT a character illustration. Luna is a **presence signal**.

Compare:
- ChatGPT generated: anime girl with detailed hair, eyes, expression (wrong)
- Luna actual: abstract face primitive with half-moon eyes (right)

Think of Luna's face like a traffic light, not a portrait. It communicates **state**, not **personality through visual detail**. The personality comes from her words, not her appearance.

---

## 1. The Identity Primitive: Half-Moon Eyes

The only non-negotiable visual element. Everything else is flexible.

```
    ◜   ◝          Two upward-facing crescents
```

These must work at:
- 8px (favicon)
- 16px (status badge)
- 24px (sidebar icon)
- 48px (chat avatar)
- 128px (presence card)
- 2 lines of text (ASCII terminal)
- 4x4 LED matrix (necklace)

---

## 2. ASCII Face — All Presence States

### IDLE (default, at rest)
```
  ╭─────────╮
  │  ◜   ◝  │
  │    ·    │
  │  ╶───╴  │
  ╰─────────╯
```
Calm resting face. Slight dot nose. Neutral mouth line.

### LISTENING (user is typing or speaking)
```
  ╭─────────╮
  │  ◜   ◝  │
  │   ···   │
  │  ╶───╴  │
  ╰─────────╯
```
Same eyes, ellipsis indicates active attention. "I'm here, go on."

### THINKING (processing, waiting for CLI)
```
  ╭─────────╮
  │  ◜   ◝  │
  │  ·····  │
  │  ╭───╮  │
  ╰─────────╯
```
Extended dots = working. Rounded mouth = concentrating. The dots can animate left→right in terminal.

### RESPONDING (delivering answer)
```
  ╭─────────╮
  │  ◜   ◝  │
  │    ·    │
  │  ╰───╯  │
  ╰─────────╯
```
Open smile. Speaking. Delivering value.

### FOCUSED (deep work, tool execution, code task)
```
  ╭─────────╮
  │  ◜ · ◝  │
  │    ─    │
  │  ╶───╴  │
  ╰─────────╯
```
Dot between eyes = concentration. Straight mouth = determination.

### ALERT (important notification, error, urgent)
```
  ╭─────────╮
  │  ◜ ! ◝  │
  │   ╱╲    │
  │  ╶─╴    │
  ╰─────────╯
```
Exclamation between eyes. Tense mouth. "Pay attention."

### SLEEP (inactive, night mode, no recent activity)
```
  ╭─────────╮
  │  ╶─╴╶─╴ │
  │    ·    │
  │  ─────  │
  ╰─────────╯
```
Closed eyes (horizontal dashes instead of crescents). Flat mouth. Peaceful.

### HANDOFF (transitioning between devices)
```
  ╭─────────╮
  │  ◜ → ◝  │
  │    ·    │
  │  ╶───╴  │
  ╰─────────╯
```
Arrow between eyes = moving. "Coming to you on another device."

### PRIVATE MODE (privacy active, muted)
```
  ╭─────────╮
  │  ◜   ◝  │
  │   [■]   │
  │  ─────  │
  ╰─────────╯
```
Shield/block symbol over nose. Flat sealed mouth. "Not observing."

### ERROR (something went wrong)
```
  ╭─────────╮
  │  ◜ × ◝  │
  │    ·    │
  │  ╶─╴    │
  ╰─────────╯
```
X between eyes. Small tight mouth. "Something broke."

---

## 3. ASCII Face — Mood Modifiers

Mood is secondary to state. It modifies the mouth and subtle details.

### CALM (default mood — applied to any state)
```
  mouth: ╶───╴    (neutral horizontal line)
```

### WARM (friendly, encouraging)
```
  mouth: ╰───╯    (gentle upward curve)
```

### PLAYFUL (humor, light conversation)
```
  mouth: ╰─~─╯    (wavy smile)
```

### SERIOUS (technical, important topic)
```
  mouth: ╶═══╴    (double line = firm)
```

### EMPATHETIC (user is frustrated, sad topic)
```
  mouth: ╰─╮      (slight asymmetric = understanding)
```

### NEUTRAL (no particular mood)
```
  mouth:   ─      (simple dash)
```

---

## 4. Compact ASCII Variants

### Ultra-compact (1 line, for status bars)
```
◜◝        idle
◜◝···     listening
◜◝~       thinking
◜◝)       responding
◜!◝       alert
──         sleep
◜■◝       private
```

### Mini (3 lines, for tight spaces)
```
 ◜   ◝
   ·
 ╶───╴
```

### Micro (2 lines, necklace/wearable)
```
◜ ◝
╶─╴
```

---

## 5. SVG Face Wireframes (described for implementation)

The SVG face uses the same primitives but as vector paths:

### Structure
```
┌─────────────────────┐
│                     │
│   ╭╮           ╭╮  │   ← Eyes: two crescent SVG paths
│                     │
│         ·           │   ← Nose: tiny circle (optional)
│                     │
│      ╶─────╴        │   ← Mouth: SVG path, varies by state
│                     │
│  ○                  │   ← Halo: subtle circle glow (optional)
│                     │
└─────────────────────┘
```

### Eye SVG path (half-moon crescent)
```
Left eye:  M 12,20 A 8,8 0 0,1 12,4   (upper crescent arc)
Right eye: M 36,20 A 8,8 0 0,1 36,4   (upper crescent arc)
```
- Stroke: 2px, current color
- Fill: none (outlined) or subtle gradient for glow states
- Scale proportionally with component size

### Mouth SVG paths by state
```
idle:       M 16,36 L 32,36                    (straight line)
listening:  M 16,36 L 32,36                    (same + pulse opacity)
thinking:   M 16,36 Q 24,36 32,36              (flat, slight tension)
responding: M 16,38 Q 24,32 32,38              (open curve downward = speaking)
warm:       M 16,38 Q 24,34 32,38              (gentle upward curve)
alert:      M 18,36 L 24,34 L 30,36            (angular = tension)
sleep:      M 16,36 L 32,36                    (flat + eyes become horizontal)
error:      M 18,38 Q 24,40 30,38              (slight frown)
```

### Halo (ambient glow ring)
```
Circle: cx=24 cy=24 r=28
Fill: none
Stroke: current color, opacity varies by state:
  idle:       0.08
  listening:  0.18 + pulse animation
  thinking:   0.14 + shimmer animation
  responding: 0.12
  alert:      0.22 + pulse animation
  sleep:      0.04
  private:    0.00
```

---

## 6. Size Reference

### xs (24px) — status badges, inline text
```
┌──┐
│◜◝│   Eyes only. No mouth. Color indicates state.
└──┘
```

### sm (32px) — sidebar icon, navigation
```
┌────┐
│◜  ◝│   Eyes + halo glow. No mouth at this size.
│ ── │
└────┘
```

### md (48px) — chat avatar, message header
```
┌──────┐
│ ◜  ◝ │   Full face. Eyes + nose + mouth.
│   ·  │   State badge below.
│ ╶──╴ │
└──────┘
```

### lg (80px) — presence card, sidebar panel
```
┌──────────┐
│          │   Full face with animation.
│  ◜    ◝  │   Halo ring visible.
│    ·     │   Mood modifier applied.
│  ╶────╴  │   State label below face.
│          │
└──────────┘
 [thinking]
```

### xl (128px) — debug page, full preview, desktop panel
```
┌──────────────┐
│              │
│   ╭╮    ╭╮  │   Detailed crescents.
│              │   Visible nose dot.
│      ·       │   Animated mouth.
│              │   Animated halo.
│   ╶──────╴   │   State + mood + privacy labels.
│              │
└──────────────┘
 thinking · warm · open
 web shell active
```

---

## 7. UI Placement Wireframes

### Sidebar (Layout.js)
```
┌──────────────────┐
│ [◜◝] Luna        │ ← sm avatar + name + state dot
│  · listening      │
├──────────────────┤
│ Dashboard         │
│ Chat              │
│ Agents            │
│ ...               │
└──────────────────┘
```

### Chat Page Header
```
┌─────────────────────────────────────┐
│ Sessions │  [◜◝] Luna · responding  │
│          │  ─────────────────────── │
│ > Phoebe │  User: tell me about...  │
│   Sales  │                          │
│   Code   │  [◜◝ thinking...]        │ ← replaces spinner
│          │                          │
│          │  Luna: Here's what I...  │
└──────────┴──────────────────────────┘
```

### Presence Card (debug page / settings)
```
┌─────────────────────────────┐
│                             │
│        ╭╮      ╭╮          │
│           ·                 │
│        ╶────╴               │
│                             │
│  State: responding          │
│  Mood:  warm                │
│  Privacy: open              │
│  Shell: whatsapp (active)   │
│                             │
│  Connected Shells:          │
│  [*] WhatsApp   [*] Web    │
│  [ ] Desktop    [ ] Mobile  │
│  [ ] Necklace   [ ] Camera  │
└─────────────────────────────┘
```

### WhatsApp (text fallback)
Since WhatsApp can't render custom avatars inline, Luna's state appears as text markers:

```
[Luna · thinking...]
---
Here's what I found about Phoebe:
...
```

Or as WhatsApp status text (via neonize):
```
Luna is listening...
Luna is thinking...
Luna is responding...
```

---

## 8. Animation Spec (CSS keyframes)

### Blink (idle state, every 2.4s)
```
@keyframes luna-blink {
  0%, 90%, 100% { transform: scaleY(1); }
  95%           { transform: scaleY(0.1); }  /* quick close */
}
```

### Pulse (listening state)
```
@keyframes luna-pulse {
  0%, 100% { opacity: 0.18; transform: scale(1); }
  50%      { opacity: 0.30; transform: scale(1.05); }
}
```

### Shimmer (thinking state)
```
@keyframes luna-shimmer {
  0%   { opacity: 0.10; }
  50%  { opacity: 0.20; }
  100% { opacity: 0.10; }
}
```

### Breathe (responding state)
```
@keyframes luna-breathe {
  0%, 100% { transform: scale(1); }
  50%      { transform: scale(1.02); }
}
```

### Alert flash
```
@keyframes luna-alert {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.6; }
}
```

All animations: `ease-in-out`, never `linear`. Premium feel = organic motion.

---

## 9. State × Mood × Privacy Matrix

| State | Eyes | Nose | Mouth (calm) | Mouth (warm) | Halo | Private override |
|-------|------|------|-------------|-------------|------|-----------------|
| idle | ◜ ◝ | · | ╶───╴ | ╰───╯ | 0.08 | [■] over nose |
| listening | ◜ ◝ | ··· | ╶───╴ | ╰───╯ | 0.18 pulse | [■] over nose |
| thinking | ◜ ◝ | ····· | ╭───╮ | ╭───╮ | 0.14 shimmer | [■] over nose |
| responding | ◜ ◝ | · | ╰───╯ | ╰─~─╯ | 0.12 | [■] over nose |
| focused | ◜·◝ | ─ | ╶───╴ | ╶───╴ | 0.16 | [■] over nose |
| alert | ◜!◝ | ╱╲ | ╶─╴ | ╶─╴ | 0.22 pulse | [■] over nose |
| sleep | ╶─╴╶─╴ | · | ───── | ───── | 0.04 | ───── |
| handoff | ◜→◝ | · | ╶───╴ | ╶───╴ | 0.10 | [■] over nose |
| private | ◜ ◝ | [■] | ───── | ───── | 0.00 | always active |
| error | ◜×◝ | · | ╶─╴ | ╶─╴ | 0.08 | [■] over nose |

---

## 10. What This Is NOT

This face system is NOT:
- A character illustration (no hair, no body, no clothing)
- An emoji set (not round yellow faces)
- An anime avatar (no detailed eyes, no expressions beyond state)
- A mascot (no personality through visual detail)
- A chatbot bubble face (no generic smiley)

This face system IS:
- A state indicator with identity
- A presence protocol visualization
- A brandable primitive that works at any resolution
- Hardware-ready (LED matrices, e-ink, OLED)
- Immediately recognizable: "that's Luna" = half-moon eyes
