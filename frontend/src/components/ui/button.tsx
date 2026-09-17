import type { ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

const variantClasses: Record<Variant, string> = {
  primary: 'bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90',
  secondary:
    'bg-transparent border border-[var(--border)] text-[var(--foreground)] hover:bg-[var(--muted-bg)]',
  danger: 'bg-[var(--danger)] text-[var(--danger-foreground)] hover:opacity-90',
  ghost: 'bg-transparent text-[var(--foreground)] hover:bg-[var(--muted-bg)]',
}

export function Button({
  className,
  variant = 'primary',
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant }) {
  return (
    <button
      className={cn(
        'inline-flex items-center justify-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed',
        variantClasses[variant],
        className,
      )}
      {...props}
    />
  )
}
