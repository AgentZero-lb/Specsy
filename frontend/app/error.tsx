"use client";

import { useEffect } from "react";
import { buttonVariants } from "@/components/ui/button";

export default function ErrorPage({
  error,
  unstable_retry,
}: {
  error: Error & { digest?: string };
  unstable_retry: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <div className="mx-auto flex max-w-xl flex-col items-center gap-4 px-4 py-28 text-center">
      <h1 className="text-2xl font-semibold text-foreground">
        We couldn&apos;t load the catalog
      </h1>
      <p className="text-muted">
        The service may be waking up or temporarily unavailable. Please try again.
      </p>
      <button
        type="button"
        onClick={() => unstable_retry()}
        className={buttonVariants({ variant: "primary" })}
      >
        Try again
      </button>
    </div>
  );
}
