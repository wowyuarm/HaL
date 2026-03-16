import { existsSync, unlinkSync } from "node:fs";
import { join } from "node:path";

const GENERATED_CONFIG_ARTIFACTS = [
  "tailwind.config.js",
  "tailwind.config.d.ts",
  "vite.config.js",
  "vite.config.d.ts",
];

for (const relativePath of GENERATED_CONFIG_ARTIFACTS) {
  const absolutePath = join(process.cwd(), relativePath);
  if (existsSync(absolutePath)) {
    unlinkSync(absolutePath);
  }
}
