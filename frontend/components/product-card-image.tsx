"use client";
import Image from "next/image";
import { useState } from "react";
import { CategoryIcon } from "@/components/category-icon";

interface Props {
  src: string;
  alt: string;
  categorySlug: string | null | undefined;
}

export function ProductCardImage({ src, alt, categorySlug }: Props) {
  const [status, setStatus] = useState<"loading" | "loaded" | "error">("loading");

  if (status === "error") {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <CategoryIcon slug={categorySlug} className="h-12 w-12 text-faint" />
      </div>
    );
  }

  return (
    <>
      {status === "loading" && (
        <div className="absolute inset-0 animate-pulse bg-elevated" />
      )}
      <Image
        src={src}
        alt={alt}
        fill
        sizes="(max-width: 640px) 100vw, (max-width: 1024px) 50vw, 33vw"
        className="object-contain p-4 transition-transform duration-300 group-hover:scale-[1.03]"
        onLoad={() => setStatus("loaded")}
        onError={() => setStatus("error")}
      />
    </>
  );
}
