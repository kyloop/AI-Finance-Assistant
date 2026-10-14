// Fills the Secrets Store ID into wrangler.jsonc, which keeps a <STORE_ID> placeholder in git.
// The ID comes from CLOUDFLARE_STORE_ID (a Workers Builds build variable), or from .env when run locally.
import { existsSync, readFileSync, writeFileSync } from "node:fs";

const fromDotenv = () =>
  existsSync(".env")
    ? readFileSync(".env", "utf8").split("\n").map((l) => l.match(/^\s*CLOUDFLARE_STORE_ID\s*=\s*["']?([^"'\s]*)/)?.[1]).find(Boolean)
    : undefined;

const id = (process.env.CLOUDFLARE_STORE_ID || fromDotenv() || "").trim();
const config = readFileSync("wrangler.jsonc", "utf8");
if (!config.includes("<STORE_ID>")) process.exit(0); // already filled in
if (!/^[0-9a-f]{32}$/i.test(id)) {
  console.error("CLOUDFLARE_STORE_ID is missing or not a 32-character hex ID (set it as a build variable, or in .env locally)");
  process.exit(1);
}
writeFileSync("wrangler.jsonc", config.replaceAll("<STORE_ID>", id));
console.log("wrangler.jsonc: Secrets Store ID filled in");
