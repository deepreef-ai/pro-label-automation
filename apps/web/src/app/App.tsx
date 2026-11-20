import { RouterProvider } from 'react-router-dom'
import { Toaster, TooltipProvider } from '@/components/ui'
import { router } from './routes'

export function App() {
  return (
    <TooltipProvider delayDuration={250} skipDelayDuration={100}>
      <RouterProvider router={router} future={{ v7_startTransition: true }} />
      <Toaster />
    </TooltipProvider>
  )
}
