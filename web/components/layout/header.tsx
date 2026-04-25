import Link from "next/link";
import { logoutAction } from "@/lib/auth/cookies";

export function Header() {
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex max-w-screen-2xl items-center justify-between px-6 py-3">
        <Link href="/" className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold tracking-tight">
            PTE
          </span>
          <span className="text-sm text-muted-foreground">
            Portfolio Thesis Engine
          </span>
        </Link>

        <nav className="flex items-center gap-6 text-sm">
          <Link href="/" className="text-foreground hover:text-primary">
            Tickers
          </Link>
          <form action={logoutAction}>
            <button
              type="submit"
              className="text-muted-foreground hover:text-foreground"
            >
              Sign out
            </button>
          </form>
        </nav>
      </div>
    </header>
  );
}
