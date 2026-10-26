# Live captures (method B)

Six of the eight feature scenes come straight from Rabik's HTML pages (`npm run capture`, no app needed). Two screens exist only
natively or in another app, so they need you at the Mac. Until they exist, the video skips these scenes and gives their time to the
others (logged in `out/build-log.md`).

| Scene | Why it needs you | Files |
|---|---|---|
| 3 · guide | System Settings, plus Rabik's ring and step cards, are native windows | `assets/screens/raw/guide_before.png`, `guide.png` |
| 4 · dictate | The text field belongs to Mail | `assets/screens/raw/dictate_field.png` |

## Before you start

1. Use a demo account or a clean desktop: no real mail, names or notifications on screen. Turn on Do Not Disturb.
2. Set a plain light wallpaper (System Settings → Wallpaper → a solid light color).
3. Every capture is the same **1152 × 720 point** rectangle, the size of the video's demo desktop. Pick its top-left corner (X, Y)
   so the window you need sits inside it, and use the same corner for both shots of a scene. Run the commands from `video/`.

## 3 · guide: "Where do I turn on Night Shift?"

1. Open System Settings → Displays, sized to fit inside your 1152 × 720 rectangle.
2. Take the "before" shot, with no Rabik overlay (replace X,Y with your corner):

   ```bash
   screencapture -x -R X,Y,1152,720 assets/screens/raw/guide_before.png
   ```

3. Hold ⌃⌥Space, say "Where do I turn on Night Shift?", let go. When the ring sits on the Night Shift button and the step card shows,
   take the second shot within a few seconds:

   ```bash
   screencapture -x -R X,Y,1152,720 assets/screens/raw/guide.png
   ```

## 4 · dictate: "Hold fn to type by voice"

1. Open Mail → New Message (To: and Subject: empty or a demo address), inside the rectangle.
2. Click into the message body, hold fn and say "Sounds good, um, let's meet Thursday at 2." Let go. With Clean up on, the text lands
   as "Sounds good, let's meet Thursday at 2." Once it has landed, take the shot:

   ```bash
   screencapture -x -R X,Y,1152,720 assets/screens/raw/dictate_field.png
   ```

## Then

Tell me the files are there. I'll mark the ring, step cards and text field (`guide.json`, `dictate.json`), run `npm run normalize`,
and the two scenes come back into the cut. Your Mac's 2× captures are 2304 px wide; the video draws the desktop at 2880 px, so these
two screens are upscaled 1.25× (within the 1.5× limit, and logged).
