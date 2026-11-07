/** @karni/ai-ui public barrel: explicit exports only. Experimental. */
import { registerAiRoles } from "./roles";

export { ExtractButton } from "./ExtractButton";
export type { ExtractButtonProps, ExtractButtonSlots, ExtractErrorProps } from "./ExtractButton";

export { ExtractPreview, defaultExtractPreviewSlots, rowFields } from "./ExtractPreview";
export type {
  ExtractPreviewProps,
  ExtractPreviewSlots,
  ExtractProblemsProps,
  ExtractRowsProps,
} from "./ExtractPreview";

export { EXTRACT_PATH, extractRefusal, useExtract } from "./hooks";

export type {
  ExtractInput,
  ExtractProblem,
  ExtractRefusal,
  ExtractResult,
  ExtractSourceKind,
  ExtractUsage,
} from "./types";

export { AI_COMPONENT_ROLES, registerAiRoles } from "./roles";
export type { ComponentRoleDefinition } from "./roles";

registerAiRoles();
