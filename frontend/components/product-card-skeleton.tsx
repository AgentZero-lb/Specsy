import { Skeleton } from "@/components/ui/skeleton";

export function ProductCardSkeleton() {
  return (
    <div className="flex flex-col overflow-hidden rounded-card border border-hairline bg-surface">
      <Skeleton className="aspect-square w-full rounded-none" />
      <div className="flex flex-col gap-3 p-4">
        <Skeleton className="h-4 w-full" />
        <Skeleton className="h-4 w-2/3" />
        <div className="mt-2 flex items-center justify-between">
          <Skeleton className="h-6 w-20" />
          <Skeleton className="h-4 w-12" />
        </div>
        <div className="border-t border-hairline pt-3">
          <Skeleton className="h-3 w-24" />
        </div>
      </div>
    </div>
  );
}
