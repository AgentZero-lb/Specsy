import Link from "next/link";
import { PackageX } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";

export default function NotFound() {
  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-5 px-4 py-32 text-center">
      <span className="grid h-14 w-14 place-items-center rounded-hero border border-hairline bg-surface">
        <PackageX className="h-6 w-6 text-faint" />
      </span>
      <h1 className="text-3xl font-semibold tracking-tight text-foreground">
        Listing not found
      </h1>
      <p className="max-w-sm text-muted">
        This product may have been removed, or the link is incorrect.
      </p>
      <Link href="/browse" className={buttonVariants({ variant: "primary" })}>
        Browse parts
      </Link>
    </div>
  );
}
