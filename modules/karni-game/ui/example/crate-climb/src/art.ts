/**
 * Crate Climb's art, painted in code on small canvases at boot: the example
 * ships no image files, and the sprites are cut from these sheets the same
 * way they would be from a loaded image.
 */
import { createSprite, defineClips, sheetFrames } from "@karni/game/draw";

function sheet(width: number, height: number, paint: (g: CanvasRenderingContext2D) => void) {
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const g = canvas.getContext("2d");
  if (g) paint(g);
  return canvas;
}

/** The climber: two idle frames, four running, one jumping, 16 by 24 each. */
function hero(g: CanvasRenderingContext2D): void {
  const legs: readonly (readonly [number, number])[] = [
    [0, 0],
    [0, 0],
    [-2, 2],
    [0, 0],
    [2, -2],
    [0, 0],
  ];
  for (let i = 0; i < 7; i += 1) {
    const x = i * 16;
    const bob = i === 1 || i === 3 || i === 5 ? 1 : 0;
    g.fillStyle = "#4cc9f0";
    g.fillRect(x + 3, 5 + bob, 10, 13);
    g.fillStyle = "#f72585";
    g.fillRect(x + 3, 5 + bob, 10, 3);
    g.fillStyle = "#ffffff";
    g.fillRect(x + 8, 10 + bob, 4, 4);
    g.fillStyle = "#0d1b2a";
    g.fillRect(x + 10, 11 + bob, 2, 2);
    g.fillStyle = "#1b263b";
    if (i === 6) {
      g.fillRect(x + 4, 18, 3, 3);
      g.fillRect(x + 9, 17, 3, 3);
    } else {
      const [a, b] = legs[i] ?? [0, 0];
      g.fillRect(x + 4 + a, 18, 3, 6);
      g.fillRect(x + 9 + b, 18, 3, 6);
    }
  }
}

/** A gem turning: four frames, 16 by 16. */
function gems(g: CanvasRenderingContext2D): void {
  const widths = [12, 8, 3, 8];
  widths.forEach((w, i) => {
    const cx = i * 16 + 8;
    g.fillStyle = "#ffd166";
    g.beginPath();
    g.moveTo(cx, 2);
    g.lineTo(cx + w / 2, 8);
    g.lineTo(cx, 14);
    g.lineTo(cx - w / 2, 8);
    g.closePath();
    g.fill();
    g.fillStyle = "#fff3c4";
    g.fillRect(cx - 1, 4, 2, 3);
  });
}

function crate(g: CanvasRenderingContext2D): void {
  g.fillStyle = "#bc6c25";
  g.fillRect(0, 0, 32, 32);
  g.strokeStyle = "#7f4f24";
  g.lineWidth = 3;
  g.strokeRect(1.5, 1.5, 29, 29);
  g.beginPath();
  g.moveTo(3, 3);
  g.lineTo(29, 29);
  g.moveTo(29, 3);
  g.lineTo(3, 29);
  g.stroke();
}

function flag(g: CanvasRenderingContext2D): void {
  g.fillStyle = "#e0e1dd";
  g.fillRect(2, 0, 2, 50);
  g.fillStyle = "#ef476f";
  g.beginPath();
  g.moveTo(4, 2);
  g.lineTo(16, 8);
  g.lineTo(4, 14);
  g.closePath();
  g.fill();
}

export function paintArt() {
  const heroFrames = sheetFrames(sheet(16 * 7, 24, hero), 16, 24, { anchor: [0.5, 1] });
  const gemFrames = sheetFrames(sheet(64, 16, gems), 16, 16, { anchor: [0.5, 0.5] });
  return {
    hero: defineClips(heroFrames, {
      idle: { frames: [0, 1], fps: 2 },
      run: { frames: { from: 2, to: 5 }, fps: 12 },
      jump: { frames: [6] },
    }),
    gem: defineClips(gemFrames, { spin: { frames: { from: 0, to: 3 }, fps: 8 } }),
    crate: createSprite(sheet(32, 32, crate)),
    flag: createSprite(sheet(16, 50, flag), { anchor: [0, 1] }),
  };
}
