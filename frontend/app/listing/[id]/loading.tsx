import { Skeleton } from "@/components/ui/skeleton";

export default function Loading() {
  return (
    <div className="mx-auto max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
      <Skeleton className="mb-8 h-4 w-64" />
      <div className="grid gap-10 lg:grid-cols-2">
        <Skeleton className="aspect-square w-full rounded-hero" />
        <div className="flex flex-col gap-6">
          <Skeleton className="h-6 w-28" />
          <Skeleton className="h-9 w-3/4" />
          <Skeleton className="h-4 w-32" />
          <Skeleton className="h-28 w-full rounded-card" />
        </div>
      </div>
      <Skeleton className="mt-14 h-64 w-full rounded-card" />
    </div>
  );
}
