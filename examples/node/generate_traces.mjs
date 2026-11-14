// Record the sample scenarios from Node. Build the SDK first:
//   npm --prefix packages/node run build
//   node examples/node/generate_traces.mjs --out some/dir
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import { SCENARIOS, TickClock } from "./scenarios.mjs";

export async function generate(outDir) {
  const paths = [];
  for (const [name, run] of Object.entries(SCENARIOS)) {
    const path = join(outDir, name + ".rootcast.json");
    await run(path, new TickClock().call);
    paths.push(path);
  }
  return paths;
}

const isMain = process.argv[1] && import.meta.url === pathToFileURL(resolve(process.argv[1])).href;
if (isMain) {
  const i = process.argv.indexOf("--out");
  if (i < 0 || !process.argv[i + 1]) {
    console.error("usage: node examples/node/generate_traces.mjs --out <dir>");
    process.exit(2);
  }
  for (const path of await generate(process.argv[i + 1])) console.log("wrote " + path);
}
