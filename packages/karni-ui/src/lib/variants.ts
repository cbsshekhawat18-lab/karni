import { cn } from "./cn";

/**
 * Hand-rolled cva-style variant utility (no extra dependency).
 *
 * Every class string appears whole in source (contract D7): a variant map
 * value is a complete Tailwind class list, selected (never concatenated)
 * at call time and merged through cn().
 */

/** A map of variant group name → allowed value → whole Tailwind class string. */
export type VariantShape = Record<string, Record<string, string>>;

/** The props accepted for a given variant shape (each group optional). */
export type VariantSelection<V extends VariantShape> = {
  [K in keyof V]?: Extract<keyof V[K], string> | null;
};

export interface VariantsConfig<V extends VariantShape> {
  /** Classes always applied, before any variant classes. */
  base?: string;
  variants: V;
  defaultVariants?: VariantSelection<V>;
  /** Extra classes applied when every listed variant value is selected. */
  compoundVariants?: ReadonlyArray<VariantSelection<V> & { className: string }>;
}

export type VariantFn<V extends VariantShape> = (
  props?: VariantSelection<V> & { className?: string },
) => string;

/**
 * Extracts the variant props of a variant function, for typing component
 * props: `type ButtonVariantProps = VariantProps<typeof buttonVariants>`.
 */
export type VariantProps<F> = F extends VariantFn<infer V> ? VariantSelection<V> : never;

/** Builds a typed class-name function from variant definitions, the way every themed component declares its looks. */
export function variants<V extends VariantShape>(config: VariantsConfig<V>): VariantFn<V> {
  const groupNames = Object.keys(config.variants) as Array<Extract<keyof V, string>>;

  return (props) => {
    const { className, ...rest } = props ?? {};
    const selection = rest as VariantSelection<V>;
    const chosen: Partial<Record<Extract<keyof V, string>, string>> = {};
    const classes: string[] = [];

    if (config.base) {
      classes.push(config.base);
    }

    for (const group of groupNames) {
      const value = selection[group] ?? config.defaultVariants?.[group];
      if (value == null) {
        continue;
      }
      chosen[group] = value;
      const groupClasses = config.variants[group][value];
      if (groupClasses) {
        classes.push(groupClasses);
      }
    }

    for (const compound of config.compoundVariants ?? []) {
      const { className: compoundClassName, ...rest } = compound;
      // TS cannot relate Omit<VariantSelection<V> & {...}, "className"> back to
      // the per-group selection shape, so narrow through unknown once here.
      const conditions = rest as unknown as Partial<
        Record<Extract<keyof V, string>, string | null>
      >;
      const conditionKeys = Object.keys(conditions) as Array<Extract<keyof V, string>>;
      const matches = conditionKeys.every((key) => {
        const expected = conditions[key];
        return expected != null && chosen[key] === expected;
      });
      if (matches) {
        classes.push(compoundClassName);
      }
    }

    return cn(...classes, className);
  };
}
