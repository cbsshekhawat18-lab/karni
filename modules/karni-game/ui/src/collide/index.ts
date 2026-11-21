/**
 * @karni/game/collide: kinematic collision for 2D games. Axis-aligned boxes
 * and circles, overlap and contact tests, segment and sweep tests, a ray
 * cast, a box mover that slides against solid boxes with one-way ledges, and
 * trigger zones. No rigid-body physics: a game that needs stacking, joints or
 * rotation uses a physics library inside the loop's fixed step. The tests
 * and the mover make no garbage and read no clock or random source, so a
 * game's pure rules can use them.
 */
export { createMove, moveBox } from "./mover";
export type { Move, MoveOptions, Solid, SolidQuery, Solids } from "./mover";
export {
  boxCircleOverlap,
  boxContact,
  boxesOverlap,
  circleBoxContact,
  circleContact,
  circlesOverlap,
  createContact,
  pointInBox,
  pointInCircle,
} from "./shapes";
export type { Box, Circle, Contact } from "./shapes";
export { castRay, createHit, segmentBox, segmentCircle, sweepBox, sweepCircle } from "./sweep";
export type { Hit } from "./sweep";
export { createTriggers } from "./triggers";
export type { TriggerHandlers, Triggers } from "./triggers";
