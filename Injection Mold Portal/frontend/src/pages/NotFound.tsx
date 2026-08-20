import { Link } from "react-router-dom";
import { Button } from "../components/ui/Button";

export function NotFound() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center px-6 py-24 text-center">
      <p className="font-mono-num text-sm font-medium text-brand-blue">404</p>
      <h1 className="mt-3 font-display text-2xl font-bold text-ink-primary">Page not found</h1>
      <p className="mt-2 text-ink-secondary">
        That page doesn't exist, or the link might be out of date.
      </p>
      <Link to="/" className="mt-6">
        <Button>Back to home</Button>
      </Link>
    </div>
  );
}
