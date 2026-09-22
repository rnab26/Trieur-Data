import { forwardRef, type InputHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...props }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          'w-full min-h-11 rounded-lg bg-[var(--card)] px-3 py-2 text-sm text-[var(--foreground)] shadow-[var(--ring-card)] outline-none focus:shadow-[inset_0_0_0_1.5px_var(--primary)]',
          className,
        )}
        {...props}
      />
    )
  },
)
