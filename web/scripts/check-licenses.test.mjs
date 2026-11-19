import { describe, expect, it } from "vitest";
import { ALLOWED, checkLockfile, offending, parse } from "./check-licenses.mjs";

describe("npm license gate", () => {
  it("parses SPDX expressions", () => {
    expect(parse("MIT")).toBe("MIT");
    expect(parse("(MIT OR Apache-2.0) AND BSD-3-Clause")).toEqual(["AND", [["OR", ["MIT", "Apache-2.0"]], "BSD-3-Clause"]]);
    expect(parse("Apache-2.0 WITH LLVM-exception")).toBe("Apache-2.0");
    expect(() => parse("(MIT")).toThrow(/unbalanced/);
  });

  it("needs every AND part and one OR part", () => {
    expect(offending(parse("MIT OR GPL-3.0-only"), ALLOWED)).toEqual([]);
    expect(offending(parse("MIT AND LGPL-3.0-or-later"), ALLOWED)).toEqual(["LGPL-3.0-or-later"]);
    expect(offending(parse("MPL-2.0"), ALLOWED)).toEqual(["MPL-2.0"]);
  });

  it("checks production packages only and fails on copyleft or a missing license", () => {
    const rows = checkLockfile({
      packages: {
        "": { name: "app" },
        "node_modules/a": { version: "1.0.0", license: "MIT" },
        "node_modules/b": { version: "1.0.0", license: "GPL-2.0", dev: true },
        "node_modules/@img/sharp-libvips-linux-x64": { version: "1.0.0", license: "LGPL-3.0-or-later", optional: true },
        "node_modules/c": { version: "2.0.0" },
        "node_modules/caniuse-lite": { version: "1.0.0", license: "CC-BY-4.0" },
        "node_modules/sharp": { resolved: "stubs/sharp", link: true },
      },
    });
    expect(rows.map((r) => [r.name, r.problem])).toEqual([
      ["@img/sharp-libvips-linux-x64", "not allowed: LGPL-3.0-or-later"],
      ["a", null],
      ["c", "no license field"],
      ["caniuse-lite", null],
    ]);
  });
});
