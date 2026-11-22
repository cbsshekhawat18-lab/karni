/**
 * @karni/game/draw: a light 2D layer on Canvas 2D. Layers drawn in order, a
 * camera, shapes, text, sprites and frame animation, tweens and easing,
 * pooled particles and a pool for anything else. No WebGL, no scene graph
 * and no entity system: a game that outgrows Canvas 2D moves to an engine
 * adapter. Every export is tree-shaken and nothing here has a dependency.
 */
export { createCamera } from "./camera";
export type { Area, Camera, CameraOptions, FollowTarget } from "./camera";
export {
  damp,
  inBack,
  inCubic,
  inExpo,
  inOutCubic,
  inOutQuad,
  inOutSine,
  inQuad,
  inSine,
  lerp,
  linear,
  outBack,
  outBounce,
  outCubic,
  outElastic,
  outExpo,
  outQuad,
  outSine,
} from "./ease";
export type { Ease } from "./ease";
export { REDUCED_MOTION, motionScale, prefersReducedMotion } from "./motion";
export { createPainter } from "./painter";
export type { Painter } from "./painter";
export { createParticles } from "./particles";
export type { Emitter, ParticleStyle, Particles, ParticlesOptions, Range } from "./particles";
export { createPool } from "./pool";
export type { Pool, PoolOptions } from "./pool";
export { createRenderer } from "./renderer";
export type {
  DrawFn,
  Layer,
  LayerOptions,
  RenderStats,
  Renderer,
  RendererOptions,
} from "./renderer";
export { createAnimator, createSprite, defineClips, sheetFrames } from "./sprite";
export type {
  Animator,
  Clip,
  ClipOptions,
  SheetOptions,
  LoadedImage,
  Sprite,
  SpriteImage,
  SpriteOptions,
  SpriteSource,
} from "./sprite";
export { textStyle } from "./text";
export type { TextLayout, TextStyle, TextStyleOptions } from "./text";
export { createTweens } from "./tween";
export type { NumberKeys, Tween, TweenOptions, Tweens } from "./tween";
export type { DrawView, Paint, Point } from "./types";
