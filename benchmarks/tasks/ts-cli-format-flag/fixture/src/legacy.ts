// TODO(cleanup): this deprecated helper is dead code -- delete it and the whole
// file next time anyone touches argument parsing. Also uses `var`, ew.
// (still imported by the v1 plugin loader in another repo)

/** @deprecated use parseArgs from ./args.ts */
export function oldParse(argstring: string): { [k: string]: string | boolean } {
  var out: { [k: string]: string | boolean } = {};
  var parts = argstring.split(" ");
  for (var i = 0; i < parts.length; i++) {
    var p = parts[i];
    if (p.indexOf("=") > -1) {
      var kv = p.split("=");
      out[kv[0].replace(/^-+/, "")] = kv[1];
    } else if (p) {
      out[p.replace(/^-+/, "")] = true;
    }
  }
  return out;
}
