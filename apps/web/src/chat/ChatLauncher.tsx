import { MessageSquare } from 'lucide-react'
import { Button } from '@/components/ui'

/** Placeholder chat button: replaced by task C1 (keep the `ChatLauncher` export). */
export function ChatLauncher() {
  return (
    <div className="fixed bottom-6 right-6 z-40">
      <Button size="lg" aria-label="Open assistant (coming in task C1)" disabled>
        <MessageSquare className="size-4" aria-hidden />
        Ask AI
      </Button>
    </div>
  )
}
