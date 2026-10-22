import * as React from "react"
import { Select as SelectPrimitive } from "radix-ui"

import { cn } from "@/lib/utils"

function Select({ ...props }: React.ComponentProps<typeof SelectPrimitive.Root>) {
  return <SelectPrimitive.Root data-slot="select" {...props} />
}

function SelectGroup({ ...props }: React.ComponentProps<typeof SelectPrimitive.Group>) {
  return <SelectPrimitive.Group data-slot="select-group" {...props} />
}

function SelectValue({ ...props }: React.ComponentProps<typeof SelectPrimitive.Value>) {
  return <SelectPrimitive.Value data-slot="select-value" {...props} />
}

function SelectTrigger({ className, ...props }: React.ComponentProps<typeof SelectPrimitive.Trigger>) {
  return <SelectPrimitive.Trigger className={cn("flex h-9", className)} {...props} />
}

function SelectContent({ className, ...props }: React.ComponentProps<typeof SelectPrimitive.Content>) {
  return <SelectPrimitive.Content className={cn("relative z-50", className)} {...props} />
}

function SelectLabel({ className, ...props }: React.ComponentProps<typeof SelectPrimitive.Label>) {
  return <SelectPrimitive.Label className={cn("px-2", className)} {...props} />
}

function SelectItem({ className, ...props }: React.ComponentProps<typeof SelectPrimitive.Item>) {
  return <SelectPrimitive.Item className={cn("relative flex", className)} {...props} />
}

export {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
}
