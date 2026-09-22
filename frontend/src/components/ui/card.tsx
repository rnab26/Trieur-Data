import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

// Thème Jarvis (2026-09-22) : jamais de bordure franche -- un "ring" à
// 8% d'opacité (--ring-card, voir index.css) fait office de contour,
// plus discret qu'un trait plein. Coins plus arrondis (rounded-xl).
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-xl bg-[var(--card)] shadow-[var(--ring-card)]', className)}
      {...props}
    />
  )
}

export function CardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-4 py-3', className)} {...props} />
}

export function CardContent({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('px-4 py-3', className)} {...props} />
}
