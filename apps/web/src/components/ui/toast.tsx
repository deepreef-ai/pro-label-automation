import { Toaster as Sonner, toast } from 'sonner'
import { useTheme } from '@/app/theme'

/** Mounted once in the app shell. Use `toast.success('Saved')` anywhere. */
export function Toaster() {
  const { theme } = useTheme()
  return (
    <Sonner
      theme={theme}
      position="bottom-right"
      offset={88}
      closeButton
      toastOptions={{
        classNames: {
          toast: '!rounded-lg !border !border-border !bg-surface !text-foreground !shadow-lg !font-sans',
          description: '!text-muted-foreground',
        },
      }}
    />
  )
}

export { toast }
