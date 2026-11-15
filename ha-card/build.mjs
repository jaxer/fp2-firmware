import { build } from "esbuild";
import { readFileSync } from "node:fs";

const { version } = JSON.parse(readFileSync(new URL("./package.json", import.meta.url), "utf8"));

await build({
  entryPoints: ["src/card.ts"],
  bundle: true,
  format: "esm",
  target: "es2022",
  outfile: "dist/fp2-local-card.js",
  define: { __CARD_VERSION__: JSON.stringify(version) },
});
