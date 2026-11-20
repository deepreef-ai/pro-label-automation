import type { ReactNode } from 'react'
import * as SelectPrimitive from '@radix-ui/react-select'
import { Check, ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export interface SelectOption {
  value: string
  label: ReactNode
  disabled?: boolean
}

/** Simple select: <Select value={v} onValueChange={setV} options={[{value:'a',label:'A'}]} /> */
export function Select({
  value,
  onValueChange,
  options,
  placeholder = 'Select…',
  className,
  size = 'md',
  disabled,
  'aria-label': ariaLabel,
  id,
}: {
  value?: string
  onValueChange: (v: string) => void
  options: SelectOption[]
  placeholder?: string
  className?: string
  size?: 'sm' | 'md' | 'touch'
  disabled?: boolean
  'aria-label'?: string
  id?: string
}) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange} disabled={disabled}>
      <SelectPrimitive.Trigger
        id={id}
        aria-label={ariaLabel}
        className={cn(
          'inline-flex w-full items-center justify-between gap-2 rounded-md border border-border bg-surface px-3 text-left text-foreground shadow-xs transition-colors',
          'hover:border-border-strong data-[placeholder]:text-muted-foreground disabled:opacity-50',
          size === 'sm' && 'h-8 text-sm',
          size === 'md' && 'h-9 text-base',
          size === 'touch' && 'h-12 text-md',
          className,
        )}
      >
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon>
          <ChevronDown className="size-4 text-muted-foreground" />
        </SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content
          position="popper"
          sideOffset={4}
          className="z-50 max-h-[min(var(--radix-select-content-available-height),320px)] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-lg border border-border bg-surface shadow-lg"
        >
          <SelectPrimitive.Viewport className="p-1">
            {options.map((o) => (
              <SelectPrimitive.Item
                key={o.value}
                value={o.value}
                disabled={o.disabled}
                className={cn(
                  'relative flex cursor-pointer items-center rounded-sm py-1.5 pr-8 pl-2.5 text-base text-foreground outline-none select-none',
                  'data-[disabled]:pointer-events-none data-[disabled]:opacity-50 data-[highlighted]:bg-surface-muted',
                  size === 'touch' && 'py-3 text-md',
                )}
              >
                <SelectPrimitive.ItemText>{o.label}</SelectPrimitive.ItemText>
                <SelectPrimitive.ItemIndicator className="absolute right-2.5">
                  <Check className="size-4 text-accent" />
                </SelectPrimitive.ItemIndicator>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  )
}
