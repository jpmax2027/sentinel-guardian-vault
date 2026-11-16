#!/usr/bin/env python3
"""
Assembles the Sentinel demo video (< 3 min) from evidence slides.

The live-loop frames present the FORK REHEARSAL results (real system-contract
and callback-proxy code on local forks of Base Sepolia + Lasna) and say so on
screen. After the live testnet run, regenerate with the real evidence.

Output: demo-video.mp4 (1280x720, H.264, silent).
"""
import os
import subprocess
import textwrap

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRAMES = os.path.join(ROOT, "demo-evidence", "frames")
os.makedirs(FRAMES, exist_ok=True)

W, H = 1280, 720
BG = (13, 17, 23)
FG = (230, 237, 243)
ACCENT = (88, 196, 255)
GREEN = (63, 185, 80)
RED = (248, 81, 73)
GREY = (139, 148, 158)
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
SANS = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
SANSB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def F(path, size):
    return ImageFont.truetype(path, size)


def slide(title, lines, accent=ACCENT, title_size=44, body_size=25, mono_from=None):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 0, W, 8], fill=accent)
    d.text((60, 46), title, font=F(SANSB, title_size), fill=FG)
    y = 140
    for i, (text, color, size, font_path) in enumerate(lines):
        font = F(font_path or SANS, size or body_size)
        for chunk in textwrap.wrap(text, width=64 if font_path != MONO else 78) or [""]:
            d.text((60, y), chunk, font=font, fill=color)
            y += (size or body_size) + 12
        y += 10
    return img


def L(text, color=FG, size=None, font=None):
    return (text, color, size, font)


slides = []

slides.append((slide("SENTINEL", [
    L("AI-Signal Guardian Vault", ACCENT, 34),
    L(""),
    L("Reactive Omni Buildathon — track: Reactive Meets AI", FG, 28),
    L(""),
    L("An AI risk score, a reactive contract, and a vault that", FG, 26),
    L("moves your money to safety by itself — across two chains,", FG, 26),
    L("with no keeper and no bot server.", FG, 26),
]), 10))

slides.append((slide("The problem", [
    L("Your stablecoins sit in a risky position. The market turns", FG, 26),
    L("at 3 a.m. Your stop-loss is… you, asleep.", FG, 26),
    L(""),
    L("Today's fixes are bad:", FG, 26),
    L("• a centralised bot with a hot wallet key, or", FG, 25),
    L("• a cron job that polls and hopes, or", FG, 25),
    L("• nothing at all.", FG, 25),
    L(""),
    L("Sentinel replaces the bot with a reactive contract:", GREEN, 26),
    L("the trigger is an on-chain event, the logic is public,", FG, 26),
    L("and the vault only obeys authenticated callbacks.", FG, 26),
]), 18))

slides.append((slide("How it works", [
    L("1.  AI AGENT (Python) scores BTC market risk from live data", ACCENT, 25),
    L("      and posts the score on-chain.", FG, 24),
    L("2.  SIGNAL ORACLE (Base Sepolia) emits SignalPosted.", ACCENT, 25),
    L("3.  SENTIMENT GUARDIAN (Reactive Lasna) is subscribed.", ACCENT, 25),
    L("      score ≤ −30  →  protection ON", FG, 24),
    L("      score ≥ +20  →  protection OFF", FG, 24),
    L("4.  CALLBACK crosses back to Base Sepolia through the", ACCENT, 25),
    L("      Reactive proxy — double-authenticated.", FG, 24),
    L("5.  GUARDIAN VAULT moves 100% of deposits into a segregated", ACCENT, 25),
    L("      SAFE BUCKET contract — and back when it clears.", FG, 24),
]), 20))

