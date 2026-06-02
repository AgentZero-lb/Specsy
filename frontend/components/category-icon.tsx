import {
  Cpu,
  CircuitBoard,
  MemoryStick,
  HardDrive,
  Power,
  Box,
  Fan,
  Monitor,
  Mouse,
  Keyboard,
  Headphones,
  Speaker,
  Mic,
  Gamepad2,
  PenTool,
  Armchair,
  Laptop,
  Tablet,
  Wifi,
  BatteryCharging,
  Camera,
  Video,
  Package,
  type LucideIcon,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  cpu: Cpu,
  gpu: CircuitBoard,
  ram: MemoryStick,
  motherboard: CircuitBoard,
  storage: HardDrive,
  psu: Power,
  case: Box,
  cooling: Fan,
  monitor: Monitor,
  mouse: Mouse,
  keyboard: Keyboard,
  headset: Headphones,
  speaker: Speaker,
  microphone: Mic,
  joystick: Gamepad2,
  "drawing-pad": PenTool,
  "gaming-chair": Armchair,
  laptop: Laptop,
  desktop: Monitor,
  tablet: Tablet,
  networking: Wifi,
  ups: BatteryCharging,
  camera: Camera,
  projector: Video,
};

export function categoryIcon(slug: string | null | undefined): LucideIcon {
  return (slug && ICONS[slug]) || Package;
}

export function CategoryIcon({
  slug,
  className,
}: {
  slug: string | null | undefined;
  className?: string;
}) {
  const Icon = categoryIcon(slug);
  return <Icon className={className} aria-hidden />;
}
