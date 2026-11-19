import { copyFileSync, mkdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const projectDirectory = resolve(scriptDirectory, "..");
mkdirSync(resolve(projectDirectory, "public"), { recursive: true });
copyFileSync(
  resolve(projectDirectory, "..", "data", "feed.json"),
  resolve(projectDirectory, "public", "feed.json"),
);
