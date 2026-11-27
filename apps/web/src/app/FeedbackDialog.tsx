import { useState, type FormEvent } from 'react'
import { useLocation } from 'react-router-dom'
import { MessageSquarePlus } from 'lucide-react'
import { api } from '@/lib/api'
import { useRole } from '@/lib/role'
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Field,
  Input,
  Textarea,
  toast,
} from '@/components/ui'
import { titleForPath } from './nav'

/** "Suggest a change" — lets the client leave feedback on any screen (POST /api/feedback). */
export function FeedbackDialog() {
  const { pathname } = useLocation()
  const role = useRole()
  const [open, setOpen] = useState(false)
  const [message, setMessage] = useState('')
  const [sending, setSending] = useState(false)
  const screen = titleForPath(pathname)

  const submit = async (e: FormEvent) => {
    e.preventDefault()
    if (!message.trim()) return
    setSending(true)
    try {
      await api.post('/api/feedback', { screen, path: pathname, message: message.trim(), role })
      toast.success('Thanks, your suggestion was sent', { description: `Logged for the ${screen} screen.` })
      setMessage('')
      setOpen(false)
    } catch (err) {
      toast.error('Could not send', { description: (err as Error).message })
    } finally {
      setSending(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="secondary" size="sm" className="hidden md:inline-flex">
          <MessageSquarePlus />
          Suggest a change
        </Button>
      </DialogTrigger>
      <DialogContent>
        <form onSubmit={submit} className="grid gap-4">
          <DialogHeader>
            <DialogTitle>Suggest a change</DialogTitle>
            <DialogDescription>Tell us what to add, remove or fix. Plain words are perfect.</DialogDescription>
          </DialogHeader>
          <Field label="Screen" htmlFor="fb-screen">
            <Input id="fb-screen" value={screen} readOnly className="bg-surface-muted text-muted-foreground" />
          </Field>
          <Field label="Your suggestion" htmlFor="fb-message">
            <Textarea
              id="fb-message"
              autoFocus
              rows={5}
              value={message}
              onChange={(e) => setMessage(e.target.value)}
              placeholder="e.g. Show the paper shortage in red at the top of this page"
            />
          </Field>
          <DialogFooter>
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Cancel
            </Button>
            <Button type="submit" loading={sending} disabled={!message.trim()}>
              Send suggestion
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
