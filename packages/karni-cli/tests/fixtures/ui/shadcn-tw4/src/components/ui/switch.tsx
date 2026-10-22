import * as React from "react"
import { Switch as SwitchPrimitive } from "@base-ui/react/switch"

import { cn } from "@/lib/utils"

function Switch({ className, ...props }: SwitchPrimitive.Root.Props) {
  return <SwitchPrimitive.Root data-slot="switch" className={cn("inline-flex", className)} {...props} />
}

export { Switch }
