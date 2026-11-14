#!/usr/bin/env node
import { listTraces, validateFile } from "./store.js";

const USAGE = "usage: rootcast validate <trace.rootcast.json ...>\n       rootcast list [store]";

function main(argv: string[]): number {
  const [command, ...rest] = argv;
  if (command === "validate" && rest.length > 0) {
    let code = 0;
    for (const path of rest) {
      const errors = validateFile(path);
      const prefix = rest.length > 1 ? path + ": " : "";
      if (errors.length > 0) {
        code = 1;
        for (const e of errors) console.log(prefix + "invalid: " + e);
      } else {
        console.log(prefix + "valid");
      }
    }
    return code;
  }
  if (command === "list") {
    for (const path of listTraces(rest[0])) console.log(path);
    return 0;
  }
  console.error(USAGE);
  return 2;
}

process.exitCode = main(process.argv.slice(2));
