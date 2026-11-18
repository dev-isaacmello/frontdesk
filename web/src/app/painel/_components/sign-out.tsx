import { signOutAction } from "../actions";

export function SignOut({ className = "" }: { className?: string }) {
  return (
    <form action={signOutAction}>
      <button type="submit" className={`text-ink-soft hover:text-ink ${className}`}>
        Sair
      </button>
    </form>
  );
}