slides.append((slide("The AI is in the running system", [
    L("A transparent scoring model — fixed published weights,", FG, 26),
    L("~150 lines of stdlib Python. No signal, no reaction.", FG, 26),
    L(""),
    L("Features (48 hourly BTC/USDT candles):", ACCENT, 25),
    L("  ret24 · EMA trend · RSI(14) · realised volatility", FG, 24, MONO),
    L("score = 1200·ret24 + 1800·mom + 0.7·(rsi−50) − vol_drag", FG, 24, MONO),
    L(""),
    L("Measured runs:", ACCENT, 25),
    L("  live market today:  score −32  (high vol drags it defensive)", FG, 24, MONO),
    L("  crash stress test:  score −100, confidence 100", RED, 24, MONO),
    L("  calm recovery:      score +100, confidence 100", GREEN, 24, MONO),
]), 20))

slides.append((slide("The loop, live — protection", [
    L("Fork rehearsal: real Lasna system contract + real Base", GREY, 22),
    L("Sepolia callback proxy code; network legs via impersonation.", GREY, 22),
    L(""),
    L("User deposits 1,000 mUSD into the GuardianVault", FG, 25),
    L("  risky = 1,000,000,000 · safe = 0", FG, 24, MONO),
    L(""),
    L("AI agent scores the crash scenario and posts on-chain:", FG, 25),
    L("  SignalPosted  score −100 · confidence 100", RED, 24, MONO),
    L(""),
    L("Guardian on Lasna reacts (react()):", FG, 25),
    L("  protectionActive = true · callbacksSent = 1", FG, 24, MONO),
    L("  lastScore = −100", FG, 24, MONO),
]), 20))

slides.append((slide("The loop, live — funds move", [
    L("The callback lands on Base Sepolia:", FG, 26),
    L(""),
    L("  vault.onRiskAlert(guardian, −100)", FG, 25, MONO),
    L("  vault.protectionActive = true", FG, 25, MONO),
    L(""),
    L("  risky = 0", RED, 28, MONO),
    L("  safe  = 1,000,000,000   ← every token in the SafeBucket", GREEN, 28, MONO),
    L(""),
    L("Forged callbacks revert: wrong proxy caller — rejected.", FG, 25),
    L("Right proxy, wrong reactive sender — rejected. (Tests.)", FG, 25),
    L("Users can still withdraw while protected.", FG, 25),
]), 20))

slides.append((slide("The loop, live — recovery", [
    L("The market recovers. The AI posts again:", FG, 26),
    L(""),
    L("  SignalPosted  score +100 · confidence 100", GREEN, 25, MONO),
    L(""),
    L("Guardian clears protection; second callback:", FG, 26),
    L(""),
    L("  vault.onRiskCleared(guardian, +100)", FG, 25, MONO),
    L("  vault.protectionActive = false", FG, 25, MONO),
    L(""),
    L("  risky = 1,000,000,000 · safe = 0   ← funds restored", GREEN, 28, MONO),
]), 18))

slides.append((slide("Proof & status", [
    L("✓  forge test — 5/5, incl. the full protect/release loop", GREEN, 25),
    L("✓  Fork rehearsal — full loop vs real system/proxy code", GREEN, 25),
    L("✓  AI agent — runs against live market data today", GREEN, 25),
    L(""),
    L("One step left: the live testnet run needs the deployer", FG, 25),
    L("funded (Base Sepolia ETH → lREACT exchange). Deploy and", FG, 25),
    L("demo scripts are ready and rehearsed end-to-end.", FG, 25),
    L(""),
    L("Sentinel — set it, and let the chain watch the market.", ACCENT, 27),
]), 18))

total = 0
list_path = os.path.join(FRAMES, "frames.txt")
with open(list_path, "w") as lf:
    for i, (img, dur) in enumerate(slides):
        p = os.path.join(FRAMES, f"frame-{i}.png")
        img.save(p)
        lf.write(f"file '{p}'\nduration {dur}\n")
        total += dur
    lf.write(f"file '{os.path.join(FRAMES, f'frame-{len(slides)-1}.png')}'\n")

out = os.path.join(ROOT, "demo-video.mp4")
cmd = [
    "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", list_path,
    "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", "30",
    "-c:a", "aac", "-shortest", "-t", str(total), out,
]
print(" ".join(cmd))
subprocess.run(cmd, check=True, capture_output=True)
print(f"wrote {out} ({os.path.getsize(out)} bytes, {total}s)")
