export interface Options {
  verbose: boolean;
  out: string | null;
  files: string[];
}

/** Parse CLI arguments (without the node/script prefix). */
export function parseArgs(argv: string[]): Options {
  const opts: Options = { verbose: false, out: null, files: [] };
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (arg === "--verbose" || arg === "-v") {
      opts.verbose = true;
    } else if (arg === "--out") {
      const value = argv[++i];
      if (value === undefined) throw new Error("--out needs a value");
      opts.out = value;
    } else if (arg.startsWith("--")) {
      throw new Error(`unknown option ${arg}`);
    } else {
      opts.files.push(arg);
    }
  }
  return opts;
}
