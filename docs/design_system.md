# Spectra Design System (2025)

## Core Philosophy

**"Cinematic Data Density"**
The UI should feel like a high-end HUD from a sci-fi film, but grounded in usability. It avoids the generic "Bootstrap/Material" look by using custom textures, specific lighting effects, and a strict grid system.

## 1. Visual Foundation

### Color Palette (Tailwind Extended)

* **Backgrounds:**
  * `bg-slate-950` (#020617) - Main canvas.
  * `bg-slate-900` (#0f172a) - Card backgrounds.
* **Accents (Functional Glows):**
  * **Safe/Idle:** `text-emerald-400` (with `shadow-emerald-500/20`).
  * **Warning/Scanning:** `text-amber-400` (with `shadow-amber-500/20`).
  * **Danger/Exploit:** `text-rose-500` (with `shadow-rose-500/20`).
  * **System/AI:** `text-violet-400` (with `shadow-violet-500/20`).

### Texture & Depth

* **Noise Overlay:** A subtle CSS noise pattern overlaying the entire screen (opacity 3%) to kill the "flat digital" look and add filmic grain.
* **Glassmorphism:** Used *sparingly* for floating elements (modals, sticky headers).
  * `backdrop-blur-md bg-slate-900/70 border border-white/10`
* **Borders:** 1px borders are too simple. Use **Gradient Borders** or **Inner Glows** to define edges.

## 2. Layout: The Bento Grid

The dashboard is strictly organized into a **Bento Grid** (CSS Grid).

* **Concept:** Everything is a "Tile". Tiles can span 1x1, 2x1, 2x2, etc.
* **Gaps:** Tight gaps (`gap-4`) to maximize screen real estate.
* **Rounded Corners:** `rounded-xl` or `rounded-2xl` for a modern feel, contrasting with the sharp data inside.

## 3. Typography

* **UI Font:** `Inter` or system sans-serif (Clean, legible).
* **Data/Terminal:** `JetBrains Mono` or `Fira Code` (Nerd Fonts compatible).
* **Hierarchy:** Uppercase, tracking-wide labels for headers (e.g., `TRACKING-WIDEST TEXT-XS TEXT-SLATE-500`).

## 4. Micro-Interactions & "Spice"

* **Live Indicators:** Pulsing CSS dots (`animate-ping`) for active scans.
* **Scanlines:** A very subtle CRT scanline effect on the Terminal window only.
* **Hover States:** Cards shouldn't just change color; they should slightly lift or glow (`hover:shadow-lg hover:shadow-violet-500/10 transition-all duration-300`).
* **Skeleton Loading:** Shimmering skeletons for data that is loading, never empty white boxes.

## 5. Implementation Strategy (No Build Step)

* **Tailwind CDN:** Use the script tag with custom config in the HTML head.

    ```html
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
      tailwind.config = {
        theme: {
          extend: {
            colors: { ... },
            animation: {
              'pulse-slow': 'pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite',
            }
          }
        }
      }
    </script>
    ```

* **Icons:** Phosphor Icons or Heroicons (via CDN).
* **Components:** Pure HTML/JS templates. No React components.

## 6. Toolbox & Plugin UI

* **Drag & Drop Zone:**
  * **Idle:** Dashed border `border-dashed border-slate-700` with `text-slate-500`.
  * **Hover:** Glow effect `border-violet-500 shadow-[0_0_15px_rgba(139,92,246,0.3)]` with `text-violet-400`.
  * **Animation:** "Holographic" scan effect when a file is dragged over.
* **Installation Progress:**
  * **Style:** "Terminal-style" progress bar (e.g., `[#####.....]`) or a "Loading Hex" animation.
  * **Feedback:** Real-time log stream in a mini-terminal window (`font-mono text-xs text-emerald-400`).
* **Tool Cards:**
  * Display tool icon, name, and status (Installed/Installing/Failed).
  * Use "Badge" indicators for categories (e.g., `bg-rose-500/10 text-rose-400` for Exploitation).
