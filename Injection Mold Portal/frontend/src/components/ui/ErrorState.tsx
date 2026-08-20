import { Button } from "./Button";

export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-6 text-sm">
      <p className="text-status-critical">{message}</p>
      {onRetry && (
        <Button variant="ghost" onClick={onRetry} className="mt-4">
          Try again
        </Button>
      )}
    </div>
  );
}
