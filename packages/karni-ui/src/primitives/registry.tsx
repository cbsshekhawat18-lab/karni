/**
 * The primitive registry: a project renders Karni's components with its own
 * design system's primitives.
 *
 *   <KarniProvider client={client} primitives={{ button: Button, input: Input }}>
 *
 * Every Karni primitive (Button, Input, Select's parts, ...) looks itself up
 * here before rendering, so ResourceTable, ResourceForm and the rest render
 * the project's button and inputs while keeping their schema-driven
 * behaviour. A role that is not registered renders Karni's own.
 *
 * Contracts: a registered component receives exactly the props Karni's
 * primitive takes (ButtonProps, InputProps, ...) and the ref. shadcn/ui's
 * components match them as they are. Any other design system registers a
 * small adapter. `select` is a family: Radix parts share a context, so its
 * parts are replaced together or not at all.
 *
 * A registered component may wrap Karni's own (`(props) => <Button
 * className="..." {...props} />`): inside it, that role resolves to Karni's
 * primitive again, so the wrapper does not call itself.
 */
import type * as SelectPrimitive from "@radix-ui/react-select";
import * as React from "react";
import type { ButtonProps } from "../components/primitives/button";
import type { CheckboxProps } from "../components/primitives/checkbox";
import type { InputProps } from "../components/primitives/input";
import type { LabelProps } from "../components/primitives/label";
import type { SkeletonProps } from "../components/primitives/skeleton";
import type { SwitchProps } from "../components/primitives/switch";
import type { TextareaProps } from "../components/primitives/textarea";

type WithRef<P, T> = React.ComponentType<P & React.RefAttributes<T>>;

/** The parts of a Radix-compatible select (what shadcn/ui's select.tsx exports). */
export interface KarniSelectParts {
  Root: React.ComponentType<SelectPrimitive.SelectProps>;
  Trigger: WithRef<SelectPrimitive.SelectTriggerProps, HTMLButtonElement>;
  Value: WithRef<SelectPrimitive.SelectValueProps, HTMLSpanElement>;
  Content: WithRef<SelectPrimitive.SelectContentProps, HTMLDivElement>;
  Item: WithRef<SelectPrimitive.SelectItemProps, HTMLDivElement>;
  Group: WithRef<SelectPrimitive.SelectGroupProps, HTMLDivElement>;
  Label: WithRef<SelectPrimitive.SelectLabelProps, HTMLDivElement>;
  Separator: WithRef<SelectPrimitive.SelectSeparatorProps, HTMLDivElement>;
}

/** Every role a project can fill with its own component. */
export interface KarniPrimitives {
  button: WithRef<ButtonProps, HTMLButtonElement>;
  input: WithRef<InputProps, HTMLInputElement>;
  textarea: WithRef<TextareaProps, HTMLTextAreaElement>;
  checkbox: WithRef<CheckboxProps, HTMLButtonElement>;
  switch: WithRef<SwitchProps, HTMLButtonElement>;
  label: WithRef<LabelProps, HTMLLabelElement>;
  skeleton: WithRef<SkeletonProps, HTMLDivElement>;
  select: KarniSelectParts;
}

/** A role that is one component (not a family of parts). */
export type KarniPrimitiveRole = Exclude<keyof KarniPrimitives, "select">;

/** The project's replacements: any subset of the roles. */
export type KarniPrimitiveOverrides = Partial<KarniPrimitives>;

const PrimitivesContext = React.createContext<KarniPrimitiveOverrides>({});

export interface KarniPrimitivesProviderProps {
  /** Role -> the project's component. Merged over any registry above it. */
  value: KarniPrimitiveOverrides;
  children?: React.ReactNode;
}

/**
 * Registers the project's primitives for everything inside it. KarniProvider
 * renders one from its `primitives` prop, and you can nest another to change
 * a subtree.
 */
export function KarniPrimitivesProvider({
  value,
  children,
}: KarniPrimitivesProviderProps): React.ReactElement {
  const parent = React.useContext(PrimitivesContext);
  const merged = React.useMemo(() => ({ ...parent, ...value }), [parent, value]);
  return <PrimitivesContext.Provider value={merged}>{children}</PrimitivesContext.Provider>;
}

/** The registered primitives in scope (the roles the project replaced). */
export function useKarniPrimitives(): KarniPrimitiveOverrides {
  return React.useContext(PrimitivesContext);
}

/**
 * Makes a Karni primitive defer to the registry.
 * @internal
 */
export function overridable<P extends object, T>(
  role: KarniPrimitiveRole,
  Default: React.ForwardRefExoticComponent<React.PropsWithoutRef<P> & React.RefAttributes<T>>,
): React.ForwardRefExoticComponent<React.PropsWithoutRef<P> & React.RefAttributes<T>> {
  const Component = React.forwardRef<T, P>((props, ref) => {
    const overrides = React.useContext(PrimitivesContext);
    // Inside the project's component this role is Karni's again (no recursion).
    const inner = React.useMemo(() => ({ ...overrides, [role]: undefined }), [overrides]);
    const Override = overrides[role] as React.ComponentType<P & React.RefAttributes<T>> | undefined;
    if (Override === undefined) return React.createElement(Default, { ...props, ref });
    return (
      <PrimitivesContext.Provider value={inner}>
        {React.createElement(Override, { ...(props as P), ref })}
      </PrimitivesContext.Provider>
    );
  });
  Component.displayName = Default.displayName;
  return Component;
}

/**
 * Makes one part of Karni's select defer to a registered `select` family.
 * @internal
 */
export function overridableSelectPart<
  K extends keyof KarniSelectParts,
  C extends KarniSelectParts[K],
>(part: K, Default: C): C {
  const Component = React.forwardRef<unknown, Record<string, unknown>>((props, ref) => {
    const family = React.useContext(PrimitivesContext).select;
    const Part = (family ? family[part] : Default) as React.ComponentType<Record<string, unknown>>;
    return React.createElement(Part, part === "Root" ? props : { ...props, ref });
  });
  Component.displayName = `Select${part === "Root" ? "Root" : part}`;
  // Same public type as Karni's own part, so `React.ElementRef<typeof SelectTrigger>` keeps working.
  return Component as unknown as C;
}
