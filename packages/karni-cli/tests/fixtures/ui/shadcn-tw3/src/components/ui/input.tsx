import * as React from "react"

import { cn } from "@/lib/utils"

const Input = React.forwardRef<HTMLInputElement, React.ComponentProps<"input">>(
  ({ className, type, ...props }, ref) => {
    return <input type={type} className={cn("flex h-10 w-full rounded-md border", className)} ref={ref} {...props} />
  }
)
Input.displayName = "Input"

export { Input }
