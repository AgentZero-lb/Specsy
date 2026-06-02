import Link from "next/link";

export function SiteFooter() {
  return (
    <footer className="border-t border-hairline bg-base">
      <div className="mx-auto flex max-w-7xl flex-col gap-6 px-4 py-12 sm:px-6 md:flex-row md:items-center md:justify-between lg:px-8">
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded-btn bg-accent text-xs font-bold text-accent-foreground">
              S
            </span>
            <span className="font-semibold text-foreground">Specsy</span>
          </div>
          <p className="text-sm text-faint">Lebanon&apos;s PC parts, compared.</p>
        </div>

        <nav className="flex gap-6 text-sm text-muted">
          <Link href="/browse" className="transition-colors hover:text-foreground">
            Browse
          </Link>
          <Link href="/build" className="transition-colors hover:text-foreground">
            Build a PC
          </Link>
          <Link href="/" className="transition-colors hover:text-foreground">
            About
          </Link>
        </nav>

        <p className="text-xs text-faint">Data refreshed every 12h</p>
      </div>
    </footer>
  );
}
