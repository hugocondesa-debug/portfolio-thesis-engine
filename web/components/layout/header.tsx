import Link from "next/link";
import { logoutAction } from "@/lib/auth/cookies";

export function Header() {
  return (
    <header className="border-b border-border bg-card">
      <div className="mx-auto flex max-w-screen-2xl items-center justify-between gap-3 px-3 py-3 md:px-6">
        <Link href="/" className="flex items-center gap-2">
          <span className="font-mono text-sm font-semibold tracking-tight">
            PTE
          </span>
          <span className="hidden text-sm text-muted-foreground md:inline">
            Portfolio Thesis Engine
          </span>
        </Link>

        <nav className="flex items-center gap-3 text-sm md:gap-6">
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
