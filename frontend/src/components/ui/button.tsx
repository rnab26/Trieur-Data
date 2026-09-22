import type { ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

// Thème Jarvis (2026-09-22) : "secondary" perd sa bordure franche pour
// un ring discret (cohérent avec Card, voir index.css) ; primary
// redevient neutre (--primary est maintenant quasi-noir, pas un bleu
// d'accent -- la couleur reste réservée aux statuts). Hauteur mini 44px
// (norme tactile Apple), même si le contenu visible est plus petit.
const variantClasses: Record<Variant, string> = {
  primary: 'bg-[var(--primary)] text-[var(--primary-foreground)] hover:opacity-90',
  secondary:
    'bg-[var(--card)] shadow-[var(--ring-card)] text-[var(--foreground)] hover:bg-[var(--muted-bg)]',
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
        'inline-flex min-h-11 items-center justify-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition disabled:opacity-50 disabled:cursor-not-allowed',
        variantClasses[variant],
        className,
      )}
      {...props}
    />
  )
}
